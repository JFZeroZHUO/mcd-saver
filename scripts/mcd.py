#!/usr/bin/env python3
"""麦当劳 MCP 省钱引擎：捡漏雷达 + 最省点单器。

直接以 MCP 客户端身份调用 https://mcp.mcd.cn（Streamable HTTP + Bearer）。
Token 从 ~/.workbuddy/mcp.json 读取，也可用环境变量 MCD_MCP_TOKEN 覆盖。

用法:
  mcd.py radar                     捡漏雷达（券/积分/抽奖/活动 + 与上次快照比对）
  mcd.py stores --city 深圳市 --keyword 科技园 [--be-type 1]
  mcd.py menu --store 1420888 [--q 麦辣] [--limit 30]
  mcd.py price --store 1420888 --plan "单点:1440:1,9900008751:1" --plan "套餐:9900005456:1"
  mcd.py price --store 1420888 --items 1440:1,9900008751:1
  mcd.py call --tool query-my-account           手工调任意工具（调试用）
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

ENDPOINT = "https://mcp.mcd.cn"
SKILL_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = SKILL_DIR / "state"
LATEST = STATE_DIR / "latest.json"

# ---------------------------------------------------------------- 基础设施


def load_token() -> str:
    tok = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if tok:
        return tok
    cfg = Path(os.path.expanduser("~")) / ".workbuddy" / "mcp.json"
    if not cfg.exists():
        sys.exit(f"找不到 {cfg}，请先配置 mcd-mcp 或设置 MCD_MCP_TOKEN")
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception as e:
        sys.exit(f"mcp.json 解析失败: {e}")
    srv = (data.get("mcpServers") or {}).get("mcd-mcp") or {}
    auth = ((srv.get("headers") or {}).get("Authorization") or "").strip()
    if not auth:
        sys.exit("mcp.json 里 mcd-mcp 缺少 headers.Authorization")
    return re.sub(r"^Bearer\s+", "", auth, flags=re.I).strip()


def rpc(name: str, args: dict, timeout: int = 30) -> str:
    """调用一个 MCP 工具，返回 content 里拼接后的文本。"""
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": name, "arguments": args}},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + load_token(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        if e.code == 401:
            sys.exit("401：MCP Token 无效或已过期，请重新获取")
        if e.code == 429:
            sys.exit("429：触发限流（600 次/分钟），稍后再试")
        sys.exit(f"HTTP {e.code}: {detail}")
    except Exception as e:
        sys.exit(f"网络异常: {e}")

    if raw.lstrip().startswith("event:"):
        parts = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
        raw = "".join(parts)
    try:
        payload = json.loads(raw)
    except Exception:
        return raw
    if "error" in payload:
        return f"[MCP error] {payload['error']}"
    return "".join(c.get("text", "") for c in payload.get("result", {}).get("content", []))


def extract_json(text: str):
    """MCP 返回常是「说明文字 + JSON + 提示」，从中救出第一个可解析对象。"""
    for pat in ('{"success"', '{"code"', '{"data"'):
        idx = 0
        while True:
            i = text.find(pat, idx)
            if i < 0:
                break
            try:
                obj, _ = json.JSONDecoder().raw_decode(text[i:])
                return obj
            except Exception:
                idx = i + 1
    return None


def yuan(fen) -> str:
    """分 → 元，去掉多余的 .0"""
    try:
        v = float(fen) / 100.0
    except (TypeError, ValueError):
        return str(fen)
    return f"{v:.2f}".rstrip("0").rstrip(".")


def parse_dt(s: str):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except Exception:
            continue
    return None


# ---------------------------------------------------------------- 解析器


def parse_available(text: str):
    """麦麦省券列表：- 优惠券标题：X / 状态：可领取|已领取"""
    out = []
    blocks = re.split(r"\n(?=- )", text)
    for b in blocks:
        t = re.search(r"优惠券标题：\s*([^\n\\]+)", b)
        s = re.search(r"状态：\s*([^\n\\]+)", b)
        if t:
            out.append({
                "title": t.group(1).strip(),
                "status": (s.group(1).strip() if s else "未知"),
            })
    return out


def parse_my_coupons(text: str):
    """我的券：## 标题 / **有效期** / **标签**"""
    out = []
    for blk in re.split(r"\n(?=## )", text):
        m = re.match(r"##\s+(.+)", blk)
        if not m:
            continue
        title = m.group(1).strip()
        exp = re.search(r"\*\*有效期\*\*:\s*(.+)", blk)
        label = re.search(r"\*\*标签\*\*:\s*(.+)", blk)
        price = re.search(r"\*\*优惠\*\*:\s*(.+)", blk)
        end_dt = None
        if exp:
            dts = re.findall(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", exp.group(1))
            if dts:
                end_dt = parse_dt(dts[-1])
        out.append({
            "title": title,
            "end": end_dt.strftime("%Y-%m-%d %H:%M") if end_dt else "",
            "raw_expire": exp.group(1).strip() if exp else "",
            "label": label.group(1).strip() if label else "",
            "price": price.group(1).strip() if price else "",
        })
    return out


def parse_campaign(text: str):
    """活动日历：#### 2026年10月21日 今日  /  - **活动标题**：X"""
    out, cur, cur_tag = [], "", ""
    for line in text.splitlines():
        h = re.match(r"####\s*(.+)", line.strip())
        if h:
            cur = h.group(1).strip()
            cur_tag = "今日" if "今日" in cur else ("往期" if "往期" in cur else "未来")
            continue
        t = re.search(r"活动标题\*\*：\s*(.+)", line)
        if t and cur_tag:
            out.append({"title": t.group(1).strip(), "when": cur, "tag": cur_tag})
    return out


# ---------------------------------------------------------------- 雷达


def load_latest():
    if LATEST.exists():
        try:
            return json.loads(LATEST.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_latest(data):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LATEST.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_radar(args):
    now = datetime.now()
    prev = load_latest()

    acc_raw = extract_json(rpc("query-my-account", {})) or {}
    acc = acc_raw.get("data") or {}
    av = parse_available(rpc("available-coupons", {}))
    mine = parse_my_coupons(rpc("query-my-coupons", {"page": "1", "pageSize": "50"}))
    lot_raw = extract_json(rpc("query-lottery-info", {})) or {}
    lot = lot_raw.get("data") or {}
    camp = parse_campaign(rpc("campaign-calendar", {}))

    # ---- 信号一：新上架券（可领取但上次没有）
    prev_avail = {c["title"] for c in prev.get("available", [])}
    new_avail = [c for c in av if c["status"] == "可领取" and c["title"] not in prev_avail]

    # ---- 信号二：券到期倒计时
    expiring = []
    for c in mine:
        dt = parse_dt(c["end"]) if c["end"] else None
        if dt:
            left = (dt - now).total_seconds() / 3600
            if 0 <= left <= args.hours:
                c["hours_left"] = round(left, 1)
                expiring.append(c)

    # ---- 信号三：积分到期
    pts = {
        "available": acc.get("availablePoint", "?"),
        "expiring_this_month": acc.get("currentMouthExpirePoint", "0"),
        "expiring_next_month": acc.get("nextMouthExpirePoint", "0"),
        "already_expired": acc.get("expiredPoint", "0"),
    }
    try:
        points_risk = float(pts["expiring_this_month"] or 0) > 0
    except ValueError:
        points_risk = False

    # ---- 信号四：抽奖可抽次数
    draw_point = lot.get("drawPoint") or "?"
    can_draw = 0
    try:
        can_draw = int(float(pts["available"]) // float(draw_point))
    except Exception:
        pass

    today_camp = []
    seen_camp = set()
    for c in camp:
        if c["tag"] == "今日" and c["title"] not in seen_camp:
            seen_camp.add(c["title"])
            today_camp.append(c)

    # ---- 输出
    L = []
    L.append(f"# 麦麦捡漏雷达 · {now.strftime('%m-%d %H:%M')}")
    L.append("")
    alerts = []
    if expiring:
        for c in expiring:
            h = c["hours_left"]
            when = f"{h/24:.1f} 天" if h >= 24 else f"{h} 小时"
            alerts.append(f"⏰ **{c['title']}** 还有 {when}过期（{c['end']}）")
    if points_risk:
        alerts.append(f"💧 本月有 **{pts['expiring_this_month']} 积分** 将过期，别攒着")
    if new_avail:
        for c in new_avail:
            alerts.append(f"🎫 新券上架：**{c['title']}**（未领取）")
    if alerts:
        L.append("## 需要你出手")
        L.extend("- " + a for a in alerts)
    else:
        L.append("## 需要你出手")
        L.append("- 暂时没有紧急项，券和积分都还安全")
    L.append("")

    L.append("## 家底")
    L.append(f"- 积分：可用 **{pts['available']}**｜累计 {acc.get('accumulativePoint','?')}｜"
             f"已过期 {pts['already_expired']}")
    L.append(f"- 可用券：**{len(mine)} 张**" + (
        "（" + "、".join(f"{c['title']}@{c['end'][5:10]}" for c in mine) + "）" if mine else ""))
    L.append(f"- 抽奖：{draw_point} 分/次，你还能抽 **{can_draw} 次**")
    L.append("")

    if today_camp:
        L.append("## 今日活动")
        for c in today_camp[:5]:
            L.append(f"- {c['title']}")
        L.append("")

    unclaimed = [c for c in av if c["status"] == "可领取"]
    if unclaimed:
        L.append("## 还能领")
        L.append("- " + "、".join(c["title"] for c in unclaimed))

    print("\n".join(L))

    save_latest({
        "date": now.strftime("%Y-%m-%d %H:%M"),
        "available": av,
        "my_coupons": mine,
        "account": pts,
        "campaigns": [c["title"] for c in today_camp],
    })


# ---------------------------------------------------------------- 门店 / 菜单


def cmd_stores(args):
    txt = rpc("query-nearby-stores", {
        "beType": args.be_type, "searchType": 2,
        "city": args.city, "keyword": args.keyword,
    })
    j = extract_json(txt) or {}
    if not j.get("success"):
        sys.exit(f"门店查询失败：{j.get('message') or txt[-200:]}")
    for s in (j.get("data") or [])[: args.limit]:
        print(f"{s.get('storeName')}\n  storeCode={s.get('storeCode')}  beCode={s.get('beCode') or '-'}  "
              f"预约={'支持' if s.get('reservation') else '不支持'}\n  {s.get('address','')}")


def cmd_menu(args):
    txt = rpc("query-meals", {
        "storeCode": args.store, "orderType": 1, "beType": 1,
    })
    j = extract_json(txt) or {}
    meals = ((j.get("data") or {}).get("meals") or {})
    if not meals:
        sys.exit(f"菜单查询失败：{txt[-200:]}")
    rows = []
    for code, m in meals.items():
        name = m.get("name", "")
        if args.q and args.q not in name:
            continue
        rows.append((name, code, m.get("currentPrice", ""), m.get("originalPrice", "")))
    rows.sort(key=lambda r: -float(r[2] or 0))
    for name, code, cur, orig in rows[: args.limit]:
        flag = "" if cur == orig else f"  (原价 {orig})"
        print(f"¥{cur:<7} {code:<12} {name}{flag}")


# ---------------------------------------------------------------- 比价


def price_plan(store, items):
    """items: [(productCode, qty)] -> dict 计价结果"""
    payload = [{"productCode": c, "quantity": q} for c, q in items]
    txt = rpc("calculate-price", {
        "storeCode": store, "orderType": 1, "beType": 1,
        "items": payload, "needTableware": False,
    })
    j = extract_json(txt) or {}
    if isinstance(j.get("data"), dict):  # calculate-price 外面套了一层 {success,data}
        j = j["data"]
    if not j or "price" not in j:
        raise RuntimeError(f"计价失败: {txt[-200:]}")
    return j


def parse_items(spec):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split(":")
        if len(bits) < 2:
            raise ValueError(f"商品写法应为 code:数量，收到 {part}")
        out.append((bits[0].strip(), int(bits[1])))
    return out


def parse_plan(spec):
    """'名称:code:qty,code:qty' -> (名称, [(code,qty)])"""
    if ":" not in spec:
        return "方案", parse_items(spec)
    name, _, rest = spec.partition(":")
    return name.strip(), parse_items(rest)


def menu_ref(store):
    """门店菜单参考价：code -> {name, current, original}。
    calculate-price 的 originalPrice 其实是当前菜单价，营销划线价只在这里。"""
    txt = rpc("query-meals", {"storeCode": store, "orderType": 1, "beType": 1})
    meals = ((extract_json(txt) or {}).get("data") or {}).get("meals") or {}
    ref = {}
    for code, m in meals.items():
        ref[code] = {
            "name": m.get("name", ""),
            "current": m.get("currentPrice", ""),
            "original": m.get("originalPrice", ""),
        }
    return ref


def cmd_price(args):
    plans = args.plan or ([f"方案:{args.items}"] if args.items else None)
    if not plans:
        sys.exit("需要 --plan 或 --items")

    results = []
    for spec in plans:
        name, items = parse_plan(spec)
        r = price_plan(args.store, items)
        results.append({"name": name, "r": r, "items": items})

    base = min(results, key=lambda x: x["r"]["price"])
    print(f"# 比价结果 · 门店 {args.store}")
    print("")
    print("| 方案 | 实付 | 商品小计 | 用券优惠 | 明细 |")
    print("|---|---|---|---|---|")
    for x in results:
        r = x["r"]
        detail = " + ".join(f"{p['productName']}×{p['quantity']}" for p in r.get("productList", []))
        disc = float(r.get("discount", 0))
        print(f"| {x['name']} | **¥{yuan(r['price'])}** | ¥{yuan(r.get('productOriginalPrice', r.get('originalPrice', 0)))} | "
              f"{'¥' + yuan(disc) if disc else '—'} | {detail} |")
    print("")
    if len(results) > 1:
        for x in results:
            if x is base:
                continue
            diff = (x["r"]["price"] - base["r"]["price"]) / 100.0
            if diff > 0:
                print(f"- 选 **{base['name']}** 比「{x['name']}」省 **¥{diff:.2f}**")

    # 营销划线价提示（接口不返回，从菜单补）
    try:
        ref = menu_ref(args.store)
        notes = []
        for x in results:
            for code, _q in x["items"]:
                m = ref.get(code) or {}
                try:
                    cur, orig = float(m.get("current") or 0), float(m.get("original") or 0)
                except ValueError:
                    continue
                if orig > cur > 0:
                    notes.append(f"- 「{m['name']}」菜单划线 ¥{orig:g}，现价 ¥{cur:g}（标识立省 ¥{orig-cur:.1f}）")
        if notes:
            print("")
            print("**菜单划线价参考**（calculate-price 不返回营销原价，此处取自门店菜单）")
            for n in dict.fromkeys(notes):
                print(n)

        # 计价接口与菜单标价不一致时必须提示，否则会误导
        warns = []
        for x in results:
            if len(x["items"]) != 1:
                continue
            code = x["items"][0][0]
            m = ref.get(code) or {}
            try:
                cur = float(m.get("current") or 0)
            except ValueError:
                continue
            paid = float(x["r"]["price"]) / 100.0
            if cur > 0 and abs(paid - cur) > 0.01:
                warns.append(
                    f"- ⚠️ 「{x['name']}」计价接口返回 ¥{paid:g}，但菜单标价 ¥{cur:g}。"
                    f"多为套餐未指定子项（roundList）或促销仅限官方渠道，**下单前请在麦当劳 App 核实**")
        if warns:
            print("")
            print("**需要核实的价差**")
            for w in dict.fromkeys(warns):
                print(w)
    except Exception:
        pass

    print("")
    print("- 实付金额来自 calculate-price 实时计算（接口单位为分，已换算为元）")


# ---------------------------------------------------------------- 调试


def cmd_call(args):
    try:
        payload = json.loads(args.arguments) if args.arguments else {}
    except Exception as e:
        sys.exit(f"--arguments 不是合法 JSON: {e}")
    print(rpc(args.tool, payload))


# ---------------------------------------------------------------- CLI


def main():
    p = argparse.ArgumentParser(description="麦当劳 MCP 省钱引擎")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("radar", help="捡漏雷达")
    r.add_argument("--hours", type=float, default=72,
                   help="券到期预警窗口（小时），默认 72")
    r.set_defaults(func=cmd_radar)

    s = sub.add_parser("stores", help="搜门店")
    s.add_argument("--city", required=True)
    s.add_argument("--keyword", required=True)
    s.add_argument("--be-type", type=int, default=1, choices=[1, 5])
    s.add_argument("--limit", type=int, default=8)
    s.set_defaults(func=cmd_stores)

    m = sub.add_parser("menu", help="查菜单")
    m.add_argument("--store", required=True)
    m.add_argument("--q", default="")
    m.add_argument("--limit", type=int, default=30)
    m.set_defaults(func=cmd_menu)

    pr = sub.add_parser("price", help="比价 / 计价")
    pr.add_argument("--store", required=True)
    pr.add_argument("--plan", action="append", help='"名称:code:qty,code:qty" 可多次')
    pr.add_argument("--items", help="code:qty,code:qty")
    pr.set_defaults(func=cmd_price)

    c = sub.add_parser("call", help="手工调工具")
    c.add_argument("--tool", required=True)
    c.add_argument("--arguments", default="")
    c.set_defaults(func=cmd_call)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
