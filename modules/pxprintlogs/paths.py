from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from core.config import load_config
from core.paths import pdf_rolls_dir, print_jpg_dir, temp_module_dir

MODULE_NAME = "PXPrintLogs"


def pxcore_base_dir() -> Path:
    cfg = load_config()
    base_dir = getattr(cfg, "base_dir", None) or r"C:\PXCore"
    return Path(base_dir)


def pdf_dir(dt: datetime) -> Path:
    return pdf_rolls_dir(pxcore_base_dir(), MODULE_NAME, dt)


def jpg_dir(dt: datetime) -> Path:
    return print_jpg_dir(pxcore_base_dir(), MODULE_NAME, dt)


def temp_dir() -> Path:
    return temp_module_dir(pxcore_base_dir(), MODULE_NAME)


def sanitize_filename(name: str) -> str:
    bad = r'\/:*?"<>|'
    for ch in bad:
        name = name.replace(ch, "_")
    name = re.sub(r"\s+", " ", name).strip()
    return name


def versioned_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    m = re.search(r"_v(\d+)$", stem, flags=re.IGNORECASE)
    base = stem[:m.start()] if m else stem

    n = 2
    while True:
        cand = path.with_name(f"{base}_v{n}{path.suffix}")
        if not cand.exists():
            return cand
        n += 1