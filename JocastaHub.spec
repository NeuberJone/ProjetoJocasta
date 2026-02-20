# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all
datas, binaries, hidden = collect_all("tkinterdnd2")
from core.version import __version__

a = Analysis(
    ['JocastaHub.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden + [
        "modules.PXFlow",
        "modules.PXComposer",
        "modules.PXDupe",
        "modules.PXPrint",
        "modules.PXPrintLogs",
        "modules.PXOrderList",
        "modules.PXBridge",
        "modules.PXList",
        "modules.PXListLite",
        "modules.PXListPlus",
        "modules.PXSort",
        "modules.PXSortLite",
        "modules.PXTotaList",
        "modules.PXSearchOrders",
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
    name=f'JocastaHub-{__version__}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
