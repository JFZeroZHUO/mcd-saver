# MCP_INTEGRATION · 麦当劳 MCP 集成说明

本文档说明 McDSaver 实际使用的麦当劳 MCP Server、Tool 清单、调用流程与业务价值。

## 一、Server 信息

| 项目 | 内容 |
|---|---|
| Server | 麦当劳中国官方 MCP Server（`mcd-mcp`，v1.0.9） |
| 端点 | `https://mcp.mcd.cn` |
| 协议 | MCP Streamable HTTP，JSON-RPC 2.0 |
| 认证 | `Authorization: Bearer <TOKEN>` 请求头（Token 运行时从环境变量 `MCD_MCP_TOKEN` 或本地 `~/.workbuddy/mcp.json` 读取，源代码不含真实凭证） |
| 限流 | 600 次/分钟 |
| 工具总数 | 35 个（本项目中接入 **9 个**） |

> 实测坑位：`Bearer ` 前缀不能省，缺失时服务端将认证方案识别为 `other` 并返回 403。

## 二、实际使用的 Tools

### 捡漏雷达使用（5 个，全部只读）

| Tool | 用途 | 项目中的用法 |
|---|---|---|
| `available-coupons` | 查询当前可领取的券 | 识别「可领取」状态的新券，与上次快照比对得出"新券上架"信号 |
| `query-my-coupons` | 查询我的券 | 解析有效期末尾时间，按预警窗口（默认 72 小时）计算到期倒计时 |
| `query-my-account` | 查询积分账户 | 读取可用积分、当月/下月将过期积分，生成"积分到期"信号 |
| `query-lottery-info` | 查询积分抽奖活动 | 用 `drawPoint` 与可用积分算出"还能抽几次"，避免抽奖机会被遗忘 |
| `campaign-calendar` | 查询当月活动日历 | 提取今日进行中的活动（已做跨日期段落去重），作为日报第三栏 |

### 最省点单器使用（3 个，全部只读）

| Tool | 用途 | 项目中的用法 |
|---|---|---|
| `query-nearby-stores` | 查询附近门店 | `searchType=2` + `city` + `keyword`（两个必传，缺一报 600058）获取 `storeCode` |
| `query-meals` | 查询门店菜单 | 从以 `code` 为键的 `meals` 字典取商品名、现价、营销划线价 |
| `calculate-price` | 真实计价 | 对每个候选组合调用官方计价接口，输出实付对比表 |

### 预留能力（1 个，需用户显式触发）

| Tool | 用途 | 边界 |
|---|---|---|
| `auto-bind-coupons` | 一键领券 | **默认不执行**。仅在用户明确说"帮我领"时调用；实测其返回带 `couponId`/`couponCode`，可进一步传给 `calculate-price` 的 `items[].couponId` 计算券后价（接口会校验券可用性，不匹配报 600012） |

## 三、调用流程

### 流程 A · 捡漏雷达（每日定时/按需触发）

```
now-time-info 获取当前时间
   │
   ├── available-coupons ──→ 与 state/latest.json 快照 diff ──→ 「新券上架」
   ├── query-my-coupons ───→ 正则解析有效期（纯 markdown，无 JSON）──→ 「券到期倒计时」
   ├── query-my-account ───→ currentMouthExpirePoint / expiredPoint ──→ 「积分到期」
   ├── query-lottery-info ─→ availablePoint ÷ drawPoint ────────────→ 「剩余抽奖次数」
   └── campaign-calendar ──→ 提取今日活动（去重）────────────────────→ 「今日活动」
   │
   └──→ 四路信号合成一条结构化日报：需要你出手 → 家底 → 今日活动 → 还能领
        并把本次结果写入 state/latest.json 作为下次比对的基准
```

### 流程 B · 最省点单器（用户提问触发）

```
query-nearby-stores（city+keyword）──→ 用户选定门店，拿到 storeCode
        │
query-meals（storeCode）──→ 按关键词筛选候选商品，拿 code / currentPrice
        │
组方案：单点 vs 套餐 / 大套餐 vs 小套餐+加购 / 多人拆单等，至少 2 组
        │
calculate-price（storeCode, orderType, beType, items[]）× N 次
        │
        ├── 金额换算：接口单位为「分」，除以 100 转元
        ├── 口径区分：calculate-price.originalPrice 是菜单现价，
        │            营销划线价只取 query-meals.originalPrice
        └── 价差告警：计价结果与菜单标价不一致时输出「需要核实的价差」区块
        │
输出实付对比表 + 省额建议（如「选方案 A 比方案 B 省 ¥6.0」）
```

## 四、业务价值

1. **挽回真实损失**：实测账号累计 1302.5 积分中 1172.1 已过期（约 90% 流失）、2 张主力券在过期前 55 小时才被发现。雷达把"事后懊悔"变成"事前提醒"，每次有效预警可挽回 ¥10～20 的实际权益。
2. **真实计价而非估算**：市面上的点单建议多靠人工经验，本项目的每个实付金额都来自官方 `calculate-price` 接口，且发现并处理了"套餐计价与菜单标价不一致"的真实坑位（如四件套菜单 ¥28 vs 计价 ¥57），避免误导用户。
3. **内容生产管线**：`campaign-calendar` 的活动日历可直接转为公众号选题日历；雷达日报可自动生成可视化 HTML 简报（见 `examples/daily-report-demo.html`），支撑"每日麦麦省钱早报"栏目持续运营。
4. **可复用的实测知识库**：`references/api-facts.md` 记录了 35 个工具中 9 个核心工具的返回结构（纯 JSON / 纯 markdown / 混合文本三类）、6 个错误码的处理方式，以及"分vs元""套餐子项需 roundList""同一活动跨日期段落重复"等实测结论，后续接入者可少走弯路。

## 五、合规说明

- 本项目**只做查询与计算**，所有写操作（领券、下单、抽奖、取消订单）均需用户显式确认，且不在定时任务中执行
- 遵守官方限流（600 次/分钟），查询结果做本地快照缓存，不做高频轮询
- 遵守麦当劳券面条款：不转让、不转售、不代下单、不代买
- Token 仅存于用户本地环境变量或配置文件，不出现在代码仓库与输出日志中
