# -*- coding: utf-8 -*-
"""
每日入口：
    python run.py                 # 读 today.txt 里的涨跌幅，出建议
    python run.py --init          # 按 config.json 重建基线状态（自动备份旧 state.json）
    python run.py --template      # 重新生成 today.txt 模板
    python run.py --no-ai         # 只跑本地规则，不调 DeepSeek
    python run.py --date 2026-11-21
today.txt 里没有填任何数字时，交互终端下会提示逐只手工输入，非交互环境直接退出。
"""
import argparse
import datetime
import os
import re
import shutil
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.environ.setdefault("FUNDLIFE_HOME", _ROOT)

from api import ai, engine, store

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PCT_RE = re.compile(r"涨跌幅\s*=\s*(.*)$")


def parse_input(path):
    changes = {}
    if not os.path.exists(path):
        return changes
    with open(path, "r", encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m_id = re.search(r"\[([A-Za-z0-9_]+)\]", line)
            if not m_id:
                continue
            m_pct = PCT_RE.search(line)
            if not m_pct:
                continue
            val = m_pct.group(1).strip()
            for a, b in (("％", ""), ("%", ""), ("＋", "+"), ("－", "-"), ("％", "")):
                val = val.replace(a, b)
            val = val.strip()
            if not val:
                continue
            try:
                changes[m_id.group(1)] = float(val)
            except ValueError:
                print(f"  ! 这一行涨跌幅无法识别，已跳过：{line[:60]}")
    return changes


def write_template(cfg, st):
    lines = [
        "# G:\\money 每日输入模板",
        f"# 生成时间：{engine.now_str()}",
        "# 在每行末尾「涨跌幅=」后填当天最终涨跌幅（百分数）：涨填正数如 2.35，跌填负数如 -1.86。",
        "# 不填的行视为今天不更新；只处理其中几只，就只填这几只。填完保存，再双击 运行.bat。",
        "",
    ]
    for f in cfg["funds"]:
        s = st["funds"][f["id"]]
        rate = (s["amount"] / s["cost"] - 1) * 100 if s["cost"] else 0.0
        lines.append(
            f"[{f['id']}] {f['name']}｜{cfg['plan_labels'][f['plan']]}｜"
            f"市值 {s['amount']:.2f} 元｜持有 {rate:+.2f}%｜涨跌幅="
        )
    with open(engine.INPUT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"已生成输入模板：{engine.INPUT_PATH}")


def interactive(cfg, st):
    print("逐只输入模式：直接回车 = 跳过，Ctrl+C 退出。\n")
    changes = {}
    for f in cfg["funds"]:
        s = st["funds"][f["id"]]
        try:
            raw = input(f"{f['name']}（{s['amount']:.2f} 元）今日涨跌幅%：").strip()
        except EOFError:
            break
        if not raw:
            continue
        for a, b in (("％", ""), ("%", ""), ("＋", "+"), ("－", "-")):
            raw = raw.replace(a, b)
        try:
            changes[f["id"]] = float(raw)
        except ValueError:
            print("  跳过（不是有效数字）")
    return changes


def archive_input(date):
    os.makedirs(engine.INPUT_DIR, exist_ok=True)
    if not os.path.exists(engine.INPUT_PATH):
        return None
    dst = os.path.join(engine.INPUT_DIR, f"{date}.txt")
    if os.path.abspath(dst) == os.path.abspath(engine.INPUT_PATH):
        return dst
    try:
        shutil.copyfile(engine.INPUT_PATH, dst)
        return dst
    except Exception as e:  # noqa
        print(f"  ! 归档输入失败：{e}")
        return None


def cli_service(args):
    """命令行侧的三种操作：预估 / 最终值 / 调仓。网页端功能等价。"""
    import json as _json
    from api import service

    if args.trade:
        if not args.fund:
            print("缺少 --fund（基金 id，可先运行 --history 或看 config.json）")
            return 1
        res, err = service.trade(args.date, args.fund, args.side, args.amount,
                                 args.to_fund or None, args.note)
        if err:
            print(f"[调仓失败] {err}")
            return 1
        print(f"已记录：{res['trade']['detail']}（{args.date}）")
    else:
        if not args.values:
            print("缺少 --values：先用网页端，或准备一个 JSON 文件，例如")
            print('  {"date":"2026-11-21","mode":"amount","values":{"gf_bdt":2331.63,"fg_hk":506.78}}')
            print("mode 可选 amount（市值）或 pct（涨跌幅，如 -1.2）")
            return 1
        try:
            with open(args.values, "r", encoding="utf-8") as fh:
                doc = _json.load(fh)
        except Exception as e:  # noqa
            print(f"读取 {args.values} 失败：{e}")
            return 1
        values = doc.get("values") or doc
        mode = doc.get("mode", "amount")
        date = doc.get("date") or args.date
        if args.estimate:
            res, err = service.estimate(date, values, mode)
            if err:
                print(f"[预估失败] {err}")
                return 1
            print("==== 预估模式（不入库，仅供盘中决策）====")
        else:
            res, err = service.finalize(date, values, mode, source="cli")
            if err:
                print(f"[保存失败] {err}")
                return 1

    print()
    print(engine.format_console(res["records"], res["portfolio"], res["warnings"], res["date"]))
    if res.get("persisted"):
        print(f"\n报告已保存：{res.get('report')}")
        print("历史已入库。刷新网页即可看到。")
    else:
        print("\n预估结果没有写盘；要正式记录请用「最终更新」或 --final。")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--template", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--dca-off", default="", help="关闭指定基金的定投并写回 config.json，如 --dca-off zs_chip,yh_jc")
    ap.add_argument("--date", default=engine.today_str())
    ap.add_argument("--history", action="store_true", help="打印历史记录（配合 web 端一起看）")
    ap.add_argument("--estimate", action="store_true", help="盘中预估：只算建议、不入库（配 --values）")
    ap.add_argument("--final", action="store_true", help="收盘最终值：入库并写当日报告（配 --values）")
    ap.add_argument("--values", default="", help="JSON 文件路径，如 {\"date\":\"2026-11-21\",\"mode\":\"amount\",\"values\":{...}}")
    ap.add_argument("--trade", action="store_true", help="记一笔调仓（配 --fund --side --amount）")
    ap.add_argument("--fund", default="", help="调仓的基金 id")
    ap.add_argument("--side", default="sell", choices=["buy", "sell", "switch"])
    ap.add_argument("--amount", type=float, default=0.0)
    ap.add_argument("--to", dest="to_fund", default="", help="转换时的转入基金 id")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    if not os.path.exists(engine.CONFIG_PATH):
        print(f"找不到配置文件：{engine.CONFIG_PATH}")
        return 1
    cfg = engine.load_config()

    if args.init:
        if os.path.exists(engine.STATE_PATH):
            bak = os.path.join(engine.BASE, f"state.bak_{datetime.datetime.now():%Y%m%d%H%M%S}.json")
            shutil.copyfile(engine.STATE_PATH, bak)
            print(f"旧状态已备份：{bak}")
        engine.save_state(engine.init_state(cfg))
        print(f"已按 {len(cfg['funds'])} 只基金重建基线（{cfg['profile']['baseline_date']}）。")
        print("提示：--init 只重建基线，不会套用当天涨跌幅；要出今日建议请去掉 --init 再运行一次。")
        return 0

    st = engine.load_state(cfg)

    if args.history:
        d = store.fetch_all()
        print(f"{'日期':<12}{'总市值':>10}{'盈亏':>10}{'科技%':>8}{'现金%':>8}  必做/择机")
        for h in d["history"]:
            adv = d["advice_by_date"].get(h["date"], [])
            n1 = sum(1 for a in adv if a["priority"] == "必做")
            n2 = sum(1 for a in adv if a["priority"] == "择机")
            print(f"{h['date']:<12}{h['total']:>10.0f}{h['pnl']:>10.0f}{h['tech_ratio']:>8.1f}{h['cash_ratio']:>8.1f}  {n1}/{n2}")
        print(f"\n数据库：{d['db_path']}｜共 {len(d['history'])} 个交易日，{d['run_count']} 次运行")
        return 0

    if args.dca_off:
        ids = [x.strip() for x in args.dca_off.replace("，", ",").split(",") if x.strip()]
        hit = 0
        for f in cfg["funds"]:
            if f["id"] in ids:
                f["dca"] = False
                st["funds"][f["id"]]["dca_on"] = False
                hit += 1
                print(f"已关闭定投：{f['name']}")
        ids_notfound = [i for i in ids if i not in {f['id'] for f in cfg['funds']}]
        for i in ids_notfound:
            print(f"  ! 找不到基金 id：{i}")
        if hit:
            with open(engine.CONFIG_PATH, "w", encoding="utf-8") as fh:
                import json as _json
                _json.dump(cfg, fh, ensure_ascii=False, indent=2)
            engine.save_state(st)
            print(f"已写回 config.json（{hit} 只）。")
        return 0

    if args.template:
        write_template(cfg, st)
        return 0

    if args.estimate or args.final or args.trade:
        return cli_service(args)

    changes = parse_input(engine.INPUT_PATH)
    if not changes:
        if not os.path.exists(engine.INPUT_PATH):
            write_template(cfg, st)
            print("首次运行已生成 today.txt，填好涨跌幅后再运行一次。")
            return 0
        print("today.txt 里还没有填任何涨跌幅，请先填写。")
        if not sys.stdin.isatty():
            return 0
        ans = input("或现在就逐只手工输入？(y=手工 / 其他=退出) ").strip().lower()
        if ans != "y":
            return 0
        changes = interactive(cfg, st)

    if not changes:
        print("没有可应用的涨跌幅，状态未变更。")
        return 0

    engine.apply_changes(cfg, st, changes, date=args.date)
    records, portfolio, warnings = engine.judge(cfg, st)

    print()
    print(engine.format_console(records, portfolio, warnings, args.date))

    ai_text = None
    if not args.no_ai:
        if ai.is_ready(cfg):
            print("\n正在调用 DeepSeek 复核……")
            ai_text, err = ai.ask(cfg, ai.build_prompt(args.date, records, portfolio, warnings))
            if ai_text:
                print("\n======== DeepSeek 复核 ========")
                print(ai_text.strip())
            else:
                print(f"\n[DeepSeek 未生效] {err}")
        else:
            print("\n[DeepSeek 未启用] 在桌面窗口点「密钥」填写后即可启用；本地规则建议已照常生成。")

    path = engine.write_report(records, portfolio, warnings, args.date, ai_text)
    archive_input(args.date)
    engine.save_state(st)
    try:
        store.record_run(args.date, cfg, st, records, portfolio, warnings, changes)
        print(f"历史已入库：{store.DB_PATH}")
    except Exception as e:  # noqa
        print(f"  ! 历史入库失败（不影响当日建议）：{e}")
    print(f"\n报告已保存：{path}")
    print(f"状态已更新，累计运行 {st.get('runs')} 次。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
