# -*- coding: utf-8 -*-
"""桌面端入口 → desktop/app.py（tkinter + 内嵌 API）。"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.environ.setdefault("FUNDLIFE_HOME", _ROOT)

from desktop.app import main

if __name__ == "__main__":
    main()