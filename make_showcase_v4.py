# -*- coding: utf-8 -*-
"""生成 v4「延时消失」三档展示图：控件条状态 + 松手后存活时长"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import controlbar

HERE = Path(__file__).resolve().parent
BW, BH = controlbar.BAR_W, controlbar.BAR_H

try:
    F_TITLE = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 21)
    F_SUB = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 13)
    F_LABEL = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 15)
    F_SMALL = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 12)
except Exception:
    F_TITLE = F_SUB = F_LABEL = F_SMALL = ImageFont.load_default()

W, H = 1120, 470
BG = (245, 247, 251)
CARD = (255, 255, 255)
LINE = (215, 222, 233)
INK = (32, 42, 62)
MUTED = (108, 120, 140)
ACCENT = (47, 108, 236)
TRACK = (226, 232, 242)

out = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(out)

d.text((30, 20), "松手后延时消失 · 三档由你决定", font=F_TITLE, fill=INK)
d.text((30, 52), "键帽可点开关不再绑定到粘滞行为；两种模式统一走同一个倒计时",
       font=F_SUB, fill=MUTED)

rows = [
    ("立即消失（默认）", 0, "松开 Ctrl 键盘马上收起，鼠标穿透/可点都一致"),
    ("5 秒后消失", 5000, "松手后仍可看清指令，或用鼠标点键帽执行"),
    ("10 秒后消失", 10000, "更长的操作窗口；期间任何点击都会重新计时"),
]

BAR_X, AXIS_X, AXIS_MAX = 30, 700, 350
for i, (label, ms, desc) in enumerate(rows):
    y = 108 + i * 98
    d.rounded_rectangle((20, y - 30, W - 20, y + BH + 14), 12,
                        fill=CARD, outline=LINE, width=1)
    d.text((34, y - 25), label, font=F_LABEL, fill=INK)
    d.text((34 + 190, y - 22), desc, font=F_SMALL, fill=MUTED)

    st = dict(mouse_click=(i == 1), fade=True, opacity=78,
              hide_delay_ms=ms, theme="light", wallpaper_theme=False)
    im = controlbar.static_image(st)
    plate = Image.new("RGBA", (BW, BH), (224, 231, 242, 255))
    plate.alpha_composite(im)
    out.paste(plate.convert("RGB"), (BAR_X, y))

    # 时间轴：起点 = 松手时刻，最大长度 = 10 秒
    d.text((AXIS_X, y - 25), "松手", font=F_SMALL, fill=MUTED)
    d.line((AXIS_X, y - 4, AXIS_X, y + BH + 4), fill=LINE, width=1)
    d.rounded_rectangle((AXIS_X, y + 14, AXIS_X + AXIS_MAX, y + 26), 6,
                        fill=TRACK)
    if ms > 0:
        length = int(AXIS_MAX * ms / 10000.0)
        d.rounded_rectangle((AXIS_X, y + 14, AXIS_X + length, y + 26), 6,
                            fill=ACCENT)
        d.text((AXIS_X + length + 8, y + 12), "自动消失",
               font=F_SMALL, fill=INK)
    else:
        d.ellipse((AXIS_X - 5, y + 15, AXIS_X + 5, y + 25), fill=ACCENT)
        d.text((AXIS_X + 12, y + 12), "立即收起", font=F_SMALL, fill=INK)

d.text((30, H - 56),
       "控件条上点「延时消失」胶囊即可循环 立即 → 5s → 10s；托盘「松手后延时消失」可选 3/5/10/15/30 秒或自定义（支持 2.5 这类小数）",
       font=F_SMALL, fill=MUTED)
d.text((30, H - 34), "Esc 随时立即收起 · Ctrl+Alt+H 锁定为常驻速查板（不受延时影响）",
       font=F_SMALL, fill=MUTED)

dest = HERE / "新功能_延时消失.png"
out.save(dest)
print("saved", dest, out.size)
