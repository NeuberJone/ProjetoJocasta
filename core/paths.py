# core/paths.py
from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

from core.config import load_config

_INVALID_WIN = re.compile(r'[\\/:*?"<>|]')


def is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def app_dir() -> Path:
    """Pasta do app.
    - Dev: pasta do projeto
    - EXE (PyInstaller): pasta onde está o executável
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


# Mantido por compatibilidade (evite usar para config do PXCore)
def config_path() -> Path:
    """Config LOCAL do app (legado).
    Atenção: o config oficial do PXCore fica em APPDATA (core/config.py).
    """
    return app_dir() / "config.json"


def default_base_dir() -> Path:
    """Padrão que você quer: C:\PXCore"""
    return Path(r"C:\PXCore")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def open_in_explorer(path: Path) -> None:
    """Abre a pasta no Explorer (Windows)."""
    path = path.resolve()
    os.startfile(str(path))  # noqa: S606 (Windows-only)


def pxcore_base_dir() -> Path:
    cfg = load_config()
    return Path(cfg.base_dir)


def safe_name(name: str, *, fallback: str = "SEM_NOME") -> str:
    s = (name or "").strip()
    if not s:
        s = fallback
    s = _INVALID_WIN.sub("-", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def ym_from_dt(dt: datetime | date | None) -> tuple[str, str]:
    if dt is None:
        dt = datetime.now()
    if isinstance(dt, date) and not isinstance(dt, datetime):
        y = dt.year
        m = dt.month
    else:
        y = int(dt.year)
        m = int(dt.month)
    return f"{y:04d}", f"{m:02d}"


def pdf_dir(module_name: str, *, category: str = "rolls", dt: datetime | date | None = None) -> Path:
    """Diretório SOMENTE PDFs:
    <base>/pdf/<Module>/<category>/YYYY/MM
    """
    base = pxcore_base_dir()
    y, m = ym_from_dt(dt)
    out = base / "pdf" / safe_name(module_name) / safe_name(category) / y / m
    ensure_dir(out)
    return out


def print_dir(module_name: str, *, kind: str = "jpg", dt: datetime | date | None = None) -> Path:
    """Diretório operacional (impressão):
    <base>/print/<Module>/<kind>/YYYY/MM
    """
    base = pxcore_base_dir()
    y, m = ym_from_dt(dt)
    out = base / "print" / safe_name(module_name) / safe_name(kind) / y / m
    ensure_dir(out)
    return out


def logs_dir(module_name: str, *, category: str = "imported", dt: datetime | date | None = None) -> Path:
    """Diretório de logs brutos/diagnóstico:
    <base>/logs/<Module>/<category>/YYYY/MM
    """
    base = pxcore_base_dir()
    y, m = ym_from_dt(dt)
    out = base / "logs" / safe_name(module_name) / safe_name(category) / y / m
    ensure_dir(out)
    return out