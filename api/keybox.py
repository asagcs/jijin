# -*- coding: utf-8 -*-
"""DeepSeek key 只存在本机当前 Windows 用户能解开的文件里。

不写进 config.json，调用方也不要把读出来的内容显示、记日志或回传给网页。
"""
import os
import ctypes
from ctypes import wintypes

_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _home():
    from api.paths import project_root
    return project_root()


def path():
    return os.path.join(_home(), "data", "deepseek.bin")


def configured():
    try:
        return os.path.isfile(path()) and os.path.getsize(path()) > 0
    except OSError:
        return False


def _blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    return blob, buf


def _protect(plain):
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    blob_in, holder = _blob(plain)
    blob_out = _DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
    )
    if not ok:
        raise OSError("本机加密失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)
        del holder


def _unprotect(cipher):
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    blob_in, holder = _blob(cipher)
    blob_out = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
    )
    if not ok:
        raise OSError("本机解密失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)
        del holder


def load():
    """返回 key 字符串。文件不存在或解不开时返回空字符串，不抛给界面。"""
    if not configured():
        return ""
    try:
        with open(path(), "rb") as f:
            cipher = f.read()
        return _unprotect(cipher).decode("utf-8").strip()
    except Exception:
        return ""


def save(key):
    text = (key or "").strip()
    if not text:
        raise ValueError("empty")
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    cipher = _protect(text.encode("utf-8"))
    tmp = path() + ".tmp"
    with open(tmp, "wb") as f:
        f.write(cipher)
    os.replace(tmp, path())


def clear():
    try:
        os.remove(path())
    except FileNotFoundError:
        pass
    except OSError:
        pass
