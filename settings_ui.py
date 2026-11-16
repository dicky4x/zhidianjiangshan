# -*- coding: utf-8 -*-
"""
设置窗口（原生 Win32 控件，无第三方 GUI 依赖）

* OpacityDialog：trackbar 滑块 + 半透明总开关，实时预览浓淡变化
* DelayDialog：输入「松手后延时消失」的秒数，支持 0 / 5 / 2.5 这类数值

窗口都是非模态的，复用主线程的现有消息循环，不新开线程、不阻塞托盘。
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W

import win32 as w

u32 = w.user32
gdi32 = w.gdi32
kernel32 = w.kernel32

WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_TABSTOP = 0x00010000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
BS_AUTOCHECKBOX = 0x0003
BS_DEFPUSHBUTTON = 0x0001
SS_RIGHT = 0x0002
TBS_AUTOTICKS = 0x0001
TBS_BOTTOM = 0x0000

TBM_GETPOS = w.WM_USER + 0
TBM_SETPOS = w.WM_USER + 5
TBM_SETTICFREQ = w.WM_USER + 20
TBM_SETRANGE = w.WM_USER + 32
BM_GETCHECK = 0x00F0
BM_SETCHECK = 0x00F1
BST_CHECKED = 1

IDC_TRACK = 1003
IDC_VALUE = 1002
IDC_FADE = 1005
IDC_CLOSE = 1007
BN_CLICKED = 0

WND_W, WND_H = 430, 246   # 含标题栏，客户区约 216px，需容纳到 y=206 的按钮
_CLASS = "KeyHintOpacityDialog"
_registered = False
_dialog = None            # 保活，防止回调被 GC


class OpacityDialog:
    def __init__(self, get_state, on_change, on_close):
        """
        get_state() -> (opacity:int 10..100, fade:bool)
        on_change(opacity, fade) -> None   （滑块/复选框每次变化实时回调）
        on_close() -> None
        """
        self.get_state = get_state
        self.on_change = on_change
        self.on_close = on_close
        self.hwnd = None
        self.htrack = None
        self.hcheck = None
        self.hvalue = None
        self._cb = w.WNDPROC(self._wndproc)

    # ------------------------------------------------------------ 窗口
    def show(self):
        global _registered, _dialog
        _dialog = self
        hinst = kernel32.GetModuleHandleW(None)
        if not _registered:
            wc = w.WNDCLASSEXW()
            wc.cbSize = C.sizeof(wc)
            wc.lpfnWndProc = self._cb
            wc.hInstance = hinst
            wc.lpszClassName = _CLASS
            wc.hbrBackground = u32.GetSysColorBrush(15)   # COLOR_3DFACE
            if not u32.RegisterClassExW(C.byref(wc)):
                err = kernel32.GetLastError()
                if err != 1410:
                    raise OSError("RegisterClassExW(OpacityDialog) failed: %s" % err)
            _registered = True

        if self.hwnd and u32.IsWindow(self.hwnd):
            self._sync_controls()
            u32.ShowWindow(self.hwnd, w.SW_RESTORE)
        else:
            sw, sh = w.screen_size()
            x, y = (sw - WND_W) // 2, max(20, int(sh * 0.20))
            self.hwnd = u32.CreateWindowExW(
                w.WS_EX_TOPMOST | w.WS_EX_TOOLWINDOW, _CLASS,
                "KeyHint · 透明度设置", WS_POPUP | WS_CAPTION | WS_SYSMENU,
                x, y, WND_W, WND_H, W.HWND(0), W.HMENU(0), hinst, None)
            if not self.hwnd:
                raise OSError("CreateWindowExW(OpacityDialog) failed: %s"
                              % kernel32.GetLastError())
            u32.ShowWindow(self.hwnd, w.SW_SHOW)
        u32.SetWindowPos(self.hwnd, w.HWND_TOPMOST, 0, 0, 0, 0,
                         w.SWP_NOMOVE | w.SWP_NOSIZE)
        u32.SetForegroundWindow(self.hwnd)
        self._sync_controls()
        return self.hwnd

    def _mk(self, cls, text, x, y, cw, ch, cid, style=0):
        h = u32.CreateWindowExW(
            0, cls, text, WS_CHILD | WS_VISIBLE | style,
            x, y, cw, ch, self.hwnd, W.HMENU(cid),
            kernel32.GetModuleHandleW(None), None)
        if h:
            fnt = gdi32.GetStockObject(17)      # DEFAULT_GUI_FONT
            u32.SendMessageW(h, w.WM_SETFONT, W.WPARAM(int(fnt or 0)), W.LPARAM(1))
        return h

    def _build_controls(self):
        hinst = kernel32.GetModuleHandleW(None)
        # 用 _mk 创建（CreateWindowExW 的 HMENU 参数承担控件 ID）
        self._mk("Static", "虚拟键盘透明度", 20, 18, 200, 20, 900)
        self.hvalue = self._mk("Static", "92%", 262, 18, 140, 20, IDC_VALUE, SS_RIGHT)
        self.htrack = u32.CreateWindowExW(
            0, "msctls_trackbar32", "",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | TBS_AUTOTICKS | TBS_BOTTOM,
            18, 48, 392, 30, self.hwnd, W.HMENU(IDC_TRACK), hinst, None)
        if self.htrack:
            u32.SendMessageW(self.htrack, TBM_SETRANGE, W.WPARAM(1),
                             W.LPARAM(10 | (100 << 16)))
            u32.SendMessageW(self.htrack, TBM_SETTICFREQ, W.WPARAM(10), W.LPARAM(0))
        self._mk("Static", "10%  极淡", 20, 84, 110, 18, 901)
        self._mk("Static", "100%  不透明", 300, 84, 110, 18, 902, SS_RIGHT)
        self.hcheck = self._mk("Button", "启用半透明显示（取消勾选 = 完全不透明）",
                               18, 112, 394, 24, IDC_FADE, BS_AUTOCHECKBOX)
        self._mk("Static", "拖动滑块实时预览 · 也可直接拖虚拟键盘右上角的滑杆",
                 20, 146, 390, 18, 903)
        self._mk("Button", "完成", 326, 176, 84, 28, IDC_CLOSE,
                 BS_DEFPUSHBUTTON | WS_TABSTOP)
        self._sync_controls()

    def _sync_controls(self):
        if not (self.hwnd and self.htrack):
            return
        opacity, fade = self.get_state()
        opacity = max(10, min(100, int(opacity)))
        u32.SendMessageW(self.htrack, TBM_SETPOS, W.WPARAM(1), W.LPARAM(opacity))
        u32.SendMessageW(self.hcheck, BM_SETCHECK,
                         W.WPARAM(BST_CHECKED if fade else 0), W.LPARAM(0))
        self._set_value(opacity, fade)

    def _set_value(self, opacity, fade):
        if self.hvalue:
            txt = "%d%%" % opacity if fade else "100%"
            u32.SetWindowTextW(self.hvalue, txt)

    def _emit(self):
        if not self.htrack:
            return
        opacity = int(u32.SendMessageW(self.htrack, TBM_GETPOS, W.WPARAM(0), W.LPARAM(0)))
        fade = bool(u32.SendMessageW(self.hcheck, BM_GETCHECK, W.WPARAM(0), W.LPARAM(0)))
        self._set_value(opacity, fade)
        try:
            self.on_change(opacity, fade)
        except Exception as e:
            print("透明度回调失败：", e)

    def close(self):
        if self.hwnd and u32.IsWindow(self.hwnd):
            u32.DestroyWindow(self.hwnd)
        self.hwnd = None

    # ------------------------------------------------------------ 消息
    def _wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == w.WM_CREATE:
                # WM_CREATE 在 CreateWindowExW 内部同步派发，此时构造函数里的
                # self.hwnd 尚未赋值，必须先接住真实 HWND 再创建子控件。
                self.hwnd = hwnd
                self._build_controls()
                return 0
            if msg == w.WM_HSCROLL:
                self._emit()
                return 0
            if msg == w.WM_COMMAND:
                cid, code = int(wp) & 0xFFFF, (int(wp) >> 16) & 0xFFFF
                if cid == IDC_FADE and code == BN_CLICKED:
                    self._emit()
                    return 0
                if cid == IDC_CLOSE and code == BN_CLICKED:
                    u32.DestroyWindow(hwnd)
                    return 0
            if msg == w.WM_CTLCOLORSTATIC:
                gdi32.SetBkMode(W.HDC(int(wp)), 1)      # TRANSPARENT
                return u32.GetSysColorBrush(15)
            if msg == w.WM_CLOSE:
                u32.DestroyWindow(hwnd)
                return 0
            if msg == w.WM_DESTROY:
                self.hwnd = None
                try:
                    self.on_close()
                except Exception as e:
                    print("透明度窗口关闭回调失败：", e)
                return 0
        except Exception as e:
            print("透明度窗口消息错误：", e)
        return u32.DefWindowProcW(hwnd, msg, wp, lp)


# ---------------------------------------------------------------- 延时设置窗口
_ES_AUTOHSCROLL = 0x0080
_WS_BORDER = 0x00800000
_EM_SETSEL = 0x00B1
_IDC_DELAY_EDIT = 2003
_IDC_DELAY_OK = 2004
_IDC_DELAY_CANCEL = 2005
_DELAY_W, _DELAY_H = 400, 214
_DELAY_CLASS = "KeyHintDelayDialog"
_delay_registered = False
_delay_dialog = None            # 保活，防止窗口过程回调被 GC


def parse_delay(text):
    """'0' -> 0；'5' -> 5000；'2.5' -> 2500；非法/越界 -> None（0~600 秒）"""
    try:
        sec = float((text or "").strip())
    except (TypeError, ValueError):
        return None
    if not (0 <= sec <= 600):
        return None
    return int(round(sec * 1000))


class DelayDialog:
    def __init__(self, get_value, on_apply, on_close):
        """
        get_value() -> hide_delay_ms:int
        on_apply(ms:int) -> None      （点确定，已换算成毫秒）
        on_close() -> None            （窗口销毁，无论确定还是取消）
        """
        self.get_value = get_value
        self.on_apply = on_apply
        self.on_close = on_close
        self.hwnd = None
        self.hedit = None
        self._cb = w.WNDPROC(self._wndproc)

    def show(self):
        global _delay_registered, _delay_dialog
        _delay_dialog = self
        hinst = kernel32.GetModuleHandleW(None)
        if not _delay_registered:
            wc = w.WNDCLASSEXW()
            wc.cbSize = C.sizeof(wc)
            wc.lpfnWndProc = self._cb
            wc.hInstance = hinst
            wc.lpszClassName = _DELAY_CLASS
            wc.hbrBackground = u32.GetSysColorBrush(15)
            if not u32.RegisterClassExW(C.byref(wc)):
                err = kernel32.GetLastError()
                if err != 1410:
                    raise OSError("RegisterClassExW(DelayDialog) failed: %s" % err)
            _delay_registered = True

        if self.hwnd and u32.IsWindow(self.hwnd):
            u32.ShowWindow(self.hwnd, w.SW_RESTORE)
        else:
            sw, sh = w.screen_size()
            x, y = (sw - _DELAY_W) // 2, max(20, int(sh * 0.22))
            self.hwnd = u32.CreateWindowExW(
                w.WS_EX_TOPMOST | w.WS_EX_TOOLWINDOW, _DELAY_CLASS,
                "KeyHint · 延时消失设置", WS_POPUP | WS_CAPTION | WS_SYSMENU,
                x, y, _DELAY_W, _DELAY_H, W.HWND(0), W.HMENU(0), hinst, None)
            if not self.hwnd:
                raise OSError("CreateWindowExW(DelayDialog) failed: %s"
                              % kernel32.GetLastError())
            u32.ShowWindow(self.hwnd, w.SW_SHOW)
        u32.SetWindowPos(self.hwnd, w.HWND_TOPMOST, 0, 0, 0, 0,
                         w.SWP_NOMOVE | w.SWP_NOSIZE)
        u32.SetForegroundWindow(self.hwnd)
        self._sync()
        return self.hwnd

    def _build_controls(self):
        self._mk("Static", "松开辅助键后，虚拟键盘延时多少秒消失？",
                 20, 18, 360, 20, 910)
        self.hedit = self._mk("Edit", "", 20, 46, 360, 26,
                              _IDC_DELAY_EDIT,
                              WS_TABSTOP | _WS_BORDER | _ES_AUTOHSCROLL)
        self._mk("Static", "填 0 = 松手立即消失；可填小数，如 2.5 秒",
                 20, 84, 360, 18, 911)
        self._mk("Static", "范围 0 ~ 600 秒 · 延时期间点键帽会重新计时",
                 20, 104, 360, 18, 912)
        self._mk("Button", "确定", 196, 140, 88, 28, _IDC_DELAY_OK,
                 BS_DEFPUSHBUTTON | WS_TABSTOP)
        self._mk("Button", "取消", 292, 140, 88, 28, _IDC_DELAY_CANCEL,
                 WS_TABSTOP)
        self._sync()

    def _sync(self):
        if not (self.hwnd and self.hedit):
            return
        ms = max(0, int(self.get_value() or 0))
        txt = ("%d" % (ms // 1000) if ms % 1000 == 0
               else "%g" % (ms / 1000.0))
        u32.SetWindowTextW(self.hedit, txt)
        u32.SendMessageW(self.hedit, _EM_SETSEL, W.WPARAM(0), W.LPARAM(-1))
        u32.SetFocus(self.hedit)

    def _apply(self):
        buf = C.create_unicode_buffer(64)
        u32.GetWindowTextW(self.hedit, buf, 64)
        ms = parse_delay(buf.value)
        if ms is None:
            u32.MessageBoxW(W.HWND(0), "请输入 0 ~ 600 之间的数字，例如 0、5 或 2.5",
                            "输入有误", 0x30)
            return
        u32.DestroyWindow(self.hwnd)
        try:
            self.on_apply(ms)
        except Exception as e:
            print("延时应答失败：", e)

    def _mk(self, cls, text, x, y, cw, ch, cid, style=0):
        h = u32.CreateWindowExW(
            0, cls, text, WS_CHILD | WS_VISIBLE | style,
            x, y, cw, ch, self.hwnd, W.HMENU(cid),
            kernel32.GetModuleHandleW(None), None)
        if h:
            fnt = gdi32.GetStockObject(17)
            u32.SendMessageW(h, w.WM_SETFONT, W.WPARAM(int(fnt or 0)), W.LPARAM(1))
        return h

    def close(self):
        if self.hwnd and u32.IsWindow(self.hwnd):
            u32.DestroyWindow(self.hwnd)
        self.hwnd = None

    def _wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == w.WM_CREATE:
                self.hwnd = hwnd
                self._build_controls()
                return 0
            if msg == w.WM_COMMAND:
                cid, code = int(wp) & 0xFFFF, (int(wp) >> 16) & 0xFFFF
                if code == BN_CLICKED and cid == _IDC_DELAY_OK:
                    self._apply()
                    return 0
                if code == BN_CLICKED and cid == _IDC_DELAY_CANCEL:
                    u32.DestroyWindow(hwnd)
                    return 0
            if msg == w.WM_CTLCOLORSTATIC:
                gdi32.SetBkMode(W.HDC(int(wp)), 1)
                return u32.GetSysColorBrush(15)
            if msg == w.WM_CLOSE:
                u32.DestroyWindow(hwnd)
                return 0
            if msg == w.WM_DESTROY:
                self.hwnd = None
                self.hedit = None
                try:
                    self.on_close()
                except Exception as e:
                    print("延时窗口关闭回调失败：", e)
                return 0
        except Exception as e:
            print("延时窗口消息错误：", e)
        return u32.DefWindowProcW(hwnd, msg, wp, lp)


# ---------------------------------------------------------------- 快捷键设置窗口
_HK_W, _HK_H = 420, 214
_HK_CLASS = "KeyHintHotkeyDialog"
_hk_registered = False
_hk_dialog = None
_IDC_HK_EDIT = 2006
_IDC_HK_OK = 2007
_IDC_HK_CANCEL = 2008


class HotkeyDialog:
    """v4.01：自定义「虚拟键盘弹出开关」的组合键"""

    def __init__(self, get_value, on_apply, on_close):
        self.get_value = get_value          # -> str，例如 "Ctrl+Esc"
        self.on_apply = on_apply            # -> None，已规范化的字符串
        self.on_close = on_close
        self.hwnd = None
        self.hedit = None
        self._cb = w.WNDPROC(self._wndproc)

    def show(self):
        global _hk_registered, _hk_dialog
        _hk_dialog = self
        hinst = kernel32.GetModuleHandleW(None)
        if not _hk_registered:
            wc = w.WNDCLASSEXW()
            wc.cbSize = C.sizeof(wc)
            wc.lpfnWndProc = self._cb
            wc.hInstance = hinst
            wc.lpszClassName = _HK_CLASS
            wc.hbrBackground = u32.GetSysColorBrush(15)
            if not u32.RegisterClassExW(C.byref(wc)):
                err = kernel32.GetLastError()
                if err != 1410:
                    raise OSError("RegisterClassExW(HotkeyDialog) failed: %s" % err)
            _hk_registered = True
        if self.hwnd and u32.IsWindow(self.hwnd):
            u32.ShowWindow(self.hwnd, w.SW_RESTORE)
        else:
            sw, sh = w.screen_size()
            x, y = (sw - _HK_W) // 2, max(20, int(sh * 0.22))
            self.hwnd = u32.CreateWindowExW(
                w.WS_EX_TOPMOST | w.WS_EX_TOOLWINDOW, _HK_CLASS,
                "KeyHint · 弹出快捷键", WS_POPUP | WS_CAPTION | WS_SYSMENU,
                x, y, _HK_W, _HK_H, W.HWND(0), W.HMENU(0), hinst, None)
            if not self.hwnd:
                raise OSError("CreateWindowExW(HotkeyDialog) failed: %s"
                              % kernel32.GetLastError())
            u32.ShowWindow(self.hwnd, w.SW_SHOW)
        u32.SetWindowPos(self.hwnd, w.HWND_TOPMOST, 0, 0, 0, 0,
                         w.SWP_NOMOVE | w.SWP_NOSIZE)
        u32.SetForegroundWindow(self.hwnd)
        self._sync()
        return self.hwnd

    def _mk(self, cls, text, x, y, cw, ch, cid, style=0):
        h = u32.CreateWindowExW(
            0, cls, text, WS_CHILD | WS_VISIBLE | style,
            x, y, cw, ch, self.hwnd, W.HMENU(cid),
            kernel32.GetModuleHandleW(None), None)
        if h:
            fnt = gdi32.GetStockObject(17)
            u32.SendMessageW(h, w.WM_SETFONT, W.WPARAM(int(fnt or 0)), W.LPARAM(1))
        return h

    def _build_controls(self):
        self._mk("Static", "按这个组合键即可开启 / 关闭「按住辅助键弹出虚拟键盘」",
                 20, 18, 380, 20, 920)
        self.hedit = self._mk("Edit", "", 20, 46, 380, 26,
                              _IDC_HK_EDIT,
                              WS_TABSTOP | _WS_BORDER | _ES_AUTOHSCROLL)
        self._mk("Static", "格式：修饰键 + 普通键，例如 Ctrl+Esc、Ctrl+Alt+P",
                 20, 84, 380, 18, 921)
        self._mk("Static", "Ctrl+Esc 会被程序拦截，不再弹出 Windows 开始菜单",
                 20, 104, 380, 18, 922)
        self._mk("Button", "确定", 216, 140, 88, 28, _IDC_HK_OK,
                 BS_DEFPUSHBUTTON | WS_TABSTOP)
        self._mk("Button", "取消", 312, 140, 88, 28, _IDC_HK_CANCEL, WS_TABSTOP)
        self._sync()

    def _sync(self):
        if not (self.hwnd and self.hedit):
            return
        u32.SetWindowTextW(self.hedit, str(self.get_value() or "Ctrl+Esc"))
        u32.SendMessageW(self.hedit, _EM_SETSEL, W.WPARAM(0), W.LPARAM(-1))
        u32.SetFocus(self.hedit)

    def _apply(self):
        buf = C.create_unicode_buffer(128)
        u32.GetWindowTextW(self.hedit, buf, 128)
        text = buf.value.strip()
        u32.DestroyWindow(self.hwnd)
        try:
            self.on_apply(text)
        except Exception as e:
            print("快捷键设置失败：", e)

    def close(self):
        if self.hwnd and u32.IsWindow(self.hwnd):
            u32.DestroyWindow(self.hwnd)
        self.hwnd = None

    def _wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == w.WM_CREATE:
                self.hwnd = hwnd
                self._build_controls()
                return 0
            if msg == w.WM_COMMAND:
                cid, code = int(wp) & 0xFFFF, (int(wp) >> 16) & 0xFFFF
                if code == BN_CLICKED and cid == _IDC_HK_OK:
                    self._apply()
                    return 0
                if code == BN_CLICKED and cid == _IDC_HK_CANCEL:
                    u32.DestroyWindow(hwnd)
                    return 0
            if msg == w.WM_CTLCOLORSTATIC:
                gdi32.SetBkMode(W.HDC(int(wp)), 1)
                return u32.GetSysColorBrush(15)
            if msg == w.WM_CLOSE:
                u32.DestroyWindow(hwnd)
                return 0
            if msg == w.WM_DESTROY:
                self.hwnd = None
                self.hedit = None
                try:
                    self.on_close()
                except Exception as e:
                    print("快捷键窗口关闭回调失败：", e)
                return 0
        except Exception as e:
            print("快捷键窗口消息错误：", e)
        return u32.DefWindowProcW(hwnd, msg, wp, lp)


# ---------------------------------------------------------------- 字体大小设置窗口
_FONT_W, _FONT_H = 420, 224
_FONT_CLASS = "KeyHintFontDialog"
_font_registered = False
_font_dialog = None
_IDC_FONT_EDIT = 2009
_IDC_FONT_OK = 2010
_IDC_FONT_CANCEL = 2011


def parse_font_scale(text):
    """'110' 或 '110%' -> 1.1；范围 50~200%，非法返回 None"""
    try:
        raw = (text or "").strip().rstrip("%")
        pct = int(round(float(raw)))
    except (TypeError, ValueError):
        return None
    if not (50 <= pct <= 200):
        return None
    return pct / 100.0


class FontDialog:
    """v4.02：自定义键帽字体大小（相对 v4.00 原始字号的百分比）"""

    def __init__(self, get_value, on_apply, on_close):
        self.get_value = get_value          # -> float，例如 1.0
        self.on_apply = on_apply            # -> None
        self.on_close = on_close
        self.hwnd = None
        self.hedit = None
        self._cb = w.WNDPROC(self._wndproc)

    def show(self):
        global _font_registered, _font_dialog
        _font_dialog = self
        hinst = kernel32.GetModuleHandleW(None)
        if not _font_registered:
            wc = w.WNDCLASSEXW()
            wc.cbSize = C.sizeof(wc)
            wc.lpfnWndProc = self._cb
            wc.hInstance = hinst
            wc.lpszClassName = _FONT_CLASS
            wc.hbrBackground = u32.GetSysColorBrush(15)
            if not u32.RegisterClassExW(C.byref(wc)):
                err = kernel32.GetLastError()
                if err != 1410:
                    raise OSError("RegisterClassExW(FontDialog) failed: %s" % err)
            _font_registered = True
        if self.hwnd and u32.IsWindow(self.hwnd):
            u32.ShowWindow(self.hwnd, w.SW_RESTORE)
        else:
            sw, sh = w.screen_size()
            x, y = (sw - _FONT_W) // 2, max(20, int(sh * 0.22))
            self.hwnd = u32.CreateWindowExW(
                w.WS_EX_TOPMOST | w.WS_EX_TOOLWINDOW, _FONT_CLASS,
                "KeyHint · 字体大小", WS_POPUP | WS_CAPTION | WS_SYSMENU,
                x, y, _FONT_W, _FONT_H, W.HWND(0), W.HMENU(0), hinst, None)
            if not self.hwnd:
                raise OSError("CreateWindowExW(FontDialog) failed: %s"
                              % kernel32.GetLastError())
            u32.ShowWindow(self.hwnd, w.SW_SHOW)
        u32.SetWindowPos(self.hwnd, w.HWND_TOPMOST, 0, 0, 0, 0,
                         w.SWP_NOMOVE | w.SWP_NOSIZE)
        u32.SetForegroundWindow(self.hwnd)
        self._sync()
        return self.hwnd

    def _mk(self, cls, text, x, y, cw, ch, cid, style=0):
        h = u32.CreateWindowExW(
            0, cls, text, WS_CHILD | WS_VISIBLE | style,
            x, y, cw, ch, self.hwnd, W.HMENU(cid),
            kernel32.GetModuleHandleW(None), None)
        if h:
            fnt = gdi32.GetStockObject(17)
            u32.SendMessageW(h, w.WM_SETFONT, W.WPARAM(int(fnt or 0)), W.LPARAM(1))
        return h

    def _build_controls(self):
        self._mk("Static", "键帽上的功能文字大小（100% = 原始默认字号）",
                 20, 18, 380, 20, 930)
        self.hedit = self._mk("Edit", "", 20, 46, 380, 26,
                              _IDC_FONT_EDIT,
                              WS_TABSTOP | _WS_BORDER | _ES_AUTOHSCROLL)
        self._mk("Static", "可填 50 ~ 200 的整数，例如 90、110、150（可带 %）",
                 20, 84, 380, 18, 931)
        self._mk("Static", "只影响键帽与信息条文字；键盘整体大小请用「键盘缩放」",
                 20, 104, 380, 18, 932)
        self._mk("Button", "确定", 216, 150, 88, 28, _IDC_FONT_OK,
                 BS_DEFPUSHBUTTON | WS_TABSTOP)
        self._mk("Button", "取消", 312, 150, 88, 28, _IDC_FONT_CANCEL, WS_TABSTOP)
        self._sync()

    def _sync(self):
        if not (self.hwnd and self.hedit):
            return
        pct = int(round(float(self.get_value() or 1.0) * 100))
        u32.SetWindowTextW(self.hedit, "%d" % pct)
        u32.SendMessageW(self.hedit, _EM_SETSEL, W.WPARAM(0), W.LPARAM(-1))
        u32.SetFocus(self.hedit)

    def _apply(self):
        buf = C.create_unicode_buffer(64)
        u32.GetWindowTextW(self.hedit, buf, 64)
        scale = parse_font_scale(buf.value)
        if scale is None:
            u32.MessageBoxW(W.HWND(0), "请输入 50 ~ 200 之间的数字，例如 90、110 或 150",
                            "输入有误", 0x30)
            return
        u32.DestroyWindow(self.hwnd)
        try:
            self.on_apply(scale)
        except Exception as e:
            print("字体大小设置失败：", e)

    def close(self):
        if self.hwnd and u32.IsWindow(self.hwnd):
            u32.DestroyWindow(self.hwnd)
        self.hwnd = None

    def _wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == w.WM_CREATE:
                self.hwnd = hwnd
                self._build_controls()
                return 0
            if msg == w.WM_COMMAND:
                cid, code = int(wp) & 0xFFFF, (int(wp) >> 16) & 0xFFFF
                if code == BN_CLICKED and cid == _IDC_FONT_OK:
                    self._apply()
                    return 0
                if code == BN_CLICKED and cid == _IDC_FONT_CANCEL:
                    u32.DestroyWindow(hwnd)
                    return 0
            if msg == w.WM_CTLCOLORSTATIC:
                gdi32.SetBkMode(W.HDC(int(wp)), 1)
                return u32.GetSysColorBrush(15)
            if msg == w.WM_CLOSE:
                u32.DestroyWindow(hwnd)
                return 0
            if msg == w.WM_DESTROY:
                self.hwnd = None
                self.hedit = None
                try:
                    self.on_close()
                except Exception as e:
                    print("字体窗口关闭回调失败：", e)
                return 0
        except Exception as e:
            print("字体窗口消息错误：", e)
        return u32.DefWindowProcW(hwnd, msg, wp, lp)


def _late_signatures():
    """补齐本模块用到的 Win32 函数签名（只执行一次）"""
    def sig(fn, args, ret=None):
        fn.argtypes, fn.restype = args, ret
    if not hasattr(u32.SetWindowTextW, "argtypes") or not u32.SetWindowTextW.argtypes:
        sig(u32.SetWindowTextW, [W.HWND, W.LPCWSTR], W.BOOL)
    if not hasattr(u32.GetSysColorBrush, "argtypes") or not u32.GetSysColorBrush.argtypes:
        sig(u32.GetSysColorBrush, [C.c_int], W.HBRUSH)
    if not hasattr(gdi32.SetBkMode, "argtypes") or not gdi32.SetBkMode.argtypes:
        sig(gdi32.SetBkMode, [W.HDC, C.c_int], C.c_int)
    if not hasattr(u32.GetWindowTextW, "argtypes") or not u32.GetWindowTextW.argtypes:
        sig(u32.GetWindowTextW, [W.HWND, W.LPWSTR, C.c_int], C.c_int)
    if not hasattr(u32.MessageBoxW, "argtypes") or not u32.MessageBoxW.argtypes:
        sig(u32.MessageBoxW, [W.HWND, W.LPCWSTR, W.LPCWSTR, W.UINT], C.c_int)
    if not hasattr(u32.SetFocus, "argtypes") or not u32.SetFocus.argtypes:
        sig(u32.SetFocus, [W.HWND], W.HWND)


_late_signatures()
