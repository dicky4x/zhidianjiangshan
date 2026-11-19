# -*- coding: utf-8 -*-
"""
一键产出交付物：
  安装包/指点江山_Setup_4.12.exe   —— 单文件图形化安装程序（拷到另一台电脑双击即可）
  安装包/指点江山_绿色版_4.12.zip  —— 免安装备用（解压后直接运行 指点江山.exe）
  安装包/SHA256.txt

前置：先跑 KeyHint.spec（或 build_app 命令）产出 build/dist/指点江山/
用法：python installer/build.py
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
APP_DIR = BUILD / "dist" / "指点江山"
PAYLOAD = BUILD / "payload.zip"
OUT_DIR = ROOT / "安装包"
SETUP_EXE_NAME = "指点江山_Setup_4.12.exe"
PORTABLE_NAME = "指点江山_绿色版_4.12.zip"


def make_payload():
    if not (APP_DIR / "指点江山.exe").exists():
        raise SystemExit("找不到 %s，请先构建主程序。" % (APP_DIR / "指点江山.exe"))
    BUILD.mkdir(parents=True, exist_ok=True)
    if PAYLOAD.exists():
        PAYLOAD.unlink()
    n = 0
    with zipfile.ZipFile(PAYLOAD, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(APP_DIR.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(APP_DIR).as_posix())
                n += 1
    print("payload.zip: %d 个文件, %.1f MB" % (n, PAYLOAD.stat().st_size / 1048576))


def make_setup():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--noconsole",
        "--name", "指点江山_Setup", "--icon", str(ROOT / "keyhint.ico"),
        "--distpath", str(BUILD / "setup"),
        "--workpath", str(BUILD / "work_setup"),
        # 生成的临时 spec 放到 build/，避免覆盖 installer/ 下手工维护的
        # 相对路径 spec（PyInstaller 按命令行生成的 spec 会写死本机绝对路径）
        "--specpath", str(BUILD / "spec"),
        "--add-data", "%s;." % PAYLOAD,
        "--add-data", "%s;." % (ROOT / "keyhint.ico"),
        str(ROOT / "installer" / "setup_app.py"),
    ]
    print("构建安装器…")
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    src = BUILD / "setup" / "指点江山_Setup.exe"
    dst = OUT_DIR / SETUP_EXE_NAME
    if dst.exists():
        dst.unlink()
    src.replace(dst)
    print("安装器: %s (%.1f MB)" % (dst, dst.stat().st_size / 1048576))


def make_portable():
    dst = OUT_DIR / PORTABLE_NAME
    if dst.exists():
        dst.unlink()
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(APP_DIR.rglob("*")):
            if p.is_file():
                z.write(p, ("指点江山/" + p.relative_to(APP_DIR).as_posix()))
        z.writestr("指点江山/双击运行说明.txt",
                   "解压后双击 指点江山.exe 即可运行，无需安装、无需 Python。\n"
                   "程序会在系统托盘驻留，按住 Ctrl / Shift / Alt / Win 呼出虚拟键盘。\n"
                   "配置保存在 %APPDATA%\\指点江山\\config.json。\n")
    print("绿色版: %s (%.1f MB)" % (dst, dst.stat().st_size / 1048576))


def checksums():
    lines = []
    for p in sorted(OUT_DIR.glob("*")):
        if p.is_file() and p.name != "SHA256.txt":
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            lines.append("%s  %s" % (h, p.name))
            print("SHA256 %-34s %s" % (p.name, h[:16] + "…"))
    (OUT_DIR / "SHA256.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    make_payload()
    make_setup()
    make_portable()
    checksums()
    print("\n完成，交付目录：" + str(OUT_DIR))
