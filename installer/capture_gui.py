# -*- coding: utf-8 -*-
"""截取最终安装向导窗口，作为交付预览图。"""
import ctypes as C
import subprocess
import time
from pathlib import Path
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "安装包" / "KeyHint_Setup_4.0.exe"
OUT = ROOT / "安装界面预览.png"

try:
    C.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    C.windll.user32.SetProcessDPIAware()

u = C.windll.user32
CB = C.WINFUNCTYPE(C.c_bool, C.c_void_p, C.c_void_p)
u.GetWindowTextW.argtypes = [C.c_void_p, C.c_wchar_p, C.c_int]
u.GetWindowTextLengthW.argtypes = [C.c_void_p]


class RECT(C.Structure):
    _fields_ = [("left", C.c_long), ("top", C.c_long),
                ("right", C.c_long), ("bottom", C.c_long)]


def find_wizard():
    found = []

    def cb(h, _):
        if u.IsWindowVisible(h):
            n = u.GetWindowTextLengthW(h)
            if n:
                b = C.create_unicode_buffer(n + 1)
                u.GetWindowTextW(h, b, n + 1)
                if b.value.startswith(("安装 ", "卸载 ")) and "KeyHint" in b.value:
                    found.append(h)
        return True

    u.EnumWindows(CB(cb), 0)
    return found[0] if found else None


p = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
hwnd = None
for i in range(16):
    time.sleep(1)
    hwnd = find_wizard()
    if hwnd:
        time.sleep(0.8)              # 等控件全部绘制完成
        print("窗口出现，用时 %d 秒" % (i + 1))
        break

if hwnd:
    r = RECT()
    u.GetWindowRect(hwnd, C.byref(r))
    box = (max(0, r.left - 6), max(0, r.top - 6), r.right + 6, r.bottom + 6)
    im = ImageGrab.grab(bbox=box, all_screens=True)
    im.save(str(OUT))
    print("已保存 %s  %dx%d" % (OUT, im.width, im.height))
else:
    print("未找到向导窗口")

p.terminate()
try:
    p.wait(timeout=5)
except Exception:
    p.kill()
