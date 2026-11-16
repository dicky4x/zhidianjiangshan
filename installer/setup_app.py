# -*- coding: utf-8 -*-
"""
KeyHint 安装 / 卸载程序（单文件、免管理员、绿色安装到用户目录）
================================================================
双击              图形化安装向导
--uninstall       卸载（图形确认）
--silent          静默安装（配合下面的开关，便于批量部署 / 自动测试）
--dir PATH        指定安装目录
--no-launch       装完不启动
--no-autostart    不写开机自启
--no-desktop      不建桌面快捷方式
--no-register     不写「应用和功能」卸载项
--no-kill         覆盖安装时不结束正在运行的 KeyHint
--purge-config    卸载时连同个人设置一起删除

安装内容：程序文件、桌面 / 开始菜单快捷方式、卸载入口、可选开机自启。
所有写入都在 HKCU 与用户目录，不需要 UAC 提权。
"""

from __future__ import annotations

import base64
import ctypes as C
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import winreg
import zipfile
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except Exception:                                    # 静默模式不依赖 GUI
    tk = None

APP_NAME = "KeyHint"
APP_TITLE = "KeyHint · 情境式指令提示"
VERSION = "4.07"
PUBLISHER = "KeyHint"
EXE_NAME = "KeyHint.exe"
UNINSTALLER_NAME = "Uninstall.exe"
UNINST_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\KeyHint"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "KeyHint"
CONFIG_DIR_NAME = "KeyHint"

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 基础路径
FROZEN = bool(getattr(sys, "frozen", False))
MEIPASS = Path(getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent)))


def payload_zip() -> Path:
    for p in (MEIPASS / "payload.zip",
              Path(__file__).resolve().parent / "payload.zip",
              Path(__file__).resolve().parent.parent / "build" / "payload.zip"):
        if p.exists():
            return p
    return MEIPASS / "payload.zip"


def icon_file() -> Path:
    for p in (MEIPASS / "keyhint.ico",
              Path(__file__).resolve().parent.parent / "keyhint.ico"):
        if p.exists():
            return p
    return MEIPASS / "keyhint.ico"


def default_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Programs", APP_NAME)


def desktop_dir() -> Path:
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        try:
            v, _ = winreg.QueryValueEx(k, "Desktop")
        finally:
            k.Close()
        p = Path(os.path.expandvars(v))
        if p.exists():
            return p
    except Exception:
        pass
    for p in (Path.home() / "Desktop", Path.home() / "桌面",
              Path(os.environ.get("USERPROFILE", "")) / "Desktop"):
        if p.exists():
            return p
    return Path.home() / "Desktop"


def start_menu_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME


def user_config_dir() -> Path:
    return Path(os.environ.get("APPDATA") or str(Path.home())) / CONFIG_DIR_NAME


def _no_window():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return si


# ---------------------------------------------------------------- 快捷方式 (COM)
class GUID(C.Structure):
    _fields_ = [("Data1", C.c_ulong), ("Data2", C.c_ushort),
                ("Data3", C.c_ushort), ("Data4", C.c_ubyte * 8)]


def _guid(text: str) -> GUID:
    g = GUID()
    ole = C.WinDLL("ole32")
    ole.IIDFromString.argtypes = [C.c_wchar_p, C.POINTER(GUID)]
    ole.IIDFromString(text, C.byref(g))
    return g


def _vcall(obj, index, restype, argtypes, *args):
    vtbl = C.cast(obj, C.POINTER(C.POINTER(C.c_void_p))).contents
    fn = C.WINFUNCTYPE(restype, C.c_void_p, *argtypes)(vtbl[index])
    return fn(obj, *args)


def _shortcut_com(lnk: Path, target: Path, workdir: Path,
                  args: str, icon: Path, desc: str) -> bool:
    ole = C.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [C.c_void_p, C.c_ulong]
    ole.CoInitializeEx(None, 2)                       # COINIT_APARTMENTTHREADED
    link = None
    persist = None
    try:
        CLSID_ShellLink = _guid("{00021401-0000-0000-C000-000000000046}")
        IID_IShellLinkW = _guid("{000214F9-0000-0000-C000-000000000046}")
        IID_IPersistFile = _guid("{0000010B-0000-0000-C000-000000000046}")
        ole.CoCreateInstance.argtypes = [C.POINTER(GUID), C.c_void_p, C.c_ulong,
                                         C.POINTER(GUID), C.POINTER(C.c_void_p)]
        ole.CoCreateInstance.restype = C.c_long
        p = C.c_void_p()
        hr = ole.CoCreateInstance(C.byref(CLSID_ShellLink), None, 1,
                                  C.byref(IID_IShellLinkW), C.byref(p))
        if hr != 0 or not p:
            return False
        link = p

        hres = C.c_long
        # IShellLinkW vtable: 7=SetDescription 9=SetWorkingDirectory
        # 11=SetArguments 15=SetShowCmd 17=SetIconLocation 20=SetPath
        _vcall(link, 20, hres, [C.c_wchar_p], str(target))
        _vcall(link, 9, hres, [C.c_wchar_p], str(workdir))
        if args:
            _vcall(link, 11, hres, [C.c_wchar_p], args)
        _vcall(link, 15, hres, [C.c_int], 1)         # SW_SHOWNORMAL
        if icon.exists():
            _vcall(link, 17, hres, [C.c_wchar_p, C.c_int], str(icon), 0)
        _vcall(link, 7, hres, [C.c_wchar_p], desc)

        pp = C.c_void_p()
        hr = _vcall(link, 0, hres,
                    [C.POINTER(GUID), C.POINTER(C.c_void_p)],
                    C.byref(IID_IPersistFile), C.byref(pp))
        if hr != 0 or not pp:
            return False
        persist = pp
        # IPersistFile::Save (vtable index 6)
        hr = _vcall(persist, 6, hres, [C.c_wchar_p, C.c_int], str(lnk), 1)
        return hr == 0
    except Exception as e:
        print("快捷方式 COM 失败：", e)
        return False
    finally:
        if persist:
            _vcall(persist, 2, C.c_ulong, [])
        if link:
            _vcall(link, 2, C.c_ulong, [])
        try:
            ole.CoUninitialize()
        except Exception:
            pass


def _shortcut_ps(lnk: Path, target: Path, workdir: Path,
                 args: str, icon: Path, desc: str) -> bool:
    """COM 不可用时的兜底：PowerShell + WScript.Shell"""
    def q(s):
        return "'" + str(s).replace("'", "''") + "'"
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut(%s);"
              "$s.TargetPath=%s;$s.WorkingDirectory=%s;$s.Arguments=%s;"
              "$s.IconLocation=%s;$s.Description=%s;$s.Save()" % (
                  q(lnk), q(target), q(workdir), q(args),
                  q(str(icon) + ",0"), q(desc)))
    code = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                            "-EncodedCommand", code],
                           startupinfo=_no_window(), timeout=25,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0 and lnk.exists()
    except Exception:
        return lnk.exists()


def create_shortcut(lnk: Path, target: Path, workdir: Path,
                    args: str = "", icon: Path = None, desc: str = APP_TITLE) -> bool:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    try:
        lnk.unlink()
    except Exception:
        pass
    icon = icon or target
    if _shortcut_com(lnk, target, workdir, args, icon, desc):
        return True
    return _shortcut_ps(lnk, target, workdir, args, icon, desc)


# ---------------------------------------------------------------- 注册表
def write_uninstall_entry(dest: Path):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINST_KEY, 0,
                            winreg.KEY_WRITE) as k:
        vals = {
            "DisplayName": "KeyHint · 情境式指令提示",
            "DisplayVersion": VERSION,
            "Publisher": PUBLISHER,
            "DisplayIcon": str(dest / EXE_NAME) + ",0",
            "InstallLocation": str(dest),
            "UninstallString": '"%s" --uninstall' % (dest / UNINSTALLER_NAME),
            "QuietUninstallString": '"%s" --uninstall --silent' % (dest / UNINSTALLER_NAME),
            "HelpLink": "https://github.com/dicky4x/KeyHint",
            "URLInfoAbout": "https://github.com/dicky4x/KeyHint",
            "NoModify": 1,
            "NoRepair": 1,
        }
        for name, value in vals.items():
            winreg.SetValueEx(k, name, 0,
                              winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ,
                              value)


def set_autostart(dest: Path, enabled: bool = True):
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_WRITE) as k:
            if enabled:
                winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ,
                                  '"%s"' % (dest / EXE_NAME))
            else:
                # 只删除确实指向 KeyHint 的值，避免误删用户其它自启项
                try:
                    v, _ = winreg.QueryValueEx(k, RUN_VALUE)
                    if "keyhint" in str(v).lower():
                        winreg.DeleteValue(k, RUN_VALUE)
                except FileNotFoundError:
                    pass
    except Exception as e:
        print("开机自启设置失败：", e)


def installed_dir() -> Path:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINST_KEY) as k:
            v, _ = winreg.QueryValueEx(k, "InstallLocation")
            if v and Path(v).exists():
                return Path(v)
    except Exception:
        pass
    return Path(sys.executable).resolve().parent if FROZEN else Path.cwd()


def delete_registry_entries():
    for key in (UNINST_KEY,):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except FileNotFoundError:
            pass
        except Exception as e:
            print("删除卸载项失败：", e)
    set_autostart(Path("."), False)


def remove_shortcuts():
    names = ["KeyHint.lnk", "卸载 KeyHint.lnk"]
    folders = [desktop_dir(), start_menu_dir()]
    for folder in folders:
        for n in names:
            try:
                (folder / n).unlink()
            except Exception:
                pass
    try:
        start_menu_dir().rmdir()
    except Exception:
        pass


# ---------------------------------------------------------------- 安装
def kill_running():
    try:
        subprocess.run(["taskkill", "/F", "/IM", EXE_NAME, "/T"],
                       startupinfo=_no_window(), timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.4)
    except Exception:
        pass


def do_install(opts: dict, progress) -> tuple[bool, str]:
    dest = Path(opts["dir"]).expanduser().resolve()
    payload = payload_zip()
    try:
        progress(3, "正在检查安装环境...")
        if not payload.exists():
            return False, "找不到安装数据 payload.zip，安装包可能已损坏。"
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return False, "无法创建安装目录：%s" % e
        probe = dest / (".keyhint_write_test_%d" % os.getpid())
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except Exception as e:
            return False, "安装目录不可写，请换一个位置：%s" % e

        if opts.get("kill", True):
            kill_running()

        progress(10, "正在释放程序文件...")
        old_internal = dest / "_internal"
        if old_internal.exists():
            try:
                shutil.rmtree(old_internal)
            except Exception:
                pass
        with zipfile.ZipFile(payload) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            total = max(1, len(names))
            for i, n in enumerate(names):
                z.extract(n, dest)
                if i % 4 == 0 or i == total - 1:
                    progress(10 + int(58 * (i + 1) / total),
                             "正在释放  %s" % n.split("/")[-1][:44])
        exe = dest / EXE_NAME
        if not exe.exists():
            return False, "安装数据不完整，缺少 %s。" % EXE_NAME

        # 卸载入口：把安装器自身复制一份，带 --uninstall 参数运行
        progress(72, "正在创建卸载入口...")
        if FROZEN:
            try:
                shutil.copy2(sys.executable, dest / UNINSTALLER_NAME)
            except Exception as e:
                print("复制卸载程序失败：", e)

        progress(78, "正在创建快捷方式...")
        ico = icon_file()
        create_shortcut(start_menu_dir() / "KeyHint.lnk", exe, dest,
                        icon=ico, desc=APP_TITLE)
        create_shortcut(start_menu_dir() / "卸载 KeyHint.lnk",
                        dest / UNINSTALLER_NAME, dest, args="--uninstall",
                        icon=ico, desc="卸载 KeyHint")
        desktop_ok = True
        if opts.get("desktop", True):
            desktop_ok = create_shortcut(desktop_dir() / "KeyHint.lnk",
                                         exe, dest, icon=ico, desc=APP_TITLE)

        progress(90, "正在写入安装信息...")
        if opts.get("register", True):
            write_uninstall_entry(dest)
        set_autostart(dest, bool(opts.get("autostart", True)))

        progress(97, "正在完成...")
        if opts.get("launch", True):
            try:
                subprocess.Popen([str(exe)], cwd=str(dest),
                                 creationflags=subprocess.DETACHED_PROCESS
                                 | subprocess.CREATE_NEW_PROCESS_GROUP,
                                 close_fds=True)
            except Exception as e:
                print("启动失败：", e)
        progress(100, "安装完成")
        note = "" if desktop_ok else "（桌面快捷方式创建失败，可从开始菜单启动）"
        return True, "安装完成！%s\n\n安装位置：%s\n按住 Ctrl / Shift / Alt / Win 即可呼出虚拟键盘。" % (note, dest)
    except Exception as e:
        return False, "安装失败：%s" % e


# ---------------------------------------------------------------- 卸载
def _delayed_remove(dest: Path, purge_config: bool):
    """卸载器自身位于 dest 内，无法自删；交给临时批处理在退出后清理。"""
    cfg = user_config_dir()
    lines = [
        "@echo off",
        "chcp 936 >nul",
        'set "D=%s"' % dest,
        'set "C=%s"' % cfg,
        "set /a n=0",
        ":again",
        "ping -n 2 127.0.0.1 >nul",
        'rmdir /s /q "%D%" 2>nul',
        'if not exist "%D%" goto done',
        "set /a n+=1",
        "if %n% GEQ 25 goto done",
        "goto again",
        ":done",
    ]
    if purge_config:
        lines.append('rmdir /s /q "%C%" 2>nul')
    lines.append('del /f /q "%~f0" >nul 2>&1')
    bat = Path(os.environ.get("TEMP", os.path.expanduser("~"))) / (
        "_keyhint_uninstall_%d.bat" % os.getpid())
    try:
        bat.write_text("\r\n".join(lines) + "\r\n", encoding="gbk")
    except Exception:
        bat.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", errors="replace")
    try:
        subprocess.Popen(["cmd.exe", "/c", str(bat)],
                         creationflags=subprocess.DETACHED_PROCESS
                         | subprocess.CREATE_NEW_PROCESS_GROUP,
                         stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         close_fds=True)
    except Exception as e:
        print("延迟清理启动失败：", e)


def do_uninstall(opts: dict, progress) -> tuple[bool, str]:
    dest = installed_dir()
    try:
        progress(10, "正在结束 KeyHint...")
        if opts.get("kill", True):
            kill_running()
        progress(35, "正在移除快捷方式...")
        remove_shortcuts()
        progress(60, "正在清理安装信息...")
        delete_registry_entries()
        progress(85, "正在删除程序文件...")
        # 只删除本程序目录，避免误删用户选择的共享目录
        if (dest / EXE_NAME).exists():
            _delayed_remove(dest, bool(opts.get("purge_config", False)))
        else:
            for p in (dest / "KeyHint.lnk",):
                try:
                    p.unlink()
                except Exception:
                    pass
        progress(100, "卸载完成")
        msg = "KeyHint 已卸载。\n\n程序文件会在几秒内自动清理完毕。"
        msg += ("\n个人设置已一并删除。" if opts.get("purge_config")
                else "\n个人设置已保留在 %s，重新安装后可继续使用。" % user_config_dir())
        return True, msg
    except Exception as e:
        return False, "卸载失败：%s" % e


# ---------------------------------------------------------------- 参数
def parse_args(argv) -> tuple[str, dict]:
    opts = {
        "dir": default_dir(), "autostart": True, "desktop": True,
        "launch": True, "register": True, "kill": True,
        "silent": False, "purge_config": False,
    }
    mode = "install"
    i = 0
    while i < len(argv):
        a = argv[i].lower()
        if a == "--uninstall":
            mode = "uninstall"
        elif a == "--silent":
            opts["silent"] = True
        elif a == "--dir" and i + 1 < len(argv):
            i += 1
            opts["dir"] = argv[i]
        elif a == "--no-launch":
            opts["launch"] = False
        elif a == "--no-autostart":
            opts["autostart"] = False
        elif a == "--no-desktop":
            opts["desktop"] = False
        elif a == "--no-register":
            opts["register"] = False
        elif a == "--no-kill":
            opts["kill"] = False
        elif a == "--purge-config":
            opts["purge_config"] = True
        i += 1
    return mode, opts


# ---------------------------------------------------------------- 图形界面
class InstallerUI:
    def __init__(self, mode, opts):
        self.mode = mode
        self.opts = opts
        self.q = queue.Queue()
        self.running = False
        self.root = tk.Tk()
        self.root.title(("卸载 " if mode == "uninstall" else "安装 ") + APP_TITLE)
        self.root.resizable(False, False)
        try:
            ico = icon_file()
            if ico.exists():
                self.root.iconbitmap(str(ico))
        except Exception:
            pass
        try:
            C.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                C.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        self._build()
        w, h = 620, 470
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 2 - 30))

    @staticmethod
    def _check(parent, text, var):
        """用经典 Tk 复选控件：Windows 原生对勾，避免 ttk/clam 把勾画成叉。"""
        return tk.Checkbutton(parent, text=text, variable=var,
                              bg="#FFFFFF", fg="#1F2937",
                              activebackground="#FFFFFF", activeforeground="#1F2937",
                              selectcolor="#FFFFFF", bd=0, highlightthickness=0,
                              anchor="w", cursor="hand2",
                              font=("Microsoft YaHei UI", 10))

    def _build(self):
        F = ("Microsoft YaHei UI", 10)
        FB = ("Microsoft YaHei UI", 15, "bold")
        FS = ("Microsoft YaHei UI", 9)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background="#F5F7FB")
        style.configure("Card.TFrame", background="#FFFFFF")
        style.configure("TLabel", background="#FFFFFF", foreground="#1F2937", font=F)
        style.configure("Muted.TLabel", background="#FFFFFF", foreground="#6B7280", font=FS)
        style.configure("Head.TLabel", background="#FFFFFF", foreground="#111827", font=FB)
        style.configure("Bg.TLabel", background="#F5F7FB", foreground="#6B7280", font=FS)
        style.configure("TCheckbutton", background="#FFFFFF", foreground="#1F2937", font=F)
        style.configure("Accent.TButton", background="#2563EB", foreground="#FFFFFF",
                        borderwidth=0, padding=(20, 8), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton",
                  background=[("active", "#1D4ED8"), ("disabled", "#9DB9F0")])
        style.configure("TButton", padding=(14, 7), font=F)
        style.configure("TProgressbar", troughcolor="#E8EDF5", background="#2563EB",
                        borderwidth=0, thickness=8)

        outer = ttk.Frame(self.root, style="TFrame", padding=12)
        outer.pack(fill="both", expand=True)
        card = ttk.Frame(outer, style="Card.TFrame", padding=20)
        card.pack(fill="both", expand=True)

        head = ttk.Frame(card, style="Card.TFrame")
        head.pack(fill="x", pady=(0, 14))
        cv = tk.Canvas(head, width=46, height=46, bg="#FFFFFF", highlightthickness=0)
        cv.create_rectangle(2, 8, 44, 40, fill="#2563EB", outline="", width=0)
        for r in range(2):
            for c in range(4):
                x, y = 8 + c * 9, 15 + r * 11
                cv.create_rectangle(x, y, x + 6, y + 6, fill="#FFFFFF", outline="")
        cv.pack(side="left", padx=(0, 12))
        titles = ttk.Frame(head, style="Card.TFrame")
        titles.pack(side="left", fill="y")
        ttk.Label(titles, text=APP_TITLE, style="Head.TLabel").pack(anchor="w")
        ttk.Label(titles, text="版本 %s  ·  华为折叠屏「情境式指令提示」PC 移植版" % VERSION,
                  style="Muted.TLabel").pack(anchor="w", pady=(3, 0))

        sep = tk.Frame(card, height=1, bg="#E5EAF2")
        sep.pack(fill="x", pady=(0, 16))

        if self.mode == "uninstall":
            ttk.Label(card, text="确定要卸载 KeyHint 吗？",
                      style="Head.TLabel").pack(anchor="w")
            ttk.Label(card, text="将移除程序文件、快捷方式和开机自启项。",
                      style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
            ttk.Label(card, text="安装位置：%s" % installed_dir(),
                      style="Muted.TLabel", wraplength=540).pack(anchor="w", pady=(4, 0))
            self.purge = tk.BooleanVar(value=False)
            self._check(card, "同时删除我的个人设置（透明度、延时等）",
                        self.purge).pack(anchor="w", pady=(18, 0))
        else:
            ttk.Label(card, text="安装位置", style="TLabel").pack(anchor="w")
            row = ttk.Frame(card, style="Card.TFrame")
            row.pack(fill="x", pady=(6, 12))
            self.dirvar = tk.StringVar(value=self.opts["dir"])
            ent = ttk.Entry(row, textvariable=self.dirvar, font=F)
            ent.pack(side="left", fill="x", expand=True, ipady=4)
            ttk.Button(row, text="浏览…", command=self._browse).pack(side="left", padx=(8, 0))
            self.autostart = tk.BooleanVar(value=True)
            self.desktop = tk.BooleanVar(value=True)
            self.launch = tk.BooleanVar(value=True)
            self._check(card, "开机自动启动（推荐）",
                        self.autostart).pack(anchor="w", pady=2)
            self._check(card, "创建桌面快捷方式",
                        self.desktop).pack(anchor="w", pady=2)
            self._check(card, "安装完成后立即运行",
                        self.launch).pack(anchor="w", pady=2)

        self.status = tk.StringVar(value="准备就绪，点击下方按钮开始。")
        ttk.Label(card, textvariable=self.status, style="Muted.TLabel",
                  wraplength=545, justify="left").pack(anchor="w", pady=(16, 6))
        self.bar = ttk.Progressbar(card, mode="determinate", maximum=100)
        self.bar.pack(fill="x")

        btns = ttk.Frame(card, style="Card.TFrame")
        btns.pack(fill="x", pady=(16, 0))
        self.cancel = ttk.Button(btns, text="取消", command=self._cancel)
        self.cancel.pack(side="right")
        self.go = ttk.Button(btns, style="Accent.TButton",
                             text="卸载" if self.mode == "uninstall" else "立即安装",
                             command=self._start)
        self.go.pack(side="right", padx=(0, 10))
        hint = "无需管理员权限  ·  Windows 10 / 11 64 位  ·  支持「设置 → 应用」中卸载"
        ttk.Label(outer, text=hint, style="Bg.TLabel").pack(anchor="w", pady=(8, 0))

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.dirvar.get() or os.path.expanduser("~"))
        if d:
            self.dirvar.set(os.path.normpath(d))

    def _cancel(self):
        if self.running:
            return
        self.root.destroy()

    def _start(self):
        if self.running:
            return
        self.running = True
        self.go.configure(state="disabled")
        self.cancel.configure(state="disabled")
        self.bar["value"] = 0
        if self.mode == "uninstall":
            self.opts["purge_config"] = bool(self.purge.get())
        else:
            self.opts["dir"] = self.dirvar.get().strip() or default_dir()
            self.opts["autostart"] = bool(self.autostart.get())
            self.opts["desktop"] = bool(self.desktop.get())
            self.opts["launch"] = bool(self.launch.get())

        def work():
            def progress(pct, text):
                self.q.put(("progress", pct, text))
            try:
                fn = do_uninstall if self.mode == "uninstall" else do_install
                ok, msg = fn(self.opts, progress)
                self.q.put(("done", ok, msg))
            except Exception as e:
                self.q.put(("done", False, str(e)))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(80, self._poll)

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "progress":
                    self.bar["value"] = item[1]
                    self.status.set(item[2])
                else:
                    _, ok, msg = item
                    self.running = False
                    self.bar["value"] = 100 if ok else self.bar["value"]
                    self.status.set(msg.replace("\n", " "))
                    self.go.configure(text="完成", state="normal",
                                      command=self.root.destroy)
                    self.cancel.configure(text="关闭", state="normal",
                                          command=self.root.destroy)
                    if not ok:
                        messagebox.showerror("KeyHint", msg)
                    else:
                        messagebox.showinfo("KeyHint", msg)
                    return
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def run(self):
        self.root.mainloop()


def main():
    mode, opts = parse_args(sys.argv[1:])
    if opts["silent"] or tk is None:
        log = Path(os.environ.get("TEMP", os.path.expanduser("~"))) / "keyhint_setup.log"

        def emit(line):
            print(line)
            try:
                with open(log, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

        def progress(pct, text):
            emit("[%3d%%] %s" % (pct, text))
        fn = do_uninstall if mode == "uninstall" else do_install
        ok, msg = fn(opts, progress)
        emit(("成功：" if ok else "失败：") + msg)
        return 0 if ok else 1
    InstallerUI(mode, opts).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
