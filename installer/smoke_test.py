# -*- coding: utf-8 -*-
"""打包产物烟测：验证 KeyHint.exe 脱离源码 / 脱离本机 Python 能独立运行。

1) --demo --shot：验证分层窗口、Pillow、字体、图标、控件条渲染
2) 常驻启动：验证托盘 + 全局钩子 + 用户配置初始化
3) 检查 %APPDATA%\\KeyHint\\config.json 由安装版自动创建
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "build" / "dist" / "KeyHint" / "KeyHint.exe"
CFG = Path(os.environ.get("APPDATA", "")) / "KeyHint" / "config.json"
SHOT = CFG.parent / "_screen_check.png"

ok = True


def check(name, cond, extra=""):
    global ok
    print("%s  %s %s" % ("[PASS]" if cond else "[FAIL]", name, extra))
    if not cond:
        ok = False


def run(args, wait, timeout=None):
    p = subprocess.Popen([str(EXE)] + args, cwd=str(EXE.parent),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        p.wait(timeout=timeout or (wait + 20))
        return p.returncode, (p.stdout.read() or b"").decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        p.kill()
        return -99, "timeout"


def main():
    if not EXE.exists():
        print("找不到 " + str(EXE))
        return 1

    saved = None
    if CFG.exists():
        saved = CFG.read_bytes()
        CFG.unlink()
    if SHOT.exists():
        SHOT.unlink()

    print("== 1/3 渲染演示（--demo --shot）==")
    rc, out = run(["--demo", "--shot", "--seconds", "3"], 5, timeout=25)
    check("演示模式正常退出", rc == 0, "rc=%s" % rc)
    check("真实屏幕截图已生成", SHOT.exists(),
          str(SHOT) if SHOT.exists() else "")
    if SHOT.exists():
        from PIL import Image
        with Image.open(SHOT) as im:
            check("截图分辨率有效", im.width > 800 and im.height > 500,
                  "%dx%d" % (im.width, im.height))
    if out.strip():
        print("   输出:", out.strip()[:300])

    print("== 2/3 常驻托盘启动 ==")
    p = subprocess.Popen([str(EXE)], cwd=str(EXE.parent),
                         creationflags=subprocess.DETACHED_PROCESS,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3.5)
    check("进程持续存活（钩子/托盘无异常）", p.poll() is None,
          "poll=%s" % p.poll())
    check("用户配置自动初始化到 %APPDATA%", CFG.exists(), str(CFG))
    if CFG.exists():
        import json
        try:
            cfg = json.loads(CFG.read_text(encoding="utf-8"))
            check("配置内容完整", "hide_delay_ms" in cfg and "mouse_click" in cfg,
                  "共 %d 项" % len(cfg))
        except Exception as e:
            check("配置可解析", False, str(e))
    p.terminate()
    try:
        p.wait(timeout=5)
    except Exception:
        p.kill()
    print("   已结束测试实例")

    print("== 3/3 清理 ==")
    if CFG.exists():
        CFG.unlink()
    if saved is not None:
        CFG.write_bytes(saved)
    print("\n结论：" + ("打包版可独立运行" if ok else "存在失败项，请检查"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
