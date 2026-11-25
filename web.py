# -*- coding: utf-8 -*-
"""Web 服务入口 → api/server.py（浏览器面板 + REST API）。"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.environ.setdefault("FUNDLIFE_HOME", _ROOT)

from api.server import main

if __name__ == "__main__":
    raise SystemExit(main())