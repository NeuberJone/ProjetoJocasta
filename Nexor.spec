# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, collect_submodules, tcl_tk
from pathlib import Path
import sys

_project_root = Path.cwd().resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

datas, binaries, hidden = collect_all("tkinterdnd2")
from core.version import __version__

# Algumas instalações portáteis do Python 3.13 não são reconhecidas pelo
# hook padrão do PyInstaller como Tcl/Tk válidos. O Nexor é uma aplicação
# Tkinter, então o runtime precisa carregar explicitamente as bibliotecas e
# os scripts Tcl/Tk no build congelado.
_python_home = Path(sys.base_prefix)
_tcl_root = _python_home / "tcl"
_dll_root = _python_home / "DLLs"
for _name in ("tcl86t.dll", "tk86t.dll"):
    _path = _dll_root / _name
    if _path.exists():
        binaries.append((str(_path), "."))
# Alimenta o mesmo objeto usado pelos hooks oficiais. Isso evita que a
# sondagem isolada do PyInstaller descarte o pacote tkinter quando o Tcl
# local não consegue abrir uma janela durante a análise.
_tcl_info = tcl_tk.tcltk_info
_tcl_info.available = True
_tcl_info.tkinter_extension_file = str(_dll_root / "_tkinter.pyd")
_tcl_info.tcl_version = (8, 6)
_tcl_info.tk_version = (8, 6)
_tcl_info.tcl_threaded = True
_tcl_info.tcl_data_dir = str(_tcl_root / "tcl8.6")
_tcl_info.tk_data_dir = str(_tcl_root / "tk8.6")
_tcl_info.tcl_module_dir = str(_tcl_root / "tcl8")
_tcl_info.tcl_shared_library = str(_dll_root / "tcl86t.dll")
_tcl_info.tk_shared_library = str(_dll_root / "tk86t.dll")
_tcl_info.data_files = (
    tcl_tk.TclTkInfo._collect_files_from_directory(
        _tcl_info.tcl_data_dir, prefix=tcl_tk.TclTkInfo.TCL_ROOTNAME,
        excludes=["demos", "*.lib", "tclConfig.sh"],
    )
    + tcl_tk.TclTkInfo._collect_files_from_directory(
        _tcl_info.tk_data_dir, prefix=tcl_tk.TclTkInfo.TK_ROOTNAME,
        excludes=["demos", "*.lib", "tkConfig.sh"],
    )
    + tcl_tk.TclTkInfo._collect_files_from_directory(
        _tcl_info.tcl_module_dir, prefix="tcl8",
    )
)

hidden += [
    *collect_submodules("tkinter"),
]

a = Analysis(
    ['Nexor.py'],
    pathex=[str(_project_root)],
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
