# workbuddy.md · WorkBuddy 开发过程上下文

本项目使用 [WorkBuddy](https://www.workbuddy.cn) 全程开发。本文档按时间线记录关键开发对话上下文，用于 WorkBuddy 联动活动奖励核验。开发日期：2026-10-21。

## 阶段一 · 连接麦当劳 MCP

**用户意图**：接入麦当劳 MCP Token，参加麦当劳程序员创意开发大赛。

**关键排障过程**：WorkBuddy 配置文件中已存在 `mcd-mcp` 记录但始终连接失败。AI 通过读取守护进程日志定位根因——`Authorization` 请求头缺少 `Bearer ` 前缀，服务端将认证方案识别为 `other` 并返回 403。修正为 `Bearer <token>` 格式后握手成功。

**验证结果**：
- `initialize` 握手 200，服务端返回 `mcd-mcp v1.0.0`
- `tools/list` 拉取到 **35 个工具**
- 真实业务调用验证：`now-time-info` 返回服务器时间、`campaign-calendar` 返回当月活动日历

## 需求探索与可行性分析

**用户意图**：想在公众号文章里给读者"即时赠送麦当劳优惠券"。

**AI 实测结论**（基于真实账号数据）：
- `query-my-coupons` 不含 `couponId`/`couponCode`，券在系统内与账号绑定，无转赠载体
- 商城券条款原文（`mall-product-detail` 的 `note` 字段）第 7、9 条明确禁止转让、转售、转发、代下单
- 微信公众号图文无"阅读完成度"数据，无法实现"读完才给券"
- 结论转向合规替代方案：MCP 定位为"今日好券情报引擎"，读者用自己的账号领券

**用户追问**：MCP 能接入网页/小程序/本地 APP 吗？AI 实测 CORS（预检 OPTIONS 返回 403、响应无 `access-control-allow-origin`），给出"前端不可直连、需自建后端持 token"的架构结论。

## 阶段二 · 功能收敛：捡漏雷达 + 最省点单器

用户从候选方案中选定两个功能合并开发。AI 先用真实 MCP 调用实测了完整链路：

- `query-nearby-stores`：发现 `searchType=2` 时 `city` 与 `keyword` 必须同时传，缺一报 `600058`
- `query-meals`：发现 `meals` 是以商品 code 为键的字典；`currentPrice`/`originalPrice` 单位为元
- `calculate-price`：发现金额单位为**分**；`originalPrice` 等于菜单现价而非营销划线价；实测"麦辣四件套菜单标 ¥28 但计价返回 ¥57"的价差问题，决定内置告警而非猜测

## 阶段三 · Skill 开发与实测

AI 将两个功能封装为 WorkBuddy Skill `mcd-saver`：

- `SKILL.md`：触发词、两模式流程、三条铁律（分vs元、划线价口径、券ID获取路径）、合规边界（不下单/不刷券/不代下单）
- `scripts/mcd.py`：自带 MCP 客户端的纯标准库引擎，支持 `radar` / `stores` / `menu` / `price` / `call` 五个子命令；token 运行时读取，永不打印
- `references/api-facts.md`：全部实测字段结构与错误码沉淀

**实测运行结果**（真实账号）：
- 雷达输出：2 张券 2.3 天后到期、积分 130.4（已过期 1172.1）、可抽 5 次、可领免费脆薯饼
- 比价输出：三方案对比，"辣么快乐套餐 ¥24 比麦辣四件套省 ¥33"

**每日自动化**：创建定时任务「麦麦捡漏雷达 · 每日 8:00」（只读模式：只查询提醒，不自动领券）。

## 阶段四 · 写操作实测与扩展

用户授权后执行 `auto-bind-coupons` 成功领取 1 张"免费脆薯饼"。**重要发现**：该工具返回带 `couponId`/`couponCode`，且 `calculate-price` 支持接收券 ID（实测会校验券适用性，早餐券晚间下单返回 `600012 当前优惠券不可用`）——修正了此前"券无法程序化算进比价"的判断。

活动口碑分析：`campaign-calendar` 提取 12 项活动的优惠力度，结合公开测评补充口碑结论（蓝莓爆爆珠麦旋风口碑最高、芝士棒升级款差评集中），生成图文日报。

## 阶段五 · 报告视觉化与参赛交付

用户要求把 markdown 日报改为视觉化版本，AI 生成麦当劳红金海报风 HTML 报告（票券式券包、优惠力度条形排行、口碑评分条、抽奖决策卡、活动时间轴），即本仓库 `examples/daily-report-demo.html`。

最后按比赛要求组装本仓库（README.md / CONTEST_DECLARATION.md / MCP_INTEGRATION.md / workbuddy.md / 源代码），推送 GitHub 公开仓库并按标准格式提交报名 Issue。

## WorkBuddy 使用要点沉淀

1. 自定义 MCP 请求头必须带 `Bearer ` 前缀，配置后需重启应用加载
2. MCP 返回文本是"markdown 说明 + JSON + markdown 提示"的混合体，需用 `raw_decode` 从 `{"success"` 位置截取解析
3. Skill 引擎自带 MCP 客户端（脚本直连）比依赖会话内 MCP 工具挂载更可靠，还能做跨天快照比对
