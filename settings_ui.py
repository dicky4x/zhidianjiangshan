# -*- coding: utf-8 -*-
"""
设置窗口（原生 Win32 控件，无第三方 GUI 依赖）

* OpacityDialog：trackbar 滑块 + 半透明总开关，实时预览浓淡变化
* DelayDialog：输入「松手后延时消失」的秒数，支持 0 / 5 / 2.5 这类数值

窗口都是非模态的，复用主线程的现有消息循环，不新开线程、不阻塞托盘。
"""
from __future__ import annotations

import copy
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
TBM_SETRANGEMIN = w.WM_USER + 7
TBM_SETRANGEMAX = w.WM_USER + 8
BM_GETCHECK = 0x00F0
BM_SETCHECK = 0x00F1
BST_CHECKED = 1
WM_HSCROLL = 0x0114
TB_THUMBTRACK = 5
TB_ENDTRACK = 8

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
                "指点江山 · 透明度设置", WS_POPUP | WS_CAPTION | WS_SYSMENU,
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
        self._mk("Static", "背景透明度（键帽始终清晰不透明）", 20, 18, 260, 20, 900)
        self.hvalue = self._mk("Static", "80%", 262, 18, 140, 20, IDC_VALUE, SS_RIGHT)
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
        self.hcheck = self._mk("Button", "背景半透明（取消勾选 = 背景完全不透明）",
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
                "指点江山 · 延时消失设置", WS_POPUP | WS_CAPTION | WS_SYSMENU,
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
                "指点江山 · 弹出快捷键", WS_POPUP | WS_CAPTION | WS_SYSMENU,
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
                "指点江山 · 字体大小", WS_POPUP | WS_CAPTION | WS_SYSMENU,
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


# ================================================================
# v4.11：自定义快捷键面板 GUI
#   CustomKeyDialog  —— 右键某个键帽时，设置该键对应的组合键 / 名称 / 作用
#   CustomPanelDialog —— 新建、重命名、删除、切换多套自定义面板
# ================================================================
_WS_VSCROLL = 0x00200000
_LBS_NOTIFY = 0x0001
_LBS_HASSTRINGS = 0x0080
_LB_ADDSTRING = 0x0180
_LB_DELETESTRING = 0x0182
_LB_RESETCONTENT = 0x0184
_LB_SETCURSEL = 0x0186
_LB_GETCURSEL = 0x0188
_LB_GETTEXT = 0x0189

_CK_W, _CK_H = 470, 370
_CK_CLASS = "ZhiDianCustomKeyDialog"
_ck_registered = False
_custom_key_dialog = None

_CK_SID = 3100
_CK_MODS = (3101, 3102, 3103, 3104)   # Ctrl / Shift / Alt / Win
_CK_KEY = 3110
_CK_NAME = 3111
_CK_ACTION = 3112
_CK_SAVE = 3120
_CK_DELETE = 3121
_CK_CANCEL = 3122


def _get_text(h):
    if not h:
        return ""
    buf = C.create_unicode_buffer(512)
    u32.GetWindowTextW(h, buf, 512)
    return buf.value.strip()


class CustomKeyDialog:
    """右键虚拟键帽后弹出的单键自定义编辑器。"""

    def __init__(self, get_entry, sid, on_save, on_delete, on_close=None):
        self.get_entry = get_entry
        self.sid = str(sid or "")
        self.on_save = on_save
        self.on_delete = on_delete
        self.on_close_cb = on_close
        self.hwnd = None
        self.hmods = {}
        self.hkey = self.hname = self.haction = None
        self._cb = w.WNDPROC(self._wndproc)

    def show(self, x=None, y=None):
        global _ck_registered, _custom_key_dialog
        _custom_key_dialog = self
        hinst = kernel32.GetModuleHandleW(None)
        if not _ck_registered:
            wc = w.WNDCLASSEXW()
            wc.cbSize = C.sizeof(wc)
            wc.lpfnWndProc = self._cb
            wc.hInstance = hinst
            wc.lpszClassName = _CK_CLASS
            wc.hbrBackground = u32.GetSysColorBrush(15)
            if not u32.RegisterClassExW(C.byref(wc)):
                err = kernel32.GetLastError()
                if err != 1410:
                    raise OSError("RegisterClassExW(CustomKeyDialog) failed: %s" % err)
            _ck_registered = True
        sw, sh = w.screen_size()
        if x is None:
            x = max(0, (sw - _CK_W) // 2)
        else:
            x = max(0, min(int(x), sw - _CK_W - 4))
        if y is None:
            y = max(10, min(int(sh * 0.18), sh - _CK_H - 10))
        else:
            y = max(0, min(int(y), sh - _CK_H - 4))
        if self.hwnd and u32.IsWindow(self.hwnd):
            self._sync()
            u32.SetWindowPos(self.hwnd, w.HWND_TOPMOST, x, y, 0, 0,
                             w.SWP_NOMOVE | w.SWP_NOSIZE)
        else:
            self.hwnd = u32.CreateWindowExW(
                w.WS_EX_TOPMOST | w.WS_EX_TOOLWINDOW, _CK_CLASS,
                "指点江山 · 自定义快捷键", WS_POPUP | WS_CAPTION | WS_SYSMENU,
                x, y, _CK_W, _CK_H, W.HWND(0), W.HMENU(0), hinst, None)
            if not self.hwnd:
                raise OSError("CreateWindowExW(CustomKeyDialog) failed: %s"
                              % kernel32.GetLastError())
            u32.ShowWindow(self.hwnd, w.SW_SHOW)
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
        self._mk("Static", "当前键帽", 20, 18, 80, 22, _CK_SID + 90)
        self._mk("Static", self.sid, 100, 18, 120, 22, _CK_SID)
        self._mk("Static", "组合键（勾选辅助键 + 填写主键）", 20, 48, 330, 22, _CK_SID + 91)
        labels = ("Ctrl", "Shift", "Alt", "Win")
        for i, (cid, lab) in enumerate(zip(_CK_MODS, labels)):
            self.hmods[cid] = self._mk("Button", lab, 20 + i * 100, 76, 90, 24,
                                       cid, BS_AUTOCHECKBOX)
        self._mk("Static", "主键", 20, 112, 60, 22, _CK_SID + 92)
        self.hkey = self._mk("Edit", "", 80, 108, 120, 26, _CK_KEY,
                             WS_TABSTOP | _WS_BORDER | _ES_AUTOHSCROLL)
        self._mk("Static", "示例：A / F5 / Space / ←", 220, 112, 220, 22, _CK_SID + 93)
        self._mk("Static", "名称（显示在键帽上）", 20, 150, 200, 22, _CK_SID + 94)
        self.hname = self._mk("Edit", "", 20, 176, 420, 26, _CK_NAME,
                              WS_TABSTOP | _WS_BORDER | _ES_AUTOHSCROLL)
        self._mk("Static", "作用（鼠标悬停时显示在键盘底部）", 20, 214, 330, 22,
                 _CK_SID + 95)
        self.haction = self._mk("Edit", "", 20, 240, 420, 26, _CK_ACTION,
                                WS_TABSTOP | _WS_BORDER | _ES_AUTOHSCROLL)
        self._mk("Button", "保存", 20, 286, 90, 30, _CK_SAVE,
                 BS_DEFPUSHBUTTON | WS_TABSTOP)
        self._mk("Button", "删除此键", 132, 286, 100, 30, _CK_DELETE, WS_TABSTOP)
        self._mk("Button", "取消", 360, 286, 90, 30, _CK_CANCEL, WS_TABSTOP)
        self._sync()

    def _sync(self):
        if not (self.hwnd and self.hkey):
            return
        entry = self.get_entry() or {}
        combo = str(entry.get("combo") or "")
        parts = [p.strip().upper() for p in combo.split("+") if p.strip()]
        mod_map = {"CTRL": _CK_MODS[0], "SHIFT": _CK_MODS[1],
                   "ALT": _CK_MODS[2], "WIN": _CK_MODS[3]}
        for cid in _CK_MODS:
            u32.SendMessageW(self.hmods[cid], BM_SETCHECK, W.WPARAM(0), W.LPARAM(0))
        for p in parts[:-1]:
            cid = mod_map.get(p)
            if cid:
                u32.SendMessageW(self.hmods[cid], BM_SETCHECK,
                                 W.WPARAM(BST_CHECKED), W.LPARAM(0))
        u32.SetWindowTextW(self.hkey, parts[-1] if parts else "")
        u32.SetWindowTextW(self.hname, str(entry.get("name") or ""))
        u32.SetWindowTextW(self.haction, str(entry.get("action") or ""))

    def _combo_value(self):
        labels = ("Ctrl", "Shift", "Alt", "Win")
        mods = []
        for cid, lab in zip(_CK_MODS, labels):
            if u32.SendMessageW(self.hmods[cid], BM_GETCHECK,
                                W.WPARAM(0), W.LPARAM(0)):
                mods.append(lab)
        key = _get_text(self.hkey).upper()
        if key in ("SPACEBAR", " "):
            key = "SPACE"
        key = key.replace("←", "LEFT").replace("→", "RIGHT").replace("↑", "UP").replace("↓", "DOWN")
        if not mods or not key:
            return ""
        return "+".join(mods + [key])

    def _save(self):
        combo = self._combo_value()
        name = _get_text(self.hname)
        action = _get_text(self.haction)
        if not combo or not name:
            u32.MessageBoxW(self.hwnd, "请至少勾选一个辅助键、填写主键和名称。",
                            "自定义快捷键", 0x40)
            return
        try:
            self.on_save({"combo": combo, "name": name, "action": action})
        except Exception as e:
            print("保存自定义快捷键失败：", e)

    def _wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == w.WM_CREATE:
                self.hwnd = hwnd
                self._build_controls()
                return 0
            if msg == w.WM_COMMAND:
                cid, code = int(wp) & 0xFFFF, (int(wp) >> 16) & 0xFFFF
                if code == BN_CLICKED:
                    if cid == _CK_SAVE:
                        self._save()
                        u32.DestroyWindow(hwnd)
                        return 0
                    if cid == _CK_DELETE:
                        try:
                            self.on_delete()
                        except Exception as e:
                            print("删除自定义快捷键失败：", e)
                        u32.DestroyWindow(hwnd)
                        return 0
                    if cid == _CK_CANCEL:
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
                if self.on_close_cb:
                    self.on_close_cb()
                return 0
        except Exception as e:
            print("自定义快捷键窗口消息错误：", e)
        return u32.DefWindowProcW(hwnd, msg, wp, lp)


_CP_W, _CP_H = 520, 430
_CP_CLASS = "ZhiDianCustomPanelDialog"
_cp_registered = False
_custom_panel_dialog = None

_CP_LIST = 3200
_CP_NAME = 3201
_CP_NEW = 3210
_CP_RENAME = 3211
_CP_DELETE = 3212
_CP_ACTIVE = 3213
_CP_DONE = 3214


class CustomPanelDialog:
    """多套自定义面板管理器。"""

    def __init__(self, get_panels, active_index, on_apply, on_close=None):
        self.panels = copy.deepcopy(list(get_panels() or []))
        if not self.panels:
            self.panels = [{"name": "我的快捷键", "keys": {}}]
        for p in self.panels:
            if not isinstance(p.get("keys"), dict):
                p["keys"] = {}
        self.active_index = int(active_index or 0)
        if not (0 <= self.active_index < len(self.panels)):
            self.active_index = 0
        self.on_apply = on_apply
        self.on_close_cb = on_close
        self.hwnd = None
        self.hlist = self.hentry = None
        self._saved = False
        self._cb = w.WNDPROC(self._wndproc)

    def show(self):
        global _cp_registered, _custom_panel_dialog
        _custom_panel_dialog = self
        hinst = kernel32.GetModuleHandleW(None)
        if not _cp_registered:
            wc = w.WNDCLASSEXW()
            wc.cbSize = C.sizeof(wc)
            wc.lpfnWndProc = self._cb
            wc.hInstance = hinst
            wc.lpszClassName = _CP_CLASS
            wc.hbrBackground = u32.GetSysColorBrush(15)
            if not u32.RegisterClassExW(C.byref(wc)):
                err = kernel32.GetLastError()
                if err != 1410:
                    raise OSError("RegisterClassExW(CustomPanelDialog) failed: %s" % err)
            _cp_registered = True
        sw, sh = w.screen_size()
        x = max(0, (sw - _CP_W) // 2)
        y = max(10, min(int(sh * 0.12), sh - _CP_H - 10))
        if self.hwnd and u32.IsWindow(self.hwnd):
            self._sync()
            return self.hwnd
        self.hwnd = u32.CreateWindowExW(
            w.WS_EX_TOPMOST | w.WS_EX_TOOLWINDOW, _CP_CLASS,
            "指点江山 · 自定义快捷键面板", WS_POPUP | WS_CAPTION | WS_SYSMENU,
            x, y, _CP_W, _CP_H, W.HWND(0), W.HMENU(0), hinst, None)
        if not self.hwnd:
            raise OSError("CreateWindowExW(CustomPanelDialog) failed: %s"
                          % kernel32.GetLastError())
        u32.ShowWindow(self.hwnd, w.SW_SHOW)
        u32.SetForegroundWindow(self.hwnd)
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
        self._mk("Static", "已有多套面板（可自定义名称）", 20, 16, 300, 22, _CP_LIST + 90)
        self.hlist = self._mk(
            "Listbox", "", 20, 44, 300, 250, _CP_LIST,
            WS_TABSTOP | _WS_BORDER | _WS_VSCROLL | _LBS_NOTIFY | _LBS_HASSTRINGS)
        self._mk("Static", "面板名称", 340, 48, 100, 22, _CP_LIST + 91)
        self.hentry = self._mk("Edit", "", 340, 74, 160, 26, _CP_NAME,
                               WS_TABSTOP | _WS_BORDER | _ES_AUTOHSCROLL)
        self._mk("Button", "新建面板", 340, 118, 160, 30, _CP_NEW, WS_TABSTOP)
        self._mk("Button", "重命名", 340, 158, 160, 30, _CP_RENAME, WS_TABSTOP)
        self._mk("Button", "设为当前", 340, 198, 160, 30, _CP_ACTIVE, WS_TABSTOP)
        self._mk("Button", "删除面板", 340, 238, 160, 30, _CP_DELETE, WS_TABSTOP)
        self._mk("Static", "使用：点虚拟键盘上方「自定义」按钮切换面板；右键键帽编辑。",
                 20, 312, 480, 22, _CP_LIST + 92)
        self._mk("Button", "完成", 380, 366, 120, 32, _CP_DONE,
                 BS_DEFPUSHBUTTON | WS_TABSTOP)
        self._sync()

    def _sync(self):
        if not (self.hwnd and self.hlist):
            return
        u32.SendMessageW(self.hlist, _LB_RESETCONTENT, W.WPARAM(0), W.LPARAM(0))
        for p in self.panels:
            name = str(p.get("name") or "")
            buf = C.create_unicode_buffer(name)
            u32.SendMessageW(self.hlist, _LB_ADDSTRING, W.WPARAM(0),
                             W.LPARAM(C.cast(buf, C.c_void_p).value))
        u32.SendMessageW(self.hlist, _LB_SETCURSEL, W.WPARAM(self.active_index), W.LPARAM(0))
        u32.SetWindowTextW(self.hentry,
                           str(self.panels[self.active_index].get("name") or ""))

    def _selected(self):
        if not self.hlist:
            return -1
        idx = int(u32.SendMessageW(self.hlist, _LB_GETCURSEL,
                                   W.WPARAM(0), W.LPARAM(0)))
        return idx if 0 <= idx < len(self.panels) else -1

    def _apply(self):
        if self._saved:
            return
        self._saved = True
        try:
            self.on_apply(self.panels, self.active_index)
        except Exception as e:
            print("保存自定义面板失败：", e)

    def _wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == w.WM_CREATE:
                self.hwnd = hwnd
                self._build_controls()
                return 0
            if msg == w.WM_COMMAND:
                cid, code = int(wp) & 0xFFFF, (int(wp) >> 16) & 0xFFFF
                if code == BN_CLICKED:
                    if cid == _CP_NEW:
                        name = _get_text(self.hentry).strip()
                        name = name or ("自定义面板 %d" % (len(self.panels) + 1))
                        self.panels.append({"name": name, "keys": {}})
                        self.active_index = len(self.panels) - 1
                        self._sync()
                        return 0
                    if cid == _CP_RENAME:
                        idx = self._selected()
                        name = _get_text(self.hentry).strip()
                        if idx >= 0 and name:
                            self.panels[idx]["name"] = name
                            self._sync()
                        return 0
                    if cid == _CP_ACTIVE:
                        idx = self._selected()
                        if idx >= 0:
                            self.active_index = idx
                            u32.SetWindowTextW(self.hentry,
                                               str(self.panels[idx].get("name") or ""))
                        return 0
                    if cid == _CP_DELETE:
                        idx = self._selected()
                        if idx >= 0:
                            if len(self.panels) == 1:
                                self.panels[0]["keys"] = {}
                            else:
                                self.panels.pop(idx)
                                self.active_index = min(self.active_index,
                                                        len(self.panels) - 1)
                            self._sync()
                        return 0
                    if cid == _CP_DONE:
                        self._apply()
                        u32.DestroyWindow(hwnd)
                        return 0
            if msg == w.WM_CTLCOLORSTATIC:
                gdi32.SetBkMode(W.HDC(int(wp)), 1)
                return u32.GetSysColorBrush(15)
            if msg == w.WM_CLOSE:
                self._apply()
                u32.DestroyWindow(hwnd)
                return 0
            if msg == w.WM_DESTROY:
                self.hwnd = None
                if not self._saved:
                    self._apply()
                if self.on_close_cb:
                    self.on_close_cb()
                return 0
        except Exception as e:
            print("自定义面板窗口消息错误：", e)
        return u32.DefWindowProcW(hwnd, msg, wp, lp)


# ================================================================
# v4.09：统一「设置」窗口 —— 把右键菜单里的调节项收纳到此
# 分组：外观 / 行为 / 触发与快捷键 / 键盘规格 / 指令显示
# 复选框 + 数值编辑框 + 下拉，底部「应用」「关闭」。
# ================================================================
_CBS_DROPDOWNLIST = 0x0003
_CBS_HASSTRINGS = 0x0020
_CB_ADDSTRING = 0x0183
_CB_SETCURSEL = 0x014E
_CB_GETCURSEL = 0x0147
_SETTINGS_W, _SETTINGS_H = 620, 800   # v4.11：加宽避免选项文字重叠，加高容纳自定义面板入口
_SETTINGS_CLASS = "ZhiDianSettingsDialog"
_settings_registered = False
_settings_dialog = None

# 控件 ID 分配（分区标题从 9000 起，控件从 100 起）
_SETTINGS_IDS = {
    # 外观
    "theme": 101, "wallpaper": 102, "fade": 103, "opacity": 104,
    # 行为
    "enabled": 110, "mouse_click": 111, "click_keep": 112,
    "hide_delay": 113, "popup": 114,
    # 触发与快捷键
    "hotkey": 120, "mod_ctrl": 121, "mod_shift": 122, "mod_alt": 123, "mod_win": 124,
    "delay": 125,
    # 键盘规格
    "layout": 130, "narrow": 131, "kb_scale": 132, "font_scale": 133, "position": 134,
    # 指令显示
    "hint_mode": 140, "app_context": 141, "show_lang": 142, "sound": 143,
    "taskbar": 150, "autostart": 151,
}
_IDC_SETTINGS_APPLY = 160
_IDC_SETTINGS_CLOSE = 161
_IDC_SETTINGS_CUSTOM = 162

# v4.09：数字参数改用滑杆（trackbar），不再手输数字。
# 每项 = dict(min/max: 滑杆档位范围, tic: 刻度间隔, valve: 数值显示 Static 的 ID,
#             to_cfg(tick)->配置值, from_cfg(值)->tick, fmt(配置值)->显示文本)
# 滑杆内部以整数档位运作，读写时通过 to_cfg/from_cfg 换算回真实配置值。
_SLIDER_SPEC = {
    "opacity": {
        "min": 10, "max": 100, "tic": 10, "valve": 904,
        "to_cfg": lambda t: int(t),
        "from_cfg": lambda v: max(10, min(100, int(v))),
        "fmt": lambda v: "%d%%" % int(v),
    },
    "hide_delay": {
        "min": 0, "max": 15, "tic": 1, "valve": 905,
        "to_cfg": lambda t: int(round(t * 1000)),
        "from_cfg": lambda v: max(0, min(15, int(round(float(v) / 1000.0)))),
        "fmt": lambda v: ("立即消失" if not v else "%g 秒" % (float(v) / 1000.0)),
    },
    "delay": {
        "min": 0, "max": 30, "tic": 1, "valve": 906,
        "to_cfg": lambda t: int(t) * 100,
        "from_cfg": lambda v: max(0, min(30, int(round(float(v) / 100.0)))),
        "fmt": lambda v: ("立即弹出" if not v else "%d 毫秒" % int(v)),
    },
    "kb_scale": {
        "min": 50, "max": 200, "tic": 10, "valve": 907,
        "to_cfg": lambda t: round(int(t) / 100.0, 3),
        "from_cfg": lambda v: max(50, min(200, int(round(float(v) * 100)))),
        "fmt": lambda v: "%d%%" % int(round(float(v) * 100)),
    },
    "font_scale": {
        "min": 50, "max": 200, "tic": 10, "valve": 908,
        "to_cfg": lambda t: round(int(t) / 100.0, 3),
        "from_cfg": lambda v: max(50, min(200, int(round(float(v) * 100)))),
        "fmt": lambda v: "%d%%" % int(round(float(v) * 100)),
    },
}
# 数值显示 Static 的 ID -> 参数 key 反查（拖动滑杆时定位用）
_SLIDER_VALVE = {spec["valve"]: key for key, spec in _SLIDER_SPEC.items()}


class SettingsDialog:
    """统一设置窗口。get_state()->cfg dict；on_apply(new_cfg:dict)->None。"""

    def __init__(self, get_state, on_apply, on_close=None, title="指点江山 · 设置",
                 on_custom=None):
        self.get_state = get_state
        self.on_apply = on_apply
        self.on_close_cb = on_close
        self.on_custom = on_custom
        self.title = title
        self.hwnd = None
        self.ctrls = {}       # key -> (hwnd, kind)
        self._cb = w.WNDPROC(self._wndproc)
        # 下拉选项定义（显示文本 -> 值）
        self.combo_opts = {
            "theme": [("深色玻璃", "dark"), ("浅色玻璃", "light"), ("跟随系统", "auto")],
            "hotkey": [("Ctrl+Esc", "Ctrl+Esc"), ("Ctrl+Alt+P", "Ctrl+Alt+P"),
                       ("Ctrl+Alt+K", "Ctrl+Alt+K")],
            "layout": [("悬浮紧凑键盘", "compact"), ("全尺寸 104 键", "full")],
            "position": [("屏幕顶部", "top"), ("屏幕底部", "bottom"), ("屏幕居中", "center")],
            "hint_mode": [("符号 + 指令", "icon"), ("纯文本指令", "text")],
        }

    # ---------------------------------------------------------- 窗口生命周期
    def show(self):
        global _settings_registered, _settings_dialog
        _settings_dialog = self
        hinst = kernel32.GetModuleHandleW(None)
        if not _settings_registered:
            wc = w.WNDCLASSEXW()
            wc.cbSize = C.sizeof(wc)
            wc.lpfnWndProc = self._cb
            wc.hInstance = hinst
            wc.lpszClassName = _SETTINGS_CLASS
            wc.hbrBackground = u32.GetSysColorBrush(15)
            if not u32.RegisterClassExW(C.byref(wc)):
                err = kernel32.GetLastError()
                if err != 1410:
                    raise OSError("RegisterClassExW(SettingsDialog) failed: %s" % err)
            _settings_registered = True
        if self.hwnd and u32.IsWindow(self.hwnd):
            self._sync()
            u32.ShowWindow(self.hwnd, w.SW_RESTORE)
        else:
            sw, sh = w.screen_size()
            x = max(0, (sw - _SETTINGS_W) // 2)
            y = max(10, min(int(sh * 0.06), sh - _SETTINGS_H - 10))
            self.hwnd = u32.CreateWindowExW(
                w.WS_EX_TOPMOST | w.WS_EX_TOOLWINDOW, _SETTINGS_CLASS,
                self.title, WS_POPUP | WS_CAPTION | WS_SYSMENU,
                x, y, _SETTINGS_W, _SETTINGS_H, W.HWND(0), W.HMENU(0), hinst, None)
            if not self.hwnd:
                raise OSError("CreateWindowExW(SettingsDialog) failed: %s"
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

    def _label(self, text, x, y, cw=200, ch=18, cid=900):
        return self._mk("Static", text, x, y, cw, ch, cid)

    def _check(self, key, text, x, y, cw=230):
        h = self._mk("Button", text, x, y, cw, 22, _SETTINGS_IDS[key], BS_AUTOCHECKBOX)
        self.ctrls[key] = (h, "check")
        return h

    def _edit(self, key, x, y, cw=90):
        h = self._mk("Edit", "", x, y, cw, 22, _SETTINGS_IDS[key],
                     WS_TABSTOP | _WS_BORDER | _ES_AUTOHSCROLL)
        self.ctrls[key] = (h, "edit")
        return h

    def _choice(self, key, x, y, cw=150):
        """v4.09：改为「点击循环切换」按钮——点一下切到下一个中文选项，不用输入。"""
        h = self._mk("Button", "", x, y, cw, 24, _SETTINGS_IDS[key], WS_TABSTOP)
        self.ctrls[key] = (h, "choice")
        return h

    def _slider(self, key, x, y, cw=150):
        """v4.09：创建一个 trackbar 滑杆 + 右侧数值显示 Static。"""
        spec = _SLIDER_SPEC[key]
        hinst = kernel32.GetModuleHandleW(None)
        h = u32.CreateWindowExW(
            0, "msctls_trackbar32", "",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | TBS_AUTOTICKS | TBS_BOTTOM,
            x, y, cw, 26, self.hwnd, W.HMENU(_SETTINGS_IDS[key]), hinst, None)
        if h:
            u32.SendMessageW(h, TBM_SETRANGE, W.WPARAM(1),
                             W.LPARAM(spec["min"] | (spec["max"] << 16)))
            u32.SendMessageW(h, TBM_SETTICFREQ, W.WPARAM(spec["tic"]), W.LPARAM(0))
        self.ctrls[key] = (h, "slider")
        # 数值显示放在滑杆右侧
        self._mk("Static", "", x + cw + 6, y + 3, 92, 20, spec["valve"], SS_RIGHT)
        return h

    def _build_controls(self):
        X, X2 = 20, 336
        y = 12
        # v4.11：窗口加宽，主题与壁纸联动分列显示，不再互相压字。
        # ---- 外观 ----
        self._label("── 外观 ──", X, y, 560); y += 24
        self._label("主题(点击切换)", X, y + 3, 130); self._choice("theme", X + 136, y, 150)
        self._check("wallpaper", "壁纸联动强调色", X2 + 10, y + 2, 230); y += 28
        self._check("fade", "背景半透明（键帽始终不透明）", X, y + 2, 560); y += 26
        self._label("背景透明度", X, y + 4, 92)
        self._slider("opacity", X + 96, y, 300); y += 34
        # ---- 行为 ----
        self._label("── 行为 ──", X, y, 560); y += 24
        self._check("enabled", "启用情境式指令提示", X, y + 2, 300)
        self._check("mouse_click", "鼠标可点击键帽", X2, y + 2, 230); y += 26
        self._check("click_keep", "执行后保持面板（可连续点击）", X, y + 2, 300)
        self._check("popup", "按住辅助键弹出面板", X2, y + 2, 230); y += 26
        self._label("松手后消失", X, y + 4, 92)
        self._slider("hide_delay", X + 96, y, 300); y += 34
        # ---- 触发与快捷键 ----
        self._label("── 触发与快捷键 ──", X, y, 560); y += 24
        self._label("弹出快捷键(点击切换)", X, y + 3, 150); self._choice("hotkey", X + 156, y, 200); y += 30
        self._label("唤起延迟", X, y + 4, 92)
        self._slider("delay", X + 96, y, 300); y += 34
        self._check("mod_ctrl", "Ctrl 触发", X, y + 2, 110)
        self._check("mod_shift", "Shift 触发", X + 120, y + 2, 110)
        self._check("mod_alt", "Alt 触发", X2, y + 2, 110)
        self._check("mod_win", "Win 触发", X2 + 120, y + 2, 110); y += 28
        # ---- 键盘规格 ----
        self._label("── 键盘规格 ──", X, y, 560); y += 24
        self._label("布局(点击切换)", X, y + 3, 110); self._choice("layout", X + 116, y, 260); y += 30
        self._label("停靠(点击切换)", X, y + 3, 110); self._choice("position", X + 116, y, 260); y += 30
        self._check("narrow", "窄距键帽", X, y + 2, 230); y += 26
        self._label("键盘缩放", X, y + 4, 92)
        self._slider("kb_scale", X + 96, y, 300); y += 34
        self._label("字体大小", X, y + 4, 92)
        self._slider("font_scale", X + 96, y, 300); y += 34
        # ---- 指令显示 ----
        self._label("── 指令显示 ──", X, y, 560); y += 24
        self._label("显示方式(点击切换)", X, y + 3, 140); self._choice("hint_mode", X + 146, y, 220); y += 30
        self._check("app_context", "应用情境感知", X, y + 2, 300)
        self._check("show_lang", "显示输入语言键帽", X2, y + 2, 230); y += 26
        self._check("sound", "按键反馈音", X, y + 2, 300)
        self._check("autostart", "开机自启动", X2, y + 2, 230); y += 30
        self._label("自定义快捷键面板：", X, y + 5, 150)
        self._mk("Button", "管理多套面板…", X + 156, y, 180, 28,
                 _IDC_SETTINGS_CUSTOM, WS_TABSTOP); y += 38
        self._label("提示：图标只在系统托盘；右键虚拟键帽可编辑当前自定义面板。",
                    X, y, 560); y += 24
        # ---- 按钮 ----
        self._mk("Button", "应用", 420, y, 84, 30, _IDC_SETTINGS_APPLY,
                 BS_DEFPUSHBUTTON | WS_TABSTOP)
        self._mk("Button", "关闭", 514, y, 84, 30, _IDC_SETTINGS_CLOSE, WS_TABSTOP)
        self._sync()

    def _sync(self):
        if not (self.hwnd and self.ctrls):
            return
        cfg = self.get_state() or {}
        mods = cfg.get("modifiers", {})
        checks = {
            "wallpaper": cfg.get("wallpaper_theme", True),
            "fade": cfg.get("fade", True),
            "enabled": cfg.get("enabled", True),
            "mouse_click": cfg.get("mouse_click", False),
            "click_keep": cfg.get("click_keep", True),
            "popup": cfg.get("popup_enabled", True),
            "mod_ctrl": mods.get("Ctrl", True), "mod_shift": mods.get("Shift", True),
            "mod_alt": mods.get("Alt", True), "mod_win": mods.get("Win", True),
            "narrow": cfg.get("narrow", False),
            "app_context": cfg.get("app_context", True),
            "show_lang": cfg.get("show_lang", True),
            "sound": cfg.get("sound", False),
            "autostart": cfg.get("autostart", True),
        }
        # 滑杆参数当前值 -> 配置键
        slider_cfg = {
            "opacity": cfg.get("opacity", 80),
            "hide_delay": cfg.get("hide_delay_ms", 0),
            "delay": cfg.get("delay_ms", 0),
            "kb_scale": cfg.get("kb_scale", 1.0),
            "font_scale": cfg.get("font_scale", 1.0),
        }
        for key, (h, kind) in self.ctrls.items():
            if kind == "check":
                u32.SendMessageW(h, BM_SETCHECK,
                                 W.WPARAM(BST_CHECKED if checks.get(key) else 0), W.LPARAM(0))
            elif kind == "slider":
                spec = _SLIDER_SPEC[key]
                tick = spec["from_cfg"](slider_cfg[key])
                u32.SendMessageW(h, TBM_SETPOS, W.WPARAM(1), W.LPARAM(tick))
                self._update_slider_value(key)
            elif kind == "choice":
                cur = cfg.get({"theme": "theme", "hotkey": "toggle_hotkey",
                               "layout": "layout", "position": "position",
                               "hint_mode": "hint_mode"}[key])
                label = next((t for t, v in self.combo_opts[key] if v == cur),
                             self.combo_opts[key][0][0])
                u32.SetWindowTextW(h, label + "  ▾")

    def _update_slider_value(self, key):
        """拖动滑杆时刷新右侧数值显示。"""
        h, kind = self.ctrls.get(key, (0, ""))
        spec = _SLIDER_SPEC[key]
        tick = int(u32.SendMessageW(h, TBM_GETPOS, W.WPARAM(0), W.LPARAM(0)))
        val = spec["to_cfg"](tick)
        valve = self._valve_hwnd(spec["valve"])
        if valve:
            u32.SetWindowTextW(valve, spec["fmt"](val))

    def _valve_hwnd(self, valve_id):
        # 数值显示 Static 不在 self.ctrls（它是纯展示），这里实时按 ID 找窗口
        return u32.GetDlgItem(self.hwnd, valve_id)

    def _cycle_choice(self, key):
        """点击选项按钮：循环切到下一个中文选项。"""
        h, kind = self.ctrls[key]
        buf = C.create_unicode_buffer(128)
        u32.GetWindowTextW(h, buf, 128)
        txt = buf.value.replace("▾", "").strip()
        opts = self.combo_opts[key]
        idx = next((i for i, (t, v) in enumerate(opts) if t == txt), 0)
        nxt = (idx + 1) % len(opts)
        u32.SetWindowTextW(h, opts[nxt][0] + "  ▾")

    def _apply(self):
        cfg = dict(self.get_state() or {})
        def chk(key):
            h, kind = self.ctrls[key]
            return bool(u32.SendMessageW(h, BM_GETCHECK, W.WPARAM(0), W.LPARAM(0)))
        def sld(key):
            h, kind = self.ctrls[key]
            tick = int(u32.SendMessageW(h, TBM_GETPOS, W.WPARAM(0), W.LPARAM(0)))
            return _SLIDER_SPEC[key]["to_cfg"](tick)
        def choice(key):
            h, kind = self.ctrls[key]
            buf = C.create_unicode_buffer(128)
            u32.GetWindowTextW(h, buf, 128)
            txt = buf.value.replace("▾", "").strip()
            for label, val in self.combo_opts[key]:
                if txt == label or txt == val:
                    return val
            return self.get_state().get({"theme": "theme", "hotkey": "toggle_hotkey",
                                         "layout": "layout", "position": "position",
                                         "hint_mode": "hint_mode"}[key])

        cfg["wallpaper_theme"] = chk("wallpaper")
        cfg["fade"] = chk("fade")
        cfg["enabled"] = chk("enabled")
        cfg["mouse_click"] = chk("mouse_click")
        cfg["click_keep"] = chk("click_keep")
        cfg["popup_enabled"] = chk("popup")
        cfg["narrow"] = chk("narrow")
        cfg["app_context"] = chk("app_context")
        cfg["show_lang"] = chk("show_lang")
        cfg["sound"] = chk("sound")
        cfg["autostart"] = chk("autostart")
        cfg["taskbar_dock"] = False   # v4.09：图标只在托盘，永不进任务栏
        cfg["modifiers"] = dict(cfg.get("modifiers", {}))
        cfg["modifiers"]["Ctrl"] = chk("mod_ctrl")
        cfg["modifiers"]["Shift"] = chk("mod_shift")
        cfg["modifiers"]["Alt"] = chk("mod_alt")
        cfg["modifiers"]["Win"] = chk("mod_win")
        cfg["opacity"] = sld("opacity")
        cfg["hide_delay_ms"] = sld("hide_delay")
        cfg["delay_ms"] = sld("delay")
        cfg["kb_scale"] = sld("kb_scale")
        cfg["font_scale"] = sld("font_scale")
        cfg["theme"] = choice("theme")
        cfg["toggle_hotkey"] = choice("hotkey")
        cfg["layout"] = choice("layout")
        cfg["position"] = choice("position")
        cfg["hint_mode"] = choice("hint_mode")
        try:
            self.on_apply(cfg)
        except Exception as e:
            print("设置应用失败：", e)

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
                if code == BN_CLICKED and cid == _IDC_SETTINGS_APPLY:
                    self._apply()
                    return 0
                if code == BN_CLICKED and cid == _IDC_SETTINGS_CLOSE:
                    u32.DestroyWindow(hwnd)
                    return 0
                if code == BN_CLICKED and cid == _IDC_SETTINGS_CUSTOM:
                    if self.on_custom:
                        try:
                            self.on_custom()
                        except Exception as e:
                            print("打开自定义面板失败：", e)
                    return 0
                # v4.09：点击选项按钮循环切换（theme/hotkey/layout/position/hint_mode）
                if code == BN_CLICKED:
                    for key in ("theme", "hotkey", "layout", "position", "hint_mode"):
                        if cid == _SETTINGS_IDS[key] and self.ctrls.get(key, (0, ""))[1] == "choice":
                            self._cycle_choice(key)
                            return 0
            if msg == WM_HSCROLL:
                # v4.09：拖动滑杆实时刷新右侧数值
                slider_id = int(lp) & 0xFFFF if lp else 0
                for key, spec in _SLIDER_SPEC.items():
                    if slider_id == _SETTINGS_IDS[key]:
                        self._update_slider_value(key)
                        return 0
                # 滑杆消息也可能来自子控件自身（lp=0），遍历所有滑杆刷新
                for key in _SLIDER_SPEC:
                    self._update_slider_value(key)
                return 0
            if msg == w.WM_CTLCOLORSTATIC:
                gdi32.SetBkMode(W.HDC(int(wp)), 1)
                return u32.GetSysColorBrush(15)
            if msg == w.WM_CLOSE:
                u32.DestroyWindow(hwnd)
                return 0
            if msg == w.WM_DESTROY:
                self.hwnd = None
                if self.on_close_cb:
                    try:
                        self.on_close_cb()
                    except Exception:
                        pass
                return 0
        except Exception as e:
            print("设置窗口消息错误：", e)
        return u32.DefWindowProcW(hwnd, msg, wp, lp)
