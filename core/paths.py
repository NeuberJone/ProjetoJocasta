from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def app_dir() -> Path:
    """
    Pasta do app.
    - Dev: raiz do projeto
    - EXE (PyInstaller): pasta onde está o executável
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def config_path() -> Path:
    """
    Caminho do config.json (local do app).
    Mantém simples e portátil: o config fica junto do exe/projeto.
    OBS: o PXCore config principal hoje está em APPDATA via core.config.
    """
    return app_dir() / "config.json"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def open_in_explorer(path: Path) -> None:
    """Abre a pasta no Explorer (Windows)."""
    path = path.resolve()
    os.startfile(str(path))  # noqa: S606 (Windows-only)


# =========================
# PXCore base + estrutura
# =========================

@dataclass(frozen=True)
class PxDirs:
    base: Path
    lists: Path
    json: Path
    logs: Path
    temp: Path
    data: Path
    pdf: Path
    print: Path
    exports: Path  # legado


def get_px_dirs(base_dir: str | Path) -> PxDirs:
    base = Path(str(base_dir))
    return PxDirs(
        base=base,
        lists=base / "lists",
        json=base / "json",
        logs=base / "logs",
        temp=base / "temp",
        data=base / "data",
        pdf=base / "pdf",
        print=base / "print",
        exports=base / "exports",
    )


def y_m(dt: datetime | None = None) -> tuple[str, str]:
    dt = dt or datetime.now()
    return dt.strftime("%Y"), dt.strftime("%m")


def pdf_rolls_dir(base_dir: str | Path, module: str, dt: datetime | None = None) -> Path:
    """
    PDFs (comprovantes): base/pdf/<module>/rolls/YYYY/MM
    """
    y, m = y_m(dt)
    return ensure_dir(Path(str(base_dir)) / "pdf" / module / "rolls" / y / m)


def print_jpg_dir(base_dir: str | Path, module: str, dt: datetime | None = None) -> Path:
    """
    Operação de impressão (JPG etc): base/print/<module>/jpg/YYYY/MM
    """
    y, m = y_m(dt)
    return ensure_dir(Path(str(base_dir)) / "print" / module / "jpg" / y / m)


def temp_module_dir(base_dir: str | Path, module: str) -> Path:
    """
    Temporários por módulo: base/temp/<module>
    """
    return ensure_dir(Path(str(base_dir)) / "temp" / module)