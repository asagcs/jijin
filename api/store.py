# -*- coding: utf-8 -*-
"""
历史数据层：SQLite 存每日净值、组合快照、每日建议。
数据库位置：G:\\money\\data\\fundlife.db
Python 端（run.py）负责写入，Web 端（web.py）只读。
"""
import json
import os
import sqlite3
import datetime

from api import engine
from api.paths import project_root

BASE = project_root()
DATA_DIR = os.path.join(BASE, "data")
DB_PATH = os.path.join(DATA_DIR, "fundlife.db")
STATE_PATH = os.path.join(BASE, "state.json")
CONFIG_PATH = os.path.join(BASE, "config.json")


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS snapshot (
                date TEXT PRIMARY KEY,
                run_at TEXT,
                total REAL, cost_total REAL, pnl REAL, rate REAL,
                tech_ratio REAL, cash REAL, cash_ratio REAL,
                fund_count INTEGER, dca_count INTEGER,
                warnings TEXT
            );
            CREATE TABLE IF NOT EXISTS nav_daily (
                date TEXT, fund_id TEXT,
                pct REAL, amount REAL, cost REAL, px REAL, px_min REAL,
                PRIMARY KEY (date, fund_id)
            );
            CREATE TABLE IF NOT EXISTS advice (
                date TEXT, fund_id TEXT, name TEXT, plan TEXT, priority TEXT,
                actions TEXT, reasons TEXT, money REAL, ratio REAL,
                PRIMARY KEY (date, fund_id)
            );
            CREATE TABLE IF NOT EXISTS run_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, run_at TEXT, changes TEXT
            );
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, fund_id TEXT, name TEXT, side TEXT,
                amount REAL, to_fund_id TEXT, note TEXT, created_at TEXT
            );
            """
        )


def has_valuation(date):
    """这一天是否已经用涨跌幅生成过建议。只记调仓、没有涨跌幅的不算。"""
    init_db()
    with connect() as con:
        rows = con.execute("SELECT changes FROM run_log WHERE date=?", (date,)).fetchall()
    for row in rows:
        try:
            changes = json.loads(row["changes"] or "{}")
        except (TypeError, ValueError):
            continue
        if changes:
            return True
    return False


def record_run(date, cfg, st, records, portfolio, warnings, changes, replace_advice=True):
    """每次运行后落库：组合快照 + 每只基金当天净值 + 当天建议 + 运行日志。"""
    init_db()
    with connect() as con:
        con.execute(
            """INSERT INTO snapshot (date, run_at, total, cost_total, pnl, rate, tech_ratio,
                                     cash, cash_ratio, fund_count, dca_count, warnings)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(date) DO UPDATE SET
                 run_at=excluded.run_at, total=excluded.total, cost_total=excluded.cost_total,
                 pnl=excluded.pnl, rate=excluded.rate, tech_ratio=excluded.tech_ratio,
                 cash=excluded.cash, cash_ratio=excluded.cash_ratio,
                 fund_count=excluded.fund_count, dca_count=excluded.dca_count,
                 warnings=excluded.warnings""",
            (date, now_str(), portfolio["total"], portfolio["cost_total"], portfolio["pnl"],
             portfolio["rate"], portfolio["tech_ratio"], portfolio["cash"], portfolio["cash_ratio"],
             portfolio["fund_count"], portfolio["dca_count"], json.dumps(warnings, ensure_ascii=False)),
        )
        # 当天填了涨跌幅的基金才写净值记录；其余沿用 state 的当前值，写一份“保持不变”的记录便于曲线对齐
        changed_ids = set(changes.keys()) if changes else set()
        for fid in changed_ids:
            s = st["funds"][fid]
            con.execute(
                """INSERT INTO nav_daily (date, fund_id, pct, amount, cost, px, px_min)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(date, fund_id) DO UPDATE SET
                     pct=excluded.pct, amount=excluded.amount, cost=excluded.cost,
                     px=excluded.px, px_min=excluded.px_min""",
                (date, fid, s["last_pct"], s["amount"], s["cost"], s["px"], s["px_min"]),
            )
        if replace_advice:
            con.execute("DELETE FROM advice WHERE date=?", (date,))
            for r in records:
                con.execute(
                    """INSERT INTO advice (date, fund_id, name, plan, priority, actions, reasons, money, ratio)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (date, r["fund_id"], r["name"], r["plan"], r["priority"],
                     " + ".join(r["actions"]), "；".join(r["reasons"]),
                     r.get("money"), r.get("ratio")),
                )
        con.execute(
            "INSERT INTO run_log (date, run_at, changes) VALUES (?,?,?)",
            (date, now_str(), json.dumps(changes, ensure_ascii=False)),
        )


def save_trade(date, fund_id, name, side, amount, to_fund_id=None, note=""):
    init_db()
    with connect() as con:
        con.execute(
            """INSERT INTO trades (date, fund_id, name, side, amount, to_fund_id, note, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (date, fund_id, name, side, amount, to_fund_id, note, now_str()),
        )


# ---------------- 读：给 Web 用 ----------------
def load_state():
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_config():
    return engine.load_config()


def fetch_all():
    init_db()
    cfg = load_config()
    st = load_state()
    with connect() as con:
        snaps = [dict(r) for r in con.execute(
            "SELECT * FROM snapshot ORDER BY date").fetchall()]
        adv = [dict(r) for r in con.execute(
            "SELECT * FROM advice ORDER BY date, priority").fetchall()]
        navs = [dict(r) for r in con.execute(
            "SELECT * FROM nav_daily ORDER BY date").fetchall()]
        runs = con.execute("SELECT COUNT(*) c FROM run_log").fetchone()["c"]
        trades = [dict(r) for r in con.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT 40").fetchall()]

    # 每只基金建议出现次数
    adv_count = {}
    for a in adv:
        adv_count[a["fund_id"]] = adv_count.get(a["fund_id"], 0) + 1

    latest_date = snaps[-1]["date"] if snaps else None
    today_adv = {}
    for a in adv:
        if a["date"] == latest_date:
            today_adv[a["fund_id"]] = a

    funds = []
    if st:
        for f in cfg["funds"]:
            s = st["funds"].get(f["id"])
            if not s:
                continue
            amt = s["amount"]
            cost = s["cost"] or amt
            rebound = (s["px"] / s["px_min"] - 1) * 100 if s["px_min"] else 0.0
            a = today_adv.get(f["id"], {})
            untouched = (s.get("last_date") == st.get("baseline_date") and not s.get("last_pct"))
            funds.append({
                "id": f["id"], "name": f["name"], "plan": f["plan"],
                "plan_label": (cfg.get("plan_labels") or {}).get(f["plan"], f["plan"]),
                "tech": bool(f.get("tech")),
                "amount": round(amt, 2),
                "cost": round(cost, 2),
                "rate": round((amt / cost - 1) * 100, 2) if cost else 0.0,
                "rebound": round(rebound, 2),
                "last_pct": None if untouched else s.get("last_pct", 0.0),
                "last_date": s.get("last_date", ""),
                "dca_on": bool(s.get("dca_on")),
                "dca_cycle": engine.fund_dca(f)[0],
                "dca_weekday": engine.fund_dca(f)[1],
                "dca_amount": engine.fund_dca(f)[2],
                "dca_weekly": engine.fund_dca(f)[2],
                "today_action": a.get("actions", "（今日无记录）"),
                "today_priority": a.get("priority", ""),
                "today_money": a.get("money"),
                "advice_count": adv_count.get(f["id"], 0),
                "note": f.get("note", ""),
            })

    total = sum(x["amount"] for x in funds) if funds else 0.0
    tech = sum(x["amount"] for x in funds if x["tech"]) if funds else 0.0
    cost_total = sum(x["cost"] for x in funds) if funds else 0.0
    cap = float((cfg.get("profile") or {}).get("capital_total") or 0)
    summary = {
        "total": round(total, 2),
        "cost_total": round(cost_total, 2),
        "pnl": round(total - cost_total, 2),
        "rate": round((total - cost_total) / cost_total * 100, 2) if cost_total else 0.0,
        "tech_ratio": round(tech / cap * 100, 2) if cap else 0.0,
        "tech_amount": round(tech, 2),
        "cash": round(cap - total, 2),
        "cash_ratio": round((cap - total) / cap * 100, 2) if cap else 0.0,
        "capital": cap,
        "fund_count": sum(1 for x in funds if x["amount"] > 0.5),
        "dca_count": sum(1 for x in funds if x["dca_on"] and x["amount"] > 0.5),
        "updated_at": snaps[-1]["run_at"] if snaps else "",
        "latest_date": latest_date,
    }

    # 按日期聚合的建议
    dates = sorted({a["date"] for a in adv}) or ([latest_date] if latest_date else [])
    advice_by_date = {}
    for a in adv:
        advice_by_date.setdefault(a["date"], []).append({
            "fund_id": a["fund_id"], "name": a["name"], "plan": a["plan"],
            "priority": a["priority"], "actions": a["actions"],
            "reasons": a["reasons"], "money": a["money"], "ratio": a["ratio"],
        })

    return {
        "summary": summary,
        "funds": funds,
        "history": snaps,
        "nav": navs,
        "advice_by_date": advice_by_date,
        "dates": dates,
        "warnings": json.loads(snaps[-1]["warnings"]) if snaps and snaps[-1]["warnings"] else [],
        "plan_labels": cfg.get("plan_labels") or {},
        "run_count": runs,
        "trades": trades,
        "db_path": DB_PATH,
    }
