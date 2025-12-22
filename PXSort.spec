# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

tkdnd_datas, tkdnd_binaries, tkdnd_hidden = collect_all('tkinterdnd2')

a = Analysis(
    ['PXSort.py'],
    pathex=[],
    binaries=tkdnd_binaries,
    datas=tkdnd_datas,
    hiddenimports=tkdnd_hidden,
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
    a.binaries,
    a.datas,
    [],
    name='PXSort',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
