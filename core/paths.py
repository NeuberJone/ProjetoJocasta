# core/paths.py
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def app_dir() -> Path:
    """
    Pasta do app.
    - Dev: pasta do projeto
    - EXE (PyInstaller): pasta onde está o executável
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def config_path() -> Path:
    """
    Caminho do config.json (local do app).
    Mantém simples e portátil: o config fica junto do exe/projeto.
    """
    return app_dir() / "config.json"


def default_base_dir() -> Path:
    """
    Padrão que você quer: C:\\PXCore
    """
    return Path(r"C:\PXCore")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def open_in_explorer(path: Path) -> None:
    """
    Abre a pasta no Explorer (Windows).
    """
    path = path.resolve()
    os.startfile(str(path))  # noqa: S606 (Windows-only)
