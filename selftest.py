# -*- coding: utf-8 -*-
"""
端到端自检：启动托盘主程序 -> 模拟按住 Ctrl -> 抓屏 -> 松开 -> 抓屏
用于验证全局键盘钩子、延迟唤起、分层窗口、自动收起整条链路。
    python selftest.py
"""
from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageGrab

HERE = Path(__file__).resolve().parent
CFG = HERE / "config.json"
u32 = ctypes.windll.user32
KEYEVENTF_KEYUP = 0x0002


def keydown(vk):
    u32.keybd_event(vk, 0, 0, 0)


def keyup(vk):
    u32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def diff_ratio(a: Image.Image, b: Image.Image) -> float:
    """粗略比较两图差异像素比例"""
    from PIL import ImageChops
    d = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
    hist = d.histogram()
    return sum(hist[24:]) / max(1, sum(hist))


def main():
    # 与「鼠标点击模式」解耦：本自检只验证默认的穿透行为
    backup = CFG.read_text(encoding="utf-8")
    cfg = json.loads(backup)
    cfg["mouse_click"] = False
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    p = subprocess.Popen([sys.executable, "-u", str(HERE / "app.py")],
                         cwd=str(HERE),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    try:
        time.sleep(2.0)
        if p.poll() is not None:
            print("主程序提前退出：", p.stdout.read())
            return 1
        base = ImageGrab.grab()
        base.save(str(HERE / "_selftest_base.png"))

        keydown(0x11)                     # VK_CONTROL
        time.sleep(0.9)                   # 等待延迟唤起 + 渲染
        on = ImageGrab.grab()
        on.save(str(HERE / "_selftest_on.png"))

        keydown(0x43)                     # 触发 Ctrl+C 的键帽闪光
        time.sleep(0.18)
        ImageGrab.grab().save(str(HERE / "_selftest_flash.png"))
        keyup(0x43)

        keyup(0x11)                       # 松开 Ctrl
        time.sleep(0.5)
        off = ImageGrab.grab()
        off.save(str(HERE / "_selftest_off.png"))

        r_on = diff_ratio(base, on)
        r_off = diff_ratio(on, off)
        print("按住 Ctrl 后屏幕变化比例: %.3f" % r_on)
        print("松开 Ctrl 后屏幕恢复差异: %.3f" % r_off)
        ok = r_on > 0.06 and r_off > 0.06
        print("端到端自检:" , "通过" if ok else "未通过（请查看 _selftest_*.png）")
        return 0 if ok else 1
    finally:
        try:
            keyup(0x11)
            keyup(0x43)
        except Exception:
            pass
        p.terminate()
        try:
            p.wait(timeout=3)
        except Exception:
            p.kill()
        try:
            out = p.stdout.read()
            if out:
                print("--- 主程序输出 ---")
                print(out.strip()[:2000])
        except Exception:
            pass
        CFG.write_text(backup, encoding="utf-8")   # 还原用户原本的配置


if __name__ == "__main__":
    sys.exit(main())
