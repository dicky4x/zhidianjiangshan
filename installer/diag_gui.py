# -*- coding: utf-8 -*-
"""诊断：安装器 GUI 窗口是否真的显示出来了。"""
import ctypes as C
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "安装包" / "KeyHint_Setup_4.0.exe"
u = C.windll.user32
CB = C.WINFUNCTYPE(C.c_bool, C.c_void_p, C.c_void_p)
u.GetWindowTextW.argtypes = [C.c_void_p, C.c_wchar_p, C.c_int]
u.GetWindowTextLengthW.argtypes = [C.c_void_p]
u.GetWindowThreadProcessId.argtypes = [C.c_void_p, C.POINTER(C.c_ulong)]


def windows():
    out = []
    def cb(h, _):
        if u.IsWindowVisible(h):
            n = u.GetWindowTextLengthW(h)
            if n:
                b = C.create_unicode_buffer(n + 1)
                u.GetWindowTextW(h, b, n + 1)
                pid = C.c_ulong()
                u.GetWindowThreadProcessId(h, C.byref(pid))
                out.append((pid.value, b.value))
        return True
    u.EnumWindows(CB(cb), 0)
    return out


p = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
print("父进程 PID =", p.pid)
for i in range(12):
    time.sleep(1)
    hits = [(pid, t) for pid, t in windows()
            if "KeyHint" in t or "安装" in t or "Setup" in t or "tk" in t.lower()]
    print("t+%2ds alive=%-5s %s" % (i + 1, p.poll() is None, hits[:5]))

try:
    from PIL import ImageGrab
    ImageGrab.grab().save(str(ROOT / "build" / "gui_diag.png"))
    print("截图 -> build/gui_diag.png")
except Exception as e:
    print("截图失败", e)

p.terminate()
try:
    p.wait(timeout=5)
except Exception:
    p.kill()
