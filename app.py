# -*- coding: utf-8 -*-
"""
指点江山 · 情境式指令提示（PC 移植版）
=====================================
把 HUAWEI MateBook Fold 虚拟键盘的「长按辅助键 -> 全键盘亮起可用组合键并显示指令」
搬到任意 Windows 电脑上：一个常驻系统托盘的小插件，按住 Ctrl / Shift / Alt / Win
即在屏幕上浮出半透明全尺寸键盘，可用组合键同时高亮，显示图标 + 功能文字。

运行：  python app.py                 常驻托盘
       python app.py --demo          演示 10 秒（不挂钩子）
       python app.py --demo --combo Ctrl+Shift --app vscode --seconds 8
       python app.py --off           启动后默认停用

依赖：Python 3.8+ / Pillow（其余全部使用标准库与 Win32 API）
"""

from __future__ import annotations

import copy
import ctypes as C
import json
import os
import sys
import threading
import winsound
import winreg
from pathlib import Path

from PIL import Image, ImageDraw

import win32 as w
import render
import shortcuts
import layout
import settings_ui
import controlbar
from layout import canonical

# ---------------------------------------------------------------- 应用标识
APP_NAME = "指点江山"
APP_VERSION = "4.12"

# v4.10：Unicode 专用上标字符 → 普通半角字符映射。
# WPS/Word 里这些专用字符会 fallback 到全角字体、占位很大；检测到 Office 时
# 改用「普通字符 + 真上标格式」（Ctrl+Shift+=）输入，显示与排版都正常。
_SUPER_TO_PLAIN = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "⁺": "+", "⁻": "-", "⁼": "=", "⁽": "(", "⁾": ")",
}
_OFFICE_EXES = ("wps", "winword", "word.exe", "et.exe", "wpp",
                "excel", "powerpnt", "soffice", "swriter", "scalc")

# ---------------------------------------------------------------- 运行路径
# 源码运行时：所有文件都在脚本目录。
# 打包成安装版后：程序安装在用户目录（可能是只读的 Program Files），
# 配置必须放到 %APPDATA%\指点江山，否则托盘里的设置无法保存。
IS_FROZEN = bool(getattr(sys, "frozen", False))
if IS_FROZEN:
    BUNDLE_DIR = Path(sys.executable).resolve().parent
    RES_DIR = Path(getattr(sys, "_MEIPASS", str(BUNDLE_DIR)))
    _appdata = Path(os.environ.get("APPDATA") or str(BUNDLE_DIR))
    DATA_DIR = _appdata / APP_NAME
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # 从旧版 KeyHint 目录迁移配置，避免改名后丢失用户设置
        _old_dir = _appdata / "KeyHint"
        _new_cfg = DATA_DIR / "config.json"
        _old_cfg = _old_dir / "config.json"
        if _old_cfg.exists() and not _new_cfg.exists():
            import shutil as _sh
            _sh.copy2(str(_old_cfg), str(_new_cfg))
    except Exception:
        DATA_DIR = BUNDLE_DIR
else:
    BUNDLE_DIR = Path(__file__).resolve().parent
    RES_DIR = BUNDLE_DIR
    DATA_DIR = BUNDLE_DIR


def _resource(name: str) -> Path:
    for base in (RES_DIR, BUNDLE_DIR):
        p = base / name
        if p.exists():
            return p
    return RES_DIR / name


HERE = DATA_DIR                      # 调试截图等临时输出
CONFIG_PATH = DATA_DIR / "config.json"
ICON_PATH = _resource("keyhint.ico")
README_PATH = _resource("README.md")
DEFAULT_CONFIG_PATH = _resource("config.default.json")

# --noconsole 打包后 sys.stdout / sys.stderr 为 None，兜底避免 print 报错
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

DEFAULT_CONFIG = {
    "enabled": True,
    "delay_ms": 0,          # v4.04：默认立即弹出（0 = 同步弹出，无定时器粒度延迟）
    "opacity": 80,          # v4.09：默认背景透明度 80%（键帽始终不透明）
    "fade": True,           # 半透明显示总开关；False = 100% 不透明
    "mouse_click": True,    # v4.11：默认键帽可点，行为区四项默认全开
    "click_keep": True,     # 点击执行后保持面板（隐藏倒计时重新计时）
    "ui_grace_ms": 1500,    # 操作右上角控件时的最短保留时间
    "hide_delay_ms": 0,     # 松开辅助键后延时消失：0=立即，5000/10000=5/10 秒
    "layout": "compact",
    "narrow": False,
    "hint_mode": "icon",
    "theme": "dark",
    "wallpaper_theme": True,
    "position": "top",       # v4.11：默认停靠屏幕顶部
    "sound": True,           # v4.11：指令显示区默认全开
    "app_context": True,
    "show_lang": True,
    "modifiers": {"Ctrl": True, "Shift": True, "Alt": True, "Win": True},
    "custom_shortcuts": {},
    # v4.11：自定义快捷键面板（可创建多套、自定义名称；右键键帽编辑）
    "custom_panels": [{"name": "我的快捷键", "keys": {}}],
    "active_custom_panel": 0,
    "custom_active": False,
    # v4.01 新增
    "popup_enabled": True,      # False = 按住辅助键不再强制弹出虚拟键盘
    "toggle_hotkey": "Ctrl+Esc",  # 开启 / 关闭弹出的快捷开关，可自定义
    "kb_scale": 1.0,            # 键盘缩放倍率（v4.11：0.5 ~ 2.0）
    "kb_pos_x": None,           # 自定义左上角坐标；None = 沿用「停靠底部 / 居中」
    "kb_pos_y": None,
    # v4.02 新增
    "font_scale": 1.0,          # 键帽字体倍率（0.5 ~ 2.0；1.0 = v4.00 原始字号）
    # v4.04：已移除「自动避开光标」，位置 / 大小在键帽开关两态完全一致
    # v4.07：常驻任务栏 / 开机自启动
    # v4.08：默认关闭任务栏常驻按钮，仅保留系统托盘图标
    "taskbar_dock": False,      # True = 任务栏常驻按钮；False = 仅托盘显示（默认）
    "autostart": True,          # True = 写 HKCU Run，开机自启（安装器已写，这里做镜像）
}

# ---------------------------------------------------------------- VK -> 键位 id
OEM = {0xC0: "`", 0xBD: "-", 0xBB: "=", 0xDB: "[", 0xDD: "]", 0xDC: "\\",
       0xBA: ";", 0xDE: "'", 0xBC: ",", 0xBE: ".", 0xBF: "/"}
SPECIAL = {0x09: "TAB", 0x0D: "ENTER", 0x20: "SPACE", 0x08: "BACK",
           0x1B: "ESC", 0x2D: "INS", 0x2E: "DEL", 0x24: "HOME",
           0x23: "END", 0x21: "PGUP", 0x22: "PGDN", 0x25: "LEFT",
           0x26: "UP", 0x27: "RIGHT", 0x28: "DOWN", 0x2C: "PRTSC",
           0x91: "SCRLK", 0x13: "PAUSE", 0x90: "NUMLOCK", 0x5D: "MENU"}
NUMPAD = {0x6A: "N*", 0x6B: "N+", 0x6D: "N-", 0x6E: "N.", 0x6F: "N/"}


def vk_to_sid(vk: int) -> str:
    if 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x70 <= vk <= 0x7B:
        return "F%d" % (vk - 0x70 + 1)
    if 0x60 <= vk <= 0x69:
        return "N%d" % (vk - 0x60)
    return SPECIAL.get(vk, OEM.get(vk, NUMPAD.get(vk, "")))


MOD_VK = {"Ctrl": 0x11, "Shift": 0x10, "Alt": 0x12, "Win": 0x5B}
_SID_VK_EXTRA = {"CTRL": 0x11, "SHIFT": 0x10, "ALT": 0x12, "WIN": 0x5B,
                 "CAPS": 0x14, "NENT": 0x0D}
_SPECIAL_REV = {v: k for k, v in SPECIAL.items()}
_OEM_REV = {v: k for k, v in OEM.items()}
_NUMPAD_REV = {v: k for k, v in NUMPAD.items()}


def sid_to_vk(sid: str) -> int:
    """键位 id -> 虚拟键码，供「点击键帽 = 按下物理键」使用"""
    sid = canonical(str(sid).upper())
    if len(sid) == 1 and ("A" <= sid <= "Z" or "0" <= sid <= "9"):
        return ord(sid)
    if sid.startswith("F") and sid[1:].isdigit() and 1 <= int(sid[1:]) <= 12:
        return 0x6F + int(sid[1:])
    if len(sid) == 2 and sid[0] == "N" and sid[1].isdigit():
        return 0x60 + int(sid[1])
    return _SID_VK_EXTRA.get(sid,
                             _SPECIAL_REV.get(sid,
                                              _OEM_REV.get(sid,
                                                           _NUMPAD_REV.get(sid, 0))))


# ---------------------------------------------------------------- 配置
def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    # 安装版首次运行：把随程序分发的默认配置复制一份到用户配置目录
    if IS_FROZEN and not CONFIG_PATH.exists() and DEFAULT_CONFIG_PATH.exists():
        try:
            CONFIG_PATH.write_text(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"),
                                   encoding="utf-8")
        except Exception as e:
            print("初始化用户配置失败：", e)
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.update(raw)
            cfg["modifiers"] = {**DEFAULT_CONFIG["modifiers"], **(raw.get("modifiers") or {})}
        except Exception as e:
            print("config.json 读取失败，使用默认配置：", e)
    # v4.11：自定义面板结构容错，避免旧配置 / 手工编辑导致界面崩溃
    panels = cfg.get("custom_panels")
    if not isinstance(panels, list) or not panels:
        panels = [{"name": "我的快捷键", "keys": {}}]
    clean = []
    for p in panels:
        if not isinstance(p, dict):
            continue
        keys = p.get("keys")
        clean.append({"name": str(p.get("name") or "自定义面板"),
                      "keys": keys if isinstance(keys, dict) else {}})
    cfg["custom_panels"] = clean or [{"name": "我的快捷键", "keys": {}}]
    idx = cfg.get("active_custom_panel", 0)
    if not isinstance(idx, int) or not (0 <= idx < len(cfg["custom_panels"])):
        cfg["active_custom_panel"] = 0
    return cfg


def save_config(cfg: dict):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except Exception as e:
        print("config.json 写入失败：", e)


def ensure_icon() -> str:
    if ICON_PATH.exists():
        return str(ICON_PATH)
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((2, 10, 62, 52), 10, fill=(38, 106, 244, 255),
                        outline=(255, 255, 255, 230), width=2)
    for r in range(2):
        for c in range(5):
            x, y = 9 + c * 10, 19 + r * 13
            hot = (r == 1 and c in (0, 2, 4))
            d.rounded_rectangle((x, y, x + 7, y + 8), 2,
                                fill=(255, 255, 255, 245) if hot else (255, 255, 255, 90))
    im.save(str(ICON_PATH), sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    return str(ICON_PATH)


# ---------------------------------------------------------------- 菜单 ID
ID_ENABLE, ID_LOCK, ID_DEMO, ID_RELOAD, ID_OPENCFG, ID_ABOUT, ID_EXIT = 100, 101, 102, 103, 104, 105, 199
ID_SETTINGS = 108
ID_STYLE_COMPACT, ID_STYLE_FULL = 201, 202
ID_HINT_ICON, ID_HINT_TEXT = 211, 212
ID_MOD_CTRL, ID_MOD_SHIFT, ID_MOD_ALT, ID_MOD_WIN = 221, 222, 223, 224
ID_THEME_DARK, ID_THEME_LIGHT, ID_THEME_AUTO, ID_THEME_WALL = 231, 232, 233, 234
ID_OP_100, ID_OP_92, ID_OP_78, ID_OP_60, ID_OP_40 = 241, 242, 243, 244, 245
ID_POS_BOTTOM, ID_POS_CENTER = 251, 252
ID_NARROW, ID_CONTEXT, ID_SOUND, ID_LANG = 261, 262, 263, 264
ID_DELAY_0, ID_DELAY_150, ID_DELAY_300, ID_DELAY_500 = 271, 272, 273, 274
# 本次新增：半透明开关 / 实时滑块 / 鼠标点击穿透
ID_FADE, ID_MOUSE_CLICK, ID_CLICK_KEEP = 301, 302, 303
ID_OP_DIALOG, ID_OP_PLUS, ID_OP_MINUS = 304, 305, 306
# v4：松手后延时消失（不再区分点击/穿透模式，统一由倒计时控制）
ID_HIDE_0, ID_HIDE_3, ID_HIDE_5 = 311, 312, 313
ID_HIDE_10, ID_HIDE_15, ID_HIDE_30 = 314, 315, 316
ID_HIDE_CUSTOM = 317
HIDE_DELAY_MAP = {ID_HIDE_0: 0, ID_HIDE_3: 3000, ID_HIDE_5: 5000,
                  ID_HIDE_10: 10000, ID_HIDE_15: 15000, ID_HIDE_30: 30000}

# v4.01：弹出开关 / 键盘缩放菜单
ID_POPUP_ENABLE = 305
ID_HK_CTRL_ESC, ID_HK_CTRL_ALT_P, ID_HK_CTRL_ALT_K, ID_HK_CUSTOM = 401, 402, 403, 404
ID_KB_SCALE_80, ID_KB_SCALE_100, ID_KB_SCALE_125, ID_KB_SCALE_150, ID_KB_RESET = \
    411, 412, 413, 414, 415
HOTKEY_PRESETS = {ID_HK_CTRL_ESC: "Ctrl+Esc",
                  ID_HK_CTRL_ALT_P: "Ctrl+Alt+P",
                  ID_HK_CTRL_ALT_K: "Ctrl+Alt+K"}
KB_SCALE_MAP = {ID_KB_SCALE_80: 0.8, ID_KB_SCALE_100: 1.0,
                ID_KB_SCALE_125: 1.25, ID_KB_SCALE_150: 1.5}
# v4.02：字体大小菜单
ID_FONT_90, ID_FONT_100, ID_FONT_110, ID_FONT_125, ID_FONT_150, ID_FONT_CUSTOM = \
    501, 502, 503, 504, 505, 506
FONT_SCALE_MAP = {ID_FONT_90: 0.9, ID_FONT_100: 1.0, ID_FONT_110: 1.1,
                  ID_FONT_125: 1.25, ID_FONT_150: 1.5}
_MOD_NAMES = {"CTRL": "Ctrl", "SHIFT": "Shift", "ALT": "Alt", "WIN": "Win"}
# v4.07：常驻任务栏 / 开机自启动
ID_TASKBAR_DOCK, ID_AUTOSTART = 601, 602
# v4.11：虚拟键帽右键菜单——自定义快捷键
ID_CUSTOM_EDIT_KEY, ID_CUSTOM_MANAGE, ID_CUSTOM_TRAY_MENU = 701, 702, 703
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "KeyHint"


def autostart_enabled() -> bool:
    """读取 HKCU Run 里是否登记了指向 KeyHint 的自启项"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, _RUN_VALUE)
            return "keyhint" in str(val).lower()
    except OSError:
        return False


def set_autostart(enabled: bool):
    """勾选/取消开机自启；只增删指向 KeyHint 的值，不碰其它自启项"""
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                                winreg.KEY_WRITE) as k:
            if enabled:
                exe = sys.executable if IS_FROZEN else str(Path(sys.argv[0]).resolve())
                winreg.SetValueEx(k, _RUN_VALUE, 0, winreg.REG_SZ, '"%s"' % exe)
            else:
                try:
                    val, _ = winreg.QueryValueEx(k, _RUN_VALUE)
                    if "keyhint" in str(val).lower():
                        winreg.DeleteValue(k, _RUN_VALUE)
                except FileNotFoundError:
                    pass
    except OSError as e:
        print("开机自启设置失败：", e)


def parse_hotkey(text):
    """'Ctrl+Esc' -> ({'Ctrl'}, 0x1B)；非法返回 (None, None)"""
    mods, key = set(), ""
    for part in str(text or "").split("+"):
        p = part.strip().upper()
        if not p:
            continue
        if p in ("CTRL", "CONTROL"):
            mods.add("Ctrl")
        elif p in ("SHIFT",):
            mods.add("Shift")
        elif p in ("ALT",):
            mods.add("Alt")
        elif p in ("WIN", "WINDOWS", "META"):
            mods.add("Win")
        elif not key:
            key = p
        else:
            return None, None
    if not mods or not key or key in _MOD_NAMES:
        return None, None                      # 至少 1 个修饰键 + 1 个普通键
    vk = sid_to_vk(key)
    if not vk:
        return None, None
    return mods, vk


def format_hotkey(mods, vk):
    """({'Ctrl'}, 0x1B) -> 'Ctrl+Esc'"""
    parts = [m for m in ("Ctrl", "Shift", "Alt", "Win") if m in (mods or set())]
    sid = vk_to_sid(vk)
    parts.append(sid.capitalize() if sid else "?")
    return "+".join(parts)


def chk(mid, text, cond, enabled=True):
    return (mid, text, bool(cond), enabled)


class KeyHintApp:
    def __init__(self, cfg: dict, start_disabled=False):
        self.cfg = cfg
        if start_disabled:
            cfg["enabled"] = False
        w.enable_dpi_awareness()
        self.sw, self.sh = w.screen_size()
        self.cfg["screen_w"], self.cfg["screen_h"] = self.sw, self.sh

        self.held: set[str] = set()
        self.combo = "Ctrl"
        self.app_key = "generic"
        self.exe_name = ""
        self.visible = False
        self.locked = False
        self.sticky = False                  # 点击模式：松开辅助键后保持面板供鼠标点击
        self.flash_sid = None
        self.hover_sid = None
        self.mouse_down_sid = None
        self.virtual_mods: set[str] = set()  # 点击修饰键帽「虚拟按住」的组合
        self.hit_keys = []                   # 与当前画面严格一致的键帽几何
        # v4.04：渲染缓存——底图只在状态变化时重绘，鼠标悬停只叠加描边
        self._base_image = None
        self._blit_xy = (0, 0)
        self._rendered_hover = None
        self._rendered_hover_action = ""
        self._right_click_sid = None
        self._cache = None
        self._demo_timer = False
        self._settings_preview = False
        self._bar_grace = False           # 正在操作右上角控件 → 短暂保留面板
        self._kb_drag = None              # v4.01：顶栏移动 / 右下角缩放的拖拽状态
        self.header_h = 40                # 顶栏高度，refresh 时用真实值覆盖
        # v4.08：特殊符号页（独立于普通键盘画面，点击即输入 Unicode 符号）
        self.symbol_mode = False          # 是否处于符号页
        self.symbol_cat = 0               # 当前分类索引
        self.symbol_cells: list = []      # 与画面严格同源的格子几何
        self._symbol_base = None          # 符号页底图缓存
        self._mouse_click_before_symbols = None  # 进入符号页前的点击模式，退出时恢复
        # v4.08 修复：符号页点击时记住「真正要输入到的窗口」，注入前恢复其焦点。
        # 点击 WS_EX_NOACTIVATE 的分层窗口会让系统把焦点切走，导致 Unicode
        # 字符发给错误窗口（乱码/无输入）。
        self._symbol_target_hwnd = 0
        # v4.08：符号延迟注入队列——点击发生在鼠标消息过程内，立刻 SendInput
        # 会与焦点切换 / 鼠标状态交织导致字符丢失。排到 timer 6 注入更稳。
        self._pending_symbol = None

        self.overlay = w.LayeredWindow(on_mouse=self._overlay_mouse)
        self._wndproc = w.WNDPROC(self._wndproc_impl)
        self.hwnd = w.create_message_window("KeyHintMain", "KeyHint", self._wndproc)
        # v4.07：任务栏常驻按钮（与消息窗口共用 KeyHintMain 窗口类/WNDPROC）
        self.taskbar_hwnd = 0
        # v4.09：用户要求图标只留在托盘、绝不出现在任务栏。
        # 旧配置里 taskbar_dock=true 的，启动时强制纠正为 False 并回写，
        # 且不再创建任务栏代理窗口（即使配置残留 true 也不生效）。
        if self.cfg.get("taskbar_dock", False):
            self.cfg["taskbar_dock"] = False
            try:
                save_config(self.cfg)
            except Exception:
                pass
        self.tray = w.TrayIcon(self.hwnd, ensure_icon(), "%s · 情境式指令提示\n右键打开设置" % APP_NAME)
        # v4.08：托盘保活独立于任务栏开关——即使不开任务栏按钮，托盘图标也要常驻
        w.user32.SetTimer(self.hwnd, 7, 30000, None)  # 托盘图标保活
        self.hook = w.KeyboardHook(self.hwnd, w.WM_APP + 1,
                                   swallow=self._swallow_hotkey)
        self.hook.start()

        # 右上角控件条：独立分层窗口，永远可点击（键盘主体穿透时也一样）
        self.controlbar = controlbar.ControlBar(
            get_state=self.bar_state,
            on_toggle_click=lambda: self.set_mouse_click(
                not self.cfg.get("mouse_click", False), from_bar=True),
            on_toggle_fade=self.toggle_fade_from_bar,
            on_opacity=lambda v: self.set_opacity(v, True),
            on_commit=lambda: save_config(self.cfg),
            on_activity=self.note_bar_activity,
            on_cycle_delay=self.cycle_hide_delay_from_bar,
            on_toggle_symbols=self.toggle_symbols_from_bar,
            on_cycle_custom=self.cycle_custom_panel_from_bar,
            on_manage_custom=self.open_custom_panel_manager)

        self.op_dialog = settings_ui.OpacityDialog(
            lambda: (self.cfg.get("opacity", 92), self.cfg.get("fade", True)),
            self.on_opacity_change, self.on_opacity_close)
        self.delay_dialog = settings_ui.DelayDialog(
            lambda: self.hide_delay(), self.set_hide_delay, self.on_delay_close)
        self.hotkey_dialog = settings_ui.HotkeyDialog(
            lambda: self.cfg.get("toggle_hotkey", "Ctrl+Esc"),
            self.set_toggle_hotkey, self.on_hotkey_close)
        self.font_dialog = settings_ui.FontDialog(
            lambda: self.cfg.get("font_scale", 1.0),
            self.set_font_scale, self.on_font_close)
        # v4.09：统一设置窗口（收纳右键菜单的全部调节项）
        self.settings_dialog = settings_ui.SettingsDialog(
            lambda: self.cfg, self.apply_settings, self.on_settings_close,
            title="%s · 设置" % APP_NAME,
            on_custom=self.open_custom_panel_manager)
        # v4.11：自定义 GUI 对话框保活引用
        self.custom_key_dialog = None
        self.custom_panel_dialog = None

        # 首次启动提示
        if cfg.get("enabled"):
            tip = ("按住 Ctrl 查看组合键；%s 可开关弹出。"
                   "键帽可点时拖顶栏移动、拖右下角缩放。"
                   % self.cfg.get("toggle_hotkey", "Ctrl+Esc"))
            self._balloon("已启动", tip)

        # v4.05：后台预热壁纸取色 / 阴影 / 字体缓存。
        # 壁纸取色首次约 110ms（读图+缩放+统计），若留到第一次弹出时算会明显卡顿；
        # 放到启动后的后台线程预热，用户开始按键时缓存已热，渲染稳定在 ~25ms。
        threading.Thread(target=self._warmup_render, daemon=True).start()

    def _warmup_render(self):
        """后台预热渲染缓存，纯计算、不碰 UI，可在任意线程执行"""
        try:
            if self.cfg.get("wallpaper_theme", True):
                render.wallpaper_accent()
            scale = max(0.5, min(2.0, float(self.cfg.get("kb_scale", 1.0) or 1.0)))
            _, cw, ch, _, _ = layout.build(
                self.cfg["layout"], self.cfg["narrow"], self.sw, scale)
            accent = (render.wallpaper_accent()
                      if self.cfg.get("wallpaper_theme", True) else None)
            C = render.theme_colors(self.cfg.get("theme", "dark"), accent)
            render._shadow_layer(cw, ch, C["shadow"])
            for s in (8, 9, 10, 11, 12, 13):
                render.font(s, False)
                render.font(s, True)
        except Exception:
            pass

    def bar_state(self) -> dict:
        return {"mouse_click": self.cfg.get("mouse_click", True),
                "fade": self.cfg.get("fade", True),
                "opacity": self.cfg.get("opacity", 80),
                "hide_delay_ms": self.hide_delay(),
                "theme": self.cfg.get("theme", "dark"),
                "wallpaper_theme": self.cfg.get("wallpaper_theme", True),
                "symbol_mode": self.symbol_mode,
                "custom_active": self.custom_active(),
                "custom_label": self.custom_panel_name()}

    # ------------------------------------------------------------ v4.11 自定义面板
    def custom_active(self) -> bool:
        return bool(self.cfg.get("custom_active", False))

    def custom_panels(self) -> list:
        panels = self.cfg.get("custom_panels")
        if not isinstance(panels, list) or not panels:
            panels = [{"name": "我的快捷键", "keys": {}}]
            self.cfg["custom_panels"] = panels
        return panels

    def current_custom_panel(self) -> dict:
        panels = self.custom_panels()
        idx = self.cfg.get("active_custom_panel", 0)
        if not isinstance(idx, int) or not (0 <= idx < len(panels)):
            idx = 0
            self.cfg["active_custom_panel"] = 0
        p = panels[idx]
        if not isinstance(p, dict):
            p = {"name": "我的快捷键", "keys": {}}
            panels[idx] = p
        if not isinstance(p.get("keys"), dict):
            p["keys"] = {}
        return p

    def custom_panel_name(self) -> str:
        return str(self.current_custom_panel().get("name") or "自定义")

    def custom_key_entry(self, sid: str) -> dict | None:
        sid = canonical(str(sid or ""))
        entry = self.current_custom_panel().get("keys", {}).get(sid)
        return entry if isinstance(entry, dict) else None

    def cycle_custom_panel_from_bar(self):
        """v4.12：左键点击「我的快捷键」= 开关切换。
        开 → 全灰自定义面板（所有快捷键需自定义）；关 → 恢复常用快捷键面板。"""
        if self.custom_active():
            self.cfg["custom_active"] = False
            self._balloon("我的快捷键", "已关闭，恢复常用快捷键面板。")
        else:
            self.cfg["custom_active"] = True
            self._balloon("我的快捷键", "已开启：%s。所有键位全灰，右键任意键帽自定义。"
                          % self.custom_panel_name())
        save_config(self.cfg)
        self._cache = None
        if self.visible:
            self.refresh(force=True)
        self.controlbar.refresh(force=True)

    def open_custom_key_editor(self, sid: str, x: int, y: int):
        """右键虚拟键帽：直接打开当前键的组合键 / 名称 / 作用编辑器。"""
        sid = canonical(str(sid or ""))
        if not sid or sid.startswith(("CAT:", "SYM:")):
            return
        if not self.custom_active():
            self.cfg["custom_active"] = True
        entry = dict(self.custom_key_entry(sid) or {})

        def get_entry():
            return entry

        def save(entry_data):
            panel = self.current_custom_panel()
            if entry_data:
                panel.setdefault("keys", {})[sid] = entry_data
            else:
                panel.setdefault("keys", {}).pop(sid, None)
            save_config(self.cfg)
            self._cache = None
            if self.visible:
                self.refresh(force=True)

        def delete():
            self.current_custom_panel().setdefault("keys", {}).pop(sid, None)
            save_config(self.cfg)
            self._cache = None
            if self.visible:
                self.refresh(force=True)

        self.custom_key_dialog = settings_ui.CustomKeyDialog(
            get_entry, sid, save, delete, self.on_custom_key_close)
        self.custom_key_dialog.show(x, y)
        self.note_bar_activity()

    def on_custom_key_close(self):
        self.custom_key_dialog = None
        self.controlbar.refresh(force=True)

    def open_custom_panel_manager(self):
        def get_panels():
            return self.custom_panels()

        def apply(panels, active_idx):
            self.cfg["custom_panels"] = panels
            self.cfg["active_custom_panel"] = active_idx
            self.cfg["custom_active"] = True
            save_config(self.cfg)
            self._cache = None
            if self.visible:
                self.refresh(force=True)
            self.controlbar.refresh(force=True)

        self.custom_panel_dialog = settings_ui.CustomPanelDialog(
            get_panels, int(self.cfg.get("active_custom_panel", 0) or 0),
            apply, self.on_custom_panel_close)
        self.custom_panel_dialog.show()
        self.note_bar_activity()

    def on_custom_panel_close(self):
        self.custom_panel_dialog = None
        self.controlbar.refresh(force=True)

    # ------------------------------------------------------------ v4.01 弹出开关
    def _hotkey_parts(self):
        return parse_hotkey(self.cfg.get("toggle_hotkey", "Ctrl+Esc"))

    def _swallow_hotkey(self, vk, down):
        """钩子线程调用：命中开关时阻止系统默认行为（Ctrl+Esc 不再开开始菜单）"""
        mods, key_vk = self._hotkey_parts()
        if mods is None or vk != key_vk:
            return False
        real = set(w.held_modifiers())
        if vk in (0x11, 0x10, 0x12, 0x5B, 0x5D):
            real |= {m for m, v in MOD_VK.items() if v == vk}
        return real == mods

    # ------------------------------------------------ v4.07 常驻任务栏 / 自启
    def set_taskbar_dock(self, on: bool):
        """开/关任务栏常驻按钮；托盘图标同时保持注册（锁定显示）"""
        on = bool(on)
        try:
            if on and not self.taskbar_hwnd:
                self.taskbar_hwnd = w.create_taskbar_window(
                    "KeyHintMain", "%s · 情境式指令提示" % APP_NAME, str(ICON_PATH))
            elif not on and self.taskbar_hwnd:
                w.taskbar_destroy(self.taskbar_hwnd)
                self.taskbar_hwnd = 0
        except Exception as e:
            print("任务栏按钮切换失败：", e)
        # v4.08：托盘保活始终开启，不再随任务栏开关关闭
        w.user32.SetTimer(self.hwnd, 7, 30000, None)
        self.cfg["taskbar_dock"] = on
        save_config(self.cfg)
        self._balloon("常驻任务栏", "已开启：任务栏出现按钮，点击可弹出菜单。" if on else
                      "已关闭：任务栏按钮已移除（托盘图标保留）。")

    def toggle_autostart(self):
        on = not autostart_enabled()
        set_autostart(on)
        self.cfg["autostart"] = on
        save_config(self.cfg)
        self._balloon("开机自启动", "已开启：下次开机会自动运行 %s。" % APP_NAME if on else
                      "已关闭：下次开机不再自动运行。")

    def popup_enabled(self) -> bool:
        return bool(self.cfg.get("popup_enabled", True))

    def toggle_popup(self):
        on = not self.popup_enabled()
        self.cfg["popup_enabled"] = on
        save_config(self.cfg)
        if not on:
            self.kill_show_timer()
            self.hide()
        hk = self.cfg.get("toggle_hotkey", "Ctrl+Esc")
        self._balloon("虚拟键盘弹出",
                      "已开启：按住 Ctrl / Shift / Alt / Win 自动弹出。" if on else
                      "已关闭：按住辅助键不再弹出。按 %s 可重新开启。" % hk)

    def set_toggle_hotkey(self, text):
        mods, vk = parse_hotkey(text)
        if mods is None:
            self._balloon("快捷键无效",
                          "请填「修饰键+普通键」，例如 Ctrl+Esc 或 Ctrl+Alt+P")
            return
        value = format_hotkey(mods, vk)
        self.cfg["toggle_hotkey"] = value
        save_config(self.cfg)
        self._balloon("弹出快捷键", "已设为 %s，按它可开关虚拟键盘自动弹出。" % value)

    def on_hotkey_close(self):
        save_config(self.cfg)

    # ------------------------------------------------------------ v4.01 键盘几何
    def set_kb_scale(self, scale):
        self.cfg["kb_scale"] = max(0.5, min(2.0, float(scale)))
        self._cache = None
        save_config(self.cfg)
        if self.visible:
            self.refresh(force=True)

    def reset_kb_geometry(self):
        self.cfg["kb_scale"] = 1.0
        self.cfg["kb_pos_x"] = None
        self.cfg["kb_pos_y"] = None
        self._cache = None
        save_config(self.cfg)
        if self.visible:
            self.refresh(force=True)
        self._balloon("键盘布局", "已恢复默认大小与停靠位置。")

    # ------------------------------------------------------------ v4.02 字体大小
    def set_font_scale(self, scale):
        self.cfg["font_scale"] = max(0.5, min(2.0, float(scale)))
        self._cache = None
        save_config(self.cfg)
        if self.visible:
            self.refresh(force=True)
        self._balloon("字体大小", "键帽文字已设为 %d%%（100%% 为原始默认）。"
                      % int(round(self.cfg["font_scale"] * 100)))

    def on_font_close(self):
        save_config(self.cfg)

    # ------------------------------------------------------------ v4.09 统一设置窗口
    def open_settings(self):
        """打开统一设置窗口：先确保面板可见，便于实时预览外观变化。"""
        self._settings_preview = True
        if not self.visible:
            self.detect_context()
            self.combo = self.current_combo() or "Ctrl"
            self.visible = True
            self.refresh(force=True)
        self.settings_dialog.show()

    def apply_settings(self, new_cfg):
        """把设置窗口返回的配置一次性应用（含各类副作用）并保存。"""
        old = self.cfg
        taskbar_changed = bool(new_cfg.get("taskbar_dock")) != bool(self.taskbar_hwnd)
        autostart_new = bool(new_cfg.get("autostart"))
        autostart_changed = autostart_new != autostart_enabled()

        # 更新配置本体（保留运行时字段）
        for k, v in new_cfg.items():
            old[k] = v
        old["screen_w"], old["screen_h"] = self.sw, self.sh

        # 点击穿透 / 缓存
        self.overlay.set_click_through(not self.mouse_mode())
        self._cache = None
        # 任务栏 / 自启
        if taskbar_changed:
            self.set_taskbar_dock(bool(new_cfg.get("taskbar_dock")))
        if autostart_changed:
            set_autostart(autostart_new)
        save_config(old)
        if self.visible:
            self.refresh(force=True)

    def on_settings_close(self):
        self._settings_preview = False
        save_config(self.cfg)
        if not self.locked and not self.held and not self.symbol_mode:
            self.schedule_hide()

    # ------------------------------------------------------------ 延时消失
    def hide_delay(self) -> int:
        return max(0, min(600000, int(self.cfg.get("hide_delay_ms", 0) or 0)))

    def schedule_hide(self):
        """
        松开辅助键后按 hide_delay_ms 延时收起。
        0 = 立即消失（默认）；>0 = 延时期间可用鼠标点键帽 / 拖控件条，
        任何交互都会重置倒计时。正在操作控件条时至少保留 ui_grace_ms。
        """
        if self.locked or self._settings_preview or self.held or not self.visible:
            return
        delay = self.hide_delay()
        if self.controlbar.active or self._bar_grace:
            delay = max(delay, max(300, int(self.cfg.get("ui_grace_ms", 1500))))
        w.user32.KillTimer(self.hwnd, 4)
        self.sticky = delay > 0
        if delay <= 0:
            self.hide()
            return
        w.user32.SetTimer(self.hwnd, 4, delay, None)
        self.refresh(force=True)

    def reset_hide_timer(self):
        """延时阶段有鼠标操作：重新计时，避免操作到一半被收起"""
        if (not self.sticky or self.locked or self._settings_preview
                or self.held or not self.visible):
            return
        delay = max(self.hide_delay(), max(300, int(self.cfg.get("ui_grace_ms", 1500)))) \
            if self._bar_grace else self.hide_delay()
        if delay <= 0:
            return
        w.user32.KillTimer(self.hwnd, 4)
        w.user32.SetTimer(self.hwnd, 4, delay, None)

    def set_hide_delay(self, ms, notify=False):
        ms = max(0, min(600000, int(ms)))
        self.cfg["hide_delay_ms"] = ms
        self._cache = None
        save_config(self.cfg)
        if self.visible:
            self.refresh(force=True)
            if self.sticky and not self.held and not self.locked:
                self.schedule_hide()
        if notify:
            self._balloon("延时消失",
                          "松开辅助键后「%s」消失；期间点键帽或拖控件条会重新计时。"
                          % ("立即" if ms == 0 else render.delay_label(ms)))

    def cycle_hide_delay_from_bar(self):
        self.set_hide_delay(controlbar.next_delay_preset(self.hide_delay()))

    def open_delay_dialog(self):
        self._settings_preview = True
        w.user32.KillTimer(self.hwnd, 4)
        self.sticky = False
        if not self.visible:
            self.detect_context()
            self.combo = self.current_combo() or "Ctrl"
            self.visible = True
        self.refresh(force=True)
        try:
            self.delay_dialog.show()
        except Exception as e:
            print("延时设置窗口打开失败：", e)
            self._settings_preview = False

    def on_delay_close(self):
        self._settings_preview = False
        save_config(self.cfg)
        if not self.locked and not self.held:
            self.schedule_hide()

    def note_bar_activity(self):
        """控件条被按下 / 拖动：至少保留 ui_grace_ms，不打断手上的动作"""
        grace = max(300, int(self.cfg.get("ui_grace_ms", 1500)))
        self._bar_grace = True
        w.user32.KillTimer(self.hwnd, 5)
        w.user32.SetTimer(self.hwnd, 5, grace, None)
        if (self.visible and not self.locked and not self._settings_preview
                and not self.held):
            self.sticky = True
            w.user32.KillTimer(self.hwnd, 4)
            w.user32.SetTimer(self.hwnd, 4, max(grace, self.hide_delay()), None)
            self.refresh(force=True)

    def toggle_fade_from_bar(self):
        self.cfg["fade"] = not self.cfg.get("fade", True)
        self._cache = None
        save_config(self.cfg)
        if self.visible:
            self.refresh(force=True)

    # ------------------------------------------------------------ 托盘
    def _balloon(self, title, text):
        try:
            nid = self.tray.nid
            nid.uFlags |= 0x10  # NIF_INFO
            nid.szInfoTitle = title[:63]
            nid.szInfo = text[:255]
            nid.dwInfoFlags = 0x1  # NIIF_INFO
            w.shell32.Shell_NotifyIconW(w.NIM_MODIFY, C.byref(nid))
            nid.uFlags &= ~0x10
        except Exception:
            pass

    def menu_items(self):
        """v4.09：极简右键菜单——所有调节项收进「设置」窗口。"""
        c = self.cfg
        return [
            ("info", "%s  v%s" % (APP_NAME, APP_VERSION)),
            ("sep",),
            chk(ID_ENABLE, "启用" + ("" if c["enabled"] else "（当前已停用）"), c["enabled"]),
            (ID_SETTINGS, "设置…   外观 / 行为 / 快捷键 / 键盘规格", False, True),
            chk(ID_LOCK, "锁定速查面板  Ctrl+Alt+H", self.locked),
            ("sep",),
            (ID_DEMO, "预览 3 秒", False, True),
            # v4.09：移除「编辑指令数据库 / 配置…」——它用记事本打开 JSON 代码，
            # 新手容易改坏。所有可调项已收进「设置」窗口的 GUI。
            (ID_ABOUT, "关于", False, True),
            ("sep",),
            (ID_EXIT, "退出 %s" % APP_NAME, False, True),
        ]

    def handle_cmd(self, cmd):
        c = self.cfg
        # ---- v4.07：常驻任务栏 / 开机自启动 ----
        if cmd == ID_TASKBAR_DOCK:
            self.set_taskbar_dock(not bool(self.taskbar_hwnd))
            return
        if cmd == ID_AUTOSTART:
            self.toggle_autostart()
            return
        # ---- v4.01 新增：弹出开关 / 快捷键 / 键盘几何 ----
        if cmd == ID_POPUP_ENABLE:
            self.toggle_popup()
            return
        if cmd in HOTKEY_PRESETS:
            self.set_toggle_hotkey(HOTKEY_PRESETS[cmd])
            return
        if cmd == ID_HK_CUSTOM:
            self.hotkey_dialog.show()
            return
        if cmd in KB_SCALE_MAP:
            self.set_kb_scale(KB_SCALE_MAP[cmd])
            return
        if cmd == ID_KB_RESET:
            self.reset_kb_geometry()
            return
        if cmd in FONT_SCALE_MAP:
            self.set_font_scale(FONT_SCALE_MAP[cmd])
            return
        if cmd == ID_FONT_CUSTOM:
            self.font_dialog.show()
            return
        # ---- 原有开关 ----
        if cmd == ID_MOUSE_CLICK:
            self.set_mouse_click(not c.get("mouse_click", False))
            save_config(c)
            return
        if cmd in HIDE_DELAY_MAP:
            self.set_hide_delay(HIDE_DELAY_MAP[cmd], notify=True)
            return
        if cmd == ID_HIDE_CUSTOM:
            self.open_delay_dialog()
            return
        if cmd == ID_OP_DIALOG:
            self.open_opacity_dialog()
            return
        if cmd in (ID_OP_PLUS, ID_OP_MINUS):
            delta = 5 if cmd == ID_OP_PLUS else -5
            self.set_opacity(c.get("opacity", 92) + delta, c.get("fade", True))
            save_config(c)
            return

        simple = {
            ID_STYLE_COMPACT: ("layout", "compact"), ID_STYLE_FULL: ("layout", "full"),
            ID_HINT_ICON: ("hint_mode", "icon"), ID_HINT_TEXT: ("hint_mode", "text"),
            ID_THEME_DARK: ("theme", "dark"), ID_THEME_LIGHT: ("theme", "light"),
            ID_THEME_AUTO: ("theme", "auto"),
            ID_POS_BOTTOM: ("position", "bottom"), ID_POS_CENTER: ("position", "center"),
            ID_OP_100: ("opacity", 100), ID_OP_92: ("opacity", 92),
            ID_OP_78: ("opacity", 78), ID_OP_60: ("opacity", 60), ID_OP_40: ("opacity", 40),
            ID_DELAY_0: ("delay_ms", 0), ID_DELAY_150: ("delay_ms", 150),
            ID_DELAY_300: ("delay_ms", 300), ID_DELAY_500: ("delay_ms", 500),
        }
        toggles = {ID_ENABLE: "enabled", ID_NARROW: "narrow", ID_CONTEXT: "app_context",
                   ID_SOUND: "sound", ID_LANG: "show_lang", ID_THEME_WALL: "wallpaper_theme",
                   ID_FADE: "fade", ID_CLICK_KEEP: "click_keep"}
        if cmd in simple:
            k, v = simple[cmd]
            c[k] = v
        elif cmd in toggles:
            c[toggles[cmd]] = not c[toggles[cmd]]
        elif cmd in (ID_MOD_CTRL, ID_MOD_SHIFT, ID_MOD_ALT, ID_MOD_WIN):
            name = {ID_MOD_CTRL: "Ctrl", ID_MOD_SHIFT: "Shift",
                    ID_MOD_ALT: "Alt", ID_MOD_WIN: "Win"}[cmd]
            c["modifiers"][name] = not c["modifiers"].get(name, True)
        elif cmd == ID_LOCK:
            self.toggle_lock()
            return
        elif cmd == ID_DEMO:
            self.demonstrate(3)
            return
        elif cmd == ID_RELOAD:
            self.cfg = load_config()
            self.cfg["screen_w"], self.cfg["screen_h"] = self.sw, self.sh
            self._cache = None
            self.overlay.set_click_through(not self.cfg.get("mouse_click", False))
            if self.visible:
                self.refresh(force=True)
            return
        elif cmd == ID_OPENCFG:
            try:
                os.startfile(str(CONFIG_PATH))
            except Exception:
                pass
            return
        elif cmd == ID_SETTINGS:
            self.open_settings()
            return
        elif cmd == ID_ABOUT:
            lines = ["%s  v%s" % (APP_NAME, APP_VERSION), "情境式指令提示（PC 移植）", ""]
            lines += ["✓ " + a + "\n   → " + b for a, b in shortcuts.HUAWEI_FEATURE_MAP[:6]]
            try:
                C.windll.user32.MessageBoxW(0, "\n".join(lines)[:1500],
                                            "关于 %s" % APP_NAME, 0x40)
            except Exception:
                pass
            return
        elif cmd == ID_EXIT:
            self.cleanup()
            w.user32.PostQuitMessage(0)
            return
        else:
            return
        if cmd == ID_ENABLE and not c["enabled"]:
            self.hide()
        save_config(c)
        self._cache = None
        self.overlay.set_click_through(not c.get("mouse_click", False))
        if self.visible:
            self.refresh(force=True)

    # ------------------------------------------------------------ 状态机
    def effective_held(self) -> set[str]:
        return {m for m in self.held if self.cfg["modifiers"].get(m, True)}

    def current_mods(self) -> set[str]:
        """物理按住的辅助键 + 鼠标点击修饰键帽「虚拟按住」的辅助键"""
        return self.effective_held() | self.virtual_mods

    def current_combo(self) -> str:
        mods = self.current_mods()
        return shortcuts.combo_name(mods) if mods else (self.combo or "Ctrl")

    def mouse_mode(self) -> bool:
        return bool(self.cfg.get("mouse_click", False))

    def schedule_show(self):
        w.user32.KillTimer(self.hwnd, 1)
        # v4.05：始终走异步定时器。v4.04 的「0ms 同步弹出」会在键盘消息线程里
        # 直接渲染（首次含壁纸取色 ~110ms），阻塞钩子消息处理反而更卡。
        # 用 1ms 定时器把渲染挪回消息循环，按键响应立即返回，主观更快。
        delay = max(1, int(self.cfg.get("delay_ms", 0) or 0))
        w.user32.SetTimer(self.hwnd, 1, delay, None)

    def kill_show_timer(self):
        w.user32.KillTimer(self.hwnd, 1)

    def on_delay(self):
        # 用系统真实按键状态校正（钩子可能错过应用启动前已按住的键）
        self.held = w.held_modifiers()
        if not self.cfg["enabled"] or not self.popup_enabled() or not self.effective_held():
            return
        self.combo = self.current_combo()
        self.sticky = False
        w.user32.KillTimer(self.hwnd, 4)
        self.show()

    def detect_context(self):
        exe = w.foreground_exe() if self.cfg["app_context"] else ""
        self.app_key = shortcuts.detect_app(exe)
        self.exe_name = exe

    def show(self):
        self.detect_context()
        self.visible = True
        self.refresh(force=True)

    def hide(self):
        if self._kb_drag:
            self._kb_drag = None
            if self.overlay.hwnd and w.user32.GetCapture() == self.overlay.hwnd:
                w.user32.ReleaseCapture()
        if self.visible:
            self.overlay.hide()
            self.visible = False
        self.controlbar.hide()
        self.sticky = False
        self._bar_grace = False
        self.virtual_mods.clear()
        self.hover_sid = None
        self.mouse_down_sid = None
        self._cache = None
        w.user32.KillTimer(self.hwnd, 4)
        w.user32.KillTimer(self.hwnd, 5)

    def toggle_lock(self):
        # v4.08：符号页本身就是锁定态，Ctrl+Alt+H 直接视为退出符号页
        if self.symbol_mode:
            self.close_symbols()
            return
        self.locked = not self.locked
        if self.locked:
            if not self.combo:
                self.combo = "Ctrl"
            self.detect_context()
            self.visible = True
            self.sticky = False
            self.refresh(force=True)
        else:
            self.hide()

    def toggle_symbols_from_bar(self):
        """控件条「符号页」按钮：切换符号页；首次打开时若面板未显示则先显示。"""
        self.toggle_symbols(from_bar=True)
        self.note_bar_activity()

    # ------------------------------------------------------------ 两个新开关
    def set_mouse_click(self, on: bool, from_bar: bool = False):
        """
        切换鼠标点击 / 穿透。
        v4 起「何时消失」不再与该开关绑定：两种模式都走 hide_delay_ms 倒计时，
        默认是 0（松手即隐），用户可自行设为 5 秒 / 10 秒 / 自定义。
        """
        on = bool(on)
        self.cfg["mouse_click"] = on
        self.overlay.set_click_through(not on)
        self._cache = None
        save_config(self.cfg)
        # 从右上角开关切换时手还在控件条上，给宽限，别让控件条立刻消失
        if from_bar:
            self.note_bar_activity()
        if self.visible:
            self.refresh(force=True)
            if (not self.held and not self.locked
                    and not self._settings_preview):
                self.schedule_hide()
        if not from_bar:
            self._balloon("鼠标点击",
                          "已开启：点击虚拟键帽即执行快捷键。"
                          if on else "已关闭：鼠标完全穿透覆盖层。")

    def set_opacity(self, value: int, fade: bool | None = None):
        self.cfg["opacity"] = max(10, min(100, int(value)))
        if fade is not None:
            self.cfg["fade"] = bool(fade)
        self._cache = None
        if self.visible:
            self.refresh(force=True)

    def open_opacity_dialog(self):
        """打开滑块窗口，并让虚拟键盘保持显示以便实时预览浓淡变化"""
        self._settings_preview = True
        if not self.visible:
            self.detect_context()
            self.combo = self.current_combo() or "Ctrl"
            self.visible = True
        self.refresh(force=True)
        try:
            self.op_dialog.show()
        except Exception as e:
            print("透明度设置窗口打开失败：", e)
            self._settings_preview = False

    def on_opacity_change(self, opacity, fade):
        self.set_opacity(opacity, fade)

    def on_opacity_close(self):
        self._settings_preview = False
        save_config(self.cfg)
        if not self.locked and not self.held and not self.sticky:
            self.hide()

    def flash(self, sid):
        if not sid or not self.visible:
            return
        self.flash_sid = sid
        self.refresh(force=True)
        if self.cfg["sound"]:
            try:
                winsound.Beep(920, 28)
            except Exception:
                pass
        w.user32.KillTimer(self.hwnd, 2)
        w.user32.SetTimer(self.hwnd, 2, 280, None)

    def demonstrate(self, seconds=3):
        self.detect_context()
        self.combo = "Ctrl"
        self.visible = True
        self.refresh(force=True)
        self._demo_timer = True
        w.user32.KillTimer(self.hwnd, 3)
        w.user32.SetTimer(self.hwnd, 3, seconds * 1000, None)

    def _refresh_symbols(self, force=False):
        """v4.08：符号页刷新——与键盘渲染分流，共用 overlay / 控件条 / 悬停叠加。"""
        import symbol_render as symr
        key = (self.symbol_cat, self.cfg.get("theme", "dark"),
               self.cfg.get("wallpaper_theme", True),
               self.cfg.get("opacity", 92), self.cfg.get("fade", True),
               self.cfg.get("kb_scale", 1.0), self.cfg.get("font_scale", 1.0),
               self.cfg.get("kb_pos_x"), self.cfg.get("kb_pos_y"),
               self.cfg.get("position", "bottom"), self.flash_sid)
        hover = self.hover_sid
        full = force or key != self._cache
        if not full and hover == self._rendered_hover:
            return
        if full:
            self._cache = key
            try:
                im, x, y, cells = symr.render_image(
                    self.cfg, self.symbol_cat, hover, self.flash_sid)
                self._symbol_base = im
                self.symbol_cells = cells
                self._blit_xy = (x, y)
                self.overlay.set_click_through(not self.mouse_mode())
                self.hit_keys = []          # 符号页不用键盘 hit_keys
                self.controlbar.place(x, y, im.width, im.height, self.sw)
            except Exception as e:
                print("符号页渲染失败：", e)
                return
        if self._symbol_base is None:
            return
        out = self._symbol_base.copy()
        symr.draw_hover(out, self.symbol_cells, hover, self.flash_sid)
        # v4.08：透明度只作用于面板背景（render_image 内处理），键帽恒不透明
        data = render.to_premultiplied_bgra(out, 100)
        self._rendered_hover = hover
        self.overlay.blit(data, out.width, out.height, *self._blit_xy)

    def refresh(self, force=False):
        if not self.visible:
            return
        if self.symbol_mode:
            self._refresh_symbols(force)
            return
        combo = self.current_combo()
        self.combo = combo
        mapping = shortcuts.resolve(combo, self.app_key, self.cfg.get("custom_shortcuts"))
        app_name = shortcuts.app_display_name(self.app_key)
        if self.custom_active():
            # v4.12：开启自定义后整块键盘全灰，不显示任何内置快捷键；
            # 只有用户亲自右键设置过的键帽才显示名称、才可点击执行。
            mapping = {}
            for sid, item in self.current_custom_panel().get("keys", {}).items():
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if name:
                    mapping[canonical(sid)] = name
            app_name = "我的快捷键：%s" % self.custom_panel_name()
        lang = w.input_language() if self.cfg["show_lang"] else ""
        # v4.04：hover_sid 不进缓存键——悬停只在缓存底图上叠加描边，
        # 不再整幅重绘（原来每次鼠标跨键帽都要重画几百个键 + 高斯模糊 + 壁纸取色）。
        key = (combo, self.app_key, lang, self.flash_sid,
               self.locked, self.sticky, self.mouse_mode(),
               self.cfg["layout"], self.cfg["narrow"], self.cfg["hint_mode"],
               self.cfg["theme"], self.cfg["wallpaper_theme"],
               self.cfg["opacity"], self.cfg["fade"], self.cfg["position"],
               self.cfg.get("kb_scale", 1.0), self.cfg.get("kb_pos_x"),
               self.cfg.get("kb_pos_y"), self.cfg.get("font_scale", 1.0),
               # v4.06：快捷键/开关状态变化时强制重绘底部提示胶囊
               self.cfg.get("toggle_hotkey", "Ctrl+Esc"),
               self.cfg.get("popup_enabled", True),
               self.custom_active(), self.custom_panel_name(),
               self.hide_delay(), tuple(sorted(self.current_mods())))
        hover = self.hover_sid
        hover_action = ""
        if hover and self.custom_active():
            ent = self.custom_key_entry(hover)
            if ent:
                bits = [str(ent.get("name") or ""),
                        str(ent.get("action") or ""),
                        str(ent.get("combo") or "")]
                hover_action = "  ·  ".join(b for b in bits if b)
        prev_action = getattr(self, "_rendered_hover_action", "")
        custom_hover_changed = self.custom_active() and (hover_action != prev_action)
        full = force or key != self._cache or (custom_hover_changed and bool(hover_action or prev_action))
        if not full and hover == self._rendered_hover:
            return
        if full:
            self._cache = key
            try:
                im, x, y = render.render_image(
                    self.cfg, combo, mapping, app_name,
                    lang, self.current_mods(), self.locked, self.flash_sid,
                    None, self.mouse_mode(), self.sticky and not self.locked,
                    hover_action=hover_action,
                    custom_mode=self.custom_active())
                self._base_image = im
                self._blit_xy = (x, y)
                self.overlay.set_click_through(not self.mouse_mode())
                # 键帽几何与刚渲染的画面严格同源，保证鼠标命中准确
                keys, _, _, _, header = layout.build(
                    self.cfg["layout"], self.cfg["narrow"], self.sw,
                    self.cfg.get("kb_scale", 1.0))
                self.hit_keys = keys
                self.header_h = header
                # 控件条贴在刚算出的面板右上角，并始终压在键盘之上
                self.controlbar.place(x, y, im.width, im.height, self.sw)
            except Exception as e:
                print("渲染失败：", e)
                return
        if self._base_image is None:
            return
        out = self._base_image.copy()
        render.draw_hover(out, self.hit_keys, hover)
        # v4.08：透明度只作用于面板背景（render_image 内处理），键帽恒不透明
        data = render.to_premultiplied_bgra(out, 100)
        self._rendered_hover = hover
        self._rendered_hover_action = hover_action
        self.overlay.blit(data, out.width, out.height, *self._blit_xy)

    # ------------------------------------------------------------ 鼠标点击
    def _local_xy(self):
        """光标屏幕坐标 -> 键盘画面局部坐标（绕开分层窗口客户区偏移）"""
        pt = w.POINT()
        w.user32.GetCursorPos(C.byref(pt))
        return pt.x - self.overlay.rect[0], pt.y - self.overlay.rect[1]

    def _screen_xy(self):
        pt = w.POINT()
        w.user32.GetCursorPos(C.byref(pt))
        return pt.x, pt.y

    def _drag_zone(self, px, py):
        """v4.01：仅「键帽可点」时生效——顶栏拖动移动，右下角拖动缩放"""
        if not self.mouse_mode() or not self.visible or self._kb_drag:
            return None
        cw, ch = self.overlay.rect[2], self.overlay.rect[3]
        if 8 <= py <= max(10, self.header_h) and 8 <= px <= cw - 46:
            return "move"
        if cw - 40 <= px <= cw - 8 and ch - 40 <= py <= ch - 8:
            return "resize"
        return None

    def _finish_kb_drag(self, hwnd):
        if not self._kb_drag:
            return
        self._kb_drag = None
        if w.user32.GetCapture() == hwnd:
            w.user32.ReleaseCapture()
        save_config(self.cfg)
        self._cache = None
        self.note_bar_activity()          # 拖拽后给宽限，别让键盘立刻消失
        if self.visible:
            self.refresh(force=True)

    def hit_test(self, px: int, py: int):
        """覆盖层客户区坐标 -> 键位 id（符号页返回 CAT:n / SYM:n）"""
        if self.symbol_mode:
            for c in self.symbol_cells:
                if c.x <= px <= c.x + c.w and c.y <= py <= c.y + c.h:
                    return c.sid
            return None
        for k in self.hit_keys:
            if k.sid == "__HEADER__":
                continue
            if k.x <= px <= k.x + k.w and k.y <= py <= k.y + k.h:
                return canonical(k.sid)
        return None

    def _send_custom_combo(self, text: str) -> bool:
        """发送用户为某个键帽自定义的组合键，例如 Ctrl+Shift+S。"""
        mods, vk = parse_hotkey(text)
        if mods is None or not vk:
            self._balloon("自定义快捷键无效",
                          "组合键格式应为「Ctrl+Shift+S」这类修饰键 + 主键。")
            return False
        mod_vks = [MOD_VK[m] for m in ("Ctrl", "Shift", "Alt", "Win") if m in mods]
        w.release_modifiers()
        w.send_combo(mod_vks, vk)
        return True

    def click_key(self, sid: str):
        """点击虚拟键帽 == 按下对应物理组合键（等价于「按键盘」）"""
        # v4.08：符号页——分类切换 / 符号直接输入
        if self.symbol_mode:
            if sid and sid.startswith("CAT:"):
                try:
                    self.symbol_cat = int(sid.split(":", 1)[1])
                except ValueError:
                    pass
                self.hover_sid = None
                self.refresh(force=True)
                return
            if sid and sid.startswith("SYM:"):
                self._input_symbol(sid)
                return
            return

        # v4.11：自定义面板优先——点击键帽执行为该键配置的实际组合键
        if self.custom_active():
            entry = self.custom_key_entry(sid)
            combo_text = str((entry or {}).get("combo") or "")
            if combo_text:
                if self._send_custom_combo(combo_text):
                    self.flash(sid)
                    self.reset_hide_timer()
                    return

        if sid in ("CTRL", "SHIFT", "ALT", "WIN"):
            name = {"CTRL": "Ctrl", "SHIFT": "Shift",
                    "ALT": "Alt", "WIN": "Win"}[sid]
            if name in self.virtual_mods:
                self.virtual_mods.discard(name)
            else:
                self.virtual_mods.add(name)
            self.combo = self.current_combo() or "Ctrl"
            self.flash(sid)
            self.refresh(force=True)
            self.reset_hide_timer()
            return

        combo = self.combo or "Ctrl"
        vk = sid_to_vk(sid)
        if not vk:
            return
        real = w.held_modifiers()
        need = [m for m in combo.split("+") if m in MOD_VK and m not in real]
        events = [(MOD_VK[m], True) for m in need]
        events += [(vk, True), (vk, False)]
        events += [(MOD_VK[m], False) for m in reversed(need)]
        self.flash(sid)
        w.send_keys(events)          # 带 INJECT_MAGIC，钩子会忽略、不自激
        self.reset_hide_timer()
        if (not self.cfg.get("click_keep", True) and self.sticky
                and not self.locked and not self.held):
            self.hide()

    # ------------------------------------------------------------ v4.08 符号页
    def _remember_input_target(self):
        """记录当前真正的前台窗口作为符号/按键输入目标。

        过滤掉本程序自己的窗口：覆盖层 / 控件条 / 主消息窗口 / 各设置窗口
        都是 WS_EX_NOACTIVATE 或工具窗口，正常不会成为前台；一旦记录到它们
        说明用户此刻并没有在外部程序打字，保留上一次的有效目标更稳妥。
        """
        try:
            fg = w.foreground_hwnd()
            if not fg:
                return
            own = (int(self.hwnd), int(self.overlay.hwnd or 0),
                   int(getattr(self.controlbar, "hwnd", 0) or 0))
            if w.is_own_window(fg, own):
                return
            self._symbol_target_hwnd = fg
        except Exception:
            pass

    def _input_symbol(self, sid: str):
        """点击符号格：用 Unicode 直注把字符送入当前焦点窗口（WPS / 任意编辑器）。"""
        import symbols as sym
        try:
            idx = int(sid.split(":", 1)[1])
        except (ValueError, IndexError):
            return
        item = sym.symbol_at(self.symbol_cat, idx)
        if not item:
            return
        char, name, alt, uni = item
        was_click = self.mouse_mode()
        # v4.08 修复：点击分层窗口发生在鼠标消息过程内，此刻切焦点 + 同步
        # SendInput 会与鼠标/焦点状态交织，字符容易丢失或发到错误窗口。
        # 把「目标窗口 + 字符 + uni标记」排队，交给 timer 6 在消息循环空闲时注入。
        # uni 以 CMD: 开头表示格式命令（选中文字转上标/下标），非可输入字符。
        target = self._symbol_target_hwnd or w.foreground_hwnd()
        self._pending_symbol = (char, target, uni)
        w.user32.KillTimer(self.hwnd, 6)
        w.user32.SetTimer(self.hwnd, 6, 30, None)
        self.flash(sid)
        self.note_bar_activity()
        # 视觉确认：短暂把格子点亮
        self.refresh()

    def _flush_symbol(self):
        """timer 6：在实际目标窗口恢复焦点后注入排队的符号。"""
        pending = self._pending_symbol
        self._pending_symbol = None
        if not pending:
            return
        char, target, uni = pending
        try:
            if target and not w.is_own_window(target):
                w.focus_window(target)
            # 关键修复：用户左手按住 Ctrl/Alt/Shift 弹出面板、右手点符号，注入时
            # 辅助键仍按着。WPS 会把 Unicode 事件解释为 Ctrl+字符 等组合快捷键
            # （执行保存/加粗等命令），而非输入字符；普通对话框不解析组合键所以正常。
            # 注入前先清除辅助键逻辑状态，让目标窗口只收到「无修饰」的字符。
            w.release_modifiers()
            if uni and uni.startswith("CMD:"):
                # 格式命令：对已选中文字套用真上标/下标（Word/WPS 标准快捷键）
                # Ctrl+= 下标，Ctrl+Shift+= 上标。VK_OEM_PLUS(0xBB) 即 "=" 键。
                # v4.10：改用 send_combo（具体左右键+扫描码+分帧），修复 WPS
                # 漏判 Shift 导致 Ctrl+Shift+= 退化成 Ctrl+= 的问题。
                VK_OEM_PLUS = 0xBB
                cmd = uni[4:]
                if cmd == "SUB":
                    w.send_combo([w.VK_CONTROL], VK_OEM_PLUS)
                elif cmd == "SUP":
                    w.send_combo([w.VK_CONTROL, w.VK_SHIFT], VK_OEM_PLUS)
            else:
                # v4.10：WPS/Word 里 Unicode 专用上标字符(⁰⁴⁵⁶⁷⁸⁹⁺⁻…)会 fallback
                # 到全角字体、占位很大。检测目标为 Office 时改用「普通半角字符 +
                # 真上标格式」：输入普通字符→选中它→Ctrl+Shift+=，显示/排版正常。
                exe = w.exe_of_hwnd(target) if target else ""
                is_office = any(k in exe for k in _OFFICE_EXES)
                if is_office and char in _SUPER_TO_PLAIN:
                    self._type_super_formatted(_SUPER_TO_PLAIN[char])
                else:
                    w.send_unicode(char)          # KEYEVENTF_UNICODE，无需 NumLock / Alt 码
        except Exception as e:
            print("符号输入失败：", e)

    def _type_super_formatted(self, plain_char: str):
        """在 Office 中把普通半角字符输入后套用真上标格式。

        流程：输入普通字符 → Shift+← 选中它 → Ctrl+Shift+= 套上标 → → 移开光标。
        用分帧 send_combo 保证 WPS 正确识别组合键；间隔不宜过长以免卡顿 UI。
        """
        import time
        w.send_unicode(plain_char)
        time.sleep(0.06)                                   # 等 WPS 落字
        w.send_combo([w.VK_SHIFT], w.VK_LEFT, 0.025)       # 选中刚输入的字符
        time.sleep(0.04)
        w.send_combo([w.VK_CONTROL, w.VK_SHIFT], 0xBB, 0.025)  # Ctrl+Shift+= 上标
        time.sleep(0.04)
        w.send_combo([], w.VK_RIGHT, 0.02)                 # 光标移到字符后，退出选中

    def toggle_symbols(self, on: bool | None = None, from_bar: bool = False):
        """
        打开 / 关闭符号页。

        v4.09：符号页不再「锁定常驻」，而是跟虚拟键盘同一套显示逻辑——
        按住任意辅助键弹出、松开按 hide_delay_ms 延时消失。开关打开时开启
        可点击并主动弹一次（sticky 保持到用户关闭或按延时设置消失）。
        """
        import symbols as sym
        target = (not self.symbol_mode) if on is None else bool(on)
        if target == self.symbol_mode and self.visible:
            return
        if target:
            # 从控件条进入符号页时同样记下输入目标（此时焦点应仍在外部程序）
            self._remember_input_target()
            self._mouse_click_before_symbols = bool(self.cfg.get("mouse_click", False))
            self.symbol_mode = True
            self.symbol_cat = max(0, min(len(sym.CATEGORIES) - 1, self.symbol_cat))
            self.locked = False               # v4.09：不锁定，跟随延时消失
            self.cfg["mouse_click"] = True    # 符号页必须可点击
            self.overlay.set_click_through(False)
            self.virtual_mods.clear()
            self.detect_context()
            if not self.visible:
                self.combo = self.current_combo() or "Ctrl"
                self.visible = True
            self.sticky = True               # 打开后保持显示，直到用户操作/按设置消失
            self._cache = None
            self.refresh(force=True)
            self.note_bar_activity()         # 给一段宽限，避免刚开就消失
        else:
            self.close_symbols()

    def close_symbols(self):
        """关闭符号页，回到普通键盘（若原本未按住辅助键则收起）。"""
        if not self.symbol_mode:
            return
        self.symbol_mode = False
        self._symbol_base = None
        self.locked = False
        # 恢复进入符号页前的点击模式（符号页强制开启了 mouse_click）
        if self._mouse_click_before_symbols is not None:
            self.cfg["mouse_click"] = self._mouse_click_before_symbols
            self._mouse_click_before_symbols = None
        self._cache = None
        self.hover_sid = None
        self.mouse_down_sid = None
        if not self.held:
            self.hide()
        else:
            self.refresh(force=True)

    def _overlay_mouse(self, hwnd, msg, wp, lp):
        """分层窗口的鼠标回调；未开启点击模式时窗口是穿透的，收不到任何消息"""
        if os.environ.get("KEYHINT_DEBUG") and msg in (
                w.WM_MOUSEMOVE, w.WM_LBUTTONDOWN, w.WM_LBUTTONUP,
                w.WM_RBUTTONUP, w.WM_MOUSEWHEEL, w.WM_SETCURSOR):
            xy = self._local_xy() if msg != w.WM_MOUSEWHEEL else None
            print("覆盖层鼠标消息 0x%04X wp=%d lp=%d xy=%s hit=%s mode=%s"
                  % (msg, int(wp), int(lp), xy,
                     self.hit_test(*xy) if xy and msg in (
                         w.WM_MOUSEMOVE, w.WM_LBUTTONDOWN, w.WM_LBUTTONUP) else "-",
                     self.mouse_mode()), flush=True)
        if not self.mouse_mode() or not self.visible:
            return None
        if msg == w.WM_SETCURSOR:
            lx, ly = self._local_xy()
            zone = self._kb_drag["zone"] if self._kb_drag else self._drag_zone(lx, ly)
            if zone == "move":
                w.user32.SetCursor(w.user32.LoadCursorW(None, w.IDC_SIZEALL))
                return 1
            if zone == "resize":
                w.user32.SetCursor(w.user32.LoadCursorW(None, w.IDC_SIZENWSE))
                return 1
            if self.hover_sid:
                w.user32.SetCursor(w.user32.LoadCursorW(None, w.IDC_HAND))
                return 1
            return None
        if msg == w.WM_MOUSEMOVE:
            if self._kb_drag:
                d = self._kb_drag
                sx, sy = self._screen_xy()
                dx, dy = sx - d["sx"], sy - d["sy"]
                if d["zone"] == "move":
                    self.cfg["kb_pos_x"] = max(0, min(d["ox"] + dx,
                                                      max(0, self.sw - d["cw"])))
                    self.cfg["kb_pos_y"] = max(0, min(d["oy"] + dy,
                                                      max(0, self.sh - d["ch"])))
                else:
                    new_scale = d["scale"] * (d["cw"] + dx) / float(d["cw"])
                    self.cfg["kb_scale"] = round(max(0.5, min(2.0, new_scale)), 3)
                    self.cfg["kb_pos_x"], self.cfg["kb_pos_y"] = d["ox"], d["oy"]
                self._cache = None
                self.refresh(force=True)
                return 0
            sid = self.hit_test(*self._local_xy())
            if sid != self.hover_sid:
                self.hover_sid = sid
                self._cache = None
                self.refresh()
            return 0
        if msg == w.WM_LBUTTONDOWN:
            lx, ly = self._local_xy()
            zone = self._drag_zone(lx, ly)
            if zone:
                sx, sy = self._screen_xy()
                ox, oy, cw, ch = self.overlay.rect
                self._kb_drag = {"zone": zone, "sx": sx, "sy": sy,
                                 "ox": ox, "oy": oy, "cw": cw, "ch": ch,
                                 "scale": float(self.cfg.get("kb_scale", 1.0) or 1.0)}
                w.user32.SetCapture(hwnd)
                self.sticky = True
                w.user32.KillTimer(self.hwnd, 4)   # 拖拽期间不自动收起
                return 0
            self.mouse_down_sid = self.hit_test(lx, ly)
            self.reset_hide_timer()
            return 0
        if msg == w.WM_LBUTTONUP:
            if self._kb_drag:
                self._finish_kb_drag(hwnd)
                return 0
            sid = self.hit_test(*self._local_xy())
            if sid and sid == self.mouse_down_sid:
                self.click_key(sid)
            self.mouse_down_sid = None
            return 0
        if msg == w.WM_RBUTTONUP:
            x, y = self._local_xy()
            ox, oy = self.overlay.rect[0], self.overlay.rect[1]
            self._right_click_sid = self.hit_test(x, y)
            w.user32.PostMessageW(self.hwnd, w.WM_APP + 21,
                                  w.WPARAM(int(ox + x)), w.LPARAM(int(oy + y)))
            return 0
        if msg == w.WM_MOUSEWHEEL:
            # 滚轮不再调节透明度（改用键盘右上角滑杆）；转发给下层应用正常滚动
            target = w.user32.GetForegroundWindow()
            if target and target not in (hwnd, self.controlbar.hwnd):
                w.user32.PostMessageW(target, w.WM_MOUSEWHEEL, wp, lp)
            return 0
        return None

    def on_key(self, vk: int, down: bool, own_injected: bool = False):
        # 点击键帽时由本程序注入的按键，钩子直接忽略，避免「自己触发自己」
        if own_injected:
            return
        mod = w.MODIFIER_VK.get(vk)
        if mod:
            # v4.09：符号页下任意辅助键（Ctrl/Alt/Shift/Win）都只当作普通弹出，
            # 不再有 Alt 特判——按任意键弹出的面板都能点符号。
            if down:
                if mod in self.held:
                    return                       # 系统自动重复，忽略
                self.held.add(mod)
                if not self.cfg["enabled"] or not self.cfg["modifiers"].get(mod, True):
                    return
                # v4.08 修复：在弹出面板前记住「用户正在打字的窗口」。
                # 只有它才是符号/快捷键应当送达的目标；点击覆盖层后焦点会丢，
                # 注入时再把这个窗口的前台焦点恢复回来。
                self._remember_input_target()
                if self.visible and not self.locked:
                    self.sticky = False
                    w.user32.KillTimer(self.hwnd, 4)
                    self.combo = self.current_combo()
                    self.refresh(force=True)     # 双组合键实时升级
                elif not self.locked and self.popup_enabled():
                    self.schedule_show()
            else:
                self.held.discard(mod)
                if not self.held:
                    self.kill_show_timer()
                    if self.locked or self._settings_preview:
                        return
                    self.schedule_hide()     # 统一按 hide_delay_ms 倒计时
                elif self.visible and not self.locked:
                    self.combo = self.current_combo()
                    self.refresh(force=True)
            return

        # v4.01：弹出开关快捷键，优先于普通组合键与 ESC 收起逻辑
        mods, hk_vk = self._hotkey_parts()
        if down and mods is not None and vk == hk_vk and self.current_mods() == mods:
            self.toggle_popup()
            return

        if not down:
            return
        sid = vk_to_sid(vk)
        # Ctrl+Alt+H：锁定 / 解锁速查面板
        if sid == "H" and self.held == {"Ctrl", "Alt"}:
            self.toggle_lock()
            return
        # Ctrl+Alt+M：鼠标点击 / 穿透；Ctrl+Alt+O：透明度滑块
        if sid == "M" and self.held == {"Ctrl", "Alt"}:
            self.set_mouse_click(not self.cfg.get("mouse_click", False))
            save_config(self.cfg)
            return
        if sid == "O" and self.held == {"Ctrl", "Alt"}:
            self.open_opacity_dialog()
            return
        if sid == "ESC" and self.visible and (self.locked or self.sticky
                                              or self._settings_preview
                                              or self._bar_grace or not self.held):
            if self.symbol_mode:
                self.close_symbols()
                return
            self.locked = False
            self._settings_preview = False
            self.hide()
            return
        if self.visible:
            self.flash(sid)                      # 按组合键：对应键帽闪光确认，键盘不消失
        else:
            self.kill_show_timer()               # 短按快捷键不打扰

    def _debug_click(self, sid="C"):
        """自检用：在本进程坐标系内把光标移到键帽中心并产生一次真实鼠标点击"""
        for k in self.hit_keys:
            if canonical(k.sid) != sid:
                continue
            sx = self.overlay.rect[0] + int(k.x + k.w / 2)
            sy = self.overlay.rect[1] + int(k.y + k.h / 2)
            w.user32.SetCursorPos(sx, sy)
            w.user32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
            w.user32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
            print("调试点击 %s -> 屏幕 (%d,%d)" % (sid, sx, sy), flush=True)
            return True
        return False

    def _debug_bar_click(self, which="click"):
        """自检用：真实鼠标点击右上角控件（验证该窗口确实不穿透）"""
        if not self.controlbar.visible:
            print("调试：控件条未显示", flush=True)
            return False
        x, y = self.controlbar.screen_point(which)
        w.user32.SetCursorPos(x, y)
        w.user32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
        w.user32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
        print("调试点击控件条 %s -> 屏幕 (%d,%d)" % (which, x, y), flush=True)
        return True

    def _debug_bar_drag(self, ratio):
        """自检用：真实鼠标按下 + 移动 + 抬起，拖动透明度滑杆"""
        if not self.controlbar.visible:
            return False
        ratio = max(0.0, min(1.0, ratio))
        st = self.bar_state()
        cur = (st["opacity"] - 10) / 90.0 if st["fade"] else 1.0
        x0, y0 = self.controlbar.track_point(cur)
        x1, y1 = self.controlbar.track_point(ratio)
        w.user32.SetCursorPos(x0, y0)
        w.user32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
        w.user32.SetCursorPos(x1, y1)
        L = self.controlbar.layout
        lx = int(L["track_x0"] + (L["track_x1"] - L["track_x0"]) * ratio)
        lp = (L["track_y"] << 16) | (lx & 0xFFFF)
        w.user32.SendMessageW(self.controlbar.hwnd, w.WM_MOUSEMOVE,
                              w.WPARAM(0), w.LPARAM(lp))
        w.user32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
        print("调试拖动滑杆 -> %d%%" % self.cfg.get("opacity", 92), flush=True)
        return True

    # ------------------------------------------------------------ 消息处理
    def _wndproc_impl(self, hwnd, msg, wp, lp):
        try:
            # v4.07：任务栏代理窗口——点击任务栏按钮时弹出托盘同款菜单
            if self.taskbar_hwnd and hwnd == self.taskbar_hwnd:
                if msg == w.WM_ACTIVATE and (int(wp) & 0xFFFF) in (1, 2):
                    w.taskbar_show(self.taskbar_hwnd)  # 立刻缩回，避免露出 1x1 窗口
                    cmd = w.show_popup_menu(self.hwnd, self.menu_items())
                    if cmd:
                        self.handle_cmd(int(cmd))
                    return 0
                if msg == w.WM_CLOSE:
                    w.taskbar_show(self.taskbar_hwnd)  # 关闭按钮＝隐藏，不退出程序
                    return 0
                return w.user32.DefWindowProcW(hwnd, msg, wp, lp)
            if msg == w.WM_APP + 1:
                flags = int(lp)
                self.on_key(int(wp), bool(flags & 1), bool(flags & 4))
                return 0
            if msg == w.WM_TIMER:
                tid = int(wp)
                if tid == 1:
                    self.on_delay()
                elif tid == 2:
                    self.flash_sid = None
                    if self.visible:
                        self.refresh(force=True)
                    w.user32.KillTimer(hwnd, 2)
                elif tid == 3:
                    if self._demo_timer:
                        self._demo_timer = False
                        if not self.locked and not self.sticky:
                            self.hide()
                    w.user32.KillTimer(hwnd, 3)
                elif tid == 4:
                    # 延时到期：只有没有正在操作控件条、没按住辅助键时才收起
                    w.user32.KillTimer(hwnd, 4)
                    if self.controlbar.active:
                        self.note_bar_activity()
                    elif (self.sticky and not self.locked and not self.held
                          and not self._settings_preview):
                        self.hide()
                elif tid == 5:
                    # 控件条宽限结束：隐藏交给 timer 4，这里只清状态 / 续期
                    w.user32.KillTimer(hwnd, 5)
                    if self.controlbar.active:
                        self.note_bar_activity()
                    else:
                        self._bar_grace = False
                elif tid == 6:
                    # v4.08：符号延迟注入（在鼠标消息处理结束后执行）
                    w.user32.KillTimer(hwnd, 6)
                    self._flush_symbol()
                elif tid == 7:
                    # v4.07：托盘图标保活刷新（防止被资源管理器折叠隐藏）
                    try:
                        self.tray.refresh()
                    except Exception:
                        pass
                return 0
            if msg == w.WM_APP + 77 and os.environ.get("KEYHINT_DEBUG"):
                self._debug_click("C")
                return 0
            if msg == w.WM_APP + 78 and os.environ.get("KEYHINT_DEBUG"):
                self._debug_bar_click({0: "custom", 1: "symbols", 2: "click",
                                       3: "fade", 4: "delay", 5: "track"}.get(int(wp), "custom"))
                return 0
            if msg == w.WM_APP + 79 and os.environ.get("KEYHINT_DEBUG"):
                self._debug_bar_drag(int(lp) / 1000.0)
                return 0
            if msg == w.WM_APP + 21:
                # 覆盖层右键：键帽上直接进入自定义快捷键设置；空白区显示托盘菜单
                x = C.c_int(int(wp)).value
                y = C.c_int(int(lp)).value
                sid = getattr(self, "_right_click_sid", None)
                if sid and not self.symbol_mode and not str(sid).startswith(("CAT:", "SYM:")):
                    items = [
                        ("info", "键帽 %s  ·  自定义快捷键" % sid),
                        ("sep",),
                        (ID_CUSTOM_EDIT_KEY, "自定义设置此键…", False, True),
                        (ID_CUSTOM_MANAGE, "管理多套自定义面板…", False, True),
                        ("sep",),
                        (ID_CUSTOM_TRAY_MENU, "显示托盘菜单", False, True),
                    ]
                    cmd = w.show_popup_menu(hwnd, items, x, y)
                    if cmd == ID_CUSTOM_EDIT_KEY:
                        self.open_custom_key_editor(sid, x, y)
                    elif cmd == ID_CUSTOM_MANAGE:
                        self.open_custom_panel_manager()
                    elif cmd == ID_CUSTOM_TRAY_MENU:
                        cmd = w.show_popup_menu(hwnd, self.menu_items(), x, y)
                        if cmd:
                            self.handle_cmd(int(cmd))
                else:
                    cmd = w.show_popup_menu(hwnd, self.menu_items(), x, y)
                    if cmd:
                        self.handle_cmd(int(cmd))
                self._right_click_sid = None
                return 0
            if msg == w.WM_APP + 20:
                mouse = int(lp) & 0xFFFF
                if mouse in (w.WM_RBUTTONUP, w.WM_LBUTTONUP, w.WM_LBUTTONDBLCLK):
                    if mouse == w.WM_LBUTTONDBLCLK:
                        self.toggle_lock()
                    else:
                        cmd = w.show_popup_menu(hwnd, self.menu_items())
                        if cmd:
                            self.handle_cmd(int(cmd))
                return 0
            if msg == w.WM_SETTINGCHANGE:
                self._cache = None
                return 0
            if msg == w.WM_DESTROY:
                w.user32.PostQuitMessage(0)
                return 0
        except Exception as e:
            print("WndProc 错误：", e)
        return w.user32.DefWindowProcW(hwnd, msg, wp, lp)

    def cleanup(self):
        try:
            self.op_dialog.close()
        except Exception:
            pass
        try:
            self.delay_dialog.close()
        except Exception:
            pass
        try:
            self.hotkey_dialog.close()
        except Exception:
            pass
        try:
            self.font_dialog.close()
        except Exception:
            pass
        try:
            self.settings_dialog.close()
        except Exception:
            pass
        try:
            self.hook.stop()
        except Exception:
            pass
        try:
            if self.taskbar_hwnd:
                w.taskbar_destroy(self.taskbar_hwnd)
                self.taskbar_hwnd = 0
        except Exception:
            pass
        try:
            self.tray.remove()
        except Exception:
            pass
        try:
            self.overlay.close()
        except Exception:
            pass
        try:
            self.controlbar.close()
        except Exception:
            pass
        for name in ("custom_key_dialog", "custom_panel_dialog"):
            try:
                dlg = getattr(self, name, None)
                if dlg and dlg.hwnd:
                    w.user32.DestroyWindow(dlg.hwnd)
            except Exception:
                pass

    def run(self):
        try:
            w.message_loop()
        finally:
            self.cleanup()


# ---------------------------------------------------------------- 演示模式
def demo(cfg, combo="Ctrl", app="word", seconds=10, shot=False, symbols=False):
    w.enable_dpi_awareness()
    sw, sh = w.screen_size()
    cfg["screen_w"], cfg["screen_h"] = sw, sh
    overlay = w.LayeredWindow("KeyHintDemoOverlay")
    if symbols:
        # v4.08：符号页演示——真实分层窗口渲染符号页 + 控件条，用于自检截图
        import symbol_render as symr
        cfg["mouse_click"] = True
        data, cw, ch, x, y, cells = symr.render_bgra(cfg, 0)
        overlay.blit(data, cw, ch, x, y)
        st = dict(cfg); st["symbol_mode"] = True
        bar = controlbar.ControlBar(
            get_state=lambda: st,
            on_toggle_click=lambda: None, on_toggle_fade=lambda: None,
            on_opacity=lambda v: st.update(opacity=v),
            on_commit=lambda: None, on_activity=lambda: None,
            on_cycle_delay=lambda: None, on_toggle_symbols=lambda: None)
        bar.place(x, y, cw, ch, sw)
        bar.refresh(force=True)   # 确保控件条置于符号页之上
        print("符号页演示：画布=%dx%d 位置=(%d,%d) 符号总数=%d"
              % (cw, ch, x, y, __import__("symbols").count()))
        if shot:
            import threading as _t, time as _time
            def _grab():
                _time.sleep(1.2)
                try:
                    from PIL import ImageGrab
                    dest = str(HERE / "_symbol_screen_check.png")
                    ImageGrab.grab().save(dest)
                    print("符号页屏幕截图：", dest)
                except Exception as e:
                    print("截图失败：", e)
            _t.Thread(target=_grab, daemon=True).start()
        def _sproc(hwnd, msg, wp, lp):
            if msg == w.WM_TIMER and int(wp) == 7:
                w.user32.PostQuitMessage(0)
                return 0
            if msg == w.WM_DESTROY:
                return 0
            return w.user32.DefWindowProcW(hwnd, msg, wp, lp)
        _cb = w.WNDPROC(_sproc)
        _h = w.create_message_window("KeyHintSymDemo", "KeyHintSymDemo", _cb)
        w.user32.SetTimer(_h, 7, seconds * 1000, None)
        try:
            w.message_loop()
        finally:
            bar.close()
            overlay.close()
        return
    detect_exe = w.foreground_exe()
    key = app if app in shortcuts.APP_PROFILES or app == "generic" else shortcuts.detect_app(detect_exe)
    mapping = shortcuts.resolve(combo, key, cfg.get("custom_shortcuts"))
    mods = set(combo.split("+"))
    data, cw, ch, x, y = render.render(cfg, combo, mapping,
                                       shortcuts.app_display_name(key),
                                       w.input_language(), mods, False, None)
    overlay.blit(data, cw, ch, x, y)
    # 演示模式也把右上角控件条画出来（静态展示，交互请用常驻托盘模式）
    bar = controlbar.ControlBar(
        get_state=lambda: cfg,
        on_toggle_click=lambda: None, on_toggle_fade=lambda: None,
        on_opacity=lambda v: cfg.update(opacity=v),
        on_commit=lambda: None, on_activity=lambda: None,
        on_cycle_delay=lambda: cfg.update(
            hide_delay_ms=controlbar.next_delay_preset(
                cfg.get("hide_delay_ms", 0))))
    bar.place(x, y, cw, ch, sw)
    print("演示中：combo=%s 情境=%s 画布=%dx%d 位置=(%d,%d) 指令数=%d"
          % (combo, key, cw, ch, x, y, len(mapping)))

    if shot:
        import threading
        import time

        def grab():
            time.sleep(1.2)
            try:
                from PIL import ImageGrab
                dest = str(HERE / "_screen_check.png")
                ImageGrab.grab().save(dest)
                print("真实屏幕截图已保存：", dest)
            except Exception as e:
                print("截图失败：", e)
        threading.Thread(target=grab, daemon=True).start()

    def proc(hwnd, msg, wp, lp):
        if msg == w.WM_TIMER and int(wp) == 7:
            w.user32.PostQuitMessage(0)
            return 0
        if msg == w.WM_DESTROY:
            return 0
        return w.user32.DefWindowProcW(hwnd, msg, wp, lp)

    cb = w.WNDPROC(proc)
    hwnd = w.create_message_window("KeyHintDemo", "KeyHintDemo", cb)
    w.user32.SetTimer(hwnd, 7, seconds * 1000, None)
    try:
        w.message_loop()
    finally:
        bar.close()
        overlay.close()


_INSTANCE_MUTEX = None


def _acquire_single_instance() -> bool:
    """安装版防止重复启动多个托盘实例；源码自检会起多进程，故只在打包版生效。"""
    global _INSTANCE_MUTEX
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.argtypes = [C.c_void_p, C.c_int, C.c_wchar_p]
    k32.CreateMutexW.restype = C.c_void_p
    h = k32.CreateMutexW(None, 0, "Local\\KeyHint_SingleInstance_v4")
    if not h:
        return True
    if C.get_last_error() == 183:        # ERROR_ALREADY_EXISTS
        return False
    _INSTANCE_MUTEX = h                 # 保持句柄，进程存活期间互斥有效
    return True


def main():
    args = sys.argv[1:]
    if IS_FROZEN and "--demo" not in args and not _acquire_single_instance():
        print("KeyHint 已在运行，忽略重复启动。")
        return
    cfg = load_config()
    if "--demo" in args:
        def opt(name, default):
            if name in args:
                i = args.index(name)
                if i + 1 < len(args):
                    return args[i + 1]
            return default
        demo(cfg, opt("--combo", "Ctrl"), opt("--app", "word"),
             int(opt("--seconds", "10")), shot="--shot" in args,
             symbols="--symbols" in args)
        return
    if "--off" in args:
        cfg["enabled"] = False
    if "--center" in args:
        cfg["position"] = "center"
    if "--click" in args:                    # 命令行临时开启点击模式（不写盘）
        cfg["mouse_click"] = True
    app = KeyHintApp(cfg, start_disabled="--off" in args)
    print("%s v%s 已启动。按住 Ctrl / Shift / Alt / Win 查看指令，右键托盘图标设置。"
      % (APP_NAME, APP_VERSION))
    app.run()


if __name__ == "__main__":
    main()
