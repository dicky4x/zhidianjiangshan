# -*- mode: python ; coding: utf-8 -*-
# 使用相对路径：spec 位于 installer/，因此 ROOT 为项目根目录。
# PyInstaller 执行 spec 时会注入 SPECPATH（spec 所在目录），没有 __file__。
# 这样仓库在任意电脑 clone 后都能直接打包，不泄露本机用户名。
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / 'app.py')],
    pathex=[],
    binaries=[],
    datas=[(str(ROOT / 'keyhint.ico'), '.'),
           (str(ROOT / 'config.default.json'), '.'),
           (str(ROOT / 'README.md'), '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='KeyHint',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(ROOT / 'keyhint.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='KeyHint',
)
