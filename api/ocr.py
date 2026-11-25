# -*- coding: utf-8 -*-
"""
截图像素 → 文字（本地离线 OCR，Windows 自带 Windows.Media.Ocr）
只负责“把图变成文字”；把文字整理成「基金→市值」交给 ai.structure_ocr（DeepSeek）或人工核对。
"""
import os
import subprocess
import tempfile

from api.paths import assets_root

ASSETS = assets_root()
PS1 = os.path.join(ASSETS, "tools", "ocr_words.ps1")
PREP = os.path.join(ASSETS, "tools", "prep_tiles.ps1")


def available():
    return os.path.exists(PS1) and os.path.exists(PREP)


def _ocr_tile(path):
    """调用 PowerShell 版 Windows OCR，结果经 UTF-8 文件回传（避免控制台代码页乱码）。"""
    out_file = os.path.join(tempfile.gettempdir(), f"fundlife_ocr_{os.getpid()}.txt")
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", PS1, "-path", path, "-out", out_file],
            capture_output=True, text=True, timeout=120, encoding="utf-8", errors="ignore",
        )
    except Exception:
        return []
    try:
        with open(out_file, "r", encoding="utf-8-sig") as fh:
            text = fh.read()
    except OSError:
        return []
    finally:
        try:
            os.remove(out_file)
        except OSError:
            pass

    words = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        t, x, y, w, h = parts
        try:
            words.append((t, int(x), int(y), int(w), int(h)))
        except ValueError:
            continue
    return words


def _prepare(image_path):
    """灰度、拉对比度、按高度切片。用 Windows 自带绘图，不依赖 PIL。"""
    out_file = os.path.join(tempfile.gettempdir(), f"fundlife_prep_{os.getpid()}.txt")
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", PREP, "-path", image_path, "-out", out_file, "-owner", str(os.getpid())],
            capture_output=True, text=True, timeout=120, encoding="utf-8", errors="ignore",
        )
    except Exception as e:
        return None, f"读取图片失败：{e}"
    try:
        with open(out_file, "r", encoding="utf-8-sig") as fh:
            lines = [ln.strip() for ln in fh.read().splitlines() if ln.strip()]
    except OSError as e:
        return None, f"读取图片失败：{e}"
    finally:
        try:
            os.remove(out_file)
        except OSError:
            pass
    if not lines:
        return None, "读取图片失败：没有生成切片"
    if lines[0].startswith("ERR"):
        msg = lines[0].split("\t", 1)[-1]
        return None, f"读取图片失败：{msg}"
    tiles = []
    for line in lines:
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        try:
            tiles.append((parts[0], float(parts[1]), float(parts[2])))
        except ValueError:
            continue
    if not tiles:
        return None, "读取图片失败：没有生成切片"
    return tiles, None


def read_lines(image_path, scale=None):
    """返回 (rows, error)。rows: [{y, text, items:[(x, text)]}]，x/y 为原图坐标。"""
    tiles, err = _prepare(image_path)
    if err:
        return [], err

    words = []
    for path, offset, sc in tiles:
        for t, x, y, w, h in _ocr_tile(path):
            words.append((t, x / sc, y / sc + offset, w / sc, h / sc))
        try:
            os.remove(path)
        except OSError:
            pass

    if not words:
        return [], "OCR 没有识别到文字（截图过小/模糊，或系统缺少中文 OCR 语言包）"

    words.sort(key=lambda w: (w[2], w[1]))
    rows = []
    for t, x, y, w, h in words:
        placed = False
        for row in rows:
            tol = max(6, min(h, row["h"]) * 0.45)
            if abs(row["y"] - y) <= tol:
                row["items"].append((x, t))
                row["h"] = max(row["h"], h)
                placed = True
                break
        if not placed:
            rows.append({"y": y, "h": h, "items": [(x, t)]})
    for row in rows:
        row["items"].sort(key=lambda it: it[0])
        # 同列文字之间插空格，避免中英文/数字粘连
        pieces, last_x = [], None
        for x, t in row["items"]:
            if last_x is not None and x - last_x > 18:
                pieces.append(" ")
            pieces.append(t)
            last_x = x
        row["text"] = "".join(pieces)
    rows.sort(key=lambda r: r["y"])
    return rows, None


def raw_text(image_path):
    rows, err = read_lines(image_path)
    if err:
        return None, err
    lines = [r["text"] for r in rows if r["text"].strip()]
    return "\n".join(lines), None
