# 麦当劳 MCP 实测要点

全部为 2026-10-21 实测结论，非文档抄录。改脚本前务必先读。

## 接入

- 地址 `https://mcp.mcd.cn`，Streamable HTTP，JSON-RPC 2.0
- 请求头必须带 `Authorization: Bearer <TOKEN>`
  - **裸 token（缺 `Bearer `）会返回 403**，日志里表现为 `authorizationScheme: "other"`
- 限流 600 次/分钟，超额 429
- 35 个工具（v1.0.9）

## 返回结构（重要）

`tools/call` 的 `result.content[].text` **不是纯 JSON**，而是：

```
<面向 LLM 的字段说明 markdown>
{"success":true,"code":200,...,"data":{...}}
## 展示结果时，...
```

解析要先找 `{"success"` / `{"code"` / `{"data"` 的位置，再用 `json.JSONDecoder().raw_decode()` 从该位置解码。不能直接 `json.loads` 整个 text。`scripts/mcd.py` 里的 `extract_json()` 就是干这个的。

少数工具（`available-coupons`、`query-my-coupons`）**只返回 markdown，完全没有 JSON**，只能正则解析。

## 各工具返回

### query-my-account（纯 JSON）

```json
{"data":{"availablePoint":"130.4","accountId":"<已脱敏>","accumulativePoint":"1302.5",
"currency":"麦享会积分","currentMouthExpirePoint":"0","expiredPoint":"1172.1",
"frozenPoint":"0","lastMouthExpirePoint":"0","nextMouthExpirePoint":"0","usedPoint":"0"}}
```

积分均为字符串，比较前要 `float()`。

### available-coupons（纯 markdown）

```
### 麦麦省优惠券列表：
- 优惠券标题：11.9元麦辣鸡腿堡 \
  状态：已领取 \
  优惠券图片：\
    <img src="..." ...>
```

状态只有「已领取」「可领取」两种。行尾带 `\` 转义，正则要容忍。

### query-my-coupons（纯 markdown，**无券 ID**）

```
## 11.9元麦辣鸡腿堡
- **优惠**: ¥11.9 (用券价格)
- **有效期**: 2026-10-19 10:30-2026-10-23 23:59 周一、二、三、四、五 10:30-23:59
- **领取时间**: 3日前收到
- **标签**: 到店专用、外送专用
```

**关键限制**：不含 `couponId` / `couponCode`。**但 `auto-bind-coupons` 的返回会带**（实测）：

```
#### 成功领取的优惠券：
- 免费脆薯饼
  - couponId：<COUPON_ID_已脱敏>
  - couponCode：<COUPON_CODE_已脱敏>
```

所以想程序化算券后价，路径是：先 `auto-bind-coupons`（顺带完成领券）拿到 couponId → 传给 `calculate-price` 的 `items[].couponId` / `couponCode`。已实测接口会校验券可用性，不匹配时返回 `600012 当前优惠券不可用！`（例：脆薯饼券配的是早餐品项，晚间下单即报此错）。

已领取但未经 `auto-bind` 拿到的券（如券包里原有的），仍只能靠券面价人工代入。

有效期取第二个 `YYYY-MM-DD HH:MM`（第一个是起始时间，第三个是每日时段不含日期）。

参数 `page`（最多 5 页）、`pageSize`（默认 200，最大 200）。

### query-lottery-info（纯 JSON）

```json
{"data":{"activityCode":"dtx2","activityStatusText":"进行中","drawPoint":"24",
"availablePoint":"130.4","drawDecision":{...},"prizes":[{"name":"下单立减3元券",...}]}}
```

`drawPoint` 是每次消耗积分，字符串。可抽次数 = `availablePoint / drawPoint` 向下取整。

### campaign-calendar（纯 markdown）

```
### 当前时间：2026-10-21 15:54:10
#### 2026年10月20日 往期回顾
-   **活动标题**：麦当劳 X PEACEMINUSONE
#### 2026年10月21日 今日
-   **活动标题**：...
```

**同一活动会在多个日期段落重复出现**，必须去重。段落标记只有「往期回顾」「今日」（未来日期直接是日期）。全文搜不到「分享/口令/兑换码/优惠码/邀请」——没有可分发型券码。

### query-nearby-stores

```json
{"data":[{"storeName":"麦当劳深圳科技园长园得来速餐厅","storeCode":"1420888",
"beCode":null,"reservation":true,"address":"...","distance":"..."}]}
```

坑：
- `searchType=2` 时 **`city` 和 `keyword` 都必须传**，缺一个报 `600058 城市名或者关键词不能为空`。`city` 传「深圳市」能用，传「深圳」可能不行。
- `searchType=1`（搜收藏）对新账号直接报 `600050 收藏餐厅列表为空`
- 到店自取场景 `beCode` 为 `null`，且不需要传 —— 别拼成 `"null"` 字符串
- beType：1 到店自提，5 得来速；orderType：1 到店，2 外送

### query-meals

```json
{"data":{"categories":[{"name":"人气热卖","meals":[{"code":"1440","tags":["爆款"]}]}],
"meals":{"1440":{"name":"麦辣鸡腿汉堡","currentPrice":"22.5","originalPrice":"22.5",
"image":"...","canWithOrder":false}},
"frequent":{...}}}
```

`meals` 是 **以 code 为键的字典**，不是数组。`currentPrice` / `originalPrice` 单位是**元**（字符串）。
`originalPrice > currentPrice` 时才是营销划线价（如三件套 47 vs 33.5）。

### calculate-price

外层 `{"success":true,"data":{...}}`，**数据在 `data` 里**，直接取 `price` 会失败。

```json
{"data":{"productOriginalPrice":3200,"productPrice":3200,"originalPrice":3200,
"discount":0,"price":3200,
"productList":[{"productCode":"1440","productName":"麦辣鸡腿汉堡","quantity":1,
"originalSubtotal":2250,"subtotal":2250}],
"takeWayList":[{"code":"eat-in","title":"堂食"},{"code":"locker-in","title":"外带"},
{"code":"take-dt-quick","title":"得来速"}]}}
```

- **所有金额单位是「分」**。3200 = ¥32。
- `originalPrice` 等于 `productOriginalPrice`（当前菜单价），**不是营销划线价**
- `discount` 为券优惠，没有券时为 0
- `takeWayList` 是取餐方式选项，下单时需要
- 另有两个隐藏字段（文档结构里才出现，正常返回常缺省）：
  - `enjoyed` = 已享受的优惠 `{amountType, realDiscount, balance}`，amountType `1`特价 `2`折扣 `3`立减，`realDiscount` 单位是**元**
  - `enjoyable` = 可享受但未达门槛的优惠，`balance` 是**门槛差额（分）**
  - 这两个是做「再买 ¥X 就能用上满减」提示的依据，值得留意
- 必填：`storeCode`、`orderType`、`beType`；items 每项 `productCode` + `quantity`（≥1）

**计价结果可能与菜单标价不一致（实测踩到）**：
`query-meals` 里「麦辣鸡腿堡四件套」`currentPrice=28`、`originalPrice=57`，
但 `calculate-price` 原样传 `{productCode:"9900000891",quantity:1}` 返回 `price=5700`（¥57）。
同一门店的「辣么快乐套餐」24、「麦辣三件套」33.5 则与菜单一致。

推测原因：多子项套餐需要通过 `roundList` 指定子项，不指定时按原价返回；
或该促销价仅在官方 App/小程序生效。**这不是可以猜的，凡是价差就直接告警让用户核实**，
`scripts/mcd.py price` 已内置该检测（`需要核实的价差` 区块）。

items 还支持 `couponId`、`couponCode`、`modification`（特制）、`roundList`（套餐子项）。但券 ID 拿不到，实际用不上。

### mall-product-detail（条款原文来源）

`note` 字段是含 HTML 的条款全文。第 7、9 条明确：券**不能转让、转售、转发、截图，不能代下单、代买**；非官方渠道获得的电子券不能使用。任何"赠券给他人"的产品设计都违反此条款。

## 错误码

| code / HTTP | 含义 | 处理 |
|---|---|---|
| 401 | Token 无效/过期/未提供 | 重新申请 token |
| 403 | 缺 `Bearer ` 前缀 | 检查 Authorization 格式 |
| 429 | 超 600 次/分钟 | 降频，加缓存 |
| 600058 | 城市名或关键词为空 | city + keyword 都传 |
| 600050 | 收藏餐厅列表为空 | 改用 searchType=2 + city/keyword |

## 写操作清单（默认不做）

`auto-bind-coupons`（领券）、`create-order`（下单）、`cancel-order`（取消）、`mall-create-order`（积分兑换）、`draw-lottery`（抽奖）、`party-order-create`（主题活动下单）。这些都会改变账号状态，必须用户明确同意后才执行，且执行前展示明细。
