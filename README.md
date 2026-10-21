# 麦麦省钱助手 McDSaver 🍟

> 基于**麦当劳中国官方 MCP**（`https://mcp.mcd.cn`）开发的两用省钱助手：
> 一个帮你**盯住该出手的时候**（捡漏雷达），一个帮你**算清怎么买最省**（最省点单器）。

**参赛项目 · 麦当劳程序员节创意开发大赛（mcd-developer-innovation-challenge）**

---

## 这是什么

很多人有麦当劳优惠券，但券总是在过期后才想起来；点单时也不知道套餐、单点、加购哪个组合最划算。McDSaver 把这两件事交给 AI：

| 模式 | 解决的问题 | 数据来源 |
|---|---|---|
| 🚨 **捡漏雷达** | 新券上架不知道、券/积分悄悄过期、抽奖次数白白浪费 | `available-coupons`、`query-my-coupons`、`query-my-account`、`query-lottery-info`、`campaign-calendar` |
| 💰 **最省点单器** | 单点还是套餐？哪个组合实付最低？ | `query-nearby-stores`、`query-meals`、`calculate-price`（真实计价接口，非估算） |

两大特色设计：

1. **信号式日报，而不是信息倾倒**——雷达只输出你需要"出手"的事：新券上架、券到期倒计时、积分到期、剩余抽奖次数。没有紧急项时会明确说"暂时没有紧急项"，绝不编造提醒。
2. **真实计价比价**——调用官方 `calculate-price` 接口逐方案计算实付（金额单位为"分"，已自动换算），并内置了两项实测发现的坑位防护：菜单划线价与计价原价的口径区分、计价结果与菜单标价不一致时的「需要核实的价差」告警。

## 快速开始

### 1. 准备 MCP Token

前往 [麦当劳 MCP 控制台](https://mcp.mcd.cn) 申请 Token，然后二选一：

- **环境变量（推荐）**：`export MCD_MCP_TOKEN=你的token`
- **WorkBuddy 配置**：在 `~/.workbuddy/mcp.json` 中配置：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": { "Authorization": "Bearer YOUR_MCP_TOKEN" }
    }
  }
}
```

> ⚠️ Token **只在运行时从环境变量或本地配置读取**，本项目源代码中不含任何真实凭证。注意 `Bearer ` 前缀必须保留（实测缺失会返回 403）。

### 2. 运行

依赖：Python 3.10+，无第三方依赖（纯标准库）。

```bash
# 🚨 捡漏雷达：四路信号合成一条日报
python scripts/mcd.py radar
python scripts/mcd.py radar --hours 48        # 券到期预警窗口改为 48 小时

# 📍 定门店（city 和 keyword 必须都传）
python scripts/mcd.py stores --city 深圳市 --keyword 科技园 --limit 5

# 🍔 查菜单（拿 productCode 和价格）
python scripts/mcd.py menu --store 1420888 --q 麦辣 --limit 10

# 💰 最省点单器：多方案真实计价比价
python scripts/mcd.py price --store 1420888 \
    --plan "单点麦辣堡+可乐:1440:1,9900008751:1" \
    --plan "麦辣三件套:9900005456:1"

# 📞 直接调用任意 MCP 工具（35 个全量透传）
python scripts/mcd.py call --tool query-my-account --arguments "{}"
```

### 使用示例输出

**雷达模式（真实运行结果）：**

```
需要你出手
⏰ 11.9元麦辣鸡腿堡 还有 2.3 天过期（2026-10-23 23:59）
⏰ 19.9元王牌炸鸡任选2 还有 2.3 天过期
家底
积分：可用 130.4｜累计 1302.5｜已过期 1172.1
可用券：2 张（均 10-23 到期）
抽奖：24 分/次，你还能抽 5 次
今日活动：GD联名周边第二弹、韩式蘸酱上新、蓝莓爆爆珠麦旋风…
还能领：免费脆薯饼
```

**比价模式（真实运行结果）：**

```
| 方案           | 实付   | 建议                          |
|----------------|--------|-------------------------------|
| 辣么快乐套餐   | ¥24.0  | ✅ 选它比麦辣四件套省 ¥33.00  |
| 麦辣三件套     | ¥33.5  |                               |
| 麦辣四件套     | ¥57.0  | ⚠️ 与菜单标价 ¥28 不一致，需核实 |
```

可视化日报效果见 [`examples/daily-report-demo.html`](examples/daily-report-demo.html)（浏览器打开即可）。

## 作为 WorkBuddy Skill 使用

本仓库同时是一份标准的 [WorkBuddy Skill](https://www.workbuddy.cn)。将 `SKILL.md`、`scripts/`、`references/` 复制到 `~/.workbuddy/skills/mcd-saver/` 后，在 WorkBuddy 对话里直接说：

- "今天有什么券要过期"
- "两个人吃预算 50，想吃辣，怎么点最省"
- "公司在科技园，附近哪家麦当劳"

WorkBuddy 会自动识别意图并调用本 Skill（详见 [`SKILL.md`](SKILL.md) 中的触发词与流程约定）。

## 目标用户

- **麦门常客**：每周至少吃一次麦当劳、有券但总忘记用的人
- **价格敏感型点单者**：想知道"套餐还是单点、怎么组合最省"的人
- **公众号 / 本地生活内容创作者**：用雷达输出做每日省钱情报栏目，用活动日历做选题库
- **WorkBuddy / MCP 开发者**：`references/api-facts.md` 沉淀了 35 个工具的实测字段结构与踩坑记录，可直接复用

## 项目结构

```
mcd-saver/
├── README.md                 # 本文件
├── CONTEST_DECLARATION.md    # 参赛声明（官方原文，未改动）
├── MCP_INTEGRATION.md        # 麦当劳 MCP 集成说明（工具、调用流程、业务价值）
├── workbuddy.md              # WorkBuddy 开发过程上下文
├── SKILL.md                  # WorkBuddy Skill 定义（触发词、流程、边界）
├── scripts/
│   └── mcd.py                # 核心引擎：自带 MCP 客户端，纯标准库
├── references/
│   └── api-facts.md          # 35 个工具实测字段结构、错误码、踩坑记录
└── examples/
    └── daily-report-demo.html # 可视化日报效果演示
```

## 设计边界（合规优先）

- **不下单、不付款**：`create-order` 等写操作一律需要用户显式确认，绝不自动执行
- **不刷券**：查询类调用正常使用；绝不批量循环抢券（违反麦当劳条款）
- **不代下单**：券面条款明确禁止代下单、代买，本工具只做提醒与计算
- **数据口径诚实**：所有价格标注来源（计价接口 / 菜单标价 / 券面价），三者不一致时告警而不是替用户猜

## 免责声明

本项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，非麦当劳官方产品。项目输出仅供参考，不构成医疗、营养或其他专业建议；餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准。
