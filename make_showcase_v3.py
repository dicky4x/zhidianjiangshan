# -*- coding: utf-8 -*-
"""生成 v3 新功能展示图（离线合成，不依赖屏幕状态）"""
from pathlib import Path

from PIL import Image, ImageDraw

import controlbar
import render

HERE = Path(__file__).resolve().parent
TXT = (28, 42, 66)


def shot1():
    base = {"theme": "light", "wallpaper_theme": False}
    rows = [
        ("默认：穿透模式 · 半透明 80% · 松开 Ctrl 立即收起",
         dict(base, mouse_click=False, fade=True, opacity=80)),
        ("点「键帽可点」后：面板保留供鼠标点击 · 滑杆拖到 45%",
         dict(base, mouse_click=True, fade=True, opacity=45)),
        ("取消「半透明」：100% 不透明（滑杆仍可随时拖回）",
         dict(base, mouse_click=False, fade=False, opacity=30)),
    ]
    W = 470 * 2 + 60
    H = 18 + len(rows) * (88 + 54)
    out = Image.new("RGB", (W, H), (244, 246, 250))
    d = ImageDraw.Draw(out)
    for i, (label, st) in enumerate(rows):
        y = 12 + i * (88 + 54)
        d.text((20, y), label, font=render.font(14, True), fill=TXT)
        bg = Image.new("RGBA", (470, 44), (112, 132, 166, 255))
        bg.alpha_composite(controlbar.static_image(
            st, hover=("click" if i == 1 else None)))
        out.paste(bg.convert("RGB").resize((940, 88), Image.LANCZOS),
                  (30, y + 24))
    p = HERE / "新功能_右上角控件条.png"
    out.save(p)
    print("saved", p.name, out.size)


def shot2():
    on_p, off_p = HERE / "_v3_A_on.png", HERE / "_v3_A_off.png"
    if not (on_p.exists() and off_p.exists()):
        print("跳过对比图：缺少自检截图，请先运行 selftest_v3.py")
        return
    on = Image.open(on_p).convert("RGB").resize((640, 360), Image.LANCZOS)
    off = Image.open(off_p).convert("RGB").resize((640, 360), Image.LANCZOS)
    W, H = 1300, 448
    out = Image.new("RGB", (W, H), (244, 246, 250))
    d = ImageDraw.Draw(out)
    d.text((20, 12), "按住 Ctrl：半透明键盘 + 右上角控件条一起出现",
           font=render.font(14, True), fill=TXT)
    d.text((670, 12), "松开 Ctrl：立即全部消失，鼠标穿透点下层内容",
           font=render.font(14, True), fill=TXT)
    out.paste(on, (20, 40))
    out.paste(off, (670, 40))
    d.text((20, 412),
           "真机实测：按住时屏幕变化 0.222，松开后与基线差异 0.002（selftest_v3 阶段 A）",
           font=render.font(12), fill=(90, 104, 130))
    p = HERE / "新功能_松手即隐.png"
    out.save(p)
    print("saved", p.name, out.size)


if __name__ == "__main__":
    shot1()
    shot2()
