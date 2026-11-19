# -*- coding: utf-8 -*-
"""安装包端到端演练：静默安装 → 校验全部产物 → GUI 向导可启动 → 静默卸载 → 校验清理。

测试在独立的 build/installtest 目录进行，不碰用户已有的常驻实例；
测试前后会备份 / 恢复桌面同名快捷方式与开机自启注册表值。
"""
from __future__ import annotations

import base64
import ctypes as C
import os
import shutil
import subprocess
import sys
import time
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETUP = ROOT / "安装包" / "指点江山_Setup_4.12.exe"
TESTDIR = ROOT / "build" / "installtest"
LOG = Path(os.environ.get("TEMP", ".")) / "keyhint_setup.log"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINST_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ZhiDianJiangShan"

ok = True


def check(name, cond, extra=""):
    global ok
    print("%s  %s %s" % ("[PASS]" if cond else "[FAIL]", name, extra))
    if not cond:
        ok = False


def desktop_dir():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            v, _ = winreg.QueryValueEx(k, "Desktop")
        p = Path(os.path.expandvars(v))
        if p.exists():
            return p
    except Exception:
        pass
    return Path.home() / "Desktop"


def start_dir():
    return (Path(os.environ.get("APPDATA", str(Path.home())))
            / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "指点江山")


def reg_value(key, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            v, _ = winreg.QueryValueEx(k, name)
            return v
    except FileNotFoundError:
        return None
    except Exception:
        return None


def key_exists(key):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def lnk_target(p):
    """用 WScript.Shell 反向读取 .lnk，验证快捷方式确实可用。"""
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
              "Write-Output $s.TargetPath" % str(p).replace("'", "''"))
    code = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                            "-EncodedCommand", code],
                           capture_output=True, timeout=20)
        return (r.stdout or b"").decode("utf-8", "replace").strip()
    except Exception:
        return ""


def run_setup(args, timeout=120):
    if LOG.exists():
        LOG.unlink()
    p = subprocess.run([str(SETUP)] + args, capture_output=True, timeout=timeout)
    tail = ""
    if LOG.exists():
        lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = " | ".join(lines[-3:])
    return p.returncode, tail


def gui_window_titles():
    found = []
    CB = C.WINFUNCTYPE(C.c_bool, C.c_void_p, C.c_void_p)
    u = C.windll.user32
    u.GetWindowTextW.argtypes = [C.c_void_p, C.c_wchar_p, C.c_int]
    u.GetWindowTextLengthW.argtypes = [C.c_void_p]

    def cb(hwnd, _):
        if u.IsWindowVisible(hwnd):
            n = u.GetWindowTextLengthW(hwnd)
            if n:
                buf = C.create_unicode_buffer(n + 1)
                u.GetWindowTextW(hwnd, buf, n + 1)
                t = buf.value
                # 只认安装 / 卸载向导自己的标题，排除资源管理器等含 指点江山 的窗口
                if t.startswith(("安装 ", "卸载 ")) and "指点江山" in t:
                    found.append(t)
        return True

    u.EnumWindows(CB(cb), 0)
    return found


def main():
    if not SETUP.exists():
        print("找不到安装器：" + str(SETUP))
        return 1

    # ---- 备份可能被本测试覆盖的用户数据 ----
    saved_run = reg_value(RUN_KEY, "指点江山")
    saved_lnks = {}
    for p in (desktop_dir() / "指点江山.lnk",
              start_dir() / "指点江山.lnk",
              start_dir() / "卸载 指点江山.lnk"):
        if p.exists():
            saved_lnks[p] = p.read_bytes()

    if TESTDIR.exists():
        shutil.rmtree(TESTDIR, ignore_errors=True)

    try:
        print("== 1/5 静默安装 ==")
        rc, tail = run_setup(["--silent", "--dir", str(TESTDIR),
                              "--no-launch", "--no-kill"])
        check("安装器返回 0", rc == 0, "rc=%s %s" % (rc, tail[:160]))

        print("== 2/5 安装产物 ==")
        exe = TESTDIR / "指点江山.exe"
        uninst = TESTDIR / "Uninstall.exe"
        check("主程序已释放", exe.exists())
        check("卸载程序已释放", uninst.exists())
        check("依赖目录完整", (TESTDIR / "_internal" / "python310.dll").exists()
              or (TESTDIR / "_internal" / "PIL").is_dir())
        check("图标与默认配置随包", (TESTDIR / "_internal" / "keyhint.ico").exists()
              and (TESTDIR / "_internal" / "config.default.json").exists())
        dlnk = desktop_dir() / "指点江山.lnk"
        slnk = start_dir() / "指点江山.lnk"
        ulnk = start_dir() / "卸载 指点江山.lnk"
        check("桌面快捷方式", dlnk.exists() and dlnk.stat().st_size > 0)
        check("开始菜单快捷方式", slnk.exists() and ulnk.exists())
        if dlnk.exists():
            tgt = lnk_target(dlnk)
            check("快捷方式可被系统正确解析", str(exe).lower() in tgt.lower(),
                  tgt or "(PowerShell 读取失败，仅校验文件存在)")
        check("注册表卸载项", key_exists(UNINST_KEY),
              str(reg_value(UNINST_KEY, "DisplayName")))
        check("安装位置登记正确",
              str(reg_value(UNINST_KEY, "InstallLocation")).rstrip("\\/").lower()
              == str(TESTDIR).rstrip("\\/").lower())
        check("开机自启已写入", str(exe).lower() in
              str(reg_value(RUN_KEY, "指点江山")).lower())

        print("== 3/5 图形化向导 ==")
        p = subprocess.Popen([str(SETUP)], cwd=str(SETUP.parent),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # 单文件包首次启动需解压 + 初始化 tkinter，轮询最多 15 秒
        titles, waited = [], 0
        for i in range(15):
            time.sleep(1)
            waited = i + 1
            titles = gui_window_titles()
            if titles:
                break
        alive = p.poll() is None
        check("安装向导窗口已显示", alive and len(titles) > 0,
              "等待=%ds 进程=%s 窗口=%s" % (waited, alive, titles[:2]))
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()

        print("== 4/5 静默卸载 ==")
        rc2, tail2 = run_setup(["--uninstall", "--silent", "--no-kill"], timeout=120)
        check("卸载器返回 0", rc2 == 0, "rc=%s %s" % (rc2, tail2[:160]))
        check("桌面快捷方式已移除", not dlnk.exists())
        check("开始菜单快捷方式已移除", not slnk.exists() and not ulnk.exists())
        check("注册表卸载项已移除", not key_exists(UNINST_KEY))

        print("== 5/5 程序目录延迟清理 ==")
        gone = False
        for _ in range(20):
            if not TESTDIR.exists():
                gone = True
                break
            time.sleep(1)
        check("安装目录自动删除", gone, str(TESTDIR))
    finally:
        # ---- 恢复用户原有状态 ----
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                    winreg.KEY_WRITE) as k:
                if saved_run is None:
                    try:
                        winreg.DeleteValue(k, "指点江山")
                    except FileNotFoundError:
                        pass
                else:
                    winreg.SetValueEx(k, "指点江山", 0, winreg.REG_SZ, saved_run)
            for p, data in saved_lnks.items():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
        except Exception as e:
            print("恢复用户数据失败：", e)
        if TESTDIR.exists():
            shutil.rmtree(TESTDIR, ignore_errors=True)
        # 清理测试期间可能残留的注册表卸载项
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINST_KEY)
        except Exception:
            pass

    print("\n结论：" + ("安装包可正常安装、运行并干净卸载" if ok else "存在失败项，请检查"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
