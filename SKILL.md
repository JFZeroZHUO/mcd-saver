---
name: mcd-saver
version: 1.0.0
display_name: 麦麦省钱助手
display_name_en: McDonald's Saver
description: 麦当劳 MCP 省钱助手，含两个模式——「捡漏雷达」盯新券上架、券到期、积分到期、抽奖次数，四路信号合成一条日报；「最省点单器」用真实计价接口算单点/套餐/拆单哪个最省，输出实付对比表。触发词：麦当劳省钱、麦麦捡漏、领券提醒、今天吃什么最划算、麦当劳点单比价、券到期、积分过期、mcd、麦门。不负责下单付款（下单需用户显式确认）。
description_zh: 基于麦当劳中国官方 MCP 的两用省钱助手：捡漏雷达（新券/券到期/积分到期/抽奖次数四路信号）+ 最省点单器（真实计价比价）。
description_en: McDonald's China MCP saver with a coupon/points radar and a real-price order comparator.
---

# 麦麦省钱助手

基于麦当劳中国官方 MCP（`https://mcp.mcd.cn`）的两个实用功能，引擎已封装在 `scripts/mcd.py`。

## 何时用

| 用户说什么 | 用哪个模式 |
|---|---|
| "有什么券要过期""帮我盯券""积分要过期了""今天有什么活动" | **雷达** |
| "怎么点最划算""这两个哪个便宜""预算 50 吃什么""套餐还是单点" | **比价** |

## 快速开始

```bash
PY=<python解释器>
S=<skill目录>/scripts/mcd.py

$PY $S radar                          # 捡漏雷达
$PY $S stores --city 深圳市 --keyword 科技园   # 先定门店拿 storeCode
$PY $S menu --store 1420888 --q 麦辣          # 查菜单拿 productCode
$PY $S price --store 1420888 \
    --plan "单点:1440:1,9900008751:1" \
    --plan "套餐:9900005456:1"                # 比价
```

Token 自动从 `~/.workbuddy/mcp.json` 的 `mcd-mcp.headers.Authorization` 读取（自动剥掉 `Bearer ` 前缀再拼回去），也可用环境变量 `MCD_MCP_TOKEN` 覆盖。**永远不要把 token 打印到输出里。**

如果本会话已加载 `mcd-*` 系列 MCP 工具，也可以直接调工具；结果等价，但脚本还能做跨天比对（`state/latest.json` 快照），优先用脚本。

---

## 雷达模式

四个信号，每条日报只讲用户需要动手的事：

1. **新券上架** — `available-coupons` 里状态为"可领取"、且上次快照没有的
2. **券到期** — `query-my-coupons` 的有效期末尾，按 `--hours`（默认 72）窗口倒计时
3. **积分到期** — `query-my-account` 的 `currentMouthExpirePoint` / `nextMouthExpirePoint`
4. **抽奖次数** — `query-lottery-info` 的 `drawPoint` 与可用积分，算出还能抽几次

输出结构固定：`需要你出手` → `家底` → `今日活动` → `还能领`。**"需要你出手"为空时明确说"暂时没有紧急项"**，不要为了凑内容编造提醒。

快照写在 `state/latest.json`，每次运行覆盖。删掉它等于重置"新券"判定基准。

---

## 比价模式

标准流程，不要跳步：

1. **定门店** — `stores --city X --keyword Y`，注意 `city` 和 `keyword` **两个都必须传**，只传一个会报 `600058 城市名或者关键词不能为空`。到店自取（beType=1）不需要 `beCode`。
2. **看菜单** — `menu --store CODE --q 关键词`，拿 `code` 和 `currentPrice`。想吃的东西用户没说清时，先列候选让用户选，别自己替他决定。
3. **组方案** — 至少两组才有比价意义。常见组合维度：单点 vs 套餐、大套餐 vs 小套餐+加购、两个套餐 vs 一个套餐两份主食。
4. **计价** — `price --plan "名称:code:qty,code:qty"`，实付来自 `calculate-price` 真实接口，不是估算。

### 三条铁律

- **金额单位是"分"**。接口返回 3200 就是 ¥32。脚本已换算，直接调工具时必须自己除 100。
- **`calculate-price` 的 `originalPrice` 就是当前菜单价，不是营销划线价**。营销原价只在 `query-meals` 的 `originalPrice` 字段里（比如麦辣三件套菜单划线 ¥47 vs 现价 ¥33.5）。脚本已补这段提示，别把两者混为一谈。
- **券能不能程序化算进去，取决于 couponId 从哪来。** `query-my-coupons` 不返回券 ID，但 **`auto-bind-coupons` 的返回带 `couponId` / `couponCode`**。所以：刚领的券可以直接传给 `calculate-price` 的 `items[].couponId` 算券后价（接口会校验，不匹配报 `600012 当前优惠券不可用！`）；券包里原有的券拿不到 ID，只能把券面价手工代入比较，并标注"此价为券面价，非计价接口返回"。
- **计价结果和菜单标价可能不一致，必须告警而不是替用户猜。** 实测「麦辣鸡腿堡四件套」菜单标 ¥28，`calculate-price` 返回 ¥57。脚本会输出「需要核实的价差」区块。**看到这个区块必须原样转达给用户**，并说明"下单前请在麦当劳 App 核实"，绝不能直接拿其中一个价当作结论。

---

## 边界：不做什么

- **不下单、不付款。** `create-order` 只在用户明确说"下单"且给出完整门店/商品/取餐方式后才考虑，且必须先展示明细让用户确认。绝不自动下单。
- **默认不领券。** `auto-bind-coupons` 是写操作。雷达只提醒"可领"，用户说"帮我领"才执行。
- **不刷券。** 麦当劳条款禁止用脚本/机器人批量获取电子券，异常账号会被取消权益。查询类调用没问题，别做循环抢券。
- **不承诺券的有效性。** 券能否核销以麦当劳官方渠道为准，我们只做提醒和计算。

---

## 参考

`references/api-facts.md` — 实测字段结构、错误码、解析坑位、真实响应样例。改脚本前先看这个。
