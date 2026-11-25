# -*- coding: utf-8 -*-
"""
免费行情通道（只做预填，不写库、不改 state）：
- estimate（盘中 14:30）：新浪基金批量估值 fu_ 接口，GBK，返回估算净值与估算涨跌幅
- final（收盘后）：东财 lsjz 历史净值接口，返回官方单位净值与日增长率

说明：
- 这两个都是网页端非官方通道，无 SLA，限频/改版时单只失败会记入 missing，不影响其余；
- 接口只给净值与涨跌幅，持有成本/持有收益率仍以本机记账为准；
- QDII 净值滞后一交易日，返回日期会早于今天，属正常。
"""
import json
import re
import socket
import urllib.parse
import urllib.request

from api import engine

SINA_URL = "https://hq.sinajs.cn/list={}"
SINA_REF = "https://finance.sina.com.cn"
EM_NAV_URL = "https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize=1"
EM_REF = "https://fundf10.eastmoney.com/"
EM_SEARCH_URL = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?m=1&key={key}"
EM_SEARCH_REF = "https://fund.eastmoney.com/"
TIMEOUT = 8
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

socket.setdefaulttimeout(TIMEOUT)


def _get(url, referer, gbk=False):
    req = urllib.request.Request(url, headers={"Referer": referer, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read()
    return raw.decode("gbk" if gbk else "utf-8", errors="replace")


def _f(v):
    try:
        if v in (None, "", "—"):
            return None
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _sina_batch(codes):
    """codes: [code,...] -> {code: {name, nav, pct, date, time}}。批量一次请求。"""
    q = ",".join("fu_" + c for c in codes)
    text = _get(SINA_URL.format(q), SINA_REF, gbk=True)
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if "=" not in line or '"' not in line:
            continue
        head, payload = line.split("=", 1)
        code = head.replace("var hq_str_fu_", "").strip()
        payload = payload.strip().strip(";").strip('"')
        if not payload:
            continue
        f = payload.split(",")
        if len(f) < 10:
            continue
        name, time_s, _nav2, prev, _accum, _x, _chg, date, nav_est, pct = f[:10]
        pct_v, nav_v = _f(pct), _f(nav_est)
        if pct_v is None and nav_v is None:
            continue
        out[code] = {
            "name": name, "nav": nav_v, "pct": pct_v,
            "date": date or None, "time": time_s or None,
        }
    return out


def _em_nav(code):
    text = _get(EM_NAV_URL.format(code=code), EM_REF)
    d = json.loads(text)
    rows = ((d.get("Data") or {}).get("LSJZList")) or []
    if not rows:
        return None
    row = rows[0]
    return {
        "nav": _f(row.get("DWJZ")),
        "pct": _f(row.get("JZZZL")),
        "date": row.get("FSRQ") or None,
    }


def pull(mode="estimate"):
    """返回 {ok, mode, items, missing, note}。items 内 pct 为涨跌幅(%)，nav 为净值。"""
    cfg = engine.load_config()
    funds = [f for f in cfg["funds"] if f.get("code")]
    items, missing = [], []

    if mode == "estimate":
        try:
            quotes = _sina_batch([f["code"] for f in funds])
        except Exception as e:  # 批量通道整体失败
            return {"ok": False, "mode": mode, "items": [], "missing": [],
                    "note": f"新浪估值接口不可用：{type(e).__name__}: {e}"}
        for f in funds:
            q = quotes.get(f["code"])
            if not q or q.get("pct") is None and q.get("nav") is None:
                missing.append({"id": f["id"], "name": f["name"], "reason": "无盘中估值"})
                continue
            items.append({
                "id": f["id"], "code": f["code"], "name": f["name"],
                "pct": q.get("pct"), "nav": q.get("nav"),
                "date": q.get("date"), "time": q.get("time"),
                "source": "sina_estimate",
            })
    else:
        for f in funds:
            try:
                q = _em_nav(f["code"])
                if not q or (q.get("pct") is None and q.get("nav") is None):
                    missing.append({"id": f["id"], "name": f["name"], "reason": "无最新净值"})
                    continue
                items.append({
                    "id": f["id"], "code": f["code"], "name": f["name"],
                    "pct": q.get("pct"), "nav": q.get("nav"),
                    "date": q.get("date"), "source": "em_nav",
                })
            except Exception as e:
                missing.append({"id": f["id"], "name": f["name"],
                                "reason": f"{type(e).__name__}: {e}"})

    note = ("盘中估值为第三方估算，收盘以官方净值为准；预填后请人工核对。"
            if mode == "estimate" else
            "QDII 净值滞后一交易日属正常；预填后请人工核对。")
    return {"ok": True, "mode": mode, "items": items, "missing": missing, "note": note}


def search_funds(key):
    """天天基金名称搜索。返回 [{code, name}]，名称已去掉高亮标签。失败返回空列表。"""
    key = re.sub(r"\s+", "", str(key or ""))
    if not key:
        return []
    url = EM_SEARCH_URL.format(key=urllib.parse.quote(key))
    text = _get(url, EM_SEARCH_REF)
    data = json.loads(text)
    out = []
    for row in (data.get("Datas") or [])[:8]:
        code = str(row.get("CODE") or "").strip()
        name = str(row.get("NAME") or "")
        if not name:
            name = re.sub(r"</?font[^>]*>", "", row.get("HIGHTLIGHT") or "")
            parts = [p for p in name.split("_") if p and not p.isdigit()]
            name = parts[0] if parts else name
        name = re.sub(r"\s+", "", name)
        if re.fullmatch(r"\d{6}", code) and name:
            out.append({"code": code, "name": name})
    return out
