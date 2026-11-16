# -*- coding: utf-8 -*-
"""
虚拟键盘右上角「常驻可点击控件条」
==================================
独立的 WS_EX_LAYERED 窗口，永远不加 WS_EX_TRANSPARENT：
  * 键盘主体处于鼠标穿透模式时，本控件条依然可以点击（用户要求）
  * 控件条之外的透明区域由分层窗口的 alpha 命中规则自动穿透
  * WS_EX_NOACTIVATE 保证点击控件不会抢走前台窗口，应用情境感知不跑偏

控件全部自绘（Pillow），不依赖原生子控件：
  [键帽可点 拨动开关] [☑ 半透明] [延时消失 ● 5s] 透明度 [━━●━━] 80%

回调：
  get_state() -> {"mouse_click", "fade", "opacity", "hide_delay_ms",
                  "theme", "wallpaper_theme"}
  on_toggle_click() / on_toggle_fade() / on_cycle_delay()
  on_opacity(int) / on_commit() / on_activity()
"""
from __future__ import annotations

import ctypes as C
import os

from PIL import Image, ImageDraw

import render
import win32 as w

BAR_W, BAR_H = 636, 44

# 命中矩形（控件条客户区局部坐标）
R_CLICK = (8, 6, 140, 38)
R_FADE = (146, 6, 248, 38)
R_DELAY = (252, 6, 396, 38)
R_TRACK = (444, 8, 574, 36)

SWITCH_BOX = (96, 15, 132, 29)
CHECK_BOX = (152, 15, 168, 31)
DELAY_PILL = (322, 12, 390, 32)

TRACK_X0, TRACK_X1, TRACK_Y = 450, 568, 22
VALUE_X = 626

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
    """点击胶囊切到下一档；自定义值跳到比它大的最近档，没有则回到「立即」"""
    cur = max(0, int(cur or 0))
    for p in HIDE_PRESETS:
        if p > cur:
            return p
    return 0


def _in(rect, x, y):
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def _colors_for(st):
    accent = (render.wallpaper_accent()
              if st.get("wallpaper_theme", True) else None)
    return render.theme_colors(st.get("theme", "dark"), accent)


def render_image(st, hover=None, dragging=False):
    """绘制控件条，返回 (RGBA 图, 建议整图不透明度%)，供运行时与静态预览共用"""
    C_ = _colors_for(st)
    im = Image.new("RGBA", (BAR_W, BAR_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    # 底板：沿用键盘玻璃配色，但比键盘更实——控件必须恒定清晰可读
    pr, pg, pb, _ = C_["panel"]
    d.rounded_rectangle((0, 0, BAR_W - 1, BAR_H - 1), 14,
                        fill=(pr, pg, pb, 244),
                        outline=C_["panel_border"], width=1)
    d.rounded_rectangle((10, 3, BAR_W - 11, 5), 2, fill=(255, 255, 255, 36))

    hot_bg = (255, 255, 255, 30) if st.get("theme") != "light" else (48, 108, 246, 26)
    if hover:
        r = {"click": R_CLICK, "fade": R_FADE,
             "delay": R_DELAY, "track": R_TRACK}[hover]
        d.rounded_rectangle((r[0], r[1] - 1, r[2], r[3] + 1), 9, fill=hot_bg)

    f = render.font(11, True)

    # ---- ① 键帽可点 拨动开关 ----
    on = bool(st.get("mouse_click"))
    d.text((14, 22), "键帽可点", font=f, fill=C_["header"], anchor="lm")
    sx0, sy0, sx1, sy1 = SWITCH_BOX
    d.rounded_rectangle((sx0, sy0, sx1, sy1), 7,
                        fill=C_["accent"] if on else C_["dim"],
                        outline=C_["panel_border"], width=1)
    kx = sx1 - 7 if on else sx0 + 7
    d.ellipse((kx - 6, 16, kx + 6, 28), fill=(255, 255, 255, 250),
              outline=C_["accent"] if on else C_["panel_border"], width=1)
    d.text((90, 22), "开" if on else "关",
           font=render.font(10, True), fill=C_["sub"], anchor="rm")

    # ---- ② 半透明复选框 ----
    fade = bool(st.get("fade"))
    cx0, cy0, cx1, cy1 = CHECK_BOX
    d.rounded_rectangle((cx0, cy0, cx1, cy1), 3,
                        fill=C_["accent"] if fade else (0, 0, 0, 0),
                        outline=C_["accent"] if fade else C_["dim"], width=1)
    if fade:
        d.line([(cx0 + 3, 23), (cx0 + 6, 27), (cx1 - 2, 18)],
               fill=(255, 255, 255, 255), width=2, joint="curve")
    d.text((176, 22), "半透明", font=f, fill=C_["header"], anchor="lm")

    # ---- ③ 延时消失档位（立即 / 5s / 10s，点击循环） ----
    ms = max(0, int(st.get("hide_delay_ms", 0) or 0))
    d.ellipse((258, 18, 266, 26), fill=C_["accent"] if ms else C_["dim"])
    d.text((272, 22), "延时消失", font=f, fill=C_["header"], anchor="lm")
    p0, p1, p2, p3 = DELAY_PILL
    d.rounded_rectangle((p0, p1, p2, p3), 6,
                        fill=C_["accent"] if ms else C_["dim"],
                        outline=C_["panel_border"], width=1)
    d.text(((p0 + p2) / 2, 22), delay_short(ms),
           font=render.font(11, True),
           fill=(255, 255, 255, 250) if ms else C_["header"], anchor="mm")

    # ---- ④ 透明度滑杆 ----
    d.text((400, 22), "透明度", font=render.font(11, True),
           fill=C_["sub"], anchor="lm")
    value = max(10, min(100, int(st.get("opacity", 92))))
    if not fade:
        value = 100
    t = (value - 10) / 90.0
    fill_x = TRACK_X0 + (TRACK_X1 - TRACK_X0) * t
    d.rounded_rectangle((TRACK_X0, TRACK_Y - 4, TRACK_X1, TRACK_Y + 4), 4,
                        fill=C_["dim"])
    if fade:
        d.rounded_rectangle((TRACK_X0, TRACK_Y - 4, fill_x, TRACK_Y + 4), 4,
                            fill=C_["accent"])
    d.ellipse((fill_x - 7, TRACK_Y - 7, fill_x + 7, TRACK_Y + 7),
              fill=(255, 255, 255, 250), outline=C_["accent"], width=2)
    d.text((VALUE_X, 22), "%d%%" % value, font=render.font(11, True),
           fill=C_["header"], anchor="rm")

    # 控件条不随键盘一起变到极淡，否则低透明度时开关看不清
    return im, max(92, value if fade else 100)


def static_image(st, hover=None):
    """离线预览用：直接返回带最终 alpha 的 RGBA 图"""
    im, pct = render_image(st, hover)
    from PIL import ImageChops
    r, g, b, a = im.split()
    a = ImageChops.multiply(a, Image.new("L", im.size, int(255 * pct / 100)))
    return Image.merge("RGBA", (r, g, b, a))


class ControlBar:
    def __init__(self, get_state, on_toggle_click, on_toggle_fade,
                 on_opacity, on_commit, on_activity, on_cycle_delay=None):
        self.get_state = get_state
        self.on_toggle_click = on_toggle_click
        self.on_toggle_fade = on_toggle_fade
        self.on_cycle_delay = on_cycle_delay
        self.on_opacity = on_opacity
        self.on_commit = on_commit
        self.on_activity = on_activity

        self.x, self.y = 0, 0
        self.panel_rect = (0, 0, 0, 0)
        self.hover = None
        self.mouse_down = None
        self.dragging = False
        self._cache = None
        # 关键：start_click_through=False，窗口永远可点击
        self.win = w.LayeredWindow("KeyHintControlBar",
                                   on_mouse=self._on_mouse,
                                   start_click_through=False)

    # ------------------------------------------------------------ 状态 / 位置
    @property
    def active(self) -> bool:
        """鼠标正按下或正在拖滑杆（用于操作宽限判定）"""
        return self.dragging or self.mouse_down is not None

    @property
    def hwnd(self):
        return self.win.hwnd

    @property
    def visible(self):
        return self.win.visible

    def place(self, px, py, pw, ph, screen_w=1920):
        """贴住虚拟键盘右上角、位于面板上沿之外，不遮挡键帽与信息条"""
        self.panel_rect = (px, py, pw, ph)
        nx = max(4, min(int(screen_w) - BAR_W - 4, px + pw - BAR_W - 8))
        ny = max(4, py - BAR_H - 6)
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

    # ------------------------------------------------------------ 绘制
    def _state_key(self, st):
        return (bool(st.get("mouse_click")), bool(st.get("fade")),
                int(st.get("opacity", 92)), int(st.get("hide_delay_ms", 0) or 0),
                bool(st.get("wallpaper_theme")),
                st.get("theme", "dark"), self.hover, self.dragging)

    def refresh(self, force=False):
        st = self.get_state()
        key = self._state_key(st)
        if not force and key == self._cache:
            self.win.raise_top()
            return
        self._cache = key
        im, bar_alpha = render_image(st, self.hover, self.dragging)
        data = render.to_premultiplied_bgra(im, bar_alpha)
        self.win.blit(data, BAR_W, BAR_H, self.x, self.y)
        self.win.raise_top()

    # ------------------------------------------------------------ 命中 / 事件
    def hit(self, x, y):
        if _in(R_CLICK, x, y):
            return "click"
        if _in(R_FADE, x, y):
            return "fade"
        if _in(R_DELAY, x, y):
            return "delay"
        if _in(R_TRACK, x, y):
            return "track"
        return None

    def _value_at(self, x):
        t = (x - TRACK_X0) / float(TRACK_X1 - TRACK_X0)
        return int(round(10 + max(0.0, min(1.0, t)) * 90))

    def _local_xy(self):
        """
        用光标屏幕坐标减去画面矩形换算局部坐标。
        分层窗口用 WS_POPUP 创建后客户区原点与画面一致；仍以 UpdateLayeredWindow
        记录的屏幕矩形为准，避免 DWM 不可见边框导致「看到的」与「点到的」错位。
        """
        pt = w.POINT()
        w.user32.GetCursorPos(C.byref(pt))
        return pt.x - self.win.rect[0], pt.y - self.win.rect[1]

    def _on_mouse(self, hwnd, msg, wp, lp):
        if os.environ.get("KEYHINT_DEBUG") and msg in (
                w.WM_MOUSEMOVE, w.WM_LBUTTONDOWN, w.WM_LBUTTONUP, w.WM_RBUTTONUP):
            lx, ly = self._local_xy()
            print("控件条鼠标 0x%04X 局部=(%d,%d) 命中=%s rect=%s"
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
                if h == "click":
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
            self.on_activity()
            return 0
        # 明确屏蔽滚轮：透明度只由滑杆 / 托盘菜单控制
        if msg == w.WM_MOUSEWHEEL:
            return 0
        return None

    # ------------------------------------------------------------ 自检辅助
    def _to_screen(self, lx, ly):
        """用 UpdateLayeredWindow 时记录的屏幕矩形换算，与画面严格一致"""
        return self.win.rect[0] + int(lx), self.win.rect[1] + int(ly)

    def screen_point(self, which="click"):
        """返回控件中心的屏幕坐标，供进程内真实鼠标自检使用"""
        r = {"click": R_CLICK, "fade": R_FADE,
             "delay": R_DELAY, "track": R_TRACK}[which]
        lx = (r[0] + r[2]) // 2 if which != "track" else TRACK_X0
        ly = (r[1] + r[3]) // 2
        return self._to_screen(lx, ly)

    def delay_point(self):
        """延时档位胶囊中心的屏幕坐标"""
        p0, p1, p2, p3 = DELAY_PILL
        return self._to_screen((p0 + p2) // 2, (p1 + p3) // 2)

    def track_point(self, ratio):
        lx = TRACK_X0 + (TRACK_X1 - TRACK_X0) * max(0.0, min(1.0, ratio))
        return self._to_screen(lx, TRACK_Y)
