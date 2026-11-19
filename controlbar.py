# -*- coding: utf-8 -*-
"""
虚拟键盘上方「常驻可点击悬浮功能条」
==================================
v4.11：功能条宽度与虚拟键盘一致，不再固定在右上角一小截。
独立的 WS_EX_LAYERED 窗口，永远不加 WS_EX_TRANSPARENT：
  * 键盘主体处于鼠标穿透模式时，本功能条依然可以点击
  * 功能条之外的透明区域由分层窗口的 alpha 命中规则自动穿透
  * WS_EX_NOACTIVATE 保证点击控件不会抢走前台窗口，应用情境感知不跑偏

控件全部自绘（Pillow），不依赖原生子控件：
  [自定义] [符号页] [键帽可点] [半透明] [延时消失] 透明度 [━━●━━] 80%

回调：
  get_state() -> {"mouse_click", "fade", "opacity", "hide_delay_ms",
                  "theme", "wallpaper_theme", "symbol_mode",
                  "custom_active", "custom_label"}
  on_toggle_click() / on_toggle_fade() / on_cycle_delay()
  on_cycle_custom() / on_manage_custom()
  on_opacity(int) / on_commit() / on_activity()
"""
from __future__ import annotations

import ctypes as C
import os

from PIL import Image, ImageDraw, ImageChops

import render
import win32 as w

BAR_W, BAR_H = 786, 44
BAR_MIN_W = 620

# 控件条上的延时档位循环：立即 -> 5 秒 -> 10 秒 -> 立即
HIDE_PRESETS = (0, 5000, 10000)


def delay_short(ms) -> str:
    """5000 -> '5s'；1500 -> '1.5s'；0 -> '关'"""
    ms = max(0, int(ms or 0))
    if ms == 0:
        return "关"
    if ms % 1000 == 0:
        return "%ds" % (ms // 1000)
    return "%gs" % (ms / 1000.0)


def next_delay_preset(cur) -> int:
    cur = max(0, int(cur or 0))
    for p in HIDE_PRESETS:
        if p > cur:
            return p
    return 0


def layout_for(width: int) -> dict:
    """按功能条实际宽度计算各控件矩形，保证与键盘等宽时布局仍均匀。"""
    width = max(BAR_MIN_W, int(width or BAR_W))
    compact = width < 900
    m = 10
    fixed = (92, 70, 108, 70, 108) if compact else (150, 120, 170, 110, 170)
    min_track = 150 if compact else 180
    gap = max(8, min(36, (width - 2 * m - sum(fixed) - min_track) // 5))

    x = m
    rects = {}
    for name, fw in zip(("custom", "symbols", "click", "fade", "delay"), fixed):
        rects[name] = (x, 6, x + fw, 38)
        x += fw + gap
    rects["track"] = (x, 7, width - m, 37)

    c0, _, c1, _ = rects["click"]
    switch = (c1 - 30, 15, c1 - 8, 29)

    f0, _, f1, _ = rects["fade"]
    check = (f0 + 8, 15, f0 + 24, 31)

    d0, _, d1, _ = rects["delay"]
    pill = (max(d0 + 38, d1 - 66), 12, d1 - 6, 32)

    t0, _, t1, _ = rects["track"]
    track_x0 = t0 + (54 if compact else 68)
    track_x1 = t1 - (46 if compact else 52)
    if track_x1 - track_x0 < 60:
        track_x0, track_x1 = t0 + 40, t1 - 30
    return {
        "width": width,
        "compact": compact,
        "rects": rects,
        "switch": switch,
        "check": check,
        "delay_pill": pill,
        "track_x0": track_x0,
        "track_x1": track_x1,
        "track_y": 22,
        "value_x": t1 - 4,
    }


_DEFAULT_LAYOUT = layout_for(BAR_W)
# 兼容旧自检脚本引用的模块级常量
R_CUSTOM = _DEFAULT_LAYOUT["rects"]["custom"]
R_SYMBOLS = _DEFAULT_LAYOUT["rects"]["symbols"]
R_CLICK = _DEFAULT_LAYOUT["rects"]["click"]
R_FADE = _DEFAULT_LAYOUT["rects"]["fade"]
R_DELAY = _DEFAULT_LAYOUT["rects"]["delay"]
R_TRACK = _DEFAULT_LAYOUT["rects"]["track"]
SWITCH_BOX = _DEFAULT_LAYOUT["switch"]
CHECK_BOX = _DEFAULT_LAYOUT["check"]
DELAY_PILL = _DEFAULT_LAYOUT["delay_pill"]
TRACK_X0, TRACK_X1, TRACK_Y = (_DEFAULT_LAYOUT["track_x0"],
                               _DEFAULT_LAYOUT["track_x1"],
                               _DEFAULT_LAYOUT["track_y"])
VALUE_X = _DEFAULT_LAYOUT["value_x"]


def _in(rect, x, y):
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def _colors_for(st):
    accent = (render.wallpaper_accent()
              if st.get("wallpaper_theme", True) else None)
    return render.theme_colors(st.get("theme", "dark"), accent)


def _fit_label(text, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit - 1] + "…"


def render_image(st, hover=None, dragging=False, width=None):
    """绘制功能条，返回 (RGBA 图, 建议整图不透明度%)。"""
    L = layout_for(width or BAR_W)
    W = L["width"]
    compact = L["compact"]
    R = L["rects"]
    C_ = _colors_for(st)
    im = Image.new("RGBA", (W, BAR_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    pr, pg, pb, _ = C_["panel"]
    d.rounded_rectangle((0, 0, W - 1, BAR_H - 1), 14,
                        fill=(pr, pg, pb, 244),
                        outline=C_["panel_border"], width=1)
    d.rounded_rectangle((10, 3, W - 11, 5), 2, fill=(255, 255, 255, 36))

    hot_bg = (255, 255, 255, 30) if st.get("theme") != "light" else (48, 108, 246, 26)
    if hover and hover in R:
        r = R[hover]
        d.rounded_rectangle((r[0], r[1] - 1, r[2], r[3] + 1), 9, fill=hot_bg)

    f = render.font(10 if compact else 11, True)

    # ---- ⓪ 自定义面板按钮（v4.11）----
    custom_on = bool(st.get("custom_active"))
    r = R["custom"]
    d.rounded_rectangle((r[0], r[1], r[2], r[3]), 9,
                        fill=C_["accent"] if custom_on else C_["panel_border"],
                        outline=C_["accent"] if custom_on else C_["panel_border"],
                        width=1)
    custom_label = st.get("custom_label") or "自定义"
    if compact:
        text = "自定义"          # 窄条只显示功能名，面板名在键盘标题里显示
    else:
        text = ("✔ " if custom_on else "") + str(custom_label)
        text = _fit_label(text, 12)
    d.text(((r[0] + r[2]) / 2, 22), text, font=f,
           fill=(255, 255, 255, 255) if custom_on else C_["header"], anchor="mm")

    # ---- ① 符号页切换 ----
    sym_on = bool(st.get("symbol_mode"))
    r = R["symbols"]
    d.rounded_rectangle((r[0], r[1], r[2], r[3]), 9,
                        fill=C_["accent"] if sym_on else C_["panel_border"],
                        outline=C_["accent"] if sym_on else C_["panel_border"], width=1)
    sym_text = "✔ 符号" if sym_on else ("符号" if compact else "符号页")
    d.text(((r[0] + r[2]) / 2, 22), sym_text, font=f,
           fill=(255, 255, 255, 255) if sym_on else C_["header"], anchor="mm")

    # ---- ② 键帽可点拨动开关 ----
    on = bool(st.get("mouse_click"))
    r = R["click"]
    d.text((r[0] + 8, 22), "可点" if compact else "键帽可点", font=f,
           fill=C_["header"], anchor="lm")
    sx0, sy0, sx1, sy1 = L["switch"]
    d.rounded_rectangle((sx0, sy0, sx1, sy1), 7,
                        fill=C_["accent"] if on else C_["dim"],
                        outline=C_["panel_border"], width=1)
    kx = sx1 - 7 if on else sx0 + 7
    d.ellipse((kx - 6, 16, kx + 6, 28), fill=(255, 255, 255, 250),
              outline=C_["accent"] if on else C_["panel_border"], width=1)

    # ---- ③ 半透明复选框 ----
    fade = bool(st.get("fade"))
    r = R["fade"]
    cx0, cy0, cx1, cy1 = L["check"]
    d.rounded_rectangle((cx0, cy0, cx1, cy1), 3,
                        fill=C_["accent"] if fade else (0, 0, 0, 0),
                        outline=C_["accent"] if fade else C_["dim"], width=1)
    if fade:
        d.line([(cx0 + 3, 23), (cx0 + 6, 27), (cx1 - 2, 18)],
               fill=(255, 255, 255, 255), width=2, joint="curve")
    d.text((cx1 + 6, 22), "半透明", font=f, fill=C_["header"], anchor="lm")

    # ---- ④ 延时消失档位 ----
    ms = max(0, int(st.get("hide_delay_ms", 0) or 0))
    r = R["delay"]
    d.ellipse((r[0] + 8, 18, r[0] + 16, 26),
              fill=C_["accent"] if ms else C_["dim"])
    d.text((r[0] + 22, 22), "延时" if compact else "延时消失", font=f,
           fill=C_["header"], anchor="lm")
    p0, p1, p2, p3 = L["delay_pill"]
    d.rounded_rectangle((p0, p1, p2, p3), 6,
                        fill=C_["accent"] if ms else C_["dim"],
                        outline=C_["panel_border"], width=1)
    d.text(((p0 + p2) / 2, 22), delay_short(ms), font=f,
           fill=(255, 255, 255, 250) if ms else C_["header"], anchor="mm")

    # ---- ⑤ 透明度滑杆 ----
    r = R["track"]
    d.text((r[0] + 4, 22), "透明", font=f, fill=C_["sub"], anchor="lm")
    value = max(10, min(100, int(st.get("opacity", 80))))
    if not fade:
        value = 100
    t = (value - 10) / 90.0
    x0, x1, ty = L["track_x0"], L["track_x1"], L["track_y"]
    fill_x = x0 + (x1 - x0) * t
    d.rounded_rectangle((x0, ty - 4, x1, ty + 4), 4, fill=C_["dim"])
    if fade:
        d.rounded_rectangle((x0, ty - 4, fill_x, ty + 4), 4, fill=C_["accent"])
    d.ellipse((fill_x - 7, ty - 7, fill_x + 7, ty + 7),
              fill=(255, 255, 255, 250), outline=C_["accent"], width=2)
    d.text((L["value_x"], 22), "%d%%" % value, font=f,
           fill=C_["header"], anchor="rm")

    return im, max(92, value if fade else 100)


def static_image(st, hover=None, width=None):
    im, pct = render_image(st, hover, width=width)
    r, g, b, a = im.split()
    a = ImageChops.multiply(a, Image.new("L", im.size, int(255 * pct / 100)))
    return Image.merge("RGBA", (r, g, b, a))


class ControlBar:
    def __init__(self, get_state, on_toggle_click, on_toggle_fade,
                 on_opacity, on_commit, on_activity, on_cycle_delay=None,
                 on_toggle_symbols=None, on_cycle_custom=None,
                 on_manage_custom=None):
        self.get_state = get_state
        self.on_toggle_click = on_toggle_click
        self.on_toggle_fade = on_toggle_fade
        self.on_cycle_delay = on_cycle_delay
        self.on_toggle_symbols = on_toggle_symbols
        self.on_cycle_custom = on_cycle_custom
        self.on_manage_custom = on_manage_custom
        self.on_opacity = on_opacity
        self.on_commit = on_commit
        self.on_activity = on_activity

        self.x, self.y = 0, 0
        self.bar_w = BAR_W
        self.layout = layout_for(BAR_W)
        self.panel_rect = (0, 0, 0, 0)
        self.hover = None
        self.mouse_down = None
        self.dragging = False
        self._cache = None
        self.win = w.LayeredWindow("KeyHintControlBar",
                                   on_mouse=self._on_mouse,
                                   start_click_through=False)

    @property
    def active(self) -> bool:
        return self.dragging or self.mouse_down is not None

    @property
    def hwnd(self):
        return self.win.hwnd

    @property
    def visible(self):
        return self.win.visible

    def place(self, px, py, pw, ph, screen_w=1920):
        """与虚拟键盘等宽，贴在键盘上沿之外，不遮挡键帽与信息条。"""
        self.bar_w = max(BAR_MIN_W, int(pw or BAR_W))
        self.layout = layout_for(self.bar_w)
        self.panel_rect = (px, py, pw, ph)
        nx = max(4, min(int(screen_w) - self.bar_w - 4, int(px)))
        ny = max(4, int(py) - BAR_H - 6)
        if (nx, ny) != (self.x, self.y):
            self.x, self.y = nx, ny
            self._cache = None
        self.refresh()

    def hide(self):
        if self.dragging or self.mouse_down is not None:
            self.dragging = False
            self.mouse_down = None
            if self.win.hwnd and w.user32.GetCapture() == self.win.hwnd:
                w.user32.ReleaseCapture()
        self.win.hide()
        self.hover = None
        self._cache = None

    def close(self):
        self.hide()
        self.win.close()

    def _state_key(self, st):
        return (bool(st.get("mouse_click")), bool(st.get("fade")),
                int(st.get("opacity", 80)), int(st.get("hide_delay_ms", 0) or 0),
                bool(st.get("wallpaper_theme")), bool(st.get("symbol_mode")),
                bool(st.get("custom_active")), str(st.get("custom_label") or ""),
                st.get("theme", "dark"), self.hover, self.dragging, self.bar_w)

    def refresh(self, force=False):
        st = self.get_state()
        key = self._state_key(st)
        if not force and key == self._cache:
            self.win.raise_top()
            return
        self._cache = key
        im, bar_alpha = render_image(st, self.hover, self.dragging, self.bar_w)
        data = render.to_premultiplied_bgra(im, bar_alpha)
        self.win.blit(data, self.bar_w, BAR_H, self.x, self.y)
        self.win.raise_top()

    def hit(self, x, y):
        for name, rect in self.layout["rects"].items():
            if _in(rect, x, y):
                return name
        return None

    def _value_at(self, x):
        x0, x1 = self.layout["track_x0"], self.layout["track_x1"]
        t = (x - x0) / float(x1 - x0)
        return int(round(10 + max(0.0, min(1.0, t)) * 90))

    def _local_xy(self):
        pt = w.POINT()
        w.user32.GetCursorPos(C.byref(pt))
        return pt.x - self.win.rect[0], pt.y - self.win.rect[1]

    def _on_mouse(self, hwnd, msg, wp, lp):
        if os.environ.get("KEYHINT_DEBUG") and msg in (
                w.WM_MOUSEMOVE, w.WM_LBUTTONDOWN, w.WM_LBUTTONUP, w.WM_RBUTTONUP):
            lx, ly = self._local_xy()
            print("功能条鼠标 0x%04X 局部=(%d,%d) 命中=%s rect=%s"
                  % (msg, lx, ly, self.hit(lx, ly), self.win.rect), flush=True)
        if msg == w.WM_SETCURSOR:
            if self.hover or self.dragging:
                w.user32.SetCursor(w.user32.LoadCursorW(None, w.IDC_HAND))
                return 1
            return None
        if msg == w.WM_MOUSEMOVE:
            x, y = self._local_xy()
            if self.dragging:
                self.on_opacity(self._value_at(x))
                self.on_activity()
                return 0
            h = self.hit(x, y)
            if h != self.hover:
                self.hover = h
                self._cache = None
                self.refresh()
            return 0
        if msg == w.WM_LBUTTONDOWN:
            x, y = self._local_xy()
            h = self.hit(x, y)
            self.mouse_down = h
            self.on_activity()
            if h == "track":
                self.dragging = True
                w.user32.SetCapture(hwnd)
                self.on_opacity(self._value_at(x))
                self._cache = None
                self.refresh()
            return 0
        if msg == w.WM_LBUTTONUP:
            x, y = self._local_xy()
            h = self.hit(x, y)
            was_dragging = self.dragging
            if was_dragging:
                self.on_opacity(self._value_at(x))
                self.dragging = False
                if w.user32.GetCapture() == hwnd:
                    w.user32.ReleaseCapture()
                self.on_commit()
            elif h and h == self.mouse_down:
                if h == "custom" and self.on_cycle_custom:
                    self.on_cycle_custom()
                elif h == "symbols" and self.on_toggle_symbols:
                    self.on_toggle_symbols()
                elif h == "click":
                    self.on_toggle_click()
                elif h == "fade":
                    self.on_toggle_fade()
                elif h == "delay" and self.on_cycle_delay:
                    self.on_cycle_delay()
            self.mouse_down = None
            self.on_activity()
            self._cache = None
            self.refresh()
            return 0
        if msg == w.WM_RBUTTONUP:
            x, y = self._local_xy()
            if self.hit(x, y) == "custom" and self.on_manage_custom:
                self.on_manage_custom()
            self.on_activity()
            return 0
        if msg == w.WM_MOUSEWHEEL:
            return 0
        return None

    def _to_screen(self, lx, ly):
        return self.win.rect[0] + int(lx), self.win.rect[1] + int(ly)

    def screen_point(self, which="click"):
        r = self.layout["rects"].get(which) or self.layout["rects"]["click"]
        lx = self.layout["track_x0"] if which == "track" else (r[0] + r[2]) // 2
        return self._to_screen(lx, (r[1] + r[3]) // 2)

    def delay_point(self):
        p0, p1, p2, p3 = self.layout["delay_pill"]
        return self._to_screen((p0 + p2) // 2, (p1 + p3) // 2)

    def track_point(self, ratio):
        x0, x1 = self.layout["track_x0"], self.layout["track_x1"]
        lx = x0 + (x1 - x0) * max(0.0, min(1.0, ratio))
        return self._to_screen(lx, self.layout["track_y"])
