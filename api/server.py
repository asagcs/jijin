# -*- coding: utf-8 -*-
"""
本地 Web 端：读 data/fundlife.db + state.json；三个写操作走 service 层。
启动：python web.py          默认 http://127.0.0.1:8766
接口：
  GET  /api/data       面板数据（只读）
  POST /api/estimate   预计录入（不入库）
  POST /api/final      最终值入库
  POST /api/trade      调仓
  POST /api/ocr        截图 → 本地 OCR → DeepSeek 结构化（仅预填）
                       kind=amount 持仓市值 / trade 一笔调仓 / dca 定投计划
  POST /api/dca        保存定投开关与每次金额
  GET  /api/ai-brief   导出当天交给 AI 的 Markdown
"""
import argparse
import base64
import json
import mimetypes
import os
import posixpath
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from api import ai, engine, ocr, quotes, service, store
from api.paths import assets_root, project_root

BASE = project_root()
ASSETS = assets_root()
WEB_DIR = os.path.join(ASSETS, "web")
INBOX = os.path.join(BASE, "inbox")


class Handler(BaseHTTPRequestHandler):
    server_version = "FundLife/2.0"

    # ---------- 工具 ----------
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _file(self, path):
        if not os.path.isfile(path):
            self._json({"error": "not found", "path": path}, 404)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------- GET ----------
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/data":
            try:
                self._json(store.fetch_all())
            except Exception as e:  # noqa
                self._json({"error": str(e)}, 500)
            return
        if path == "/api/ai-brief":
            try:
                data, err = service.export_ai_brief()
                self._json({"ok": False, "error": err} if err else {"ok": True, **data})
            except Exception as e:  # noqa
                self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
            return
        if path == "/api/quotes":
            qs = parse_qs(parsed.query)
            mode = (qs.get("mode") or ["estimate"])[0]
            if mode not in ("estimate", "final"):
                mode = "estimate"
            try:
                self._json({"ok": True, **quotes.pull(mode)})
            except Exception as e:  # noqa
                self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
            return
        rel = posixpath.normpath(path).lstrip("/") or "index.html"
        target = os.path.abspath(os.path.join(WEB_DIR, rel))
        if not target.startswith(os.path.abspath(WEB_DIR)):
            self._json({"error": "forbidden"}, 403)
            return
        self._file(target)

    # ---------- POST ----------
    def do_POST(self):
        path = self.path.split("?")[0]
        body = self._body()
        try:
            if path == "/api/estimate":
                data, err = service.estimate(body.get("date") or engine.today_str(),
                                             body.get("values") or {},
                                             body.get("mode") or "amount")
                self._json({"ok": False, "error": err} if err else {"ok": True, **data})
            elif path == "/api/final":
                if body.get("replace"):
                    data, err = service.finalize_replace(body.get("date") or engine.today_str(),
                                                         body.get("holdings") or [])
                else:
                    data, err = service.finalize(body.get("date") or engine.today_str(),
                                                 body.get("values") or {},
                                                 body.get("mode") or "amount",
                                                 source=body.get("source") or "manual")
                self._json({"ok": False, "error": err} if err else {"ok": True, **data})
            elif path == "/api/trade":
                data, err = service.trade(body.get("date") or engine.today_str(),
                                          body.get("fund_id"), body.get("side"),
                                          body.get("amount"),
                                          to_fund_id=body.get("to_fund_id"),
                                          note=body.get("note") or "")
                self._json({"ok": False, "error": err} if err else {"ok": True, **data})
            elif path == "/api/dca":
                data, err = service.apply_dca(body.get("items") or [])
                self._json({"ok": False, "error": err} if err else {"ok": True, **data})
            elif path == "/api/ocr":
                self._json(self._ocr(body))
            else:
                self._json({"ok": False, "error": "unknown api"}, 404)
        except Exception as e:  # noqa
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def _ocr(self, body):
        img = body.get("image") or ""
        if not img:
            return {"ok": False, "error": "没有收到图片"}
        if "," in img and img.strip().startswith("data:"):
            img = img.split(",", 1)[1]
        try:
            raw = base64.b64decode(img)
        except Exception:
            return {"ok": False, "error": "图片解码失败"}
        os.makedirs(INBOX, exist_ok=True)
        path = os.path.join(INBOX, f"upload_{int(time.time())}.png")
        with open(path, "wb") as f:
            f.write(raw)
        if not ocr.available():
            return {"ok": False, "error": "缺少 OCR 脚本 tools/ocr_words.ps1", "path": path}

        text, err = ocr.raw_text(path)
        if err:
            return {"ok": False, "error": err, "path": path}

        cfg = engine.load_config()
        st = store.load_state() or engine.init_state(cfg)
        kind = (body.get("kind") or "amount").strip()
        funds = []
        for f in cfg["funds"]:
            slot = (st.get("funds") or {}).get(f["id"]) or {}
            funds.append({
                "id": f["id"],
                "name": f["name"],
                "amount": slot.get("amount", f.get("amount")),
                "weekly": f.get("dca_weekly", 0),
            })
        base = {
            "ok": True,
            "path": path,
            "kind": kind,
            "raw_text": text[-8000:],
        }
        if kind == "trade":
            trade, note, ai_err = ai.structure_trade(cfg, text, funds)
            base.update({
                "trade": trade,
                "note": note,
                "ai": "deepseek" if trade else ("none" if ai_err else "deepseek"),
                "ai_error": ai_err,
                "count": 1 if trade else 0,
            })
            return base
        if kind == "amount" and body.get("sync"):
            items, note, ai_err = ai.structure_holdings(cfg, text, funds)
            rows, removed = ([], [])
            if items:
                rows, removed = service.reconcile_holdings(items)
            base.update({
                "holdings": rows,
                "removed": removed,
                "note": note,
                "ai": "deepseek" if rows else ("none" if ai_err else "deepseek"),
                "ai_error": ai_err,
                "count": len(rows),
            })
            return base
        if kind == "dca":
            items, note, ai_err = ai.structure_dca(cfg, text, funds)
            base.update({
                "items": items,
                "note": note,
                "ai": "deepseek" if items else ("none" if ai_err else "deepseek"),
                "ai_error": ai_err,
                "count": len(items),
            })
            return base
        values, note, ai_err = ai.structure_ocr(cfg, text, funds)
        base.update({
            "values": values,
            "note": note,
            "ai": "deepseek" if values else ("none" if ai_err else "deepseek"),
            "ai_error": ai_err,
            "count": len(values),
        })
        return base

    def log_message(self, fmt, *args):
        # 打包成无控制台 exe 时 sys.stderr 是 None，这里必须跳过，否则每个请求都会断连
        if getattr(sys, "stderr", None) is None:
            return
        try:
            sys.stderr.write("[web] " + fmt % args + "\n")
        except Exception:
            pass


def make_server(preferred_port=8766, host="127.0.0.1"):
    """建服务实例；端口被占就顺延。返回 (httpd, port)。"""
    port = preferred_port
    for _ in range(12):
        try:
            return ThreadingHTTPServer((host, port), Handler), port
        except OSError:
            port += 1
    raise OSError("端口都被占用")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(os.path.join(WEB_DIR, "index.html")):
        print(f"缺少前端文件：{os.path.join(WEB_DIR, 'index.html')}")
        return 1

    httpd, port = make_server(args.port)
    url = f"http://127.0.0.1:{port}/"
    print(f"基金面板已启动：{url}")
    print("关闭这个窗口即停止服务。")
    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
