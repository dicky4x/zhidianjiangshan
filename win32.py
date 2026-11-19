# -*- coding: utf-8 -*-
"""
极简 Win32 绑定：分层半透明窗口 / 消息循环 / 系统托盘 / 全局键盘钩子 / 前台进程
只用 ctypes，不依赖 PyQt、tkinter、pywin32 或 Electron。
"""

from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
import threading

user32 = C.WinDLL("user32", use_last_error=True)
gdi32 = C.WinDLL("gdi32", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)
shell32 = C.WinDLL("shell32", use_last_error=True)
comctl32 = C.WinDLL("comctl32", use_last_error=True)

LRESULT = C.c_ssize_t
WPARAM = C.c_size_t
LPARAM = C.c_ssize_t
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, WPARAM, LPARAM)
HOOKPROC = C.WINFUNCTYPE(LRESULT, C.c_int, WPARAM, LPARAM)

# ---------------------------------------------------------------- 常量
WM_APP = 0x8000
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_DESTROY = 0x0002
WM_QUIT = 0x0012
WM_NULL = 0x0000
WM_CLOSE = 0x0010
WM_RBUTTONUP = 0x0205
WM_LBUTTONUP = 0x0202
WM_LBUTTONDOWN = 0x0201
WM_MOUSEMOVE = 0x0200
WM_MOUSEWHEEL = 0x020A
WM_LBUTTONDBLCLK = 0x0203
WM_SETTINGCHANGE = 0x001A
WM_SETCURSOR = 0x0020
WM_HSCROLL = 0x0114
WM_CREATE = 0x0001
WM_CTLCOLORSTATIC = 0x0138
WM_SETFONT = 0x0030
WM_USER = 0x0400
IDC_HAND = 32649
IDC_SIZENWSE = 32642      # v4.01：右下角缩放光标
IDC_SIZEALL = 32646       # v4.01：顶栏移动光标
SW_RESTORE = 9

WS_POPUP = 0x80000000
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000      # v4.07：强制在任务栏显示独立按钮
GWL_EXSTYLE = -20
SW_SHOW = 5
SW_HIDE = 0
SW_MINIMIZE = 6                    # v4.07：最小化窗口仍有任务栏按钮
WM_SIZE = 0x0005
WM_ACTIVATE = 0x0006
SIZE_RESTORED = 0
WM_SETICON = 0x0080
ICON_BIG = 1
ICON_SMALL = 0
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0
BI_RGB = 0

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

NIF_MESSAGE = 0x00000002
NIF_ICON = 0x00000001
NIF_TIP = 0x00000004
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2

MF_STRING = 0x00000000
MF_CHECKED = 0x00000008
MF_UNCHECKED = 0x00000000
MF_GRAYED = 0x00000001
MF_SEPARATOR = 0x00000800
MF_POPUP = 0x00000010
TPM_RIGHTBUTTON = 0x0002
TPM_LEFTALIGN = 0x0000
TPM_RETURNCMD = 0x0100

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040

VK_LSHIFT, VK_RSHIFT, VK_SHIFT = 0xA0, 0xA1, 0x10
VK_LCONTROL, VK_RCONTROL, VK_CONTROL = 0xA2, 0xA3, 0x11
VK_LMENU, VK_RMENU, VK_MENU = 0xA4, 0xA5, 0x12
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_LEFT, VK_RIGHT, VK_HOME, VK_END = 0x25, 0x27, 0x24, 0x23

MODIFIER_VK = {
    VK_LCONTROL: "Ctrl", VK_RCONTROL: "Ctrl", VK_CONTROL: "Ctrl",
    VK_LSHIFT: "Shift", VK_RSHIFT: "Shift", VK_SHIFT: "Shift",
    VK_LMENU: "Alt", VK_RMENU: "Alt", VK_MENU: "Alt",
    VK_LWIN: "Win", VK_RWIN: "Win",
}

# ---------------------------------------------------------------- 结构
class POINT(C.Structure):
    _fields_ = [("x", C.c_long), ("y", C.c_long)]


class SIZE(C.Structure):
    _fields_ = [("cx", C.c_long), ("cy", C.c_long)]


class RECT(C.Structure):
    _fields_ = [("left", C.c_long), ("top", C.c_long),
                ("right", C.c_long), ("bottom", C.c_long)]


class MSG(C.Structure):
    _fields_ = [("hwnd", W.HWND), ("message", W.UINT), ("wParam", WPARAM),
                ("lParam", LPARAM), ("time", W.DWORD), ("pt", POINT),
                ("lPrivate", W.DWORD)]


class WNDCLASSEXW(C.Structure):
    _fields_ = [("cbSize", W.UINT), ("style", W.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", C.c_int), ("cbWndExtra", C.c_int),
                ("hInstance", W.HINSTANCE), ("hIcon", W.HICON), ("hCursor", W.HICON),
                ("hbrBackground", W.HBRUSH), ("lpszMenuName", W.LPCWSTR),
                ("lpszClassName", W.LPCWSTR), ("hIconSm", W.HICON)]


class BLENDFUNCTION(C.Structure):
    _fields_ = [("BlendOp", C.c_ubyte), ("BlendFlags", C.c_ubyte),
                ("SourceConstantAlpha", C.c_ubyte), ("AlphaFormat", C.c_ubyte)]


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", C.c_long), ("biHeight", C.c_long),
                ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                ("biSizeImage", W.DWORD), ("biXPelsPerMeter", C.c_long),
                ("biYPelsPerMeter", C.c_long), ("biClrUsed", W.DWORD),
                ("biClrImportant", W.DWORD)]


class BITMAPINFO(C.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", W.DWORD * 3)]


class KBDLLHOOKSTRUCT(C.Structure):
    _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", C.c_void_p)]


class NOTIFYICONDATAW(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("hWnd", W.HWND), ("uID", W.UINT),
                ("uFlags", W.UINT), ("uCallbackMessage", W.UINT), ("hIcon", W.HICON),
                ("szTip", W.WCHAR * 128), ("dwState", W.DWORD), ("dwStateMask", W.DWORD),
                ("szInfo", W.WCHAR * 256), ("uVersion", W.UINT),
                ("szInfoTitle", W.WCHAR * 64), ("dwInfoFlags", W.DWORD),
                ("guidItem", C.c_ubyte * 16), ("hBalloonIcon", W.HICON)]


# ---- SendInput：把「点击虚拟键帽」转换成真实的键盘组合键 -----------------
class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", C.c_long), ("dy", C.c_long), ("mouseData", W.DWORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class _INPUTUNION(C.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", _INPUTUNION)]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_UNICODE = 0x0004      # wVk=0, wScan=Unicode 码点：绕过键盘布局直接输入字符
LLKHF_INJECTED = 0x10
# 只有我们自己注入的按键才带这个 dwExtraInfo，用于在低级钩子里识别并忽略，
# 避免「点击键帽 -> 注入 Ctrl -> 钩子以为用户按住了 Ctrl」的自激。
INJECT_MAGIC = 0x4B48494A

EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,
                0x2D, 0x2E, 0x5B, 0x5C, 0x5D, 0x90, 0x6F}


# ---------------------------------------------------------------- 函数签名
def _sig(fn, argtypes, restype=None):
    fn.argtypes = argtypes
    fn.restype = restype


_sig(user32.RegisterClassExW, [C.POINTER(WNDCLASSEXW)], W.ATOM)
_sig(user32.CreateWindowExW,
     [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int, C.c_int, C.c_int,
      W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID], W.HWND)
_sig(user32.DefWindowProcW, [W.HWND, W.UINT, WPARAM, LPARAM], LRESULT)
_sig(user32.DispatchMessageW, [C.POINTER(MSG)], LRESULT)
_sig(user32.TranslateMessage, [C.POINTER(MSG)], W.BOOL)
_sig(user32.GetMessageW, [C.POINTER(MSG), W.HWND, W.UINT, W.UINT], W.BOOL)
_sig(user32.PostMessageW, [W.HWND, W.UINT, WPARAM, LPARAM], W.BOOL)
_sig(user32.PostThreadMessageW, [W.DWORD, W.UINT, WPARAM, LPARAM], W.BOOL)
_sig(user32.SendMessageW, [W.HWND, W.UINT, WPARAM, LPARAM], LRESULT)
_sig(user32.SetTimer, [W.HWND, C.c_size_t, W.UINT, W.LPVOID], C.c_size_t)
_sig(user32.KillTimer, [W.HWND, C.c_size_t], W.BOOL)
_sig(user32.ShowWindow, [W.HWND, C.c_int], W.BOOL)
_sig(user32.SetWindowPos, [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT], W.BOOL)
_sig(user32.DestroyWindow, [W.HWND], W.BOOL)
_sig(user32.PostQuitMessage, [C.c_int], None)
_sig(user32.GetWindowLongW, [W.HWND, C.c_int], C.c_long)
_sig(user32.SetWindowLongW, [W.HWND, C.c_int, C.c_long], C.c_long)
_sig(user32.GetForegroundWindow, [], W.HWND)
_sig(user32.GetWindowThreadProcessId, [W.HWND, C.POINTER(W.DWORD)], W.DWORD)
_sig(user32.GetSystemMetrics, [C.c_int], C.c_int)
_sig(user32.GetCursorPos, [C.POINTER(POINT)], W.BOOL)
_sig(user32.SetForegroundWindow, [W.HWND], W.BOOL)
_sig(user32.BringWindowToTop, [W.HWND], W.BOOL)
_sig(user32.SetActiveWindow, [W.HWND], W.HWND)
_sig(user32.IsIconic, [W.HWND], W.BOOL)
_sig(user32.AttachThreadInput, [W.DWORD, W.DWORD, W.BOOL], W.BOOL)
_sig(user32.GetAncestor, [W.HWND, W.UINT], W.HWND)
_sig(user32.SetFocus, [W.HWND], W.HWND)
_sig(user32.GetAsyncKeyState, [C.c_int], C.c_short)
_sig(user32.GetKeyboardLayout, [W.DWORD], W.HKL)
_sig(user32.SetWindowsHookExW, [C.c_int, HOOKPROC, W.HINSTANCE, W.DWORD], W.HHOOK)
_sig(user32.UnhookWindowsHookEx, [W.HHOOK], W.BOOL)
_sig(user32.CallNextHookEx, [W.HHOOK, C.c_int, WPARAM, LPARAM], LRESULT)
_sig(user32.LoadImageW, [W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT], W.HANDLE)
_sig(user32.CreatePopupMenu, [], W.HMENU)
_sig(user32.AppendMenuW, [W.HMENU, W.UINT, C.c_size_t, W.LPCWSTR], W.BOOL)
_sig(user32.TrackPopupMenuEx, [W.HMENU, W.UINT, C.c_int, C.c_int, W.HWND, W.LPVOID], W.BOOL)
_sig(user32.DestroyMenu, [W.HMENU], W.BOOL)
_sig(user32.CreateMenu, [], W.HMENU)
_sig(shell32.Shell_NotifyIconW, [W.DWORD, C.POINTER(NOTIFYICONDATAW)], W.BOOL)
_sig(shell32.ShellExecuteW, [W.HWND, W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, C.c_int], W.HINSTANCE)
_sig(gdi32.CreateCompatibleDC, [W.HDC], W.HDC)
_sig(gdi32.DeleteDC, [W.HDC], W.BOOL)
_sig(gdi32.SelectObject, [W.HDC, W.HGDIOBJ], W.HGDIOBJ)
_sig(gdi32.DeleteObject, [W.HGDIOBJ], W.BOOL)
_sig(gdi32.CreateDIBSection, [W.HDC, C.POINTER(BITMAPINFO), W.UINT,
                              C.POINTER(C.c_void_p), W.HANDLE, W.DWORD], W.HBITMAP)
_sig(gdi32.GdiFlush, [], W.BOOL)
_sig(user32.GetDC, [W.HWND], W.HDC)
_sig(user32.ReleaseDC, [W.HWND, W.HDC], C.c_int)
_sig(user32.UpdateLayeredWindow,
     [W.HWND, W.HDC, C.POINTER(POINT), C.POINTER(SIZE), W.HDC,
      C.POINTER(POINT), W.DWORD, C.POINTER(BLENDFUNCTION), W.DWORD], W.BOOL)
_sig(kernel32.GetModuleHandleW, [W.LPCWSTR], W.HINSTANCE)
_sig(kernel32.OpenProcess, [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)
_sig(kernel32.CloseHandle, [W.HANDLE], W.BOOL)
_sig(kernel32.QueryFullProcessImageNameW,
     [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)], W.BOOL)
_sig(kernel32.GetCurrentThreadId, [], W.DWORD)
_sig(kernel32.GetLastError, [], W.DWORD)
_sig(user32.SendInput, [W.UINT, C.POINTER(INPUT), C.c_int], W.UINT)
_sig(user32.MapVirtualKeyW, [W.UINT, W.UINT], W.UINT)
_sig(user32.LoadCursorW, [W.HINSTANCE, C.c_void_p], W.HANDLE)
_sig(user32.SetCursor, [W.HANDLE], W.HANDLE)
_sig(user32.WindowFromPoint, [POINT], W.HWND)
_sig(user32.IsWindow, [W.HWND], W.BOOL)
_sig(user32.ClientToScreen, [W.HWND, C.POINTER(POINT)], W.BOOL)
_sig(user32.SetCursorPos, [C.c_int, C.c_int], W.BOOL)
_sig(user32.mouse_event, [W.DWORD, W.DWORD, W.DWORD, W.DWORD, C.c_size_t], None)
_sig(user32.SetCapture, [W.HWND], W.HWND)
_sig(user32.ReleaseCapture, [], W.BOOL)
_sig(user32.GetCapture, [], W.HWND)
_sig(gdi32.GetStockObject, [C.c_int], W.HGDIOBJ)
_sig(comctl32.InitCommonControls, [], None)

HWND_TOPMOST = W.HWND(-1)
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_FRAMECHANGED = 0x0020
SWP_NOZORDER = 0x0004


def enable_dpi_awareness():
    try:
        C.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def async_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def send_keys(events: list[tuple[int, bool]]) -> int:
    """
    events: [(vk, down), ...] —— 一次性注入整串按键，等价于物理按下。
    全部带 INJECT_MAGIC，低级键盘钩子可据此忽略自身注入、避免状态自激。
    """
    if not events:
        return 0
    arr = (INPUT * len(events))()
    for i, (vk, down) in enumerate(events):
        arr[i].type = INPUT_KEYBOARD
        arr[i].ki.wVk = int(vk) & 0xFFFF
        arr[i].ki.dwFlags = (0 if down else KEYEVENTF_KEYUP)
        if vk in EXTENDED_VKS:
            arr[i].ki.dwFlags |= KEYEVENTF_EXTENDEDKEY
        arr[i].ki.dwExtraInfo = INJECT_MAGIC
    sent = user32.SendInput(len(events), arr, C.sizeof(INPUT))
    if sent != len(events):
        print("SendInput 只发送了 %d/%d 个事件，错误码 %s"
              % (sent, len(events), kernel32.GetLastError()))
    return sent


def _send_one(vk: int, down: bool) -> int:
    """发送单个按键事件（具体键 + 扫描码 + INJECT_MAGIC）。"""
    e = INPUT()
    e.type = INPUT_KEYBOARD
    e.ki.wVk = int(vk) & 0xFFFF
    e.ki.wScan = int(user32.MapVirtualKeyW(int(vk) & 0xFFFF, 0)) & 0xFFFF
    e.ki.dwFlags = (0 if down else KEYEVENTF_KEYUP)
    if vk in EXTENDED_VKS:
        e.ki.dwFlags |= KEYEVENTF_EXTENDEDKEY
    e.ki.dwExtraInfo = INJECT_MAGIC
    return int(user32.SendInput(1, C.byref(e), C.sizeof(INPUT)))


def send_combo(mods: list[int], vk: int, gap_s: float = 0.035) -> int:
    """稳健发送组合键，专治 WPS/Word 对「一次性 SendInput 多事件」漏判修饰键。

    与 send_keys 一次性塞满 INPUT 数组不同，这里逐帧发送并在每帧间留间隔，
    让目标程序有机会逐条处理；修饰键统一用具体左右键（VK_LCONTROL/VK_LSHIFT）
    并填扫描码，避免 WPS 把 Ctrl+Shift+= 误判成 Ctrl+=。
    """
    _MAP = {VK_CONTROL: VK_LCONTROL, VK_SHIFT: VK_LSHIFT, VK_MENU: VK_LMENU}
    keys = [_MAP.get(m, m) for m in mods]
    n = 0
    for k in keys:
        n += _send_one(k, True)
        C.windll.kernel32.Sleep(int(gap_s * 1000))
    n += _send_one(vk, True)
    C.windll.kernel32.Sleep(int(gap_s * 1000))
    n += _send_one(vk, False)
    for k in reversed(keys):
        n += _send_one(k, False)
        C.windll.kernel32.Sleep(int(gap_s * 1000))
    return n


def send_unicode(text: str) -> int:
    """
    用 KEYEVENTF_UNICODE 把字符串直接注入当前焦点窗口，不依赖键盘布局、
    NumLock 或目标软件对 Alt 码的解析。适用于 √ × ☑ 等任意 BMP 内符号。

    每个字符发一对 keydown/keyup，wScan=码点，wVk=0。
    全部带 INJECT_MAGIC，低级键盘钩子据此忽略、避免状态自激。
    超出 BMP 的字符（如部分 emoji）拆成 UTF-16 代理对逐个发送。
    """
    if not text:
        return 0
    units: list[int] = []
    for ch in text:
        cp = ord(ch)
        if cp <= 0xFFFF:
            units.append(cp)
        else:
            cp -= 0x10000
            units.append(0xD800 + (cp >> 10))
            units.append(0xDC00 + (cp & 0x3FF))
    events = (INPUT * (len(units) * 2))()
    n = 0
    for i, u in enumerate(units):
        for up in (False, True):
            e = events[n]
            e.type = INPUT_KEYBOARD
            e.ki.wVk = 0
            e.ki.wScan = u & 0xFFFF
            e.ki.dwFlags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
            e.ki.dwExtraInfo = INJECT_MAGIC
            n += 1
    sent = user32.SendInput(n, events, C.sizeof(INPUT))
    if sent != n:
        print("Unicode SendInput 只发送了 %d/%d 个事件，错误码 %s"
              % (sent, n, kernel32.GetLastError()))
    return sent


def mouse_xy(lparam: int) -> tuple[int, int]:
    """从 WM_MOUSE* 的 lParam 解析相对窗口客户区坐标（可能为负）"""
    x = C.c_short(int(lparam) & 0xFFFF).value
    y = C.c_short((int(lparam) >> 16) & 0xFFFF).value
    return x, y


def release_modifiers() -> int:
    """清除当前按住的 Ctrl/Shift/Alt 逻辑状态，避免注入字符被目标软件当成快捷键。

    用户左手按住 Ctrl 弹出面板、右手点符号，注入时 Ctrl 仍按着；WPS 会把
    Unicode 事件当成 Ctrl+字符 组合键执行对应功能（如保存/加粗），而不是输入
    字符。发送这些修饰键的 KEYUP 可清除目标窗口的修饰键状态。事件带
    INJECT_MAGIC，本程序全局钩子会忽略，不影响面板显示逻辑。
    只释放当前实际按住的修饰键，避免无谓事件干扰。
    """
    vk_groups = []
    if async_down(VK_CONTROL) or async_down(VK_LCONTROL) or async_down(VK_RCONTROL):
        vk_groups.extend((VK_LCONTROL, VK_RCONTROL, VK_CONTROL))
    if async_down(VK_SHIFT) or async_down(VK_LSHIFT) or async_down(VK_RSHIFT):
        vk_groups.extend((VK_LSHIFT, VK_RSHIFT, VK_SHIFT))
    if async_down(VK_MENU) or async_down(VK_LMENU) or async_down(VK_RMENU):
        vk_groups.extend((VK_LMENU, VK_RMENU, VK_MENU))
    if not vk_groups:
        return 0
    events = (INPUT * len(vk_groups))()
    for i, vk in enumerate(vk_groups):
        e = events[i]
        e.type = INPUT_KEYBOARD
        e.ki.wVk = vk
        e.ki.wScan = 0
        e.ki.dwFlags = KEYEVENTF_KEYUP
        e.ki.dwExtraInfo = INJECT_MAGIC
    n = user32.SendInput(len(events), events, C.sizeof(INPUT))
    if n != len(events):
        print("释放修饰键只发送了 %d/%d，错误码 %s"
              % (n, len(events), kernel32.GetLastError()))
    return n


def held_modifiers() -> set[str]:
    """用 GetAsyncKeyState 同步当前真实按住的修饰键（校正钩子可能丢失的按下事件）"""
    held = set()
    if async_down(VK_CONTROL) or async_down(VK_LCONTROL) or async_down(VK_RCONTROL):
        held.add("Ctrl")
    if async_down(VK_SHIFT) or async_down(VK_LSHIFT) or async_down(VK_RSHIFT):
        held.add("Shift")
    if async_down(VK_MENU) or async_down(VK_LMENU) or async_down(VK_RMENU):
        held.add("Alt")
    if async_down(VK_LWIN) or async_down(VK_RWIN):
        held.add("Win")
    return held


# ---------------------------------------------------------------- 窗口
_classes = {}
_wndprocs = []   # 防止回调被 GC


def create_message_window(class_name: str, title: str, wndproc) -> W.HWND:
    hinst = kernel32.GetModuleHandleW(None)
    if class_name not in _classes:
        cb = wndproc if isinstance(wndproc, WNDPROC) else WNDPROC(wndproc)
        wc = WNDCLASSEXW()
        wc.cbSize = C.sizeof(wc)
        wc.lpfnWndProc = cb
        wc.hInstance = hinst
        wc.lpszClassName = class_name
        if not user32.RegisterClassExW(C.byref(wc)):
            err = kernel32.GetLastError()
            if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS
                raise OSError("RegisterClassExW failed: %s" % err)
        _classes[class_name] = cb
    _wndprocs.append(wndproc)
    # WS_POPUP：窗口没有边框/标题栏非客户区，客户区 = 整个窗口矩形。
    # 若用默认的 WS_OVERLAPPED(0)，分层窗口会出现 (8,31) 的客户区偏移，
    # 矮控件条上的点击会全部变成 WM_NC* 消息而收不到 WM_LBUTTONDOWN。
    # v4.09：主消息窗口加 WS_EX_TOOLWINDOW，确保它永远不进任务栏 / Alt+Tab；
    # 程序图标只保留在系统托盘。托盘图标由独立 TrayIcon 维护，不受此标志影响。
    hwnd = user32.CreateWindowExW(WS_EX_TOOLWINDOW, class_name, title, WS_POPUP, 0, 0, 0, 0,
                                  W.HWND(0), W.HMENU(0), hinst, None)
    if not hwnd:
        raise OSError("CreateWindowExW failed: %s" % kernel32.GetLastError())
    return hwnd


def create_taskbar_window(class_name: str, title: str, icon_path: str = None) -> W.HWND:
    """v4.07：创建一个在任务栏常驻显示的代理窗口。

    用同一个 WNDPROC（由调用方传入的类），但指定 WS_EX_APPWINDOW + 可见样式，
    Windows 就会在任务栏给它一个按钮。窗口本身 1x1、放到屏幕外，用户看不到；
    点击任务栏按钮时由 WndProc 的 WM_ACTIVATE 弹出托盘同款菜单。
    """
    hinst = kernel32.GetModuleHandleW(None)
    # 复用已注册的类（create_message_window 已注册同名类），避免重复注册丢失 WNDPROC
    hwnd = user32.CreateWindowExW(
        WS_EX_APPWINDOW, class_name, title,
        WS_OVERLAPPEDWINDOW & ~0x00800000,  # 去掉最大化框，保留最小化/关闭
        -32000, -32000, 1, 1, W.HWND(0), W.HMENU(0), hinst, None)
    if not hwnd:
        raise OSError("CreateWindowExW(taskbar) failed: %s" % kernel32.GetLastError())
    if icon_path and os.path.exists(icon_path):
        hicon = user32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0,
                                  LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if hicon:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
    # 最小化而非隐藏：最小化窗口仍保留任务栏按钮，且不会露出 1x1 窗口本体
    user32.ShowWindow(hwnd, SW_MINIMIZE)
    return hwnd


def taskbar_show(hwnd):
    w = user32
    w.ShowWindow(hwnd, SW_MINIMIZE)


def taskbar_destroy(hwnd):
    if hwnd:
        user32.DestroyWindow(hwnd)


class LayeredWindow:
    """
    真正的逐像素 alpha 分层窗口：置顶、不抢焦点。
    WS_EX_TRANSPARENT 可动态开关：
      开 -> 鼠标完全穿透，点击被键盘遮住的文字 / 文件
      关 -> 窗口接收鼠标消息，可以点击虚拟键帽执行快捷键
    on_mouse(hwnd, msg, wp, lp) 返回 None 表示交给 DefWindowProcW。
    """

    def __init__(self, class_name="KeyHintOverlay", on_mouse=None,
                 start_click_through=True):
        """
        start_click_through=False 用于「右上角控件条」：该窗口永远不加
        WS_EX_TRANSPARENT，因此即使虚拟键盘处于穿透模式，控件仍可直接点击。
        """
        self.hwnd = None
        self.hdc = None
        self.hbmp = None
        self.hbmp_old = None
        self.bits = None
        self.size = (0, 0)
        self.visible = False
        self.rect = (0, 0, 0, 0)          # 屏幕坐标 (x, y, w, h)
        self.click_through = bool(start_click_through)
        self.on_mouse = on_mouse

        def proc(h, m, wp, lp):
            if self.on_mouse is not None:
                try:
                    r = self.on_mouse(h, m, wp, lp)
                    if r is not None:
                        return r
                except Exception as e:
                    print("鼠标消息处理失败：", e)
            return user32.DefWindowProcW(h, m, wp, lp)

        self._cb = WNDPROC(proc)
        self.hwnd = create_message_window(class_name, "KeyHintOverlay", self._cb)
        style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        style |= (WS_EX_LAYERED | WS_EX_NOACTIVATE |
                  WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
        if self.click_through:
            style |= WS_EX_TRANSPARENT
        user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style)
        # 必须让系统重算非客户区/命中测试缓存，否则「初始就不穿透」的窗口
        # 仍会被当成穿透窗口而收不到任何鼠标消息（实测现象）。
        user32.SetWindowPos(self.hwnd, W.HWND(0), 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |
                            SWP_NOACTIVATE | SWP_FRAMECHANGED)
        self.hdc = gdi32.CreateCompatibleDC(None)
        if not self.hdc:
            raise OSError("CreateCompatibleDC failed")

    def set_click_through(self, transparent: bool):
        """True = 鼠标穿透；False = 接收鼠标点击"""
        transparent = bool(transparent)
        if transparent == self.click_through or not self.hwnd:
            return
        style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        if transparent:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style)
        user32.SetWindowPos(self.hwnd, W.HWND(0), 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |
                            SWP_NOACTIVATE | SWP_FRAMECHANGED)
        self.click_through = transparent

    def _ensure_bitmap(self, w, h):
        if (w, h) == self.size and self.hbmp:
            return
        if self.hbmp:
            gdi32.SelectObject(self.hdc, self.hbmp_old)
            gdi32.DeleteObject(self.hbmp)
        bi = BITMAPINFO()
        bi.bmiHeader.biSize = C.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = w
        bi.bmiHeader.biHeight = -h          # top-down
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = BI_RGB
        bits = C.c_void_p()
        hbmp = gdi32.CreateDIBSection(self.hdc, C.byref(bi), DIB_RGB_COLORS,
                                      C.byref(bits), None, 0)
        if not hbmp:
            raise OSError("CreateDIBSection failed: %s" % kernel32.GetLastError())
        self.hbmp = hbmp
        self.hbmp_old = gdi32.SelectObject(self.hdc, hbmp)
        self.bits = bits
        self.size = (w, h)

    def blit(self, bgra: bytes, w: int, h: int, x: int, y: int, global_alpha=255):
        """bgra: 已预乘 alpha 的 BGRA 字节流"""
        self.rect = (x, y, w, h)
        self._ensure_bitmap(w, h)
        C.memmove(self.bits, bgra, len(bgra))
        gdi32.GdiFlush()
        ppt_dst = POINT(x, y)
        psize = SIZE(w, h)
        ppt_src = POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, global_alpha, AC_SRC_ALPHA)
        screendc = user32.GetDC(None)
        try:
            ok = user32.UpdateLayeredWindow(self.hwnd, screendc, C.byref(ppt_dst),
                                            C.byref(psize), self.hdc, C.byref(ppt_src),
                                            0, C.byref(blend), ULW_ALPHA)
            if not ok:
                raise OSError("UpdateLayeredWindow failed: %s" % kernel32.GetLastError())
        finally:
            user32.ReleaseDC(None, screendc)
        if not self.visible:
            user32.ShowWindow(self.hwnd, SW_SHOW)
            self.visible = True
            # 只在首次显示时提升 Z 序；频繁提升会把透明度设置窗口压到键盘下面
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def raise_top(self):
        """把本窗口提到键盘之上（同为 TOPMOST 时仍需显式保证相对次序）"""
        if self.hwnd and self.visible:
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def hide(self):
        if self.visible:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            self.visible = False
        if self.hwnd and user32.GetCapture() == self.hwnd:
            user32.ReleaseCapture()

    def close(self):
        self.hide()
        if self.hdc:
            if self.hbmp:
                gdi32.SelectObject(self.hdc, self.hbmp_old)
                gdi32.DeleteObject(self.hbmp)
            gdi32.DeleteDC(self.hdc)
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)


# ---------------------------------------------------------------- 托盘
class TrayIcon:
    def __init__(self, hwnd, icon_path, tip, callback_msg=WM_APP + 20):
        self.hwnd = hwnd
        self.callback_msg = callback_msg
        self.nid = NOTIFYICONDATAW()
        self.nid.cbSize = C.sizeof(NOTIFYICONDATAW)
        self.nid.hWnd = hwnd
        self.nid.uID = 1
        self.nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP
        self.nid.uCallbackMessage = callback_msg
        self.nid.szTip = tip[:127]
        self.nid.hIcon = user32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0,
                                           LR_LOADFROMFILE | LR_DEFAULTSIZE)
        shell32.Shell_NotifyIconW(NIM_ADD, C.byref(self.nid))

    def refresh(self):
        """v4.07：定期 NIM_MODIFY 刷新，防止托盘图标被资源管理器自动折叠隐藏"""
        shell32.Shell_NotifyIconW(NIM_MODIFY, C.byref(self.nid))

    def remove(self):
        shell32.Shell_NotifyIconW(NIM_DELETE, C.byref(self.nid))


def _fill_menu(hmenu, items):
    for item in items:
        if item[0] == "sep":
            user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
            continue
        if item[0] == "menu":
            _, text, subitems = item
            sub = user32.CreatePopupMenu()
            _fill_menu(sub, subitems)
            user32.AppendMenuW(hmenu, MF_POPUP | MF_STRING, C.c_size_t(int(sub)), text)
            continue
        if item[0] == "info":
            user32.AppendMenuW(hmenu, MF_STRING | MF_GRAYED, 0, item[1])
            continue
        mid, text, checked, enabled = item
        flags = MF_STRING | (MF_CHECKED if checked else MF_UNCHECKED)
        if not enabled:
            flags |= MF_GRAYED
        user32.AppendMenuW(hmenu, flags, mid, text)


def show_popup_menu(hwnd, items, x=None, y=None) -> int:
    """items: [(id, text, checked, enabled)]，('sep',) 分隔线，('menu', 文本, 子项) 子菜单"""
    hmenu = user32.CreatePopupMenu()
    _fill_menu(hmenu, items)
    if x is None:
        pt = POINT()
        user32.GetCursorPos(C.byref(pt))
        x, y = pt.x, pt.y
    user32.SetForegroundWindow(hwnd)
    cmd = user32.TrackPopupMenuEx(hmenu, TPM_RIGHTBUTTON | TPM_LEFTALIGN | TPM_RETURNCMD,
                                  x, y, hwnd, None)
    user32.DestroyMenu(hmenu)
    user32.PostMessageW(hwnd, WM_NULL, 0, 0)
    return cmd


# ---------------------------------------------------------------- 前台进程 / 输入语言
def foreground_exe() -> str:
    try:
        hwnd = user32.GetForegroundWindow()
        pid = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
        h = kernel32.OpenProcess(0x1000, False, pid.value)
        if not h:
            return ""
        try:
            buf = C.create_unicode_buffer(1024)
            size = W.DWORD(1024)
            ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, C.byref(size))
            return os.path.basename(buf.value) if ok else ""
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        return ""


def exe_of_hwnd(hwnd: int) -> str:
    """返回指定窗口所属进程的 exe 文件名（小写），失败返回空串。"""
    try:
        if not hwnd:
            return ""
        pid = W.DWORD()
        user32.GetWindowThreadProcessId(W.HWND(hwnd), C.byref(pid))
        if not pid.value:
            return ""
        h = kernel32.OpenProcess(0x1000, False, pid.value)
        if not h:
            return ""
        try:
            buf = C.create_unicode_buffer(1024)
            size = W.DWORD(1024)
            ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, C.byref(size))
            return os.path.basename(buf.value).lower() if ok else ""
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        return ""


def foreground_tid() -> int:
    try:
        hwnd = user32.GetForegroundWindow()
        pid = W.DWORD()
        return int(user32.GetWindowThreadProcessId(hwnd, C.byref(pid)))
    except Exception:
        return 0


def foreground_hwnd() -> int:
    """当前前台窗口句柄（整数），供输入类工具记住「真正的目标窗口」。"""
    try:
        return int(user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


def is_own_window(hwnd: int, own: tuple[int, ...] = ()) -> bool:
    """判断 hwnd 是否属于本程序自己（含其顶层所有者），用于过滤目标窗口。"""
    if not hwnd:
        return True
    try:
        cur_tid, _ = user32.GetWindowThreadProcessId(W.HWND(hwnd), None)
        my_tid = kernel32.GetCurrentThreadId()
        if cur_tid and cur_tid == my_tid:
            return True
    except Exception:
        pass
    return int(hwnd) in tuple(int(h) for h in own if h)


def focus_window(hwnd: int) -> bool:
    """
    强制把前台焦点交给指定窗口，绕过 Windows 的前台锁定限制。
    点击虚拟符号页时，鼠标落在 WS_EX_NOACTIVATE 的分层窗口上，系统可能把
    焦点切到桌面/资源管理器；注入 Unicode 前必须先把焦点还给真正的目标窗口，
    否则字符会发给错误的窗口（表现为乱码 / 无输入）。
    """
    hwnd = int(hwnd or 0)
    if not hwnd:
        return False
    h = W.HWND(hwnd)
    if not user32.IsWindow(h):
        return False
    try:
        fg = user32.GetForegroundWindow()
        if fg == h:
            return True
        cur_tid = kernel32.GetCurrentThreadId()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        tgt_tid = user32.GetWindowThreadProcessId(h, None)
        attached_fg = bool(fg_tid and fg_tid != cur_tid
                           and user32.AttachThreadInput(cur_tid, fg_tid, True))
        attached_tgt = bool(tgt_tid and tgt_tid != cur_tid
                            and user32.AttachThreadInput(cur_tid, tgt_tid, True))
        try:
            if user32.IsIconic(h):
                user32.ShowWindow(h, SW_RESTORE)
            user32.BringWindowToTop(h)
            user32.SetForegroundWindow(h)
            user32.SetActiveWindow(h)
            user32.SetFocus(h)
        finally:
            if attached_fg:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
            if attached_tgt:
                user32.AttachThreadInput(cur_tid, tgt_tid, False)
        return int(user32.GetForegroundWindow() or 0) == hwnd
    except Exception:
        return False


_LANG_NAMES = {
    0x0409: "EN", 0x0809: "EN", 0x0404: "繁", 0x0804: "中",
    0x0411: "日", 0x0412: "한", 0x0419: "RU", 0x0407: "DE",
    0x040C: "FR", 0x0410: "IT", 0x0C0A: "ES", 0x0416: "PT",
}


def input_language() -> str:
    """模拟华为「显示输入语言 / 多语言键帽」"""
    try:
        tid = foreground_tid()
        hkl = user32.GetKeyboardLayout(tid)
        lang = int(hkl) & 0xFFFF
        return _LANG_NAMES.get(lang, hex(lang))
    except Exception:
        return ""


# ---------------------------------------------------------------- 全局键盘钩子
class KeyboardHook:
    def __init__(self, target_hwnd, message=WM_APP + 1, swallow=None):
        self.target = target_hwnd
        self.message = message
        self.thread = None
        self.tid = None
        self.hhook = None
        self._ready = threading.Event()
        # v4.01：swallow(vk, down) -> True 时吞掉该按键，阻止系统默认行为
        # （例如 Ctrl+Esc 默认会打开开始菜单）。仍会投递给本程序窗口。
        self.swallow = swallow

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self._ready.wait(2.0)

    def _run(self):
        self.tid = kernel32.GetCurrentThreadId()
        proc = HOOKPROC(self._callback)
        self._cb = proc  # 保活
        self.hhook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc,
                                              kernel32.GetModuleHandleW(None), 0)
        self._ready.set()
        if not self.hhook:
            return
        msg = MSG()
        while user32.GetMessageW(C.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(C.byref(msg))
            user32.DispatchMessageW(C.byref(msg))
        user32.UnhookWindowsHookEx(self.hhook)
        self.hhook = None

    def _callback(self, nCode, wParam, lParam):
        if nCode >= 0 and self.target:
            kb = C.cast(lParam, C.POINTER(KBDLLHOOKSTRUCT)).contents
            msg = wParam
            if msg in (WM_KEYDOWN, WM_SYSKEYDOWN):
                down = 1
            elif msg in (WM_KEYUP, WM_SYSKEYUP):
                down = 0
            else:
                down = -1
            if down >= 0:
                injected = 1 if (kb.flags & LLKHF_INJECTED) else 0
                extra = int(kb.dwExtraInfo or 0) & 0xFFFFFFFF
                own = 4 if extra == INJECT_MAGIC else 0   # 本程序点击键帽注入的按键
                # 先给本程序投递，再决定是否阻止系统默认行为
                user32.PostMessageW(self.target, self.message,
                                    WPARAM(kb.vkCode),
                                    LPARAM(down | (injected << 1) | own))
                if injected or own:
                    blocked = False
                else:
                    try:
                        blocked = bool(self.swallow(kb.vkCode, bool(down))) \
                            if self.swallow else False
                    except Exception:
                        blocked = False
                if blocked:
                    return 1
        return user32.CallNextHookEx(self.hhook, nCode, wParam, lParam)

    def stop(self):
        if self.tid:
            user32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)


def message_loop():
    msg = MSG()
    while True:
        r = user32.GetMessageW(C.byref(msg), None, 0, 0)
        if r == -1 or r == 0:
            return
        user32.TranslateMessage(C.byref(msg))
        user32.DispatchMessageW(C.byref(msg))
