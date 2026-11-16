# -*- coding: utf-8 -*-
"""
v4 端到端自检（请用装了 Pillow 的 Python 运行）：
  A. hide_delay_ms=0 且「键帽可点」开启：松开 Ctrl 仍然立即消失（本版核心改动）
  B. 右上角延时胶囊点击循环：立即 -> 5s -> 10s -> 立即，写盘生效
  C. hide_delay_ms=5000：松手 0.8s 后面板仍在，5.8s 后自动消失
  D. 延时期间用鼠标点 C 键确实注入 Ctrl+C，且倒计时被重置（不会中途消失）
  E. hide_delay_ms=10000 时按 Esc 立即收起
  F. 自定义秒数窗口：解析 0 / 5 / 2.5 / 越界，真实窗口输入 2.5 -> 2500ms
  G. 回归：半透明开关、透明度滑杆仍工作，滚轮不再调透明度

运行：  <带 Pillow 的 python> selftest_v4.py
输出：  _v4_*.png 截图；结束时自动恢复 config.json
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
import settings_ui
import controlbar

HERE = Path(__file__).resolve().parent
CFG = HERE / "config.json"
u32 = w.user32
KEYEVENTF_KEYUP = 0x0002
GWL_EXSTYLE = -20

BASE = dict(enabled=True, mouse_click=False, fade=True, opacity=80,
            click_keep=True, ui_grace_ms=1500, hide_delay_ms=0,
            theme="light", wallpaper_theme=True, delay_ms=150)


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


def bar_track_point(bar_h, ratio):
    """控件条窗口是 WS_POPUP，客户区原点 == 窗口左上角，可直接按常量换算"""
    l, t, _, _ = rect(bar_h)
    lx = controlbar.TRACK_X0 + (controlbar.TRACK_X1 - controlbar.TRACK_X0) * ratio
    return int(l + lx), int(t + controlbar.TRACK_Y)


def bar_point(bar_h, which):
    l, t, _, _ = rect(bar_h)
    if which == "delay":
        p0, p1, p2, p3 = controlbar.DELAY_PILL
        lx, ly = (p0 + p2) / 2, (p1 + p3) / 2
    else:
        r = {"click": controlbar.R_CLICK, "fade": controlbar.R_FADE,
             "track": controlbar.R_TRACK}[which]
        lx, ly = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
    return int(l + lx), int(t + ly)


def click_bar(bar_h, which, settle=0.45):
    """分步真实鼠标点击，避免连发 mouse_event 的异步竞态"""
    x, y = bar_point(bar_h, which)
    u32.SetCursorPos(x, y)
    time.sleep(0.20)
    u32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.15)
    u32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(settle)


def read_cfg():
    return json.loads(CFG.read_text(encoding="utf-8"))


def set_cfg(**kw):
    cfg = dict(BASE)
    cfg.update(kw)
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def run_app(log):
    env = dict(os.environ)
    env["KEYHINT_DEBUG"] = "1"
    return subprocess.Popen([sys.executable, "-u", str(HERE / "app.py")],
                            cwd=str(HERE), stdout=log,
                            stderr=subprocess.STDOUT, env=env)


def stop_app(p, log=None):
    keyup(0x11)
    if p.poll() is None:
        p.terminate()
    try:
        p.wait(timeout=3)
    except Exception:
        p.kill()
    if log:
        try:
            log.close()
        except Exception:
            pass
    time.sleep(0.35)


def phase(name, cfg_kw, body, results, main_holder):
    print("\n[%s] %s" % (name.split()[0], name.split(" ", 1)[1]), flush=True)
    set_cfg(**cfg_kw)
    log = open(str(HERE / "_v4_app.log"), "w", encoding="utf-8", errors="replace")
    p = run_app(log)
    try:
        time.sleep(1.9)
        base = ImageGrab.grab()
        main = u32.FindWindowW("KeyHintMain", None)
        main_holder["h"] = main
        ok = bool(body(p, base, main))
    except Exception as e:
        print("   阶段异常：", e, flush=True)
        ok = False
    finally:
        stop_app(p, log)
    print("   -> %s" % ("PASS" if ok else "FAIL"), flush=True)
    results[name] = ok


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
    watcher = InjectWatcher()
    watcher.start()
    results = {}
    holder = {"h": None}

    # ---------------------------------------------------------------- A
    def body_a(p, base, main):
        kb = u32.FindWindowW("KeyHintOverlay", None)
        keydown(0x11)
        time.sleep(0.9)
        on = ImageGrab.grab()
        on.save(str(HERE / "_v4_A_on.png"))
        appeared = diff(base, on) > 0.05
        clickable = not bool(exstyle(kb) & w.WS_EX_TRANSPARENT)
        print("   键帽可点已开启（覆盖层不带穿透样式）：", clickable,
              "；键盘出现：", appeared, flush=True)
        keyup(0x11)
        time.sleep(0.55)
        off = ImageGrab.grab()
        off.save(str(HERE / "_v4_A_off.png"))
        gone = diff(base, off) < 0.045
        print("   松开 Ctrl 后立即消失：", gone,
              " 差异 %.3f" % diff(base, off), flush=True)
        return appeared and clickable and gone

    phase("A 点击模式 + 0 延时：松手即隐", dict(mouse_click=True, hide_delay_ms=0),
          body_a, results, holder)

    # ---------------------------------------------------------------- B
    def body_b(p, base, main):
        bar_h = u32.FindWindowW("KeyHintControlBar", None)
        keydown(0x11)
        time.sleep(0.9)
        seq = []
        for _ in range(3):
            click_bar(bar_h, "delay")
            seq.append(int(read_cfg().get("hide_delay_ms", -1)))
        ImageGrab.grab().save(str(HERE / "_v4_B_bar.png"))
        keyup(0x11)
        print("   点延时胶囊三次的档位序列：", seq,
              "（期望 [5000, 10000, 0]）", flush=True)
        return seq == [5000, 10000, 0]

    phase("B 控件条延时档位循环并写盘", dict(mouse_click=False, hide_delay_ms=0),
          body_b, results, holder)

    # ---------------------------------------------------------------- C
    def body_c(p, base, main):
        keydown(0x11)
        time.sleep(0.9)
        on = ImageGrab.grab()
        on.save(str(HERE / "_v4_C_on.png"))
        appeared = diff(base, on) > 0.05
        keyup(0x11)
        time.sleep(0.8)
        mid = ImageGrab.grab()
        mid.save(str(HERE / "_v4_C_mid.png"))
        stays = diff(base, mid) > 0.05
        time.sleep(5.0)
        end = ImageGrab.grab()
        end.save(str(HERE / "_v4_C_end.png"))
        gone = diff(base, end) < 0.045
        print("   松手 0.8s 后面板仍在：", stays,
              "；累计 5.8s 后自动消失：", gone,
              " 差异 %.3f" % diff(base, end), flush=True)
        return appeared and stays and gone

    phase("C 5 秒延时：到点自动消失", dict(mouse_click=False, hide_delay_ms=5000),
          body_c, results, holder)

    # ---------------------------------------------------------------- D
    def body_d(p, base, main):
        watcher.events.clear()
        keydown(0x11)
        time.sleep(0.9)
        keyup(0x11)
        time.sleep(1.6)
        u32.SendMessageW(main, w.WM_APP + 77, W.WPARAM(0), W.LPARAM(0))
        time.sleep(0.6)
        ev = [(hex(m), hex(vk)) for m, vk in watcher.events]
        injected = any(vk == 0x43 for _, vk in watcher.events)
        ImageGrab.grab().save(str(HERE / "_v4_D_click.png"))
        print("   点 C 键注入的按键：", ev, flush=True)
        time.sleep(1.9)                      # 距松手 4.1s > 3s，若未续期应已消失
        still = ImageGrab.grab()
        still.save(str(HERE / "_v4_D_still.png"))
        alive = diff(base, still) > 0.05
        time.sleep(3.4)                      # 从点击算 5.9s > 3s
        end = ImageGrab.grab()
        end.save(str(HERE / "_v4_D_end.png"))
        gone = diff(base, end) < 0.045
        print("   点击后面板续期仍在：", alive,
              "；最终自动消失：", gone, " 差异 %.3f" % diff(base, end), flush=True)
        return injected and alive and gone

    phase("D 延时期间点键帽注入并重新计时",
          dict(mouse_click=True, hide_delay_ms=3000),
          body_d, results, holder)

    # ---------------------------------------------------------------- E
    def body_e(p, base, main):
        keydown(0x11)
        time.sleep(0.9)
        keyup(0x11)
        time.sleep(0.6)
        mid = ImageGrab.grab()
        stays = diff(base, mid) > 0.05
        keydown(0x1B)
        keyup(0x1B)
        time.sleep(0.5)
        end = ImageGrab.grab()
        end.save(str(HERE / "_v4_E_esc.png"))
        gone = diff(base, end) < 0.045
        print("   延时中面板可见：", stays, "；按 Esc 立即收起：", gone,
              " 差异 %.3f" % diff(base, end), flush=True)
        return stays and gone

    phase("E 10 秒延时中按 Esc 立即收起",
          dict(mouse_click=False, hide_delay_ms=10000),
          body_e, results, holder)

    # ---------------------------------------------------------------- F
    print("\n[F] 自定义秒数窗口与解析", flush=True)
    parsed = [settings_ui.parse_delay(x)
              for x in ("0", "5", "2.5", "600", "601", "abc", "")]
    ok_parse = parsed == [0, 5000, 2500, 600000, None, None, None]
    print("   parse_delay 边界：", parsed, "->", ok_parse, flush=True)
    applied = []
    dlg = settings_ui.DelayDialog(lambda: 5000,
                                  lambda ms: applied.append(ms),
                                  lambda: None)
    try:
        w.comctl32.InitCommonControls()
        h = dlg.show()
        ok_win = bool(h and dlg.hedit)
        u32.SetWindowTextW(dlg.hedit, "2.5")
        u32.SendMessageW(h, w.WM_COMMAND,
                         W.WPARAM(settings_ui._IDC_DELAY_OK), W.LPARAM(0))
        time.sleep(0.3)
        ok_apply = applied == [2500]
        print("   窗口/输入框创建：", ok_win,
              "；输入 2.5 点确定回调：", applied, "->", ok_apply, flush=True)
    except Exception as e:
        print("   窗口异常：", e, flush=True)
        ok_win = ok_apply = False
    finally:
        try:
            dlg.close()
        except Exception:
            pass
    results["F 自定义秒数输入与边界"] = bool(ok_parse and ok_win and ok_apply)

    # ---------------------------------------------------------------- G
    def body_g(p, base, main):
        bar_h = u32.FindWindowW("KeyHintControlBar", None)
        keydown(0x11)
        time.sleep(0.9)
        op0 = read_cfg().get("opacity", 80)
        # 像真人一样分步拖动：移到滑块 -> 按下 -> 移动 -> 抬起
        x0, y0 = bar_track_point(bar_h, (op0 - 10) / 90.0)
        x1, y1 = bar_track_point(bar_h, 0.3)
        u32.SetCursorPos(x0, y0)
        time.sleep(0.25)
        u32.mouse_event(0x0002, 0, 0, 0, 0)     # LEFTDOWN
        time.sleep(0.25)
        u32.SetCursorPos(x1, y1)
        time.sleep(0.35)
        u32.mouse_event(0x0004, 0, 0, 0, 0)     # LEFTUP
        time.sleep(0.6)
        op1 = read_cfg().get("opacity", 80)
        dragged = abs(op1 - op0) > 20 and 30 <= op1 <= 45
        kb = u32.FindWindowW("KeyHintOverlay", None)
        u32.SendMessageW(kb, w.WM_MOUSEWHEEL, W.WPARAM(120 << 16), W.LPARAM(0))
        time.sleep(0.4)
        op2 = read_cfg().get("opacity", 80)
        wheel_ignored = op2 == op1
        click_bar(bar_h, "fade")
        fade_off = not bool(read_cfg().get("fade", True))
        keyup(0x11)
        print("   滑杆 %d%% -> %d%%：" % (op0, op1), dragged,
              "；滚轮不调透明度：", wheel_ignored,
              "；半透明开关可切：", fade_off, flush=True)
        return dragged and wheel_ignored and fade_off

    phase("G 旧控件回归：滑杆 / 滚轮 / 半透明开关",
          dict(mouse_click=False, hide_delay_ms=0),
          body_g, results, holder)

    watcher.stop()
    print("\n================ 汇总 ================", flush=True)
    for k, v in results.items():
        print(("  [PASS] " if v else "  [FAIL] ") + k, flush=True)
    print("=====================================", flush=True)
    return all(results.values()) and len(results) == 7


if __name__ == "__main__":
    ok = main()
    print("总结果：", "全部通过" if ok else "存在失败项", flush=True)
    sys.exit(0 if ok else 1)
