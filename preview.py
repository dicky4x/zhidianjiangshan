# -*- coding: utf-8 -*-
"""
生成效果预览图（不启动钩子/托盘，可用于快速检查配色与排版）
    python preview.py                      -> preview_Ctrl.png
    python preview.py Ctrl+Shift vscode   -> 指定组合与情境
    python preview.py Win excel full      -> 指定键盘规格
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import render
import shortcuts

HERE = Path(__file__).resolve().parent


def desktop(w, h):
    """模拟一张深色桌面壁纸，方便观察半透明玻璃效果"""
    im = Image.new("RGBA", (w, h), (26, 32, 48, 255))
    d = ImageDraw.Draw(im)
    for i in range(0, h, 4):
        t = i / h
        d.line((0, i, w, i), fill=(int(30 + 24 * t), int(38 + 30 * t), int(62 + 42 * t), 255))
    blob = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blob)
    bd.ellipse((w * 0.05, h * 0.12, w * 0.62, h * 0.95), fill=(52, 96, 210, 85))
    bd.ellipse((w * 0.58, -h * 0.2, w * 1.15, h * 0.62), fill=(140, 62, 190, 70))
    return Image.alpha_composite(im, blob.filter(ImageFilter.GaussianBlur(120)))


def main():
    combo = sys.argv[1] if len(sys.argv) > 1 else "Ctrl"
    app_key = sys.argv[2] if len(sys.argv) > 2 else "word"
    style = sys.argv[3] if len(sys.argv) > 3 else "compact"

    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    cfg.update({"screen_w": 1920, "screen_h": 1080, "opacity": 100,
                "wallpaper_theme": False, "layout": style, "position": "bottom"})
    mapping = shortcuts.resolve(combo, app_key, cfg.get("custom_shortcuts"))
    im, x, y = render.render_image(cfg, combo, mapping,
                                   shortcuts.app_display_name(app_key),
                                   "中", set(combo.split("+")), False, None)
    bg = desktop(im.width + 60, im.height + 60)
    layer = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    layer.alpha_composite(im, (30, 30))
    out = Image.alpha_composite(bg, layer).convert("RGB")
    name = "preview_%s_%s.png" % (combo.replace("+", "_"), app_key)
    out.save(str(HERE / name))
    print("saved", name, out.size, "instructions=", len(mapping))


if __name__ == "__main__":
    main()
