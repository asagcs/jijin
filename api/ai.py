# -*- coding: utf-8 -*-
"""DeepSeek：① 复核规则清单；② 把 OCR 出来的文字结构化成「基金→市值」。
DeepSeek 只吃文本，不读图片；图片先由本地 OCR（ocr.py）转成文字再送过来。
"""
import json
import re
import urllib.error
import urllib.request


def resolve_key(cfg):
    """优先读本机加密存储。config.json 里的明文只作为旧数据兜底，调用方不要显示返回值。"""
    try:
        from api import keybox
        stored = keybox.load()
        if stored:
            return stored
    except Exception:
        pass
    key = str(((cfg or {}).get("deepseek") or {}).get("api_key") or "").strip()
    if not key or key.startswith("在这里"):
        return ""
    return key


def is_ready(cfg):
    return bool(resolve_key(cfg))


# ---------------- 通用请求 ----------------

def _post(cfg, messages, max_tokens=None, temperature=None, timeout=90, json_mode=False):
    ds = cfg["deepseek"]
    body = {
        "model": ds.get("model", "deepseek-chat"),
        "messages": messages,
        "max_tokens": int(max_tokens or ds.get("max_tokens", 900)),
        "temperature": float(ds.get("temperature", 0.3) if temperature is None else temperature),
        "stream": False,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    url = ds.get("base_url", "https://api.deepseek.com").rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + resolve_key(cfg)},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"], None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        return None, f"DeepSeek 接口返回 {e.code}：{detail}"
    except urllib.error.URLError as e:
        return None, f"网络错误：{e.reason}"
    except Exception as e:  # noqa
        return None, f"调用失败：{e}"


# ---------------- ① 复核清单 ----------------

SYSTEM = (
    "你是一位严格、克制的基金组合管理助手。用户是散户，总资金上限以输入里的「组合.capital」为准，"
    "目标是先把仓位结构做健康，其次才是收益。"
    "纪律底线：不追热点，不给弱势基金继续输血，不一次性满仓，不推荐新的细分赛道，"
    "不以回本作为卖出理由。"
    "输出要求：中文，纯文本，200~350字，不要客套，不要复述输入，直接给结论。"
    "结构固定为三段：1) 今日最该做的一件事；2) 对规则引擎给的清单有无异议（若无异议写“无异议”）；"
    "3) 明天需要盯的一个信号。"
)


def build_prompt(date, records, portfolio, warnings):
    rows = []
    for r in records:
        rows.append({
            "基金": r["name"],
            "分类": r["plan"],
            "建议": " + ".join(r["actions"]),
            "优先级": r["priority"],
            "涉及金额": r.get("money"),
            "理由": "；".join(r["reasons"]),
        })
    payload = {"日期": date, "组合": portfolio, "风控提醒": warnings, "清单": rows}
    return "以下是今天按既定规则算出的处理清单，请复核。\n" + json.dumps(payload, ensure_ascii=False, indent=1)


ADVISE_SYSTEM = (
    "你根据用户给出的当日涨跌和持仓事实，判断每只基金今天要不要动。"
    "不要套用固定档位，也不要因为跌了某个百分比就自动加仓、涨了某个百分比就自动暂停。"
    "优先级只能是：必做、择机、观察、持有。"
    "必做是今天就该执行的，择机是可以做但要看当时盘面，观察是先看着，持有是不动。"
    "只输出需要变动的基金，也就是必做或择机。没有要动的，items 为空数组。"
    "action 写一句动作，reason 写一句理由，理由里要引用今天的涨跌幅或持有收益率。"
    "money 是这个动作涉及的金额（元），没有明确金额就填 null。"
    "id 必须来自给定清单，不要编造基金。只输出 JSON。"
)


def market_advice(cfg, date, rows, portfolio):
    """按当日行情生成建议。返回 (records, note, error)。records 可直接入库。"""
    if not is_ready(cfg):
        return None, "", "未配置 DeepSeek API Key"
    known = {r["id"]: r["name"] for r in rows}
    user = (
        "下面是今天的持仓和涨跌，请给出要变动的建议。\n"
        + json.dumps({"日期": date, "组合": portfolio, "持仓": rows}, ensure_ascii=False)
        + '\n输出格式：{"items":[{"id":"fund_a","priority":"择机","action":"暂停今日定投","reason":"今日涨 2.1%，持有收益率仍为 -6%，不适合今天加仓","money":null}],"note":""}'
    )
    content, err = _post(cfg, [{"role": "system", "content": ADVISE_SYSTEM},
                               {"role": "user", "content": user}],
                         max_tokens=1800, temperature=0.3, timeout=120, json_mode=True)
    if err:
        return None, "", err
    data = _parse_json(content)
    if not data:
        return None, "", "DeepSeek 返回的内容不是合法 JSON"
    records = []
    for it in data.get("items") or []:
        fid = str(it.get("id") or "").strip()
        if fid not in known:
            continue
        priority = str(it.get("priority") or "").strip()
        if priority not in ("必做", "择机", "观察", "持有"):
            continue
        action = str(it.get("action") or "").strip()
        reason = str(it.get("reason") or "").strip()
        if not action or not reason:
            continue
        money = None
        if it.get("money") not in (None, ""):
            try:
                money = round(float(it.get("money")), 2)
            except (TypeError, ValueError):
                money = None
        records.append({
            "fund_id": fid,
            "name": known[fid],
            "plan": "",
            "priority": priority,
            "actions": [action],
            "reasons": [reason],
            "money": money,
            "ratio": None,
        })
    return records, str(data.get("note") or ""), None


def ask(cfg, user_prompt, timeout=60):
    """返回 (文本, 错误信息)。"""
    if not is_ready(cfg):
        return None, "未检测到有效的 DeepSeek API Key（在桌面窗口点「密钥」填写）"
    return _post(cfg, [{"role": "system", "content": SYSTEM},
                       {"role": "user", "content": user_prompt}], timeout=timeout)


# ---------------- ② OCR 文字 → 结构化 ----------------

STRUCT_SYSTEM = (
    "你是数据录入助手，任务是把基金 App 截图 OCR 出来的凌乱文字，还原成结构化金额。"
    "OCR 常见错误：数字被认成汉字（2→乙、8→&、6→口）、小数点丢失、千分位逗号消失、"
    "多列内容挤在同一行、名称被拆成两三行。你要根据上下文与每只基金的上次市值做合理还原。"
    "只输出 JSON，不要任何解释文字。"
)


def structure_ocr(cfg, text, funds, date=None):
    """返回 (values{id:amount}, note, error)。"""
    if not is_ready(cfg):
        return {}, "", "未配置 DeepSeek key，只能用手工核对 OCR 原文"

    items = [{"id": f["id"], "name": f["name"], "上次市值": f.get("amount")} for f in funds]
    user = (
        f"日期：{date or ''}\n"
        "下面是 App 截图经 OCR 得到的文字（顺序大致按页面从上到下）。\n"
        "请把每只基金的「金额（市值）」还原出来，单位为元，保留两位小数。\n"
        "规则：\n"
        "1) 只能使用下面给定的基金清单，id 原样返回，不要编造基金；\n"
        "2) 数值应接近「上次市值」，单日涨跌一般不超过 ±12%，明显偏离说明识别错了，请按最接近的合理值还原；\n"
        "3) 没在文字里出现的基金不要输出；\n"
        "4) 不确定的给低置信度，不要瞎猜；\n"
        "5) 这份文字来自手机截图的 OCR，中文常被拆成单字（如「平 安 中 证」），数字易被误认："
        "2 常成「乙/乙」，0 常成「口/〇/O」，6 常成「&/口」，8 常成「&/8」，小数点与千分位常丢失；"
        "数字之间的空格是识别断字，例如「乙 601 50」应还原为 2,601.50，「331 1 7」还原为 331.17，「1 112 20」还原为 1,112.20；\n"
        '输出格式：{"items":[{"id":"fund_a","amount":1000.00,"confidence":0.9}],"note":"简短说明"}\n\n'
        "基金清单：\n" + json.dumps(items, ensure_ascii=False) +
        "\n\nOCR 文字：\n" + text[:6000]
    )
    content, err = _post(cfg, [{"role": "system", "content": STRUCT_SYSTEM},
                               {"role": "user", "content": user}],
                         max_tokens=1200, temperature=0, timeout=120, json_mode=True)
    if err:
        return {}, "", err

    data = _parse_json(content)
    if not data:
        return {}, "", "DeepSeek 返回的内容不是合法 JSON"
    raw_items = data.get("items") or []
    prior = {f["id"]: float(f.get("amount") or 0) for f in funds}
    values = {}
    for it in raw_items:
        fid = str(it.get("id", "")).strip()
        if fid not in prior:
            continue
        try:
            amt = float(it.get("amount"))
        except (TypeError, ValueError):
            continue
        if amt <= 0:
            continue
        prev = prior[fid]
        # 与上次市值偏离过大视为误识别，保留但标记（前端会提示核对）
        if prev > 0 and (amt < prev * 0.7 or amt > prev * 1.35):
            continue
        values[fid] = round(amt, 2)
    return values, str(data.get("note", "")), None


def structure_holdings(cfg, text, funds):
    """从持仓截图抽出全部基金的名称和市值，不限于已有清单。返回 (items, note, error)。"""
    if not is_ready(cfg):
        return [], "", "未配置 DeepSeek key，只能用手工核对 OCR 原文"
    known = [{"name": f["name"], "code": f.get("code") or ""} for f in funds]
    user = (
        "下面是基金持仓截图的 OCR 文字。请把页面上每一只持仓都还原出来。\n"
        "规则：\n"
        "1) 以截图为准，输出文字里出现的全部基金，不要漏，也不要补文字里没有的。\n"
        "2) name 用完整基金名，份额要保留：联接C 不是联接A，(QDII)C 不是 (QDII)A。\n"
        "3) 如果和下面清单是同一只，name 用清单里的原名；清单里没有的，按截图还原名称，不要丢弃。\n"
        "4) amount 是当前金额（市值），单位元。可以和上次市值差很多，差得多也要按截图填写，不要改回旧值。\n"
        "5) 截图里能看到 6 位基金代码就填 code，看不到就填空字符串，不要编造代码。\n"
        "6) 数字常被拆开或认错：2 常成「乙」，0 常成「口/〇/O」，小数点会丢。"
        "「乙 601 50」还原为 2601.50。\n"
        '输出格式：{"items":[{"name":"某某基金C","amount":1000.00,"code":"","confidence":0.9}],"note":""}\n\n'
        "已有清单（只用于对齐名称，不是输出范围）：\n"
        + json.dumps(known, ensure_ascii=False)
        + "\n\nOCR 文字：\n" + text[:9000]
    )
    content, err = _post(cfg, [{"role": "system", "content": STRUCT_SYSTEM},
                               {"role": "user", "content": user}],
                         max_tokens=2600, temperature=0, timeout=120, json_mode=True)
    if err:
        return [], "", err
    data = _parse_json(content)
    if not data:
        return [], "", "DeepSeek 返回的内容不是合法 JSON"
    items = []
    for it in data.get("items") or []:
        name = re.sub(r"\s+", "", str(it.get("name") or ""))
        if not name:
            continue
        try:
            amt = round(float(it.get("amount")), 2)
        except (TypeError, ValueError):
            continue
        if amt <= 0:
            continue
        code = str(it.get("code") or "").strip()
        if not re.fullmatch(r"\d{6}", code):
            code = ""
        items.append({"name": name, "amount": amt, "code": code})
    return items, str(data.get("note") or ""), None


def structure_trade(cfg, text, funds):
    """从交易/调仓截图文字里抽出一笔。返回 (trade|None, note, error)。"""
    if not is_ready(cfg):
        return None, "", "未配置 DeepSeek key，只能用手工核对 OCR 原文"
    items = [{"id": f["id"], "name": f["name"]} for f in funds]
    user = (
        "下面是基金 App 交易或调仓截图的 OCR 文字。请抽出其中一笔交易。\n"
        "规则：\n"
        "1) side 只能是 buy（买入/申购）、sell（卖出/赎回）、switch（转换）；\n"
        "2) fund_id、to_fund_id 只能用下面清单里的 id，按名称对应，不要编造；\n"
        "3) amount 是这笔交易的金额（元），不是持仓市值；转换时 fund_id 是转出，to_fund_id 是转入；\n"
        "4) 文字里有多笔时，取页面上最靠前、信息最完整的一笔；\n"
        "5) 认不出基金或金额就不要猜，把对应字段留空；\n"
        '输出格式：{"side":"sell","fund_id":"fund_a","to_fund_id":null,"amount":200.00,"note":"","confidence":0.8}\n\n'
        "基金清单：\n" + json.dumps(items, ensure_ascii=False) +
        "\n\nOCR 文字：\n" + text[:6000]
    )
    content, err = _post(cfg, [{"role": "system", "content":
                               "你是数据录入助手，从基金 App 交易截图的 OCR 文字里还原一笔买卖或转换。"
                               "OCR 常见错误：数字被认成汉字、小数点丢失、名称被拆行。"
                               "只输出 JSON，不要解释。"},
                               {"role": "user", "content": user}],
                         max_tokens=400, temperature=0, timeout=120, json_mode=True)
    if err:
        return None, "", err
    data = _parse_json(content)
    if not data:
        return None, "", "DeepSeek 返回的内容不是合法 JSON"
    known = {f["id"] for f in funds}
    side = str(data.get("side") or "").strip()
    fid = str(data.get("fund_id") or "").strip()
    to_id = str(data.get("to_fund_id") or "").strip() or None
    try:
        amount = round(float(data.get("amount")), 2)
    except (TypeError, ValueError):
        amount = 0
    if side not in ("buy", "sell", "switch") or fid not in known or amount <= 0:
        return None, str(data.get("note", "")), None
    if side == "switch" and (not to_id or to_id not in known or to_id == fid):
        return None, str(data.get("note", "")), None
    if side != "switch":
        to_id = None
    trade = {
        "side": side,
        "fund_id": fid,
        "to_fund_id": to_id,
        "amount": amount,
        "note": str(data.get("note") or "")[:80],
    }
    return trade, trade["note"], None


def structure_dca(cfg, text, funds):
    """从定投计划截图抽出周期、星期和每次金额。返回 (items, note, error)。"""
    if not is_ready(cfg):
        return [], "", "未配置 DeepSeek key，只能用手工核对 OCR 原文"
    items = [{"id": f["id"], "name": f["name"]} for f in funds]
    user = (
        "下面是基金 App「买卖计划 / 定投」页面的 OCR 文字。请抽出每笔进行中的定投。\n"
        "规则：\n"
        "1) 只能使用清单里的 id。名称要连份额一起对上：联接C 不是联接A，(QDII)C 不是 (QDII)A，全球精选不是半导体，纳斯达克不是标普500。对不上就不要输出。\n"
        "2) 只看「进行中」。已暂停、已终止不要输出。\n"
        "3) amount 只填「买入金额」或「定投金额」那一栏的每次扣款。不要填累计定投、已投期数、持仓市值、收益率，也不要把每天金额乘成每周。\n"
        "4) 写着每日定投、每个交易日、每交易日的，cycle 为 daily，weekday 为 null。下次扣款刚好是某一天，不能据此当成每周定投。\n"
        "5) 写着每周一到每周日、或「每周」并标出星期的，cycle 为 weekly，weekday 用数字：周一=1 … 周日=7。没写星期就不要猜。\n"
        "6) 同一只基金有多笔进行中计划时，逐笔输出，不要合并金额。页面上没出现的基金不要输出。\n"
        '输出格式：{"items":[{"id":"fund_a","on":true,"cycle":"daily","weekday":null,"amount":50,"confidence":0.9}],"note":"简短说明"}\n\n'
        "基金清单：\n" + json.dumps(items, ensure_ascii=False) +
        "\n\nOCR 文字：\n" + text[:6000]
    )
    content, err = _post(cfg, [{"role": "system", "content":
                               "你是数据录入助手，从基金定投计划截图的 OCR 文字里还原每笔定投的周期、星期和每次买入金额。"
                               "累计定投不是每次金额。每日定投不要改成每周。只输出 JSON，不要解释。"},
                               {"role": "user", "content": user}],
                         max_tokens=1200, temperature=0, timeout=120, json_mode=True)
    if err:
        return [], "", err
    data = _parse_json(content)
    if not data:
        return [], "", "DeepSeek 返回的内容不是合法 JSON"
    known = {f["id"] for f in funds}
    out = []
    for it in data.get("items") or []:
        fid = str(it.get("id", "")).strip()
        if fid not in known:
            continue
        cycle = str(it.get("cycle") or "").strip().lower()
        if cycle in ("day", "daily", "每日"):
            cycle = "daily"
        elif cycle in ("week", "weekly", "每周"):
            cycle = "weekly"
        else:
            continue
        try:
            amount = round(float(it.get("amount")), 2)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        weekday = 0
        if cycle == "weekly":
            try:
                weekday = int(it.get("weekday") or 0)
            except (TypeError, ValueError):
                weekday = 0
            if not (1 <= weekday <= 7):
                continue
        out.append({
            "id": fid,
            "on": bool(it.get("on", True)),
            "cycle": cycle,
            "weekday": weekday,
            "amount": amount,
        })
    return out, str(data.get("note", "")), None


def _parse_json(text):
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.MULTILINE).strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None
