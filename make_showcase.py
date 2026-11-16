# -*- coding: utf-8 -*-
"""生成两个新开关的效果展示图：透明度三档对比 / 鼠标点击悬停态。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

import render
import shortcuts
from preview import desktop

HERE = Path(__file__).resolve().parent
BASE = {
    "layout": "compact", "narrow": False, "hint_mode": "icon",
    "theme": "dark", "wallpaper_theme": False, "screen_w": 1920,
    "screen_h": 1080, "position": "bottom", "show_lang": True,
}
MAPPING = shortcuts.resolve("Ctrl", "word")


def panel(opacity, fade, hover=None, mouse_mode=False):
    cfg = dict(BASE)
    cfg["opacity"], cfg["fade"] = opacity, fade
    im, _, _ = render.render_image(
        cfg, "Ctrl", MAPPING, shortcuts.app_display_name("word"),
        "中", {"Ctrl"}, False, None, hover, mouse_mode)
    if fade and opacity < 100:
        r, g, b, a = im.split()
        a = ImageChops.multiply(a, Image.new("L", im.size, int(255 * opacity / 100)))
        im = Image.merge("RGBA", (r, g, b, a))
    return im


def compare():
    rows = [(30, True, "30%   极淡 · 下层文字/文件清晰可见"),
            (70, True, "70%   平衡 · 指令与内容兼顾"),
            (100, False, "关闭半透明开关 → 100% 完全不透明")]
    scale = 0.72
    pw = int(1235 * scale)
    ph = int(510 * scale)
    W, H = pw + 76, 104 + len(rows) * (ph + 54)
    out = desktop(W, H)
    d = ImageDraw.Draw(out)
    d.text((34, 22), "KeyHint  ·  半透明显示开关（滑块 10% ~ 100% 连续可调）",
           font=render.font(23, True), fill=(240, 246, 255, 255))
    for i, (op, fade, label) in enumerate(rows):
        y = 96 + i * (ph + 54)
        d.text((34, y - 26), label, font=render.font(17, True),
               fill=(170, 205, 255, 255))
        im = panel(op, fade).resize((pw, ph), Image.LANCZOS)
        out.alpha_composite(im, (34, y))
    p = HERE / "新功能_透明度开关.png"
    out.convert("RGB").save(str(p))
    print("saved", p.name, out.size)


def hover_shot():
    im = panel(92, True, hover="C", mouse_mode=True)
    bg = desktop(im.width + 60, im.height + 60)
    layer = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    layer.alpha_composite(im, (30, 30))
    out = Image.alpha_composite(bg, layer)
    d = ImageDraw.Draw(out)
    d.text((34, 12),
           "鼠标点击模式：悬停键帽出现白色可点击框，点击即执行 Ctrl+C（复制）",
           font=render.font(17, True), fill=(255, 226, 140, 255))
    p = HERE / "新功能_鼠标点击.png"
    out.convert("RGB").save(str(p))
    print("saved", p.name, out.size)


if __name__ == "__main__":
    compare()
    hover_shot()
