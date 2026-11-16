# -*- coding: utf-8 -*-
"""
v3 端到端自检（请用装了 Pillow 的 Python 运行）：
  A. 穿透模式：按住 Ctrl 出现键盘 + 右上角控件条；松开立即全部消失
  B. 控件条窗口永不带 WS_EX_TRANSPARENT，且鼠标命中测试能命中自己
  C. 穿透模式下用真实鼠标点「键帽可点」开关 -> 立即切换、键盘改为可点击
  D. 点击模式松开 Ctrl 面板保留 -> 点 C 键真的注入 Ctrl+C
  E. 真实鼠标拖动右上角滑杆 -> 透明度变化并写盘；滚轮不再改变透明度
  F. 再次点开关关闭 -> 1.5s 宽限后自动收起，不残留粘滞面板

运行：  <带 Pillow 的 python> selftest_v3.py
输出：  _v3_*.png 截图；结束时自动恢复 config.json
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

from PIL import ImageChops, ImageGrab

import win32 as w

HERE = Path(__file__).resolve().parent
CFG = HERE / "config.json"
u32 = w.user32
KEYEVENTF_KEYUP = 0x0002
GWL_EXSTYLE = -20


def _sig(fn, args, ret=None):
    fn.argtypes, fn.restype = args, ret


_sig(u32.FindWindowW, [W.LPCWSTR, W.LPCWSTR], W.HWND)
_sig(u32.GetWindowRect, [W.HWND, C.POINTER(w.RECT)], W.BOOL)
_sig(u32.IsWindowVisible, [W.HWND], W.BOOL)
_sig(u32.keybd_event, [C.c_ubyte, C.c_ubyte, W.DWORD, C.c_size_t], None)


def keydown(vk):
    u32.keybd_event(vk, 0, 0, 0)


def keyup(vk):
    u32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def diff(a, b, box=None):
    if box:
        a, b = a.crop(box), b.crop(box)
    d = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
    h = d.histogram()
    return sum(h[24:]) / max(1, sum(h))


def exstyle(hwnd):
    return u32.GetWindowLongW(hwnd, GWL_EXSTYLE)


def rect(hwnd):
    r = w.RECT()
    u32.GetWindowRect(hwnd, C.byref(r))
    return r.left, r.top, r.right, r.bottom


def read_cfg():
    return json.loads(CFG.read_text(encoding="utf-8"))


def set_cfg(**kw):
    cfg = read_cfg()
    cfg.update(kw)
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def run_app():
    env = dict(os.environ)
    env["KEYHINT_DEBUG"] = "1"
    return subprocess.Popen([sys.executable, "-u", str(HERE / "app.py")],
                            cwd=str(HERE), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env,
                            encoding="utf-8", errors="replace")


def stop_app(p):
    keyup(0x11)
    if p.poll() is None:
        p.terminate()
    try:
        p.wait(timeout=3)
    except Exception:
        p.kill()
    try:
        out = p.stdout.read()
        if out and out.strip():
            print("   主程序输出：", out.strip()[:900])
    except Exception:
        pass


class InjectWatcher:
    """独立低级键盘钩子，捕获本程序注入（带 INJECT_MAGIC）的组合键"""

    def __init__(self):
        self.events = []
        self.tid = None
        self.hhook = 0
        self._cb = w.HOOKPROC(self._callback)
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
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(2.0)

    def stop(self):
        if self.tid:
            u32.PostThreadMessageW(self.tid, w.WM_QUIT, 0, 0)


def main():
    backup = CFG.read_text(encoding="utf-8")
    atexit.register(lambda: CFG.write_text(backup, encoding="utf-8"))

    w.enable_dpi_awareness()
    set_cfg(enabled=True, mouse_click=False, fade=True, opacity=80,
            click_keep=True, ui_grace_ms=1500, theme="light",
            wallpaper_theme=True, delay_ms=150)
    watcher = InjectWatcher()
    watcher.start()
    results = {}

    print("\n[A] 穿透模式：按住 Ctrl 出现 / 松开立即消失")
    p = run_app()
    try:
        time.sleep(2.0)
        base = ImageGrab.grab()
        keydown(0x11)
        time.sleep(0.9)
        kb_h = u32.FindWindowW("KeyHintOverlay", None)
        bar_h = u32.FindWindowW("KeyHintControlBar", None)
        main_h = u32.FindWindowW("KeyHintMain", None)
        on = ImageGrab.grab()
        on.save(str(HERE / "_v3_A_on.png"))
        print("   窗口 hwnd  键盘=%s 控件条=%s 主窗口=%s" % (kb_h, bar_h, main_h))
        if not (kb_h and bar_h and main_h):
            print("   缺少窗口 -> 失败")
            return
        appeared = diff(base, on) > 0.05
        print("   半透明键盘已出现：", appeared, " 屏幕变化 %.3f" % diff(base, on))

        kb_penetrable = bool(exstyle(kb_h) & w.WS_EX_TRANSPARENT)
        bar_penetrable = bool(exstyle(bar_h) & w.WS_EX_TRANSPARENT)
        print("   键盘窗口带 WS_EX_TRANSPARENT：", kb_penetrable)
        print("   控件条窗口带 WS_EX_TRANSPARENT：", bar_penetrable,
              "（应为 False）")

        kr, br = rect(kb_h), rect(bar_h)
        print("   键盘矩形：", kr, " 控件条矩形：", br)
        aligned = (br[3] <= kr[1] + 2 and br[2] <= kr[2] + 2
                   and br[2] >= kr[2] - 200)
        print("   控件条贴住键盘右上角且不压键帽：", aligned)
        cx, cy = (br[0] + br[2]) // 2, (br[1] + br[3]) // 2
        hit = u32.WindowFromPoint(w.POINT(cx, cy))
        bar_hit = bool(hit == bar_h)
        print("   穿透模式下鼠标命中控件条中心：", bar_hit,
              " (命中=%s 期望=%s)" % (hit, bar_h))

        keyup(0x11)
        time.sleep(0.55)
        off = ImageGrab.grab()
        off.save(str(HERE / "_v3_A_off.png"))
        gone = diff(base, off) < 0.04
        bar_hidden = not bool(u32.IsWindowVisible(bar_h))
        print("   松开 Ctrl 屏幕恢复基线：", gone, " 差异 %.3f" % diff(base, off))
        print("   控件条同步隐藏：", bar_hidden)
        results["A 松手即隐 + 控件条常驻可点"] = bool(
            appeared and kb_penetrable and not bar_penetrable
            and aligned and bar_hit and gone and bar_hidden)

        # ---------------------------------------------------------- B
        print("\n[B] 穿透模式下真实鼠标点「键帽可点」开关")
        keydown(0x11)
        time.sleep(0.8)
        before = ImageGrab.grab()
        br2 = rect(bar_h)
        sx, sy = br2[0] + 74, br2[1] + 22
        hit2 = u32.WindowFromPoint(w.POINT(sx, sy))
        print("   B 阶段：控件条矩形", br2, "可见", bool(u32.IsWindowVisible(bar_h)),
              "开关中心命中", hit2, "控件条", bar_h, "一致", hit2 == bar_h)
        u32.SendMessageW(main_h, w.WM_APP + 78, W.WPARAM(0), W.LPARAM(0))
        time.sleep(0.7)
        cfg = read_cfg()
        switched = bool(cfg.get("mouse_click"))
        kb_clickable = not bool(exstyle(kb_h) & w.WS_EX_TRANSPARENT)
        print("   点开关后 config.mouse_click =", switched,
              "；键盘窗口已去掉穿透：", kb_clickable)
        after = ImageGrab.grab()
        after.save(str(HERE / "_v3_B_switched.png"))
        results["B 右上角开关在穿透模式下可点"] = bool(switched and kb_clickable)

        # ---------------------------------------------------------- C
        print("\n[C] 点击模式：松 Ctrl 面板保留，点 C 键注入 Ctrl+C")
        keyup(0x11)
        time.sleep(0.6)
        sticky = ImageGrab.grab()
        sticky.save(str(HERE / "_v3_C_sticky.png"))
        stays = diff(after, sticky) < 0.10
        print("   松开 Ctrl 后面板保留（粘滞供点击）：", stays,
              " 差异 %.3f" % diff(after, sticky))
        watcher.events.clear()
        u32.SendMessageW(main_h, w.WM_APP + 77, W.WPARAM(0), W.LPARAM(0))
        time.sleep(0.7)
        ev = [(hex(m), hex(vk)) for m, vk in watcher.events]
        print("   点击 C 键注入的按键：", ev)
        injected = any(vk == 0x43 for _, vk in watcher.events)
        results["C 点击模式粘滞 + 键帽注入组合键"] = bool(stays and injected)

        # ---------------------------------------------------------- D
        print("\n[D] 拖动右上角滑杆 / 滚轮失效")
        op0 = read_cfg().get("opacity", 80)
        u32.SendMessageW(main_h, w.WM_APP + 79, W.WPARAM(0), W.LPARAM(300))
        time.sleep(0.7)
        op1 = read_cfg().get("opacity", 80)
        dragged = ImageGrab.grab()
        dragged.save(str(HERE / "_v3_D_slider.png"))
        print("   拖动滑杆 0.3 -> 透明度 %d%% -> %d%%" % (op0, op1))
        changed = abs(op1 - op0) > 20 and 30 <= op1 <= 45
        faded = diff(sticky, dragged, (342, 514, 1577, 1024)) > 0.015
        print("   滑杆生效且写盘：", changed, "；键盘浓淡变化：%.3f"
              % diff(sticky, dragged, (342, 514, 1577, 1024)))
        # 滚轮不应再改变透明度
        u32.SendMessageW(kb_h, w.WM_MOUSEWHEEL, W.WPARAM(120 << 16), W.LPARAM(0))
        time.sleep(0.45)
        op2 = read_cfg().get("opacity", 80)
        wheel_ignored = (op2 == op1)
        print("   滚轮后透明度仍为 %d%%（不操控）：" % op2, wheel_ignored)
        results["D 滑杆实时调节 + 滚轮不再调节"] = bool(changed and faded
                                                      and wheel_ignored)

        # ---------------------------------------------------------- E
        print("\n[E] 再点开关关闭 -> 恢复穿透且不残留面板")
        u32.SendMessageW(main_h, w.WM_APP + 78, W.WPARAM(0), W.LPARAM(0))
        time.sleep(0.6)
        cfg = read_cfg()
        off_state = not bool(cfg.get("mouse_click"))
        back_penetrable = bool(exstyle(kb_h) & w.WS_EX_TRANSPARENT)
        print("   开关已关闭：", off_state, " 键盘恢复穿透：", back_penetrable)
        time.sleep(2.0)                      # 等 1.5s 宽限到期
        cleared = ImageGrab.grab()
        cleared.save(str(HERE / "_v3_E_cleared.png"))
        recovered = diff(base, cleared) < 0.05
        print("   宽限到期后面板自动收起：", recovered,
              " 差异 %.3f" % diff(base, cleared))
        results["E 关闭开关后恢复穿透且自动收起"] = bool(
            off_state and back_penetrable and recovered)
    finally:
        stop_app(p)
        watcher.stop()

    print("\n================ 汇总 ================")
    for k, v in results.items():
        print(("  [PASS] " if v else "  [FAIL] ") + k)
    print("=====================================")
    return all(results.values()) and len(results) == 5


if __name__ == "__main__":
    ok = main()
    print("总结果：", "全部通过" if ok else "存在失败项")
    sys.exit(0 if ok else 1)
