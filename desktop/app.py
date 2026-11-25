# -*- coding: utf-8 -*-
"""
基金纪律面板 · 桌面端（tkinter，只用标准库）
- pythonw desktop.py 打开无控制台小窗口；打包后双击 exe 也是同一个窗口
- 「分析」按钮：确保 Web 服务在跑 → 取最新数据 → 默认浏览器打开面板
- Web 服务跑在本进程的后台线程里，所以打包成单文件 exe 不需要外部 python
"""
import json
import os
import shutil
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
import ctypes
import tkinter as tk

from api import ai, engine, keybox, service

PORT = int(os.environ.get("FUNDLIFE_PORT", "8766"))
FROZEN = bool(getattr(sys, "frozen", False))

# 打包后：数据放 exe 旁边，静态资源在 PyInstaller 的解包目录
if FROZEN:
    HOME = os.path.dirname(os.path.abspath(sys.executable))
    ASSETS = getattr(sys, "_MEIPASS", HOME)
else:
    HOME = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    ASSETS = HOME
os.environ.setdefault("FUNDLIFE_HOME", HOME)
os.environ.setdefault("FUNDLIFE_ASSETS", ASSETS)

LOG_PATH = os.path.join(HOME, "desktop.log")


def log(msg):
    """无控制台 exe 也要能排查：写 desktop.log。"""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def seed_files():
    """首次运行：把 config.json 从打包目录复制到数据目录，建好各个子目录。"""
    for d in ("data", "reports", "inbox", "daily_inputs"):
        os.makedirs(os.path.join(HOME, d), exist_ok=True)
    src = os.path.join(ASSETS, "config.json")
    dst = os.path.join(HOME, "config.json")
    if os.path.exists(src) and not os.path.exists(dst):
        try:
            shutil.copyfile(src, dst)
        except OSError:
            pass


def port_alive(port=PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ---------------- 服务（同进程后台线程） ----------------
_srv = {"httpd": None, "port": None}


def start_server():
    if port_alive():
        log("端口已在监听，复用现有服务")
        return True
    try:
        from api.server import make_server
        httpd, port = make_server(PORT)
    except Exception:
        log("启动内置服务失败：\n" + traceback.format_exc())
        return False
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _srv["httpd"] = httpd
    _srv["port"] = port
    log(f"内置服务已启动 端口 {port}，资源目录 {ASSETS}")
    for _ in range(40):
        time.sleep(0.25)
        if port_alive(port):
            return True
    log("服务启动后端口仍不通")
    return False


def stop_server():
    httpd = _srv.get("httpd")
    if httpd:
        try:
            httpd.shutdown()
        except Exception:
            pass
        _srv["httpd"] = None
        _srv["port"] = None
        time.sleep(0.8)


def base_url():
    return f"http://127.0.0.1:{_srv.get('port') or PORT}"


def fetch_data(timeout=6):
    try:
        with urllib.request.urlopen(f"{base_url()}/api/data", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def fmt(n, digits=2):
    if n is None:
        return "—"
    try:
        return f"{n:,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


class App:
    def __init__(self, root):
        self.root = root
        root.title("基金纪律面板 · 桌面端")
        root.configure(bg="#f4f6f9")
        self.scale = float(root.tk.call("tk", "scaling") or 1.333)
        self._fitted = False

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        factor = max(1.0, self.scale / (96 / 72))
        w = min(int(sw * 0.34), max(int(560 * factor), 520))
        h = min(int(sh * 0.72), max(int(640 * factor), 600))
        w = min(max(w, 480), sw - 48)
        h = min(max(h, 560), sh - 80)
        root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")
        root.minsize(min(560, sw - 80), min(420, sh - 120))
        root.resizable(True, True)

        head = tk.Frame(root, bg="#ffffff")
        head.pack(fill="x")
        head_inner = tk.Frame(head, bg="#ffffff")
        head_inner.pack(fill="x", padx=22, pady=(16, 14))
        title_row = tk.Frame(head_inner, bg="#ffffff")
        title_row.pack(fill="x")
        tk.Label(title_row, text="基金纪律面板", font=("Microsoft YaHei UI", 16, "bold"),
                 bg="#ffffff", fg="#1b2130", anchor="w").pack(side="left")
        tk.Button(
            title_row, text="密钥", command=self.open_key, relief="flat", bg="#ffffff",
            fg="#5d6676", activebackground="#e8edf5", activeforeground="#1b2130",
            font=("Microsoft YaHei UI", 9), cursor="hand2",
            highlightthickness=1, highlightbackground="#e6e9ef",
        ).pack(side="right", ipady=2, ipadx=8)
        self.status = tk.Label(head_inner, text="正在检查服务…", font=("Microsoft YaHei UI", 9),
                               bg="#ffffff", fg="#6b7688", anchor="w", justify="left")
        self.status.pack(anchor="w", fill="x", pady=(4, 0))

        foot = tk.Frame(root, bg="#f4f6f9")
        foot.pack(side="bottom", fill="x", padx=22, pady=(4, 18))
        self.btn = tk.Frame(foot, bg="#2f6fed", cursor="hand2")
        self.btn_label = tk.Label(
            self.btn, text="分析", font=("Microsoft YaHei UI", 12, "bold"),
            bg="#2f6fed", fg="#ffffff", cursor="hand2",
        )
        self.btn_label.pack(fill="x", pady=10)
        self.btn.pack(fill="x")
        for widget in (self.btn, self.btn_label):
            widget.bind("<Button-1>", lambda _e: self.on_analyze())
        self.export_btn = tk.Frame(foot, bg="#ffffff", cursor="hand2",
                                   highlightthickness=1, highlightbackground="#c5cedd")
        self.export_label = tk.Label(
            self.export_btn, text="导出给 AI", font=("Microsoft YaHei UI", 10),
            bg="#ffffff", fg="#1b2130", cursor="hand2",
        )
        self.export_label.pack(fill="x", pady=8)
        self.export_btn.pack(fill="x", pady=(8, 0))
        for widget in (self.export_btn, self.export_label):
            widget.bind("<Button-1>", lambda _e: self.on_export())
        bar = tk.Frame(foot, bg="#f4f6f9")
        bar.pack(fill="x", pady=(10, 0))
        actions = (("打开数据目录", self.open_dir), ("重启服务", self.on_restart), ("退出", self.on_quit))
        for i, (text, cmd) in enumerate(actions):
            tk.Button(
                bar, text=text, command=cmd, relief="flat", bg="#ffffff",
                fg="#1b2130", activebackground="#e8edf5", activeforeground="#1b2130",
                font=("Microsoft YaHei UI", 9), cursor="hand2",
                highlightthickness=1, highlightbackground="#e6e9ef",
            ).pack(side="left", expand=True, fill="x", ipady=6, padx=(0 if i == 0 else 8, 0))

        self.body = tk.Frame(root, bg="#f4f6f9")
        self.body.pack(fill="x", padx=22, pady=(16, 8))
        self._head = head
        self._foot = foot

        def card(title):
            box = tk.Frame(self.body, bg="#ffffff", highlightthickness=1, highlightbackground="#e6e9ef")
            box.pack(fill="x", pady=(0, 8))
            inner = tk.Frame(box, bg="#ffffff")
            inner.pack(fill="x", padx=16, pady=10)
            tk.Label(inner, text=title, font=("Microsoft YaHei UI", 9),
                     bg="#ffffff", fg="#8b94a3", anchor="w").pack(anchor="w")
            row = tk.Frame(inner, bg="#ffffff")
            row.pack(fill="x", pady=(4, 0))
            val = tk.Label(row, text="—", font=("Microsoft YaHei UI", 18, "bold"),
                           bg="#ffffff", fg="#1b2130", anchor="w")
            val.pack(side="left")
            sub = tk.Label(row, text="", font=("Microsoft YaHei UI", 11),
                           bg="#ffffff", fg="#5d6676", anchor="w")
            sub.pack(side="left", padx=(12, 0))
            return val, sub

        self.val_total, self.sub_total = card("总市值")
        self.val_pnl, self.sub_pnl = card("持仓盈亏")
        self.val_tech, self.sub_tech = card("科技占比")
        self._values = (self.val_total, self.sub_total, self.val_pnl, self.sub_pnl, self.val_tech, self.sub_tech)

        self.tip = tk.Label(self.body, text="", font=("Microsoft YaHei UI", 10),
                            bg="#f4f6f9", fg="#5d6676", justify="left", anchor="w")
        self.tip.pack(fill="x", pady=(16, 0))
        self.warn = tk.Label(self.body, text="", font=("Microsoft YaHei UI", 9),
                             bg="#fff8ec", fg="#8a5a10", justify="left", anchor="w",
                             padx=12, pady=10)
        self._warn_shown = False

        self.body.bind("<Configure>", self._fit_wrap)
        root.bind("<Configure>", self._fit_wrap)
        root.protocol("WM_DELETE_WINDOW", self.on_quit)
        root.after(30, self._fit_wrap)
        root.after(400, self._prompt_setup)
        threading.Thread(target=self.boot, daemon=True).start()

    def _fit_wrap(self, event=None):
        width = self.body.winfo_width()
        if width < 40:
            return
        self.status.configure(wraplength=max(self.root.winfo_width() - 56, 160))
        self.tip.configure(wraplength=width)
        self.warn.configure(wraplength=max(width - 36, 200))
        for lab in self._values:
            lab.configure(wraplength=max(width - 48, 120))

    def _ensure_fit(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        need_w = min(max(self.root.winfo_reqwidth() + 24, 680), int(sw * 0.5))
        need_h = min(self.root.winfo_reqheight() + 36, int(sh * 0.86))
        x = max(0, (sw - need_w) // 2)
        y = max(0, (sh - need_h) // 2)
        self.root.geometry(f"{need_w}x{need_h}+{x}+{y}")
        self.root.minsize(min(640, sw - 80), min(self.root.winfo_reqheight() + 24, int(sh * 0.86)))
        self.root.after(30, self._fit_wrap)
        self._fitted = True

    # ---------- 逻辑 ----------
    def boot(self):
        def work():
            ok = start_server()
            self.root.after(0, lambda: self.set_status(
                f"服务已就绪 · {base_url()}" if ok else "服务启动失败：缺少 config.json 或前端文件", ok))
            if not ok:
                return
            self.root.after(0, self.refresh_numbers)
            try:
                plan = service.afternoon_plan()
                if plan.get("status") != "needed":
                    return
                self.root.after(0, lambda: self.set_status(
                    "已过 14:30，正在拉取行情并由 DeepSeek 给出建议…", True))
                result = service.auto_afternoon()
            except Exception:
                log("自动生成建议失败：\n" + traceback.format_exc())
                self.root.after(0, lambda: self.set_status("自动生成建议失败", False))
                return
            self.root.after(0, lambda: self._after_auto(result))

        threading.Thread(target=work, daemon=True).start()

    def _after_auto(self, result):
        status = (result or {}).get("status")
        if status == "ready":
            self.refresh_numbers()
            text = f"今日建议已由 DeepSeek 生成 · 行情 {result.get('count', 0)} 只 · 要变动 {result.get('advice', 0)} 只"
            self.set_status(text, True)
        elif status == "error":
            self.set_status(result.get("error") or "自动生成建议失败", False)
        elif status == "busy":
            self.set_status("正在生成今日建议…", True)

    def set_status(self, text, ok=True):
        self.status.configure(text=text, fg="#2f6fed" if ok else "#b02b2b")
        self.root.after(0, self._fit_wrap)

    def refresh_numbers(self):
        d = fetch_data()
        if not d:
            self.tip.configure(text="读不到数据。首次使用：点「分析」，在网页里录一次最终值就行。")
            self._hide_warn()
            self._ensure_fit()
            return
        s = d.get("summary") or {}
        self.val_total.configure(text=fmt(s.get("total")))
        self.sub_total.configure(text="元")
        pnl = s.get("pnl") or 0
        color = "#d93a3a" if pnl > 0 else "#129d5b" if pnl < 0 else "#1b2130"
        self.val_pnl.configure(text=f"{fmt(pnl)} 元", fg=color)
        self.sub_pnl.configure(text=f"{fmt(s.get('rate'))}%", fg=color)
        ratio = s.get("tech_ratio") or 0
        self.val_tech.configure(text=f"{fmt(ratio, 1)}%", fg="#e8890c" if ratio > 35 else "#1b2130")
        self.sub_tech.configure(text="上限 35%")
        newest = s.get("latest_date") or ""
        advice = d.get("advice_by_date") or {}
        todo = sum(1 for a in advice.get(newest, []) if a.get("priority") == "必做")
        pick = sum(1 for a in advice.get(newest, []) if a.get("priority") == "择机")
        self.tip.configure(text=f"最新记录 {newest or '—'}\n必做 {todo} 条 · 择机 {pick} 条")
        warns = d.get("warnings") or []
        if warns:
            self.warn.configure(text="\n".join(f"⚠ {w}" for w in warns[:3]), wraplength=620)
            if not self._warn_shown:
                self.warn.pack(fill="x", pady=(12, 0))
                self._warn_shown = True
        else:
            self._hide_warn()
        self.set_status(f"服务已就绪 · {base_url()}", True)
        self._ensure_fit()

    def _hide_warn(self):
        if self._warn_shown:
            self.warn.pack_forget()
            self._warn_shown = False

    def on_analyze(self):
        self.btn_label.configure(text="分析中…")
        self.btn.configure(bg="#9db7f5")
        self.btn_label.configure(bg="#9db7f5")
        self.set_status("正在取最新数据…", True)

        def work():
            ok = start_server()
            d = fetch_data() if ok else None
            self.root.after(0, lambda: self._after_analyze(ok, d))

        threading.Thread(target=work, daemon=True).start()

    def _after_analyze(self, ok, d):
        self.btn.configure(bg="#2f6fed")
        self.btn_label.configure(text="分析", bg="#2f6fed")
        if not ok:
            self.set_status("服务启动失败，请检查 config.json / web 资源是否齐全", False)
            return
        self.refresh_numbers()
        webbrowser.open(f"{base_url()}/?t={int(time.time())}")
        self.set_status(f"已在浏览器打开 · {base_url()}", True)

    def on_export(self):
        self.set_status("正在导出给 AI 的文件…", True)

        def work():
            try:
                data, err = service.export_ai_brief()
            except Exception as e:
                data, err = None, f"{type(e).__name__}: {e}"
            self.root.after(0, lambda: self._after_export(data, err))

        threading.Thread(target=work, daemon=True).start()

    def _after_export(self, data, err):
        if err or not data:
            self.set_status(err or "导出失败", False)
            return
        self.set_status(f"已导出 {data['filename']}", True)
        try:
            os.startfile(data["path"])
        except OSError:
            pass

    def on_restart(self):
        self.set_status("正在重启服务…", True)

        def work():
            stop_server()
            ok = start_server()
            self.root.after(0, lambda: self.set_status(
                f"服务已重启 · {base_url()}" if ok else "重启失败", ok))
            if ok:
                self.root.after(0, self.refresh_numbers)

        threading.Thread(target=work, daemon=True).start()

    def _center(self, win):
        win.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = max(0, (sw - win.winfo_reqwidth()) // 2)
        y = max(0, (sh - win.winfo_reqheight()) // 2)
        win.geometry(f"+{x}+{y}")

    def _plan_missing(self):
        try:
            cap = float((engine.load_config().get("profile") or {}).get("capital_total") or 0)
        except (TypeError, ValueError):
            return True
        return cap <= 0

    def _prompt_setup(self):
        """没有密钥先填密钥；没有总计划金额再填金额。已经有的不弹。"""
        try:
            ready = ai.is_ready(engine.load_config())
        except Exception:
            log("检查密钥失败：\n" + traceback.format_exc())
            ready = True
        if not ready:
            self.open_key(then=self._prompt_plan)
            return
        self._prompt_plan()

    def _prompt_plan(self):
        if not self._plan_missing():
            return
        self.open_plan()

    def open_plan(self):

        win = tk.Toplevel(self.root)
        win.title("总计划金额")
        win.configure(bg="#f4f6f9")
        win.transient(self.root)
        win.resizable(False, False)
        win.grab_set()
        box = tk.Frame(win, bg="#f4f6f9")
        box.pack(fill="both", padx=18, pady=16)
        tk.Label(
            box, text="计划放在基金里的总金额",
            font=("Microsoft YaHei UI", 11, "bold"), bg="#f4f6f9", fg="#1b2130", anchor="w",
        ).pack(anchor="w")
        tk.Label(
            box, text="科技占比、现金比例和单只上限都按这个数计算。单位是元。",
            font=("Microsoft YaHei UI", 9), bg="#f4f6f9", fg="#6b7688",
            justify="left", anchor="w", wraplength=360,
        ).pack(anchor="w", pady=(6, 10))
        ent = tk.Entry(
            box, font=("Consolas", 12), relief="flat", bg="#ffffff", fg="#1b2130",
            insertbackground="#1b2130", highlightthickness=1, highlightbackground="#e6e9ef",
            highlightcolor="#2f6fed", width=36,
        )
        ent.pack(fill="x", ipady=6)
        hint = tk.Label(
            box, text="例如 30000",
            font=("Microsoft YaHei UI", 9), bg="#f4f6f9", fg="#8b94a3", anchor="w",
        )
        hint.pack(anchor="w", pady=(8, 12))

        def on_save():
            raw = ent.get().replace(",", "").replace("，", "").strip()
            try:
                amount = round(float(raw), 2)
            except (TypeError, ValueError):
                hint.configure(text="请填一个大于 0 的数字", fg="#b02b2b")
                return
            if amount <= 0:
                hint.configure(text="金额要大于 0", fg="#b02b2b")
                return
            try:
                cfg = engine.load_config()
                cfg.setdefault("profile", {})["capital_total"] = amount
                engine.save_config(cfg)
            except Exception:
                log("保存总计划金额失败：\n" + traceback.format_exc())
                hint.configure(text="保存失败，请再试一次", fg="#b02b2b")
                return
            self.set_status(f"总计划金额已保存 · {amount:.0f} 元", True)
            win.destroy()

        bar = tk.Frame(box, bg="#f4f6f9")
        bar.pack(fill="x")
        save = tk.Frame(bar, bg="#2f6fed", cursor="hand2")
        save_label = tk.Label(
            save, text="保存", font=("Microsoft YaHei UI", 9, "bold"),
            bg="#2f6fed", fg="#ffffff", cursor="hand2",
        )
        save_label.pack(padx=16, pady=6)
        save.pack(side="right")
        for widget in (save, save_label):
            widget.bind("<Button-1>", lambda _e: on_save())
        win.bind("<Return>", lambda _e: on_save())
        self._center(win)
        ent.focus_set()

    def open_key(self, then=None):

        win = tk.Toplevel(self.root)
        win.title("DeepSeek")
        win.configure(bg="#f4f6f9")
        win.transient(self.root)
        win.resizable(False, False)
        win.grab_set()

        box = tk.Frame(win, bg="#f4f6f9")
        box.pack(fill="both", padx=18, pady=16)
        state = tk.Label(
            box, text="已设置" if keybox.configured() else "未设置",
            font=("Microsoft YaHei UI", 11, "bold"), bg="#f4f6f9", fg="#1b2130", anchor="w",
        )
        state.pack(anchor="w")
        tk.Label(
            box, text="只保存在本机当前用户下。窗口、网页和 config.json 都不会显示这串内容。",
            font=("Microsoft YaHei UI", 9), bg="#f4f6f9", fg="#6b7688",
            justify="left", anchor="w", wraplength=360,
        ).pack(anchor="w", pady=(6, 10))
        ent = tk.Entry(
            box, show="●", font=("Consolas", 12), relief="flat", bg="#ffffff", fg="#1b2130",
            insertbackground="#1b2130", highlightthickness=1, highlightbackground="#e6e9ef",
            highlightcolor="#2f6fed", exportselection=False, width=36,
        )
        ent.pack(fill="x", ipady=6)
        ent.bind("<<Copy>>", lambda _e: "break")
        ent.bind("<<Cut>>", lambda _e: "break")
        hint = tk.Label(
            box, text="留空保存不会改掉已有内容",
            font=("Microsoft YaHei UI", 9), bg="#f4f6f9", fg="#8b94a3", anchor="w",
        )
        hint.pack(anchor="w", pady=(8, 12))

        def blank_config():
            cfg = engine.load_config()
            ds = cfg.setdefault("deepseek", {})
            if ds.get("api_key"):
                ds["api_key"] = ""
                engine.save_config(cfg)

        def on_save():
            text = ent.get().strip()
            ent.delete(0, "end")
            if not text:
                hint.configure(text="未输入新内容，已保留原来的设置", fg="#6b7688")
                return
            try:
                keybox.save(text)
                blank_config()
            except Exception:
                log("保存密钥失败：\n" + traceback.format_exc())
                hint.configure(text="保存失败，请再试一次", fg="#b02b2b")
                return
            del text
            state.configure(text="已设置")
            hint.configure(text="已保存。这里不会回显。", fg="#2f6fed")
            self.set_status("DeepSeek 已保存", True)
            if then:
                finish()

        def on_clear():
            ent.delete(0, "end")
            keybox.clear()
            try:
                blank_config()
            except Exception:
                log("清除密钥时写配置失败：\n" + traceback.format_exc())
            state.configure(text="未设置")
            hint.configure(text="已清除", fg="#6b7688")
            self.set_status("DeepSeek 已清除", True)

        bar = tk.Frame(box, bg="#f4f6f9")
        bar.pack(fill="x")
        tk.Button(
            bar, text="清除", command=on_clear, relief="flat", bg="#ffffff",
            fg="#1b2130", activebackground="#e8edf5", font=("Microsoft YaHei UI", 9),
            cursor="hand2", highlightthickness=1, highlightbackground="#e6e9ef",
        ).pack(side="left", ipady=4, ipadx=10)
        save = tk.Frame(bar, bg="#2f6fed", cursor="hand2")
        save_label = tk.Label(
            save, text="保存", font=("Microsoft YaHei UI", 9, "bold"),
            bg="#2f6fed", fg="#ffffff", cursor="hand2",
        )
        save_label.pack(padx=16, pady=6)
        save.pack(side="right")
        for widget in (save, save_label):
            widget.bind("<Button-1>", lambda _e: on_save())
        closed = {"done": False}

        def finish():
            if closed["done"]:
                return
            closed["done"] = True
            win.destroy()
            if then:
                self.root.after(80, then)

        win.protocol("WM_DELETE_WINDOW", finish)
        win.bind("<Escape>", lambda _e: finish())
        self._center(win)
        ent.focus_set()

    def open_dir(self):
        if os.name == "nt":
            os.startfile(HOME)  # noqa
        elif sys.platform == "darwin":
            os.system(f'open "{HOME}"')
        else:
            os.system(f'xdg-open "{HOME}"')

    def on_quit(self):
        self.root.destroy()


def _hide_plaintext_key():
    """config.json 里如果还留着明文 key，挪到本机加密文件后立刻清空。日志不写 key。"""
    try:
        cfg = engine.load_config()
        raw = str(((cfg.get("deepseek") or {}).get("api_key") or "")).strip()
        if not raw or raw.startswith("在这里"):
            return
        if not keybox.configured():
            keybox.save(raw)
        cfg.setdefault("deepseek", {})["api_key"] = ""
        engine.save_config(cfg)
        log("已把 DeepSeek key 从 config.json 移走")
    except Exception:
        log("转移明文 key 失败：\n" + traceback.format_exc())


def main():
    log(f"启动：frozen={FROZEN} HOME={HOME} ASSETS={ASSETS}")
    try:
        if os.name == "nt":
            try:
                # 让窗口按系统 DPI 真实渲染，避免高缩放比例下文字被裁切
                ctypes.windll.shcore.SetProcessDpiAwarenessContext(-4)
            except Exception:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
        seed_files()
        _hide_plaintext_key()
        root = tk.Tk()
        App(root)
        root.mainloop()
    except Exception:
        log("界面异常：\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
