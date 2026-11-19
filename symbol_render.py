# -*- coding: utf-8 -*-
"""
特殊符号页渲染器
================
与虚拟键盘共用主题色、字体、阴影，绘制「分类标签 + 符号网格」的独立画面。
每个符号格子显示：大符号（主体）+ 名称 + Alt 码角标，点击即输入该符号。

对外接口：
  render_image(cfg, category, hover_sid, flash_sid) -> (Image, x, y, cells)
  draw_hover(im, cells, hover_sid) -> Image
  render_bgra(cfg, ...) -> (bgra, w, h, x, y, cells)
"""

from __future__ import annotations

from PIL import Image, ImageDraw

import render
import symbols


def _symbol_font(size: int, char: str = ""):
    """按字符挑选能真正渲染的字体。

    Segoe UI Symbol 覆盖 √ ✘ ☑ ◇ 等数学/图形符号，但不含 CJK 括号
    （「」【】《》）与带圈汉字（㈠㈡㈢）——这些字符在它里面是空字形/豆腐块，
    必须回退到微软雅黑。用 U+10FFFF（永久非字符，任何字体都无字形）作
    对照，逐个字体检测 getmask 是否真的为该字符产出不同字形。
    """
    import os
    from PIL import ImageFont
    fonts = render.FONTS
    order = ("seguisym.ttf", "msyh.ttc", "simsun.ttc", "segoeui.ttf", "arial.ttf")
    _TOFU = "\U0010ffff"
    if char:
        try:
            blank = bytes(ImageFont.truetype(os.path.join(fonts, "seguisym.ttf"),
                                             size).getmask(_TOFU))
        except Exception:
            blank = b""
        for name in order:
            p = os.path.join(fonts, name)
            if not os.path.exists(p):
                continue
            try:
                f = ImageFont.truetype(p, size)
                if bytes(f.getmask(char)) != bytes(f.getmask(_TOFU)):
                    return f
            except Exception:
                pass
    # 兜底：沿用旧逻辑，取第一个存在的字体
    for name in order:
        p = os.path.join(fonts, name)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return render.font(size)


def _theme(cfg):
    accent = (render.wallpaper_accent()
              if cfg.get("wallpaper_theme", True) else None)
    return render.theme_colors(cfg.get("theme", "dark"), accent), accent


def _place(cfg, cw, ch):
    """与键盘一致的停靠逻辑：自定义坐标 > 底部/居中。"""
    sw, sh = cfg.get("screen_w", 1920), cfg.get("screen_h", 1080)
    x = (sw - cw) // 2
    px, py = cfg.get("kb_pos_x"), cfg.get("kb_pos_y")
    if isinstance(px, (int, float)) and isinstance(py, (int, float)):
        x = max(0, min(int(px), max(0, sw - cw)))
        y = max(0, min(int(py), max(0, sh - ch)))
    elif cfg.get("position", "bottom") == "bottom":
        y = sh - ch - 56
    else:
        y = (sh - ch) // 2
    return x, max(0, y)


def render_image(cfg: dict, category: int = 0,
                 hover_sid: str | None = None,
                 flash_sid: str | None = None):
    """绘制符号页，返回 (RGBA 图, x, y, cells)。"""
    render._FONT_SCALE = max(0.5, min(2.0, float(cfg.get("font_scale", 1.0) or 1.0)))
    # v4.08：与键盘一致，透明度只作用于面板背景，符号格恒不透明
    render._BG_ALPHA = render.background_alpha(cfg)
    C, accent = _theme(cfg)
    cells, cw, ch, header_h = symbols.build_page(cfg, category)

    im = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    im = Image.alpha_composite(im, render._shadow_layer(cw, ch, C["shadow"]))
    d = ImageDraw.Draw(im)
    panel_fill = C["panel"][:3] + (render._BG_ALPHA,)
    d.rounded_rectangle((8, 8, cw - 8, ch - 8), 18,
                        fill=panel_fill, outline=C["panel_border"], width=1)

    pad = 18
    f_title = render.sf(13, True)
    f_sub = render.sf(10)
    f_cat = render.sf(11, True)
    f_name = render.sf(9)
    f_alt = render.sf(9, True)

    # ---------- 顶部信息条 ----------
    pill = "特殊符号"
    pf = render.sf(12, True)
    pill_w = render._tw(d, pill, pf) + 22
    d.rounded_rectangle((pad + 10, 14, pad + 10 + pill_w, 40), 13, fill=C["accent"])
    d.text((pad + 10 + pill_w / 2, 27), pill, font=pf,
           fill=(255, 255, 255, 255), anchor="mm")
    d.text((pad + 10 + pill_w + 14, 27),
           "点击符号直接输入到光标处  ·  无需记 Alt 码",
           font=f_title, fill=C["header"], anchor="lm")
    d.text((cw - pad, 27),
           "%s v%s  ·  任意辅助键弹出  ·  Esc 关闭符号页"
           % (render.APP_NAME, render.APP_VERSION),
           font=f_sub, fill=C["sub"], anchor="rm")

    # ---------- 分类标签 ----------
    for cell in cells:
        if cell.kind != "cat":
            continue
        x, y, w, h = int(cell.x), int(cell.y), int(cell.w), int(cell.h)
        if cell.active:
            d.rounded_rectangle((x, y, x + w, y + h), 9,
                                fill=C["accent"], outline=C["accent"], width=1)
            text_col = (255, 255, 255, 255)
        else:
            hot = (hover_sid == cell.sid)
            d.rounded_rectangle((x, y, x + w, y + h), 9,
                                fill=C["key"], outline=C["key_border"], width=1)
            text_col = C["header"] if hot else C["sub"]
        d.text((x + w / 2, y + h / 2), cell.name, font=f_cat,
               fill=text_col, anchor="mm")

    # ---------- 符号网格 ----------
    big_cache = {}
    for cell in cells:
        if cell.kind != "sym":
            continue
        x, y, w, h = int(cell.x), int(cell.y), int(cell.w), int(cell.h)
        hot = (hover_sid == cell.sid)
        flash = (flash_sid == cell.sid)
        fill = C["hot"] if (hot or flash) else C["key"]
        edge = C["hot_edge"] if (hot or flash) else C["key_border"]
        r = max(6, int(min(w, h) * 0.16))
        d.rounded_rectangle((x, y, x + w, y + h), r,
                            fill=fill, outline=edge, width=2 if (hot or flash) else 1)

        # 主体符号（放大）——按字符挑字体，缓存键含字符
        # 略下移并右偏，给左上角 Alt 码角标让位，避免 √ 斜线被角标压住
        fs = max(22, int(h * 0.46))
        ck = (fs, cell.char)
        sfont = big_cache.get(ck)
        if sfont is None:
            sfont = _symbol_font(fs, cell.char)
            big_cache[ck] = sfont
        sym_col = (255, 255, 255, 255) if (hot or flash) else C["key_text"]
        d.text((x + w / 2 + 6, y + h * 0.50), cell.char, font=sfont,
               fill=sym_col, anchor="mm")
        # 名称
        d.text((x + w / 2, y + h * 0.80), cell.name, font=f_name,
               fill=C["sub"] if not (hot or flash) else (255, 255, 255, 220),
               anchor="mm")
        # Alt 码角标：移到左上角，不再压住符号主体
        tag = ("Alt+" + cell.alt) if cell.alt else ("U+" + cell.uni)
        tw = render._tw(d, tag, f_alt)
        d.rounded_rectangle((x + 4, y + 3, x + tw + 14, y + 18), 4,
                            fill=C["panel"], outline=C["key_border"], width=1)
        d.text((x + 9 + tw / 2, y + 10.5), tag, font=f_alt,
               fill=C["header"], anchor="mm")

    # ---------- 底部信息条 ----------
    by = ch - 20
    total = symbols.count()
    d.text((pad, by),
           "共 %d 个符号  ·  %d 个分类  ·  点击即输入" % (total, len(symbols.CATEGORIES)),
           font=f_sub, fill=C["sub"], anchor="lm")

    x, y = _place(cfg, cw, ch)
    return im, x, y, cells


def draw_hover(im: Image.Image, cells, hover_sid: str | None,
               flash_sid: str | None = None):
    """在缓存底图上叠加悬停/按下高亮。"""
    if not hover_sid and not flash_sid:
        return im
    C, _ = _theme_cached(im)
    d = ImageDraw.Draw(im)
    for cell in cells:
        if cell.sid == "__HEADER__":
            continue
        # v4.08b：描边外扩收窄到 1px，避免盖住相邻格子的缝隙
        if hover_sid and cell.sid == hover_sid:
            d.rounded_rectangle((cell.x - 1, cell.y - 1,
                                 cell.x + cell.w + 1, cell.y + cell.h + 1),
                                max(6, int(min(cell.w, cell.h) * 0.16) + 1),
                                outline=(255, 255, 255, 255), width=2)
        if flash_sid and cell.sid == flash_sid:
            d.rounded_rectangle((cell.x - 1, cell.y - 1,
                                 cell.x + cell.w + 1, cell.y + cell.h + 1),
                                max(6, int(min(cell.w, cell.h) * 0.16) + 1),
                                outline=(255, 200, 90, 255), width=2)
    return im


def _theme_cached(im):
    # draw_hover 只需描边，主题取默认即可，无需重新算壁纸
    return {"panel": (0, 0, 0, 0)}, None


def render_bgra(cfg: dict, category: int = 0, hover_sid=None, flash_sid=None):
    """返回 (bgra, w, h, x, y, cells)，可直接喂给 LayeredWindow.blit。"""
    im, x, y, cells = render_image(cfg, category, hover_sid, flash_sid)
    # v4.08：透明度只作用于面板背景，符号格恒不透明
    return render.to_premultiplied_bgra(im, 100), im.width, im.height, x, y, cells
