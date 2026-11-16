# -*- coding: utf-8 -*-
"""
虚拟键盘几何布局（ANSI 104 键）
坐标以「键宽单位 u」表示，渲染时再换算成像素。
对应华为规范中的「折叠态-全尺寸键盘 / 展开态-悬浮键盘」两种规格。
"""

from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Key:
    sid: str          # 与 shortcuts.py 中的键位 id 对应
    label: str        # 键帽原始字母/文字（华为规范：提示时必须保留原有字母）
    x: float
    y: float
    w: float
    h: float
    small: bool = False   # 功能键行，字号更小


ROW_GAP = 1.12          # 行间距（单位 u）
KEY_H = 0.92
FN_H = 0.80

# ---------------- 主键盘区 ----------------
MAIN_ROWS: list[list[tuple]] = [
    # row 0: 功能键区
    [("ESC", "Esc", 1.0), ("_gap", "", 0.55),
     ("F1", "F1", 1.0), ("F2", "F2", 1.0), ("F3", "F3", 1.0), ("F4", "F4", 1.0),
     ("_gap", "", 0.32),
     ("F5", "F5", 1.0), ("F6", "F6", 1.0), ("F7", "F7", 1.0), ("F8", "F8", 1.0),
     ("_gap", "", 0.32),
     ("F9", "F9", 1.0), ("F10", "F10", 1.0), ("F11", "F11", 1.0), ("F12", "F12", 1.0),
     ("_gap", "", 0.32),
     ("PRTSC", "PrtSc", 1.0), ("SCRLK", "ScrLk", 1.0), ("PAUSE", "Pause", 1.0)],
    # row 1: 数字行
    [("`", "`", 1.0), ("1", "1", 1.0), ("2", "2", 1.0), ("3", "3", 1.0),
     ("4", "4", 1.0), ("5", "5", 1.0), ("6", "6", 1.0), ("7", "7", 1.0),
     ("8", "8", 1.0), ("9", "9", 1.0), ("0", "0", 1.0),
     ("-", "-", 1.0), ("=", "=", 1.0), ("BACK", "Backspace", 2.0)],
    # row 2
    [("TAB", "Tab", 1.5),
     ("Q", "Q", 1.0), ("W", "W", 1.0), ("E", "E", 1.0), ("R", "R", 1.0),
     ("T", "T", 1.0), ("Y", "Y", 1.0), ("U", "U", 1.0), ("I", "I", 1.0),
     ("O", "O", 1.0), ("P", "P", 1.0), ("[", "[", 1.0), ("]", "]", 1.0),
     ("\\", "\\", 1.5)],
    # row 3
    [("CAPS", "Caps", 1.75),
     ("A", "A", 1.0), ("S", "S", 1.0), ("D", "D", 1.0), ("F", "F", 1.0),
     ("G", "G", 1.0), ("H", "H", 1.0), ("J", "J", 1.0), ("K", "K", 1.0),
     ("L", "L", 1.0), (";", ";", 1.0), ("'", "'", 1.0),
     ("ENTER", "Enter", 2.25)],
    # row 4
    [("LSHIFT", "Shift", 2.25),
     ("Z", "Z", 1.0), ("X", "X", 1.0), ("C", "C", 1.0), ("V", "V", 1.0),
     ("B", "B", 1.0), ("N", "N", 1.0), ("M", "M", 1.0),
     (",", ",", 1.0), (".", ".", 1.0), ("/", "/", 1.0),
     ("RSHIFT", "Shift", 2.75)],
    # row 5
    [("LCTRL", "Ctrl", 1.25), ("LWIN", "Win", 1.25), ("LALT", "Alt", 1.25),
     ("SPACE", "", 6.25),
     ("RALT", "Alt", 1.25), ("RWIN", "Win", 1.25), ("MENU", "Menu", 1.25),
     ("RCTRL", "Ctrl", 1.25)],
]

# 左右成对的功能键共享同一指令 id
SID_ALIAS = {
    "LCTRL": "CTRL", "RCTRL": "CTRL",
    "LSHIFT": "SHIFT", "RSHIFT": "SHIFT",
    "LALT": "ALT", "RALT": "ALT",
    "LWIN": "WIN", "RWIN": "WIN",
}


def canonical(sid: str) -> str:
    return SID_ALIAS.get(sid, sid)


# ---------------- 编辑 / 导航 / 方向键区 ----------------
NAV_KEYS: list[tuple] = [
    ("INS", "Ins", 0.0, 0.0, 1.0), ("HOME", "Home", 1.0, 0.0, 1.0),
    ("PGUP", "PgUp", 2.0, 0.0, 1.0),
    ("DEL", "Del", 0.0, 1.0, 1.0), ("END", "End", 1.0, 1.0, 1.0),
    ("PGDN", "PgDn", 2.0, 1.0, 1.0),
    ("UP", "↑", 1.0, 3.0, 1.0),
    ("LEFT", "←", 0.0, 4.0, 1.0), ("DOWN", "↓", 1.0, 4.0, 1.0),
    ("RIGHT", "→", 2.0, 4.0, 1.0),
]

# ---------------- 数字小键盘 ----------------
NUM_KEYS: list[tuple] = [
    ("NUMLOCK", "Num", 0.0, 0.0, 1.0, 1.0), ("N/", "/", 1.0, 0.0, 1.0, 1.0),
    ("N*", "*", 2.0, 0.0, 1.0, 1.0), ("N-", "−", 3.0, 0.0, 1.0, 1.0),
    ("N7", "7", 0.0, 1.0, 1.0, 1.0), ("N8", "8", 1.0, 1.0, 1.0, 1.0),
    ("N9", "9", 2.0, 1.0, 1.0, 1.0), ("N+", "+", 3.0, 1.0, 1.0, 2.0),
    ("N4", "4", 0.0, 2.0, 1.0, 1.0), ("N5", "5", 1.0, 2.0, 1.0, 1.0),
    ("N6", "6", 2.0, 2.0, 1.0, 1.0),
    ("N1", "1", 0.0, 3.0, 1.0, 1.0), ("N2", "2", 1.0, 3.0, 1.0, 1.0),
    ("N3", "3", 2.0, 3.0, 1.0, 1.0), ("NENT", "Enter", 3.0, 3.0, 1.0, 2.0),
    ("N0", "0", 0.0, 4.0, 2.0, 1.0), ("N.", ".", 2.0, 4.0, 1.0, 1.0),
]


def build(style: str = "compact", narrow: bool = False, screen_w: int = 1920,
          scale: float = 1.0):
    """
    返回 (keys, canvas_w, canvas_h, unit, header)
    style: 'compact' 悬浮紧凑键盘（华为折叠态全键盘造型） / 'full' 含数字键盘的 104 键
    scale: v4.01 新增的键盘缩放倍率（0.6 ~ 2.4），仅影响几何尺寸，键位关系不变
    """
    total_units = 18.55 if style == "compact" else 22.9
    unit = min((screen_w - 140.0) / total_units, 64.0 if style == "compact" else 58.0)
    unit = max(unit, 34.0)
    # v4.01：缩放后再按屏幕宽度夹紧，避免放大后左右超出可视区
    scale = max(0.55, min(2.4, float(scale or 1.0)))
    # +0.76u 是左右 pad_x 合计，避免放大后画布超出屏幕
    unit = min(unit * scale, (screen_w - 60.0) / (total_units + 0.76))
    unit = max(unit, 18.0)

    pad_x = int(unit * 0.38)
    header = int(unit * 0.78)
    pad_bottom = int(unit * 0.28)
    content_h = 0.92 + ROW_GAP * 4 + KEY_H      # 最后一行底边 = 6.32u
    canvas_w = int(total_units * unit + pad_x * 2)
    canvas_h = int((content_h + 0.62) * unit + header + pad_bottom)

    gap = unit * (0.045 if narrow else 0.115)
    keys: list[Key] = []

    def push(sid, label, x, y, w, h, small=False):
        keys.append(Key(sid, label,
                        pad_x + x * unit + gap / 2,
                        header + y * unit + gap / 2,
                        w * unit - gap, h * unit - gap, small))

    # 主区
    for ri, row in enumerate(MAIN_ROWS):
        x = 0.0
        y = 0.0 if ri == 0 else 0.92 + (ri - 1) * ROW_GAP
        h = FN_H if ri == 0 else KEY_H
        for item in row:
            sid, label, w = item[0], item[1], item[2]
            if sid == "_gap":
                x += w
                continue
            push(sid, label, x, y, w, h, small=(ri == 0))
            x += w

    # 导航区
    nav_x = 15.42
    nav_y = 0.92
    for sid, label, x, y, w in NAV_KEYS:
        push(sid, label, nav_x + x, nav_y + y * ROW_GAP, w, KEY_H)

    # 数字键盘
    if style == "full":
        num_x = 18.85
        num_y = 0.92
        for sid, label, x, y, w, h in NUM_KEYS:
            push(sid, label, num_x + x, num_y + y * ROW_GAP, w,
                 h * ROW_GAP - (ROW_GAP - KEY_H) if h > 1 else KEY_H)

    keys.append(Key("__HEADER__", "", 0, 0, 0, 0))  # 占位，渲染器忽略
    return keys, canvas_w, canvas_h, unit, header


if __name__ == "__main__":
    for s in ("compact", "full"):
        k, w, h, u, hd = build(s)
        print(s, "keys=", len(k) - 1, "canvas=", w, h, "unit=", round(u, 1), "header=", hd)
