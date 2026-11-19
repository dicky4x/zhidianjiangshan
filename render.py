# -*- coding: utf-8 -*-
"""
虚拟键盘渲染器（Pillow -> 逐像素 alpha 分层窗口）
复刻华为 MateBook Fold「情境式指令提示」的视觉规则：
  * 半透明全尺寸键盘，按住辅助键即时浮现
  * 可用组合键同时亮起，显示「符号 + 指令」，并保留原有字母
  * 文本过长或应用未提供图标时，自动退化为纯文本
"""

from __future__ import annotations

import colorsys
import ctypes
import os
import winreg
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageStat

import icons
import layout

WINDIR = os.environ.get("WINDIR", r"C:\Windows")
FONTS = os.path.join(WINDIR, "Fonts")
APP_NAME = "指点江山"
APP_VERSION = "4.12"


@lru_cache(maxsize=64)
def font(size: int, bold: bool = False):
    names = (["msyhbd.ttc", "msyh.ttc", "simhei.ttf"] if bold
             else ["msyh.ttc", "segoeui.ttf", "arial.ttf"])
    for n in names:
        p = os.path.join(FONTS, n)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


# ---------------------------------------------------------------- v4.02 字体大小
# 默认 1.0 = v4.00 原始字号；可独立自定义，不再跟随键盘缩放倍率。
_FONT_SCALE = 1.0

# v4.08：背景面板透明度（10~255）。键帽 / 文字 / 高亮永远不透明；
# 只有「面板背景」随此值变化，实现「背景透明度可调、键帽不透视」。
_BG_ALPHA = 255


def background_alpha(cfg) -> int:
    """从配置计算背景面板 alpha。

    fade=False（半透明总开关关闭）=> 255 全不透明；
    fade=True 时按 opacity(10~100) 映射到 alpha(约 26~255)。
    """
    if not cfg.get("fade", True):
        return 255
    pct = max(10, min(100, int(cfg.get("opacity", 100) or 100)))
    return max(26, min(255, int(round(255 * pct / 100.0))))


def sf(size: int, bold: bool = False):
    """scaled font：字体倍率为 1.0 时与原来的 font() 完全一致"""
    return font(max(7, int(round(size * _FONT_SCALE))), bold)


# 高频常用指令：用金橙色 + 加粗描边突出，查找更快
COMMON_SIDS = {
    "C", "V", "X", "S", "A", "Z", "Y", "F", "P", "N", "O", "W", "T", "R", "L",
    "ESC", "TAB", "ENTER", "SPACE", "BACK", "DEL", "LEFT", "RIGHT", "UP", "DOWN",
    "HOME", "END", "F5", "F11", "F12",
}
COMMON_HINT_WORDS = (
    "复制", "粘贴", "保存", "全选", "撤销", "剪切", "重做", "打印", "打开", "新建",
    "查找", "搜索", "关闭", "刷新", "退出", "切换", "任务管理器", "显示桌面",
    "重命名", "删除", "锁定", "截图", "回到", "前往",
)


def is_common(sid: str, label: str | None) -> bool:
    if not label:
        return False
    if layout.canonical(sid) in COMMON_SIDS:
        return True
    return any(word in label for word in COMMON_HINT_WORDS)


# 常用键的金橙色系：深色/浅色主题下都比默认蓝紫色更醒目
# v4.08：全部改为不透明，避免高亮键帽透出底层文本
COMMON_FILL = (255, 178, 46, 255)
COMMON_GLOW = (255, 150, 20, 255)
COMMON_EDGE = (255, 240, 196, 255)
COMMON_TEXT = (48, 28, 4, 255)


def system_is_light() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        v, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return bool(v)
    except Exception:
        return False


_WALLPAPER_CACHE = {}   # v4.04：壁纸取色很重（读图+统计），只在壁纸变化时算一次


def wallpaper_accent() -> tuple[int, int, int]:
    """壁纸联动主题：取桌面壁纸平均色，提饱和后作为强调色（华为壁纸联动的 PC 实现）"""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        ok = ctypes.windll.user32.SystemParametersInfoW(0x0073, 1024, buf, 0)
        path = buf.value
        if not ok or not path or not os.path.exists(path):
            return _WALLPAPER_CACHE.get("color", (58, 122, 255))
        if _WALLPAPER_CACHE.get("path") == path:
            return _WALLPAPER_CACHE["color"]
        with Image.open(path) as im:
            im = im.convert("RGB").resize((32, 32))
            r, g, b = ImageStat.Stat(im).mean
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        s = max(s, 0.48)
        v = min(max(v, 0.52), 0.82)
        rr, gg, bb = colorsys.hsv_to_rgb(h, s, v)
        color = (int(rr * 255), int(gg * 255), int(bb * 255))
        _WALLPAPER_CACHE["path"] = path
        _WALLPAPER_CACHE["color"] = color
        return color
    except Exception:
        return _WALLPAPER_CACHE.get("color", (58, 122, 255))


_SHADOW_CACHE = {}      # v4.04：高斯模糊阴影按尺寸缓存，避免每次重绘都模糊整幅大图


def _shadow_layer(cw: int, ch: int, color):
    key = (cw, ch, color)
    got = _SHADOW_CACHE.get(key)
    if got is not None:
        return got
    shadow = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((8, 8 + 12, cw - 8, ch - 8 + 12), 18, fill=color)
    out = shadow.filter(ImageFilter.GaussianBlur(16))
    if len(_SHADOW_CACHE) > 6:
        _SHADOW_CACHE.clear()
    _SHADOW_CACHE[key] = out
    return out


def theme_colors(theme: str, accent: tuple[int, int, int] | None = None):
    light = system_is_light() if theme == "auto" else (theme == "light")
    acc = accent or (48, 108, 246)
    # v4.08 修复：键盘上所有「实体像素」一律 alpha=255，杜绝任何透视。
    # 半透明只保留给面板背景（由 bg_opacity 单独控制）和面板外阴影。
    # 键帽本体 / 边框 / 文字 / 高亮 / 发光全部不透明，避免键帽之间出现
    # 「缝隙」、键帽顶部出现「透视到底层文本的长条」。
    if light:
        return {
            "panel": (248, 250, 253, 255), "panel_border": (200, 210, 228, 255),
            "key": (255, 255, 255, 255), "key_border": (205, 214, 230, 255),
            "key_text": (36, 46, 66, 255), "dim": (110, 122, 145, 255),
            "header": (36, 46, 66, 255), "sub": (95, 108, 132, 255),
            "hot": acc + (255,), "hot_edge": (255, 255, 255, 255),
            "hot_text": (255, 255, 255, 255), "glow": acc + (255,),
            "accent": acc + (255,), "shadow": (20, 30, 50, 120),
        }
    return {
        "panel": (17, 21, 30, 255), "panel_border": (78, 86, 104, 255),
        "key": (36, 43, 58, 255), "key_border": (92, 101, 122, 255),
        "key_text": (222, 230, 244, 255), "dim": (168, 178, 198, 255),
        "header": (242, 246, 255, 255), "sub": (176, 187, 208, 255),
        "hot": acc + (255,), "hot_edge": (255, 255, 255, 255),
        "hot_text": (255, 255, 255, 255), "glow": acc + (255,),
        "accent": acc + (255,), "shadow": (0, 0, 0, 150),
    }


def _tw(draw, text, fnt):
    try:
        return draw.textlength(text, font=fnt)
    except Exception:
        return len(text) * fnt.size


def _fit(draw, text, fnt_size, max_w):
    """按可用宽度自适应字号；返回 (字体, 是否放得下)（恢复 v4.00 候选档）"""
    for sz in (fnt_size, fnt_size - 1, fnt_size - 2, 9, 8):
        if sz < 8:
            break
        f = sf(sz, True)
        if _tw(draw, text, f) <= max_w:
            return f, True
    return sf(8, True), False


def _draw_key(d, k, label, C, hint_mode, accent, pressed, flash=False, hover=False,
              common=False):
    # v4.01：坐标取整。Pillow 10.x 的 rounded_rectangle 在 1px 描边 + 浮点坐标
    # 且键盘放大时会抛出「x1 must be >= x0」，取整后彻底规避。
    x, y = int(round(k.x)), int(round(k.y))
    w, h = int(round(k.w)), int(round(k.h))
    r = max(3, int(min(w, h) * 0.16))
    box = (x, y, x + w, y + h)
    hot = label is not None
    sid = layout.canonical(k.sid)
    # v4.01：常用功能换金橙色 + 深色字，一眼可辨
    fill_c = COMMON_FILL if (hot and common) else C["hot"]
    glow_c = COMMON_GLOW if (hot and common) else C["glow"]
    edge_c = COMMON_EDGE if (hot and common) else C["hot_edge"]
    text_c = COMMON_TEXT if (hot and common) else C["hot_text"]

    if hot:
        # v4.08：去掉半透明发光描边与顶部高光长条——它们会在键帽上形成
        # 「透视到底层文本的长条」。高亮键帽整体用不透明金色实心绘制。
        # v4.08b：发光外扩收窄到 1px（原 3px）。相邻高亮键间距约 6px，
        # 外扩 3px 会把缝隙填满让键帽看起来「贴在一起」；收窄后缝隙清晰可见，
        # 且发光仍是不透明实心，不产生任何透视。
        d.rounded_rectangle((x - 1, y - 1, x + w + 1, y + h + 1), r + 1, fill=glow_c)
        d.rounded_rectangle(box, r, fill=fill_c, outline=edge_c,
                            width=2 if common else 1)
    else:
        d.rounded_rectangle(box, r, fill=C["key"], outline=C["key_border"], width=1)
        if pressed:
            d.rounded_rectangle(box, r, outline=C["accent"], width=2)

    # ① 华为规范：无论是否显示指令，都保留原有字母（默认恢复原字号）
    if k.label:
        base_sz = 9 if k.small else (10 if len(k.label) > 4 else 12)
        lf = sf(base_sz, False)
        d.text((x + 5, y + 4), k.label, font=lf,
               fill=text_c if hot else C["key_text"], anchor="la")

    if flash:
        # v4.08：点击反馈只用不透明描边，不再叠加半透明白色填充（会造成透视）
        # v4.08b：外扩收窄到 1px，避免点击时描边盖住相邻键帽缝隙
        d.rounded_rectangle((x - 1, y - 1, x + w + 1, y + h + 1), r + 1,
                            outline=(255, 255, 255, 255), width=2)

    if hover:
        # v4.01：鼠标悬停只用实心高亮描边，不再叠加半透明白色让键帽「变淡」
        # v4.08b：外扩收窄到 1px，避免悬停时描边盖住相邻键帽缝隙
        d.rounded_rectangle((x - 1, y - 1, x + w + 1, y + h + 1), r + 1,
                            outline=(255, 255, 255, 255), width=2)

    if not hot:
        return

    # ② 带图标 / 纯文本两种样式：文本过长或未匹配到图标时退化为纯文本
    max_w = w - 8
    tf, fits = _fit(d, label, 10 if k.small else (12 if w > 62 else 11), max_w)
    use_icon = (hint_mode == "icon") and (not k.small) and len(label) <= 5
    icon_s = max(10, int(h * 0.22))
    if use_icon:
        # 预演一次图标匹配，避免画了图标又发现不匹配
        tmp = Image.new("RGBA", (icon_s + 2, icon_s + 2))
        use_icon = icons.draw_icon(ImageDraw.Draw(tmp), label, 1, 1, icon_s, text_c)
        del tmp

    cx = x + w / 2
    lines = [label]
    if not fits and k.small:
        # 功能键行较矮：强制单行，超长指令截断（华为「纯文本」降级）
        tf = sf(9, True)
        t = label
        while len(t) > 2 and _tw(d, t, tf) > max_w:
            t = t[:-1]
        if t != label and len(t) > 2:
            t = t[:-1] + "…"
        lines = [t]
        use_icon = False
    elif not fits and len(label) > 4 and h > 46:
        cut = (len(label) + 1) // 2
        lines = [label[:cut], label[cut:]]
        tf = sf(9, True)
        use_icon = False

    line_h = tf.size + 2
    total_h = line_h * len(lines)
    top = y + h - total_h - max(3, h * 0.08)
    min_top = y + int((14 if k.small else 16) * max(1.0, _FONT_SCALE))
    top = max(top, min_top)
    top = min(top, y + h - total_h - 1)

    for li, line in enumerate(lines):
        ly = top + li * line_h + line_h / 2
        tw = _tw(d, line, tf)
        tx = cx - tw / 2
        if use_icon and li == len(lines) - 1:
            ix = tx - icon_s - 3
            if ix >= x + 2:
                icons.draw_icon(d, label, ix, ly - icon_s / 2, icon_s, text_c)
        d.text((tx, ly), line, font=tf, fill=text_c, anchor="lm")


def delay_label(ms) -> str:
    """5000 -> '5 秒'；1500 -> '1.5 秒'；0 -> '立即'（菜单与信息条共用）"""
    ms = max(0, int(ms or 0))
    if ms == 0:
        return "立即"
    if ms % 1000 == 0:
        return "%d 秒" % (ms // 1000)
    return "%g 秒" % (ms / 1000.0)


def render_image(cfg, combo: str, mapping: dict[str, str], app_name: str,
                 lang: str = "", pressed_mods: set[str] | None = None,
                 locked: bool = False, flash_sid: str | None = None,
                 hover_sid: str | None = None, mouse_mode: bool = False,
                 pending_hide: bool = False,
                 cursor_xy: tuple[int, int] | None = None,
                 hover_action: str | None = None,
                 custom_mode: bool = False):
    """
    绘制成普通 RGBA 图，返回 (Image, x, y)；供预览导出与正式渲染共用。
    cursor_xy：v4.04 起已忽略（保留参数仅为兼容旧调用）。
    """
    pressed_mods = pressed_mods or set()
    style = cfg.get("layout", "compact")
    narrow = cfg.get("narrow", False)
    hint_mode = cfg.get("hint_mode", "icon")
    theme = cfg.get("theme", "dark")
    accent = wallpaper_accent() if cfg.get("wallpaper_theme", True) else None
    C = theme_colors(theme, accent)

    # v4.02：字体大小独立配置，默认 1.0 = v4.00 原始字号（与键盘缩放解耦）
    global _FONT_SCALE, _BG_ALPHA
    _FONT_SCALE = max(0.5, min(2.0, float(cfg.get("font_scale", 1.0) or 1.0)))
    # v4.08：只有面板背景跟随透明度设置，键帽等实体像素恒为不透明
    _BG_ALPHA = background_alpha(cfg)
    scale = max(0.5, min(2.0, float(cfg.get("kb_scale", 1.0) or 1.0)))

    sw, sh = cfg.get("screen_w", 1920), cfg.get("screen_h", 1080)
    keys, cw, ch, unit, header = layout.build(style, narrow, sw, scale)

    im = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))

    # 阴影（v4.04：缓存，避免每次重绘都做一次高斯模糊）
    im = Image.alpha_composite(im, _shadow_layer(cw, ch, C["shadow"]))

    d = ImageDraw.Draw(im)
    # v4.08：面板背景按透明度设置绘制；键帽等实体像素在其上以不透明覆盖，
    # 实现「背景可调透明、键帽始终清晰不透视」。
    panel_fill = C["panel"][:3] + (_BG_ALPHA,)
    d.rounded_rectangle((8, 8, cw - 8, ch - 8), 18,
                        fill=panel_fill, outline=C["panel_border"], width=1)

    # ---------- 顶部信息条 ----------
    pad = 18
    # v4.04：两态布局一致，把手位始终预留，避免键帽开关切换时标题跳动
    title_pad = pad + 12
    pill = combo.replace("+", " + ")
    pf = sf(12, True)
    pill_w = _tw(d, pill, pf) + 22
    d.rounded_rectangle((title_pad, 14, title_pad + pill_w, 40), 13, fill=C["accent"])
    d.text((title_pad + pill_w / 2, 27), pill, font=pf, fill=(255, 255, 255, 255), anchor="mm")

    title = "%s v%s  ·  情境式指令提示  ·  %s" % (APP_NAME, APP_VERSION, app_name)
    d.text((title_pad + pill_w + 14, 27), title, font=sf(13, True),
           fill=C["header"], anchor="lm")
    ms = max(0, int(cfg.get("hide_delay_ms", 0) or 0))
    if locked:
        right = "已锁定速查（Ctrl+Alt+H 解锁）"
    elif pending_hide:
        tail = (delay_label(ms) + "后自动消失" if ms else "操作结束后自动消失")
        right = tail + "  ·  鼠标操作重新计时  ·  Esc 立即收起"
    elif ms > 0:
        right = "松手后 %s 消失  ·  右上角可改档位" % delay_label(ms)
        if mouse_mode:
            right = "键帽可点  ·  " + right
    else:
        right = "松开辅助键立即收起  ·  右上角可设延时消失"
        if mouse_mode:
            right = "键帽可点  ·  " + right
    if mouse_mode:
        right = "键帽可点  ·  拖顶栏移动 / 右下角缩放"
    d.text((cw - pad - (40 if lang else 0), 27), right, font=sf(11),
           fill=C["sub"], anchor="rm")
    if lang:
        d.rounded_rectangle((cw - pad - 32, 12, cw - pad, 38), 8,
                            outline=C["panel_border"], width=1)
        d.text((cw - pad - 16, 25), lang, font=sf(10, True), fill=C["sub"], anchor="mm")

    # ---------- 键帽 ----------
    pressed_sids = {m.upper() for m in pressed_mods}
    for k in keys:
        if k.sid == "__HEADER__":
            continue
        sid = layout.canonical(k.sid)
        label = mapping.get(sid)
        _draw_key(d, k, label, C, hint_mode, accent,
                  pressed=(sid in pressed_sids), flash=(flash_sid == sid),
                  hover=(hover_sid is not None and hover_sid == sid),
                  common=is_common(sid, label))

    # 组合键暂无指令时给出可操作的空状态提示
    if not mapping:
        cy = header + unit * 2.8
        d.rounded_rectangle((cw * 0.16, cy - 26, cw * 0.84, cy + 26), 14,
                            fill=C["panel_border"], outline=C["key_border"], width=1)
        if custom_mode:
            empty_tip = "自定义面板  ·  所有键位需自行设置  ·  右键任意键帽自定义组合键"
        else:
            empty_tip = "「%s」暂无内置指令  ·  可在 config.json 的 custom_shortcuts 中自行添加" % combo
        d.text((cw / 2, cy), empty_tip,
               font=sf(13, True), fill=C["header"], anchor="mm")

    # ---------- 底部信息条 ----------
    bottom_y = ch - 26
    n = sum(1 for k in keys if k.sid != "__HEADER__"
            and layout.canonical(k.sid) in mapping)
    if hover_action:
        left_text = "当前键：%s" % str(hover_action)[:72]
    else:
        left_text = f"共 {n} 组可用指令   ·   金橙色 = 常用功能   ·   灰色键无对应功能"
    lf = sf(10)
    d.text((pad, bottom_y), left_text, font=lf, fill=C["sub"], anchor="lm")
    left_w = _tw(d, left_text, lf)

    # v4.06：把弹出开关快捷键做成醒目胶囊固定在键盘底部，打开键盘即可看到。
    # 跟随用户自定义快捷键与字体缩放，两态（键帽可点开/关）位置完全一致。
    hk = str(cfg.get("toggle_hotkey", "Ctrl+Esc") or "Ctrl+Esc")
    tip = "%s  开关弹出" % hk.replace("+", " + ")
    tf = sf(10, True)
    tip_w = _tw(d, tip, tf) + 20
    right_x = cw - pad - (28 if mouse_mode else 0)
    foot = "Esc 收起  ·  Ctrl+Alt+H 锁定"
    if right_x - tip_w - 12 - left_w - 12 >= pad:
        d.text((right_x - tip_w - 12, bottom_y), foot,
               font=sf(10), fill=C["sub"], anchor="rm")
    d.rounded_rectangle((right_x - tip_w, bottom_y - 11, right_x, bottom_y + 11),
                        11, fill=C["accent"])
    d.text((right_x - tip_w / 2, bottom_y), tip, font=tf,
           fill=(255, 255, 255, 255), anchor="mm")

    # ---------- v4.04 拖拽把手：两态都绘制，保证开关切换时视觉一致 ----------
    # 左上三道横纹：按住顶栏可移动整个键盘
    gx, gy = 10, 18
    for i in range(3):
        d.line([(gx, gy + i * 5), (gx + 7, gy + i * 5)], fill=C["sub"], width=2)
    # 右下三道斜纹：拖动可缩放键盘
    for i in range(3):
        o = i * 6
        d.line([(cw - 30 + o, ch - 13), (cw - 13, ch - 30 + o)],
               fill=C["sub"], width=2)

    # ---------- 位置 ----------
    # v4.04：位置只由「用户拖出的自定义坐标」或「停靠策略」决定，
    # 与「键帽可点」开关无关，也不再自动避开光标。两态共用同一位置。
    x = (sw - cw) // 2
    px, py = cfg.get("kb_pos_x"), cfg.get("kb_pos_y")
    if isinstance(px, (int, float)) and isinstance(py, (int, float)):
        x = max(0, min(int(px), max(0, sw - cw)))
        y = max(0, min(int(py), max(0, sh - ch)))
    elif cfg.get("position", "top") == "bottom":
        y = sh - ch - 56
    elif cfg.get("position", "top") == "top":
        y = 56                      # v4.11：默认停靠屏幕顶部，给悬浮功能条留出空间
    else:
        y = (sh - ch) // 2
    return im, x, max(0, y)


def draw_hover(im: Image.Image, keys, hover_sid: str | None):
    """v4.04：只在缓存底图上叠加悬停描边，鼠标移动时不再重绘整幅键盘。"""
    if not hover_sid:
        return im
    d = ImageDraw.Draw(im)
    for k in keys:
        if k.sid == "__HEADER__":
            continue
        if layout.canonical(k.sid) != hover_sid:
            continue
        x, y = int(round(k.x)), int(round(k.y))
        w, h = int(round(k.w)), int(round(k.h))
        r = max(3, int(min(w, h) * 0.16)) + 4
        d.rounded_rectangle((x - 4, y - 4, x + w + 4, y + h + 4), r,
                            outline=(255, 255, 255, 255), width=3)
        break
    return im


def to_premultiplied_bgra(im: Image.Image, opacity: int = 100):
    r, g, b, a = im.split()
    if opacity < 100:
        a = ImageChops.multiply(a, Image.new("L", im.size, int(255 * opacity / 100)))
    return Image.merge("RGBA", (ImageChops.multiply(b, a), ImageChops.multiply(g, a),
                                ImageChops.multiply(r, a), a)).tobytes()


def render(cfg, combo: str, mapping: dict[str, str], app_name: str,
           lang: str = "", pressed_mods: set[str] | None = None,
           locked: bool = False, flash_sid: str | None = None,
           hover_sid: str | None = None, mouse_mode: bool = False,
           pending_hide: bool = False,
           cursor_xy: tuple[int, int] | None = None):
    """
    返回 (预乘 BGRA 字节流, w, h, x, y)，可直接喂给 LayeredWindow.blit()。
    fade=False 时强制 100% 不透明（「半透明显示」总开关）。
    """
    im, x, y = render_image(cfg, combo, mapping, app_name, lang,
                            pressed_mods, locked, flash_sid, hover_sid,
                            mouse_mode, pending_hide, cursor_xy)
    # v4.08：透明度已在 render_image 内只作用于面板背景，键帽保持不透明。
    # 这里整图 alpha 固定 100，绝不能再整体衰减（否则键帽重新透视）。
    return to_premultiplied_bgra(im, 100), im.width, im.height, x, y


if __name__ == "__main__":
    from shortcuts import resolve, app_display_name
    cfg = {"layout": "compact", "narrow": False, "hint_mode": "icon",
           "theme": "dark", "opacity": 100, "wallpaper_theme": False,
           "screen_w": 1920, "screen_h": 1080, "position": "bottom"}
    m = resolve("Ctrl", "word")
    data, w, h, x, y = render(cfg, "Ctrl", m, app_display_name("word"), "中", {"Ctrl"})
    print("render ok:", w, h, "bytes=", len(data), "pos=", x, y, "keys=", len(m))
