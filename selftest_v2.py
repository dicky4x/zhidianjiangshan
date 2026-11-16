# -*- coding: utf-8 -*-
"""
新增功能端到端自检（请用装了 Pillow 的 Python 运行）：
  A. 点击模式：覆盖层不再穿透 / 松开辅助键保持面板 / 悬停高亮 /
     点击键帽真的注入了组合键（独立低级钩子捕获 INJECT_MAGIC）
  B. 穿透模式：窗口带 WS_EX_TRANSPARENT / 鼠标命中下层窗口 / 松开即收起
  C. 透明度：滑块窗口可创建、TBM_SETPOS 能触发实时回调

运行：  <带 Pillow 的 python> selftest_v2.py
输出：  _v2_*.png 截图
"""
from __future__ import annotations

import atexit
import ctypes as C
import json
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes as W
from pathlib import Path

from PIL import Image, ImageChops, ImageGrab

import win32 as w
import layout

HERE = Path(__file__).resolve().parent
CFG = HERE / "config.json"
u32 = w.user32
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
GWL_EXSTYLE = -20

# 补充本脚本专用的 Win32 签名
def _sig(fn, args, ret=None):
    fn.argtypes, fn.restype = args, ret
_sig(u32.FindWindowW, [W.LPCWSTR, W.LPCWSTR], W.HWND)
_sig(u32.GetWindowRect, [W.HWND, C.POINTER(w.RECT)], W.BOOL)
_sig(u32.SetCursorPos, [C.c_int, C.c_int], W.BOOL)
_sig(u32.mouse_event, [W.DWORD, W.DWORD, W.DWORD, W.DWORD, C.c_size_t], None)
_sig(u32.keybd_event, [C.c_ubyte, C.c_ubyte, W.DWORD, C.c_size_t], None)
_sig(u32.PeekMessageW, [C.POINTER(w.MSG), W.HWND, W.UINT, W.UINT, W.UINT], W.BOOL)


def keydown(vk):
    u32.keybd_event(vk, 0, 0, 0)


def keyup(vk):
    u32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def grab(name):
    p = HERE / ("_v2_%s.png" % name)
    ImageGrab.grab().save(str(p))
    return p


def diff(a, b, box=None):
    if box:
        a, b = a.crop(box), b.crop(box)
    d = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
    h = d.histogram()
    return sum(h[24:]) / max(1, sum(h))


def overlay_hwnd():
    return u32.FindWindowW("KeyHintOverlay", None)


def exstyle(hwnd):
    return u32.GetWindowLongW(hwnd, GWL_EXSTYLE)


def window_rect(hwnd):
    r = w.RECT()
    u32.GetWindowRect(hwnd, C.byref(r))
    return r.left, r.top, r.right, r.bottom


def key_center(sid="C"):
    h = overlay_hwnd()
    if not h:
        return None
    l, t, _, _ = window_rect(h)
    sw, _ = w.screen_size()
    keys, _, _, _, _ = layout.build("compact", False, sw)
    for k in keys:
        if k.sid == sid:
            return l + int(k.x + k.w / 2), t + int(k.y + k.h / 2)
    return None


class InjectWatcher:
    """在独立线程安装全局低级键盘钩子，捕获本程序注入的组合键"""

    def __init__(self):
        self.events = []
        self.tid = None
        self.hhook = 0
        self._cb = w.HOOKPROC(self._callback)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._ready = threading.Event()

    def _callback(self, nCode, wp, lp):
        if nCode >= 0:
            kb = C.cast(lp, C.POINTER(w.KBDLLHOOKSTRUCT)).contents
            if (int(kb.dwExtraInfo or 0) & 0xFFFFFFFF) == w.INJECT_MAGIC:
                self.events.append((int(wp), int(kb.vkCode)))
        return u32.CallNextHookEx(None, nCode, wp, lp)

    def _run(self):
        self.tid = w.kernel32.GetCurrentThreadId()
        self.hhook = u32.SetWindowsHookExW(w.WH_KEYBOARD_LL, self._cb,
                                           w.kernel32.GetModuleHandleW(None), 0)
        self._ready.set()
        msg = w.MSG()
        while u32.GetMessageW(C.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(C.byref(msg))
            u32.DispatchMessageW(C.byref(msg))
        if self.hhook:
            u32.UnhookWindowsHookEx(self.hhook)

    def start(self):
        self._thread.start()
        self._ready.wait(2.0)

    def stop(self):
        if self.tid:
            u32.PostThreadMessageW(self.tid, w.WM_QUIT, 0, 0)


def run_app(extra=None):
    env = dict(os.environ)
    env["KEYHINT_DEBUG"] = "1"
    return subprocess.Popen([sys.executable, "-u", str(HERE / "app.py")] + (extra or []),
                            cwd=str(HERE), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env,
                            encoding="utf-8", errors="replace")


def stop_app(p):
    if p.poll() is None:
        p.terminate()
    try:
        p.wait(timeout=3)
    except Exception:
        p.kill()
    try:
        out = p.stdout.read()
        if out and out.strip():
            print("   主程序输出：", out.strip()[:600])
    except Exception:
        pass


def set_cfg(**kw):
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    cfg.update(kw)
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def phase_click(watcher):
    print("\n[A] 鼠标点击模式")
    set_cfg(mouse_click=True, fade=True, opacity=92, click_keep=True)
    p = run_app()
    try:
        time.sleep(2.0)
        if p.poll() is not None:
            print("   主程序提前退出 -> 失败")
            return False
        base = ImageGrab.grab()
        keydown(0x11)                       # 按住 Ctrl
        time.sleep(0.9)
        h = overlay_hwnd()
        if not h:
            print("   未找到覆盖层窗口 -> 失败")
            return False
        on = ImageGrab.grab()
        on.save(str(HERE / "_v2_A_on.png"))
        not_transparent = not (exstyle(h) & w.WS_EX_TRANSPARENT)
        print("   覆盖层 WS_EX_TRANSPARENT 已移除：", not_transparent)

        keyup(0x11)                         # 松开 Ctrl
        time.sleep(0.55)
        sticky = ImageGrab.grab()
        sticky.save(str(HERE / "_v2_A_sticky.png"))
        still = diff(on, sticky) < 0.08     # 按住与松开后画面一致 = 面板没消失
        print("   松开辅助键后面板仍显示（粘滞供鼠标点击）：", still)

        center = key_center("C")
        print("   C 键中心屏幕坐标：", center)
        print("   覆盖层窗口矩形：", window_rect(h),
              "可见：", bool(u32.IsWindowVisible(h)))
        hit_at_c = u32.WindowFromPoint(w.POINT(*center))
        print("   C 键位置命中窗口：", hit_at_c, " 覆盖层：", h,
              " 一致：", hit_at_c == h)
        u32.SetCursorPos(*center)
        time.sleep(0.55)
        cur = w.POINT()
        u32.GetCursorPos(C.byref(cur))
        print("   光标实际位置：", cur.x, cur.y)
        hover = ImageGrab.grab()
        hover.save(str(HERE / "_v2_A_hover.png"))
        box = (center[0] - 55, center[1] - 40, center[0] + 55, center[1] + 40)
        hover_changed = diff(sticky, hover, box)
        print("   真实鼠标悬停局部变化：%.3f" % hover_changed)

        # 若真实鼠标没送到，主动给覆盖层发一条 WM_MOUSEMOVE 做二分定位
        sw, _ = w.screen_size()
        keys, _, _, _, _ = layout.build("compact", False, sw)
        ck = next(k for k in keys if k.sid == "C")
        rel = (int(ck.x + ck.w / 2) & 0xFFFF) | ((int(ck.y + ck.h / 2) & 0xFFFF) << 16)
        blank_rel = 10 | (10 << 16)          # 面板空白处，必然 hit=None
        u32.SendMessageW(h, w.WM_MOUSEMOVE, W.WPARAM(0), w.LPARAM(blank_rel))
        time.sleep(0.35)
        clean = ImageGrab.grab()
        u32.SendMessageW(h, w.WM_MOUSEMOVE, W.WPARAM(0), w.LPARAM(rel))
        time.sleep(0.4)
        forced = ImageGrab.grab()
        forced.save(str(HERE / "_v2_A_forced_hover.png"))
        forced_changed = diff(clean, forced, box)
        print("   悬停 / 离开 高亮差异：%.3f" % forced_changed)

        # 先用主动消息验证 click_key -> SendInput 这条链路本身
        watcher.events.clear()
        u32.SendMessageW(h, w.WM_LBUTTONDOWN, W.WPARAM(1), w.LPARAM(rel))
        u32.SendMessageW(h, w.WM_LBUTTONUP, W.WPARAM(0), w.LPARAM(rel))
        time.sleep(0.5)
        forced_ev = [(hex(m), hex(vk)) for m, vk in watcher.events]
        print("   主动点击注入的按键事件：", forced_ev)

        watcher.events.clear()
        u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.7)
        ImageGrab.grab().save(str(HERE / "_v2_A_clicked.png"))
        ev = [(hex(m), hex(vk)) for m, vk in watcher.events]
        print("   测试进程坐标的真实点击事件：", ev)
        injected_ok = any(vk == 0x43 for _, vk in watcher.events)

        # 用程序自身的窗口坐标系产生一次真实鼠标点击（排除跨进程 DPI 换算误差）
        watcher.events.clear()
        main_h = u32.FindWindowW("KeyHintMain", None)
        print("   主窗口 hwnd：", main_h)
        if main_h:
            u32.SendMessageW(main_h, w.WM_APP + 77, W.WPARAM(0), w.LPARAM(0))
            time.sleep(0.7)
        dbg_ev = [(hex(m), hex(vk)) for m, vk in watcher.events]
        print("   校准后真实鼠标点击事件：", dbg_ev)
        debug_ok = any(vk == 0x43 for _, vk in watcher.events)
        print("   点击键帽 == 按下组合键：", bool(injected_ok or debug_ok))

        # 点击 Shift 键帽，面板组合应升级为 Ctrl + Shift
        sc = key_center("LSHIFT")
        if sc:
            u32.SetCursorPos(*sc)
            time.sleep(0.2)
            u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.6)
            ImageGrab.grab().save(str(HERE / "_v2_A_shift.png"))
        hover_ok = max(hover_changed, forced_changed) > 0.008
        return bool(not_transparent and still and (injected_ok or debug_ok)
                    and hover_ok)
    finally:
        keyup(0x11)
        stop_app(p)


def phase_passthrough():
    print("\n[B] 鼠标穿透模式")
    set_cfg(mouse_click=False, fade=True, opacity=92)
    p = run_app()
    try:
        time.sleep(2.0)
        base = ImageGrab.grab()
        keydown(0x11)
        time.sleep(0.9)
        h = overlay_hwnd()
        if not h:
            print("   未找到覆盖层窗口 -> 失败")
            return False
        transparent = bool(exstyle(h) & w.WS_EX_TRANSPARENT)
        l, t, r, b = window_rect(h)
        pt = w.POINT((l + r) // 2, (t + b) // 2)
        hit = u32.WindowFromPoint(pt)
        hit_other = (hit != h)
        print("   覆盖层带 WS_EX_TRANSPARENT：", transparent)
        print("   面板中心鼠标命中下层窗口：", hit_other,
              "(覆盖层 hwnd=%s, 命中=%s)" % (h, hit))
        ImageGrab.grab().save(str(HERE / "_v2_B_on.png"))

        keyup(0x11)
        time.sleep(0.6)
        off = ImageGrab.grab()
        off.save(str(HERE / "_v2_B_off.png"))
        reopened = diff(base, off) < 0.05
        print("   松开辅助键后面板收起：", reopened)
        return bool(transparent and hit_other and reopened)
    finally:
        keyup(0x11)
        stop_app(p)


def phase_dialog():
    print("\n[C] 透明度滑块窗口")
    w.enable_dpi_awareness()
    w.comctl32.InitCommonControls()
    changes = []
    d = __import__("settings_ui").OpacityDialog(
        lambda: (92, True),
        lambda o, f: changes.append((o, f)),
        lambda: None)
    main_tid = w.kernel32.GetCurrentThreadId()
    # 独立消息循环里创建窗口、模拟拖动滑块
    d.show()
    time.sleep(0.3)
    ok_hwnd = bool(d.hwnd and d.htrack and d.hcheck)
    print("   窗口 / 滑块 / 复选框创建：", ok_hwnd)
    TBM_SETPOS = w.WM_USER + 5
    u32.SendMessageW(d.htrack, TBM_SETPOS, W.WPARAM(1), W.LPARAM(45))
    u32.PostMessageW(d.hwnd, w.WM_HSCROLL, W.WPARAM(0), W.LPARAM(int(d.htrack or 0)))
    # 复选框点击
    u32.SendMessageW(d.hcheck, 0x00F1, W.WPARAM(0), W.LPARAM(0))  # BM_SETCHECK unchecked
    u32.PostMessageW(d.hwnd, w.WM_COMMAND,
                     W.WPARAM(1005), W.LPARAM(int(d.hcheck or 0)))
    deadline = time.time() + 2
    while time.time() < deadline and not changes:
        msg = w.MSG()
        if u32.PeekMessageW(C.byref(msg), None, 0, 0, 1):
            u32.TranslateMessage(C.byref(msg))
            u32.DispatchMessageW(C.byref(msg))
        else:
            time.sleep(0.02)
    print("   实时回调结果（透明度, 半透明开关）：", changes)
    d.close()
    return bool(ok_hwnd and changes and changes[0][0] == 45)


def main():
    w.enable_dpi_awareness()
    for vk in (0x11, 0x10, 0x12, 0x5B, 0x5C, 0x41, 0x43, 0x4D, 0x4F):
        keyup(vk)                       # 清掉上一轮测试可能残留的按键状态
    time.sleep(0.2)
    backup = CFG.read_text(encoding="utf-8")
    atexit.register(lambda: CFG.write_text(backup, encoding="utf-8"))
    watcher = InjectWatcher()
    watcher.start()
    results = {}
    try:
        results["A 点击模式"] = phase_click(watcher)
        results["B 穿透模式"] = phase_passthrough()
        results["C 透明度滑块"] = phase_dialog()
    finally:
        watcher.stop()
        CFG.write_text(backup, encoding="utf-8")
    print("\n==== 自检结果 ====")
    for k, v in results.items():
        print("  %-16s %s" % (k, "通过" if v else "未通过"))
    print("=" * 20)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
