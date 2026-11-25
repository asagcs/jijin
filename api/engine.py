# -*- coding: utf-8 -*-
"""
fundlife 规则引擎
- 读取 config.json（基金清单 + 规则）与 state.json（每日累计状态）
- 应用当天涨跌幅，更新净值指数、阶段低点、成本、当前市值
- 按「科技核心 / 清理名单 / 海外 / 防守」四类规则给出处理建议，并合并同一只基金的多条动作
- 输出组合体检（科技占比、现金比例、单只上限、回撤风控）
"""
import json
import os
import re
import datetime

from api.paths import project_root

BASE = project_root()
CONFIG_PATH = os.path.join(BASE, "config.json")
STATE_PATH = os.path.join(BASE, "state.json")
REPORT_DIR = os.path.join(BASE, "reports")
INPUT_DIR = os.path.join(BASE, "daily_inputs")
INPUT_PATH = os.path.join(BASE, "today.txt")

PRIORITY_ORDER = ["必做", "择机", "观察", "持有"]


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def today_str():
    return datetime.date.today().isoformat()


def normalize_date(value=None):
    """统一成 YYYY-MM-DD。网页在部分电脑上会传来 2026/11/25，不能直接当文件名。"""
    if value in (None, ""):
        return today_str()
    text = str(value).strip().replace("/", "-").replace(".", "-")
    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    text = re.sub(r"\s+", "", text)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if not m:
        return today_str()
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return today_str()


_DEFAULT_PLAN_LABELS = {
    "CORE": "科技核心底仓-保留并小额定投",
    "CORE_OPT": "科技可选仓-精简时优先砍",
    "CLEAR": "清理名单-关定投+反弹分批卖",
    "HOLD": "海外宽基-持有不追加",
    "HOLD_DEF": "防守配置-持有不动",
}


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("funds", [])
    cfg.setdefault("plan_labels", dict(_DEFAULT_PLAN_LABELS))
    cfg.setdefault("profile", {})
    cfg["profile"].setdefault("capital_total", 0)
    cfg["profile"].setdefault("injected", 0)
    cfg["profile"].setdefault("baseline_date", "")
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_state(cfg):
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return init_state(cfg)


def init_state(cfg):
    st = {
        "created_at": now_str(),
        "updated_at": now_str(),
        "baseline_date": cfg["profile"]["baseline_date"],
        "runs": 0,
        "funds": {},
        "history": [],
    }
    for f in cfg["funds"]:
        amt = float(f["amount"])
        rate = float(f["rate"]) / 100.0
        cost = amt / (1 + rate) if (1 + rate) != 0 else amt
        st["funds"][f["id"]] = {
            "amount": round(amt, 2),
            "cost": round(cost, 2),
            "px": 100.0,
            "px_min": 100.0,
            "px_max": 100.0,
            "dca_on": bool(f.get("dca")),
            "last_pct": 0.0,
            "last_date": cfg["profile"]["baseline_date"],
            "sold": 0.0,
            "notes": [],
        }
    return st


def save_state(st):
    st["updated_at"] = now_str()
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


_WEEKDAY = "一二三四五六日"


def fund_dca(f):
    """返回 (cycle, weekday, amount)。旧配置没有周期时，按每周、金额用 dca_weekly。"""
    cycle = f.get("dca_cycle") or "weekly"
    if cycle not in ("daily", "weekly"):
        cycle = "weekly"
    raw = f.get("dca_amount")
    if raw in (None, ""):
        raw = f.get("dca_weekly") or 0
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        amount = 0.0
    try:
        weekday = int(f.get("dca_weekday") or 0)
    except (TypeError, ValueError):
        weekday = 0
    if cycle == "daily" or not (1 <= weekday <= 7):
        weekday = 0
    return cycle, weekday, amount


def dca_text(f):
    cycle, weekday, amount = fund_dca(f)
    amt = f"{amount:.0f}" if amount == int(amount) else f"{amount:.2f}"
    if cycle == "daily":
        return f"每日 {amt} 元"
    if 1 <= weekday <= 7:
        return f"每周{_WEEKDAY[weekday - 1]} {amt} 元"
    return f"每周 {amt} 元"


# ---------------- 每日应用 ----------------

def apply_changes(cfg, st, changes, date=None):
    """changes: {fund_id: pct}，pct 为当天涨跌幅百分数，如 -1.25。"""
    date = normalize_date(date)
    st["runs"] = st.get("runs", 0) + 1
    applied = []
    for fid, pct in changes.items():
        s = st["funds"].get(fid)
        if s is None:
            continue
        k = 1.0 + float(pct) / 100.0
        s["px"] = round(s["px"] * k, 6)
        s["px_min"] = min(s["px_min"], s["px"])
        s["px_max"] = max(s["px_max"], s["px"])
        s["amount"] = round(s["amount"] * k, 2)
        s["last_pct"] = float(pct)
        s["last_date"] = date
        applied.append({"id": fid, "pct": float(pct)})
    st["history"].append({"date": date, "run_at": now_str(), "changes": applied})
    st["history"] = st["history"][-400:]
    return st


# ---------------- 单只规则 ----------------

def _item(f, action, priority, reason, money=None, ratio=None):
    return {
        "fund_id": f["id"],
        "name": f["name"],
        "plan": f["plan"],
        "action": action,
        "priority": priority,
        "money": money,
        "ratio": ratio,
        "reason": reason,
    }


def judge_fund(cfg, st, f):
    R = cfg["rules"]
    s = st["funds"][f["id"]]
    amt = s["amount"]
    pct = s["last_pct"]
    plan = f["plan"]
    rate = (amt / s["cost"] - 1) if s["cost"] else 0.0
    cap = float(cfg["profile"]["capital_total"])
    items = []

    # 清理名单：定投必须先关（第一次提醒算必做，之后降级为观察，避免每天重复刷屏）
    if plan == "CLEAR" and s["dca_on"]:
        first = not s.get("dca_warned")
        s["dca_warned"] = True
        reason = f"清理名单不能继续摊低成本，把{dca_text(f)}的定投关掉"
        if not first:
            reason += "（已提醒过，若已关闭请执行 --dca-off 让我记住）"
        items.append(_item(f, "关闭定投", "必做" if first else "观察", reason))

    if plan == "CLEAR":
        cr = R["clear"]
        rebound = (s["px"] / s["px_min"] - 1) * 100 if s["px_min"] else 0.0
        if pct <= cr["no_sell_if_drop"]:
            items.append(_item(f, "不卖，等反弹", "观察",
                               f"今日跌 {pct:.2f}%，跌超 {abs(cr['no_sell_if_drop'])}% 不卖出，避免卖在低点"))
        elif pct >= cr["single_day_strong"]:
            items.append(_item(f, f"卖出 {int(cr['single_day_sell']*100)}%", "择机",
                               f"单日涨 {pct:.2f}%（≥{cr['single_day_strong']}%），强势日先兑现一部分",
                               money=round(amt * cr["single_day_sell"], 2), ratio=cr["single_day_sell"]))
        elif rebound >= cr["rebound_tier2"]:
            items.append(_item(f, "清空剩余", "必做",
                               f"自低点累计反弹 {rebound:.2f}%（≥{cr['rebound_tier2']}%），按计划清干净",
                               money=round(amt, 2), ratio=1.0))
        elif rebound >= cr["rebound_tier1"]:
            items.append(_item(f, f"卖出 {int(cr['sell_tier1']*100)}%", "择机",
                               f"自低点累计反弹 {rebound:.2f}%（≥{cr['rebound_tier1']}%），卖一半，剩余等更高档",
                               money=round(amt * cr["sell_tier1"], 2), ratio=cr["sell_tier1"]))
        else:
            items.append(_item(f, "持有等反弹", "持有",
                               f"低点反弹 {rebound:.2f}%，未到 {cr['rebound_tier1']}% 出手档"))

    elif plan == "CORE":
        cc = R["core"]
        if rate >= cc["trim_profit_rate"] / 100.0:
            items.append(_item(f, "分批止盈 30%", "择机",
                               f"持有收益率 {rate*100:+.1f}%，已到 {cc['trim_profit_rate']}% 止盈线",
                               money=round(amt * 0.3, 2), ratio=0.3))
        elif pct <= cc["add_on_drop"]:
            cycle, _weekday, each = fund_dca(f)
            base = each if each > 0 else float(cc["base_weekly"])
            add = round(base * cc["add_times"], 2)
            items.append(_item(f, "定投加码一次", "择机",
                               f"今日跌 {pct:.2f}%（≤{cc['add_on_drop']}%），用预备金加 {cc['add_times']} 倍这一笔定投",
                               money=add))
        elif pct >= cc["pause_on_rise"]:
            cycle, _weekday, _each = fund_dca(f)
            pause = "暂停今日定投" if cycle == "daily" else "暂停本周定投"
            items.append(_item(f, pause, "择机",
                               f"今日涨 {pct:.2f}%（≥{cc['pause_on_rise']}%），大涨日不加仓"))
        else:
            items.append(_item(f, "维持小额定投", "持有",
                               f"波动在常态区间，按{dca_text(f)}继续", money=fund_dca(f)[2]))

    elif plan == "CORE_OPT":
        items.append(_item(f, "持有，不加仓", "持有",
                           f"可选仓，浮亏 {rate*100:+.1f}%，等整体精简时一次性处理"))
        if s["dca_on"]:
            items.append(_item(f, "可关闭定投", "择机",
                               f"若决定精简，先停掉{dca_text(f)}的定投"))

    elif plan == "HOLD":
        band = R["hold"]["watch_band"]
        if abs(pct) >= band:
            items.append(_item(f, "只记录，不动", "观察",
                               f"今日 {pct:+.2f}%，波动虽大但仓位小，不因单日波动调仓"))
        else:
            items.append(_item(f, "持有不追加", "持有", "海外宽基作对冲底仓，暂停大额追加"))

    elif plan == "HOLD_DEF":
        items.append(_item(f, "持有不动", "持有", "防守配置，不清理也不追加"))

    if plan in ("CORE", "CORE_OPT") and amt > cap * R["single_fund_cap_ratio"]:
        items.append(_item(f, "触单只上限", "观察",
                           f"该只 {amt:.0f} 元，超单只上限 {cap*R['single_fund_cap_ratio']:.0f} 元，不再加仓"))

    return items


def merge(items):
    """同一只基金多条动作合并成一条，优先级取最强的，动作与理由拼接。"""
    order = {p: i for i, p in enumerate(PRIORITY_ORDER)}
    m = {}
    out = []
    for it in items:
        fid = it["fund_id"]
        if fid not in m:
            rec = {
                "fund_id": fid, "name": it["name"], "plan": it["plan"],
                "priority": it["priority"], "actions": [], "reasons": [],
                "money": None, "ratio": None,
            }
            m[fid] = rec
            out.append(rec)
        rec = m[fid]
        if order.get(it["priority"], 9) < order.get(rec["priority"], 9):
            rec["priority"] = it["priority"]
        if it["action"] not in rec["actions"]:
            rec["actions"].append(it["action"])
        if it["reason"] not in rec["reasons"]:
            rec["reasons"].append(it["reason"])
        if rec["money"] is None and it["money"] is not None:
            rec["money"] = it["money"]
        if rec["ratio"] is None and it["ratio"] is not None:
            rec["ratio"] = it["ratio"]
    out.sort(key=lambda r: (order.get(r["priority"], 9), -(r["money"] or 0)))
    return out


def portfolio_snapshot(cfg, st):
    R = cfg["rules"]
    cap = float(cfg["profile"]["capital_total"])
    total = sum(s["amount"] for s in st["funds"].values())
    cost_total = sum(s["cost"] for s in st["funds"].values())
    tech = sum(st["funds"][f["id"]]["amount"] for f in cfg["funds"] if f.get("tech"))
    pnl = total - cost_total
    p = {
        "total": round(total, 2),
        "cost_total": round(cost_total, 2),
        "pnl": round(pnl, 2),
        "rate": round(pnl / cost_total * 100, 2) if cost_total else 0.0,
        "capital": cap,
        "cash": round(cap - total, 2),
        "cash_ratio": round((cap - total) / cap * 100, 2) if cap else 0.0,
        "tech": round(tech, 2),
        "tech_ratio": round(tech / cap * 100, 2) if cap else 0.0,
        "fund_count": sum(1 for s in st["funds"].values() if s["amount"] > 0.5),
        "dca_count": sum(1 for f in cfg["funds"]
                         if st["funds"][f["id"]]["dca_on"] and st["funds"][f["id"]]["amount"] > 0.5),
    }
    warnings = []
    if cap > 0 and p["tech_ratio"] > R["tech_cap_ratio"] * 100:
        warnings.append(f"科技相关占比 {p['tech_ratio']:.1f}%，超上限 {R['tech_cap_ratio']*100:.0f}%，"
                        f"需要减掉约 {p['tech'] - cap*R['tech_cap_ratio']:.0f} 元科技仓")
    if cap > 0 and p["cash_ratio"] < R["cash_min_ratio"] * 100:
        warnings.append(f"现金/预备金只剩 {p['cash_ratio']:.1f}%，低于 {R['cash_min_ratio']*100:.0f}%，停止一切新增加仓")
    if p["rate"] <= -R["account_stop_add_drawdown"] * 100:
        warnings.append(f"账户整体回撤 {p['rate']:.1f}%，触发 {R['account_stop_add_drawdown']*100:.0f}% 风控线，只减不加")
    if p["fund_count"] > 10:
        warnings.append(f"持仓仍有 {p['fund_count']} 只，目标精简到 6~8 只")
    for f in cfg["funds"]:
        s = st["funds"][f["id"]]
        if cap > 0 and s["amount"] > cap * R["single_fund_cap_ratio"] and f["plan"] != "CLEAR":
            warnings.append(f"{f['name']} 市值 {s['amount']:.0f} 元，超单只上限 {cap*R['single_fund_cap_ratio']:.0f} 元")
    return p, warnings


def judge(cfg, st):
    items = []
    for f in cfg["funds"]:
        if st["funds"][f["id"]]["amount"] <= 0.5:
            continue
        items.extend(judge_fund(cfg, st, f))
    p, warnings = portfolio_snapshot(cfg, st)
    return merge(items), p, warnings


# ---------------- 输出 --------------

def _label(rec):
    if rec["money"]:
        return f"，约 {rec['money']:.0f} 元"
    return ""


def format_console(records, portfolio, warnings, date):
    lines = []
    lines.append(f"======== 基金处理建议 {date} ========")
    lines.append(f"总市值 {portfolio['total']:.2f} 元 | 持仓盈亏 {portfolio['pnl']:+.2f} 元 "
                 f"({portfolio['rate']:+.2f}%) | 持有 {portfolio['fund_count']} 只 | 定投中 {portfolio['dca_count']} 只")
    lines.append(f"科技相关 {portfolio['tech_ratio']:.1f}%（上限 35%）| 现金/预备金 {portfolio['cash']:.0f} 元 "
                 f"({portfolio['cash_ratio']:.1f}%，目标 30%）")

    g = {k: [] for k in PRIORITY_ORDER}
    for r in records:
        g.setdefault(r["priority"], []).append(r)

    for p in PRIORITY_ORDER:
        rs = g.get(p, [])
        if not rs:
            continue
        lines.append("")
        lines.append(f"【{p}】{len(rs)} 只")
        if p == "持有":
            for r in rs:
                lines.append(f"  · {r['name']}：{' + '.join(r['actions'])}")
            continue
        for r in rs:
            lines.append(f"  · {r['name']} → {' + '.join(r['actions'])}{_label(r)}")
            for reason in r["reasons"]:
                lines.append(f"      {reason}")

    if warnings:
        lines.append("")
        lines.append("【组合体检】")
        for w in warnings:
            lines.append(f"  ! {w}")

    money_sell = sum(r["money"] or 0 for r in records if r["ratio"])
    if money_sell > 0:
        lines.append("")
        lines.append(f"【今日回收资金】按建议卖出合计约 {money_sell:.0f} 元，卖出后先放货币/短债，不马上换赛道。")
    lines.append("")
    lines.append("提示：以上为纪律执行清单，不构成投资建议。")
    return "\n".join(lines)


def write_report(records, portfolio, warnings, date, ai_text=None):
    date = normalize_date(date)
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"{date}.md")
    g = {k: [] for k in PRIORITY_ORDER}
    for r in records:
        g.setdefault(r["priority"], []).append(r)

    md = [f"# 基金每日处理建议 · {date}", "",
          f"> 生成时间 {now_str()}｜规则 `config.json`｜状态 `state.json`", "",
          "## 组合快照", "",
          f"- 总市值 {portfolio['total']:.2f} 元，持仓盈亏 {portfolio['pnl']:+.2f} 元（{portfolio['rate']:+.2f}%）",
          f"- 科技相关占比 {portfolio['tech_ratio']:.1f}%（上限 35%）",
          f"- 现金/预备金 {portfolio['cash']:.0f} 元（{portfolio['cash_ratio']:.1f}%，目标 30%）",
          f"- 持仓 {portfolio['fund_count']} 只，定投中 {portfolio['dca_count']} 只", ""]

    for p in PRIORITY_ORDER:
        rs = g.get(p, [])
        if not rs:
            continue
        md += [f"## {p}（{len(rs)} 只）", ""]
        for r in rs:
            md.append(f"- **{r['name']}**：{' + '.join(r['actions'])}{_label(r)}")
            for reason in r["reasons"]:
                md.append(f"  - {reason}")
        md.append("")

    if warnings:
        md += ["## 组合体检", ""]
        md += [f"- {w}" for w in warnings]
        md.append("")

    if ai_text:
        md += ["## DeepSeek 复核", "", ai_text.strip(), ""]

    md.append("> 仅为个人纪律提示，不构成投资建议。")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    return path
