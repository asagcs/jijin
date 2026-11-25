# -*- coding: utf-8 -*-
"""项目根目录与打包资源路径（数据在 exe 旁，静态资源在 FUNDLIFE_ASSETS）。"""
import os

_PKG = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_PKG, ".."))


def project_root():
    return os.path.abspath(os.environ.get("FUNDLIFE_HOME") or _ROOT)


def assets_root():
    return os.path.abspath(os.environ.get("FUNDLIFE_ASSETS") or project_root())