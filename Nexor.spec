# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all
datas, binaries, hidden = collect_all("tkinterdnd2")
from core.version import __version__

a = Analysis(
    ['Nexor.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden + [
        "modules.planejador",
        "modules.operacao",
        "modules.registros",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name=f'Nexor-{__version__}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
