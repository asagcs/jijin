# -*- coding: utf-8 -*-
"""
业务层：三种操作共用同一套规则。
- estimate()  14:30 预计录入：只算不存，页面刷新即消失
- finalize()  收盘最终值：写 state.json + 历史库 + 当日报告
- trade()     买卖/转换：改持仓市值与成本，并记录调仓流水
"""
import datetime
import os
import re
import time
from difflib import SequenceMatcher

from api import ai, engine, quotes, store


def _load(cfg):
    st = engine.load_state(cfg)
    if not st:
        st = engine.init_state(cfg)
    return st


def _pct_map(cfg, st, values, mode):
    """values: {id: 数值}；mode=amount 时数值是市值，mode=pct 时是涨跌幅。"""
    out, bad = {}, []
    for fid, v in (values or {}).items():
        s = st["funds"].get(fid)
        if not s:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            bad.append(fid)
            continue
        prev = float(s["amount"])
        if mode == "amount":
            if v <= 0:
                bad.append(fid)
                continue
            pct = (v / prev - 1) * 100 if prev > 0 else 0.0
        else:
            pct = v
        out[fid] = round(pct, 4)
    return out, bad


def _payload(records, portfolio, warnings, mode, date, extra=None):
    data = {
        "mode": mode,
        "date": date,
        "records": records,
        "portfolio": portfolio,
        "warnings": warnings,
        "updated_at": engine.now_str(),
    }
    if extra:
        data.update(extra)
    return data


def estimate(date, values, mode="amount"):
    date = engine.normalize_date(date)
    cfg = engine.load_config()
    st = _load(cfg)
    pct_map, bad = _pct_map(cfg, st, values, mode)
    if not pct_map:
        return None, "没有可用的输入值（数值需为正数）"
    engine.apply_changes(cfg, st, pct_map, date=date)   # 只在内存里，不落盘
    records, portfolio, warnings = engine.judge(cfg, st)
    return _payload(records, portfolio, warnings, "estimate", date,
                    {"persisted": False, "ignored": bad}), None


def finalize(date, values, mode="amount", source="manual", ai_text=None, advice_records=None):
    date = engine.normalize_date(date)
    cfg = engine.load_config()
    st = _load(cfg)
    pct_map, bad = _pct_map(cfg, st, values, mode)
    if not pct_map:
        return None, "没有可用的输入值（数值需为正数）"
    engine.apply_changes(cfg, st, pct_map, date=date)
    records, portfolio, warnings = engine.judge(cfg, st)
    if advice_records is not None:
        by_id = {f["id"]: f for f in cfg["funds"]}
        for rec in advice_records:
            fund = by_id.get(rec.get("fund_id"))
            if fund:
                rec["plan"] = fund.get("plan") or ""
        records = advice_records
    engine.save_state(st)
    path = engine.write_report(records, portfolio, warnings, date, ai_text)
    store.record_run(date, cfg, st, records, portfolio, warnings, pct_map)
    return _payload(records, portfolio, warnings, "final", date,
                    {"persisted": True, "ignored": bad, "report": path, "source": source}), None


def _norm_name(name):
    text = re.sub(r"<[^>]+>", "", str(name or ""))
    text = re.sub(r"\s+", "", text)
    return text.replace("（", "(").replace("）", ")").upper()


def _share_class(name):
    text = _norm_name(name)
    qdii = "QDII" in text
    tail = ""
    if text.endswith("C"):
        tail = "C"
    elif text.endswith("A"):
        tail = "A"
    return qdii, tail


_TECH_WORDS = ("半导体", "芯片", "人工智能", "科技", "信息", "软件", "集成电路", "卫星", "科创", "互联网")


def _looks_tech(name):
    return any(word in str(name or "") for word in _TECH_WORDS)


def _lookup_code(name):
    """没有代码时用天天基金搜索。只接受名称和份额都对得上的结果。"""
    raw = re.sub(r"\s+", "", str(name or ""))
    if not raw:
        return None
    keys = [raw]
    short = re.sub(r"\(QDII\)", "", raw, flags=re.I)
    short = re.sub(r"ETF联接[AC]?$|联接[AC]?$", "", short)
    if short and short not in keys and len(short) >= 4:
        keys.append(short[:18])
    target = _norm_name(name)
    want = _share_class(name)
    for key in keys:
        try:
            hits = quotes.search_funds(key)
        except Exception:
            continue
        exact = next((h for h in hits if _norm_name(h["name"]) == target), None)
        if exact:
            return exact
        best, score = None, 0.0
        for hit in hits:
            if _share_class(hit["name"]) != want:
                continue
            if _norm_name(hit["name"])[:2] != target[:2]:
                continue
            ratio = SequenceMatcher(None, target, _norm_name(hit["name"])).ratio()
            if ratio > score:
                best, score = hit, ratio
        if best and score >= 0.84:
            return best
    return None


def _match_existing(name, funds, used):
    target = _norm_name(name)
    want = _share_class(name)
    exact = next((f for f in funds if f["id"] not in used and _norm_name(f["name"]) == target), None)
    if exact:
        return exact
    best, score = None, 0.0
    for fund in funds:
        if fund["id"] in used or _share_class(fund["name"]) != want:
            continue
        ratio = SequenceMatcher(None, target, _norm_name(fund["name"])).ratio()
        if ratio > score:
            best, score = fund, ratio
    if best and score >= 0.9:
        return best
    return None


def reconcile_holdings(items):
    """把截图里的持仓对到现有名单。返回 (rows, removed)。不写盘。"""
    cfg = engine.load_config()
    st = _load(cfg)
    funds = cfg["funds"]
    used = set()
    rows = []

    def remember(row):
        for old in rows:
            if row.get("code") and old.get("code") == row["code"]:
                old["amount"] = row["amount"]
                return
            if row.get("id") and old.get("id") == row["id"]:
                old["amount"] = row["amount"]
                return
        rows.append(row)

    for it in items or []:
        name = re.sub(r"\s+", "", str(it.get("name") or ""))
        try:
            amt = round(float(it.get("amount")), 2)
        except (TypeError, ValueError):
            continue
        if not name or amt <= 0:
            continue
        code = str(it.get("code") or "").strip()
        if not re.fullmatch(r"\d{6}", code):
            code = ""
        fund = _match_existing(name, funds, used)
        if fund is None and code:
            fund = next((f for f in funds if f["id"] not in used and str(f.get("code") or "") == code), None)
        if fund:
            used.add(fund["id"])
            slot = (st.get("funds") or {}).get(fund["id"]) or {}
            prev = round(float(slot.get("amount") or fund.get("amount") or 0), 2)
            got = code or str(fund.get("code") or "")
            if not re.fullmatch(r"\d{6}", got):
                found = _lookup_code(fund["name"])
                got = found["code"] if found else ""
            remember({
                "id": fund["id"],
                "name": fund["name"],
                "code": got,
                "amount": amt,
                "prev": prev,
                "status": "keep",
            })
            continue
        found = None
        if not code:
            found = _lookup_code(name)
            if found:
                code = found["code"]
                name = found["name"]
                fund = _match_existing(name, funds, used)
                if fund is None:
                    fund = next((f for f in funds if f["id"] not in used and str(f.get("code") or "") == code), None)
                if fund:
                    used.add(fund["id"])
                    slot = (st.get("funds") or {}).get(fund["id"]) or {}
                    prev = round(float(slot.get("amount") or fund.get("amount") or 0), 2)
                    remember({
                        "id": fund["id"],
                        "name": fund["name"],
                        "code": code or str(fund.get("code") or ""),
                        "amount": amt,
                        "prev": prev,
                        "status": "keep",
                    })
                    continue
        remember({
            "id": "",
            "name": name,
            "code": code,
            "amount": amt,
            "prev": amt,
            "status": "new",
        })
    removed = [{"id": f["id"], "name": f["name"]} for f in funds if f["id"] not in used]
    return rows, removed


def _alloc_id(code, name, used):
    base = f"f{code}" if re.fullmatch(r"\d{6}", code or "") else "n" + re.sub(r"\W+", "", name)[:12] or "nfund"
    fid, i = base, 2
    while fid in used:
        fid = f"{base}_{i}"
        i += 1
    return fid


def finalize_replace(date, holdings):
    """按截图结果替换持仓：旧的不在名单里就删掉，新的补上，金额用最新的。"""
    date = engine.normalize_date(date)
    cleaned = []
    for h in holdings or []:
        name = re.sub(r"\s+", "", str(h.get("name") or ""))
        try:
            amt = round(float(h.get("amount")), 2)
        except (TypeError, ValueError):
            continue
        if not name or amt <= 0:
            continue
        code = str(h.get("code") or "").strip()
        if not re.fullmatch(r"\d{6}", code):
            code = ""
        cleaned.append({
            "id": str(h.get("id") or "").strip(),
            "name": name,
            "code": code,
            "amount": amt,
        })
    if not cleaned:
        return None, "没有可用的持仓，原来的名单没有改"
    cfg = engine.load_config()
    st = _load(cfg)
    by_id = {f["id"]: f for f in cfg["funds"]}
    used = set()
    kept = []
    values = {}
    for h in cleaned:
        fid = h["id"]
        fund = by_id.get(fid) if fid else None
        if fund and fid not in used:
            if h["code"] and not fund.get("code"):
                fund["code"] = h["code"]
            slot = st["funds"].setdefault(fid, {
                "amount": 0.0, "cost": 0.0, "px": 100.0, "px_min": 100.0, "px_max": 100.0,
                "dca_on": bool(fund.get("dca")), "last_pct": 0.0, "last_date": date,
                "sold": 0.0, "notes": [],
            })
            if float(slot.get("amount") or 0) <= 0.5:
                slot["amount"] = h["amount"]
                if not slot.get("cost"):
                    slot["cost"] = h["amount"]
            used.add(fid)
            values[fid] = h["amount"]
            kept.append(fund)
            continue
        fid = _alloc_id(h["code"], h["name"], set(by_id) | used)
        fund = {
            "id": fid,
            "name": h["name"],
            "code": h["code"],
            "plan": "HOLD",
            "tech": _looks_tech(h["name"]),
            "amount": h["amount"],
            "rate": 0,
            "dca": False,
            "dca_weekly": 0,
            "dca_cycle": "weekly",
            "dca_weekday": 0,
            "dca_amount": 0,
            "note": "",
        }
        st["funds"][fid] = {
            "amount": h["amount"],
            "cost": h["amount"],
            "px": 100.0,
            "px_min": 100.0,
            "px_max": 100.0,
            "dca_on": False,
            "last_pct": 0.0,
            "last_date": date,
            "sold": 0.0,
            "notes": [],
        }
        used.add(fid)
        values[fid] = h["amount"]
        kept.append(fund)
    for fid in list((st.get("funds") or {})):
        if fid not in used:
            st["funds"].pop(fid, None)
    cfg["funds"] = kept
    engine.save_config(cfg)
    engine.save_state(st)
    return finalize(date, values, mode="amount", source="screenshot")


def trade(date, fund_id, side, amount, to_fund_id=None, note=""):
    date = engine.normalize_date(date)
    cfg = engine.load_config()
    st = _load(cfg)
    s = st["funds"].get(fund_id)
    if not s:
        return None, f"找不到基金：{fund_id}"
    try:
        amt = round(float(amount), 2)
    except (TypeError, ValueError):
        return None, "金额不是有效数字"
    if amt <= 0:
        return None, "金额必须大于 0"
    if side in ("sell", "switch"):
        if amt > s["amount"] + 0.01:
            return None, f"{fund_id} 当前市值只有 {s['amount']:.2f} 元，不能卖出 {amt:.2f} 元"
    name = next(f["name"] for f in cfg["funds"] if f["id"] == fund_id)
    detail = ""
    if side == "sell":
        ratio = amt / s["amount"] if s["amount"] else 0
        s["cost"] = round(s["cost"] * (1 - ratio), 2)
        s["amount"] = round(s["amount"] - amt, 2)
        s["sold"] = round(s.get("sold", 0) + amt, 2)
        detail = f"卖出 {amt:.2f} 元"
    elif side == "buy":
        s["amount"] = round(s["amount"] + amt, 2)
        s["cost"] = round(s["cost"] + amt, 2)
        detail = f"买入 {amt:.2f} 元"
    elif side == "switch":
        t = st["funds"].get(to_fund_id)
        if not t:
            return None, f"转入目标不存在：{to_fund_id}"
        ratio = amt / s["amount"] if s["amount"] else 0
        s["cost"] = round(s["cost"] * (1 - ratio), 2)
        s["amount"] = round(s["amount"] - amt, 2)
        s["sold"] = round(s.get("sold", 0) + amt, 2)
        t["amount"] = round(t["amount"] + amt, 2)
        t["cost"] = round(t["cost"] + amt, 2)
        to_name = next(f["name"] for f in cfg["funds"] if f["id"] == to_fund_id)
        detail = f"转换 {amt:.2f} 元 → {to_name}"
    else:
        return None, f"未知方向：{side}"

    engine.save_state(st)
    records, portfolio, warnings = engine.judge(cfg, st)
    store.record_run(date, cfg, st, records, portfolio, warnings, {}, replace_advice=False)
    store.save_trade(date, fund_id, name, side, amt, to_fund_id, note)
    return _payload(records, portfolio, warnings, "trade", date,
                    {"trade": {"fund": name, "side": side, "amount": amt, "detail": detail}}), None


def _market_rows(cfg, pct_map):
    """用尚未落盘的涨跌，拼出给 DeepSeek 的持仓事实。不含规则动作。"""
    st = _load(cfg)
    cap = float((cfg.get("profile") or {}).get("capital_total") or 0)
    rows = []
    total = 0.0
    cost_total = 0.0
    for fund in cfg["funds"]:
        slot = (st.get("funds") or {}).get(fund["id"])
        if not slot:
            continue
        amount = float(slot.get("amount") or 0)
        pct = pct_map.get(fund["id"])
        if pct is not None:
            amount = round(amount * (1 + float(pct) / 100.0), 2)
        if amount <= 0.5 and pct is None:
            continue
        cost = float(slot.get("cost") or amount)
        rate = round((amount / cost - 1) * 100, 2) if cost else 0.0
        total += amount
        cost_total += cost
        rows.append({
            "id": fund["id"],
            "name": fund["name"],
            "市值": round(amount, 2),
            "成本": round(cost, 2),
            "持有收益率": rate,
            "今日涨跌幅": None if pct is None else round(float(pct), 2),
        })
    pnl = total - cost_total
    portfolio = {
        "总市值": round(total, 2),
        "总成本": round(cost_total, 2),
        "盈亏": round(pnl, 2),
        "收益率": round(pnl / cost_total * 100, 2) if cost_total else 0.0,
        "总计划金额": cap,
        "现金": round(cap - total, 2),
    }
    return rows, portfolio


def _saved_market(cfg, st, date):
    """用已经记入的持仓拼事实。涨跌幅只在 last_date 就是这一天时带上，避免把昨天的涨跌再乘一次。"""
    cap = float((cfg.get("profile") or {}).get("capital_total") or 0)
    rows = []
    total = 0.0
    cost_total = 0.0
    tech = 0.0
    missing = 0
    for fund in cfg["funds"]:
        slot = (st.get("funds") or {}).get(fund["id"])
        if not slot:
            continue
        amount = float(slot.get("amount") or 0)
        if amount <= 0.5:
            continue
        cost = float(slot.get("cost") or amount)
        rate = round((amount / cost - 1) * 100, 2) if cost else 0.0
        pct = None
        if slot.get("last_date") == date and slot.get("last_pct") not in (None, ""):
            try:
                pct = round(float(slot.get("last_pct")), 2)
            except (TypeError, ValueError):
                pct = None
        if pct is None:
            missing += 1
        total += amount
        cost_total += cost
        if fund.get("tech"):
            tech += amount
        rows.append({
            "name": fund["name"],
            "市值": round(amount, 2),
            "成本": round(cost, 2),
            "持有收益率": rate,
            "今日涨跌幅": pct,
        })
    rows.sort(key=lambda r: r["市值"], reverse=True)
    pnl = total - cost_total
    portfolio = {
        "总市值": round(total, 2),
        "总成本": round(cost_total, 2),
        "盈亏": round(pnl, 2),
        "收益率": round(pnl / cost_total * 100, 2) if cost_total else 0.0,
        "总计划金额": cap,
        "现金": round(cap - total, 2),
        "科技相关市值": round(tech, 2),
        "科技占比": round(tech / cap * 100, 2) if cap else (round(tech / total * 100, 2) if total else 0.0),
    }
    return rows, portfolio, missing


def _money(n):
    return f"{n:,.2f}"


def _pct(n):
    if n is None:
        return "—"
    return f"{n:+.2f}%"


def _ai_markdown(date, rows, portfolio, missing):
    lines = [
        f"# 交给 AI 的当日持仓 {date}",
        "",
        "请只根据下面的当日涨跌和持仓事实，判断每只基金今天要不要动。",
        "不要套用固定档位，也不要因为跌了某个百分比就自动加仓、涨了某个百分比就自动暂停。",
        "优先级只用：必做、择机、观察、持有。",
        "只写出需要变动的基金（必做或择机）。每只给一句动作、一句理由，理由里要引用今天的涨跌幅或持有收益率。",
        "没有要动的，就说明今天没有需要变动的。",
        "",
        "## 组合",
        "",
        "| 项目 | 数值 |",
        "| --- | --- |",
        f"| 总市值 | {_money(portfolio['总市值'])} 元 |",
        f"| 总成本 | {_money(portfolio['总成本'])} 元 |",
        f"| 盈亏 | {_money(portfolio['盈亏'])} 元 |",
        f"| 收益率 | {_pct(portfolio['收益率'])} |",
        f"| 总计划金额 | {_money(portfolio['总计划金额'])} 元 |",
        f"| 现金 | {_money(portfolio['现金'])} 元 |",
        f"| 科技相关市值 | {_money(portfolio['科技相关市值'])} 元 |",
        f"| 科技占比 | {portfolio['科技占比']:.2f}% |",
        "",
        "## 持仓",
        "",
        "| 基金 | 市值（元） | 成本（元） | 持有收益率 | 今日涨跌幅 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        name = str(row["name"]).replace("|", " ")
        lines.append(
            f"| {name} | {_money(row['市值'])} | {_money(row['成本'])} | {_pct(row['持有收益率'])} | {_pct(row['今日涨跌幅'])} |"
        )
    lines.append("")
    if missing == 0:
        lines.append(f"以上 {len(rows)} 只都已记入 {date} 的涨跌幅。")
    elif missing == len(rows):
        lines.append("今天的涨跌还没有记入，上表「今日涨跌幅」为空。可以先更新当天估值再导出。")
    else:
        lines.append(f"{len(rows) - missing} 只已记入 {date} 的涨跌幅，另有 {missing} 只今天还没有涨跌。")
    lines.append("")
    return "\n".join(lines)


def export_ai_brief(date=None):
    """把当天要交给 AI 的持仓事实写成 Markdown。返回 (data, error)。"""
    date = engine.normalize_date(date)
    cfg = engine.load_config()
    st = _load(cfg)
    rows, portfolio, missing = _saved_market(cfg, st, date)
    if not rows:
        return None, "当前没有可导出的持仓"
    text = _ai_markdown(date, rows, portfolio, missing)
    os.makedirs(engine.REPORT_DIR, exist_ok=True)
    filename = f"给AI-{date}.md"
    path = os.path.join(engine.REPORT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return {"path": path, "filename": filename, "markdown": text, "date": date, "count": len(rows)}, None


def _quote_is_today(qdate, today):
    if not qdate:
        return False
    text = str(qdate).strip().replace("/", "-").replace(".", "-")
    return text[:10] == today


def afternoon_plan():
    """只判断要不要自动跑，不访问网络。"""
    now = datetime.datetime.now()
    if (now.hour, now.minute) < (14, 30):
        return {"status": "before"}
    if now.weekday() >= 5:
        return {"status": "weekend"}
    date = now.date().isoformat()
    if store.has_valuation(date):
        return {"status": "exists", "date": date}
    return {"status": "needed", "date": date}


def auto_afternoon():
    """打开面板时：14:30 前什么都不做。过了 14:30，当天还没有估值建议就拉盘中数据并请 DeepSeek 复核。"""
    plan = afternoon_plan()
    if plan["status"] != "needed":
        return plan
    date = plan["date"]
    lock_path = os.path.join(engine.BASE, "data", "auto1430.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    if os.path.exists(lock_path):
        try:
            if time.time() - os.path.getmtime(lock_path) > 900:
                os.remove(lock_path)
        except OSError:
            pass
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {"status": "busy"}
    try:
        os.write(fd, str(os.getpid()).encode())
        if store.has_valuation(date):
            return {"status": "exists", "date": date}
        pulled = quotes.pull("estimate")
        if not pulled.get("ok"):
            return {"status": "error", "error": pulled.get("note") or "拉取估值失败"}
        values = {}
        for item in pulled.get("items") or []:
            if not _quote_is_today(item.get("date"), date):
                continue
            if item.get("pct") is None:
                continue
            values[item["id"]] = item["pct"]
        if not values:
            return {"status": "error", "error": "线上没有今天的盘中估值"}
        cfg = engine.load_config()
        if not ai.is_ready(cfg):
            return {"status": "error", "error": "还没有 DeepSeek 密钥，无法生成建议"}
        rows, portfolio = _market_rows(cfg, values)
        records, note, ai_err = ai.market_advice(cfg, date, rows, portfolio)
        if records is None:
            return {"status": "error", "error": ai_err or "DeepSeek 没有返回建议"}
        saved, err = finalize(date, values, mode="pct", source="auto-1430",
                              advice_records=records)
        if err:
            return {"status": "error", "error": err}
        return {
            "status": "ready",
            "date": date,
            "count": len(values),
            "advice": len(records),
            "missing": len(pulled.get("missing") or []),
            "ai": True,
            "ai_error": None,
            "note": note,
            "report": (saved or {}).get("report"),
        }
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.remove(lock_path)
        except OSError:
            pass


def apply_dca(items):
    """把定投开关和每次金额写回 config.json，并同步 state.json 的 dca_on。"""
    cfg = engine.load_config()
    st = _load(cfg)
    by_id = {f["id"]: f for f in cfg["funds"]}
    updated = []
    for it in items or []:
        fid = str((it or {}).get("id") or "").strip()
        fund = by_id.get(fid)
        if not fund:
            continue
        on = bool(it.get("on"))
        cycle = str(it.get("cycle") or fund.get("dca_cycle") or "weekly").strip()
        if cycle not in ("daily", "weekly"):
            cycle = "weekly"
        try:
            weekday = int(it.get("weekday") or 0)
        except (TypeError, ValueError):
            return None, f"{fund['name']} 的定投星期无效"
        if cycle == "daily" or not (1 <= weekday <= 7):
            weekday = 0
        raw_amt = it.get("amount")
        if raw_amt in (None, ""):
            raw_amt = it.get("weekly") or 0
        try:
            amount = round(float(raw_amt or 0), 2)
        except (TypeError, ValueError):
            return None, f"{fund['name']} 的定投金额不是数字"
        if amount < 0:
            return None, "定投金额不能为负"
        if on and amount <= 0:
            return None, f"{fund['name']} 已开启定投，每次金额要大于 0"
        if on and cycle == "weekly" and weekday == 0:
            return None, f"{fund['name']} 是每周定投，要选星期几"
        fund["dca"] = on
        fund["dca_cycle"] = cycle
        fund["dca_weekday"] = weekday
        if amount > 0:
            fund["dca_amount"] = amount
            fund["dca_weekly"] = amount
        slot = st["funds"].setdefault(fid, {})
        slot["dca_on"] = on
        updated.append({
            "id": fid,
            "name": fund["name"],
            "on": on,
            "cycle": cycle,
            "weekday": weekday,
            "amount": fund.get("dca_amount", fund.get("dca_weekly", 0)),
        })
    if not updated:
        return None, "没有可保存的定投设置"
    engine.save_config(cfg)
    engine.save_state(st)
    return {"updated": updated, "count": len(updated)}, None
