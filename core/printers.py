from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from core.migrate import migrate_legacy_path


def _store_path() -> Path:
    appdata = Path(os.environ.get("APPDATA") or str(Path.home()))
    base = appdata / "Nexor"
    base.mkdir(parents=True, exist_ok=True)
    migrate_legacy_path(appdata / "ProjetoJocasta" / "printers.json", base / "printers.json")
    return base / "printers.json"


@dataclass
class Printer:
    key: str
    name: str
    display_name: str
    speed_m_min: float = 1.5
    notes: str = ""
    jpg_output_dir: str = ""
    jpg_output_filename: str = ""


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "impressora"


def _default_printers() -> List[dict]:
    return [
        {"key": "m1", "name": "Máquina 1", "display_name": "M1", "speed_m_min": 1.5, "notes": "", "jpg_output_dir": "", "jpg_output_filename": ""},
        {"key": "m2", "name": "Máquina 2", "display_name": "M2", "speed_m_min": 1.5, "notes": "", "jpg_output_dir": "", "jpg_output_filename": ""},
    ]


def _coerce(d: dict) -> Printer:
    return Printer(
        key=str(d.get("key", "")) or _slugify(str(d.get("display_name", "")) or str(d.get("name", ""))),
        name=str(d.get("name", "")),
        display_name=str(d.get("display_name", "")),
        speed_m_min=float(d.get("speed_m_min", 1.5) or 1.5),
        notes=str(d.get("notes", "")),
        jpg_output_dir=str(d.get("jpg_output_dir", "") or ""),
        jpg_output_filename=str(d.get("jpg_output_filename", "") or ""),
    )


def _save_raw(data: List[dict]) -> None:
    _store_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_printers() -> List[Printer]:
    p = _store_path()
    if not p.exists():
        data = _default_printers()
        _save_raw(data)
        return [_coerce(d) for d in data]

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list) and raw:
            return [_coerce(d) for d in raw if isinstance(d, dict)]
    except Exception:
        pass

    data = _default_printers()
    _save_raw(data)
    return [_coerce(d) for d in data]


def save_printers(printers: List[Printer]) -> None:
    _save_raw([asdict(p) for p in printers])


def add_or_update_printer(
    printers: List[Printer],
    *,
    key: Optional[str],
    name: str,
    display_name: str,
    speed_m_min: float,
    notes: str = "",
    jpg_output_dir: str = "",
    jpg_output_filename: str = "",
) -> List[Printer]:
    """
    Retorna uma NOVA lista com o printer adicionado (key vazio/None) ou
    atualizado (key existente). Não grava em disco — use save_printers().
    """
    name = name.strip()
    display_name = display_name.strip()
    jpg_output_dir = (jpg_output_dir or "").strip()
    jpg_output_filename = (jpg_output_filename or "").strip()
    if not name:
        raise ValueError("Informe o nome da impressora.")
    if not display_name:
        raise ValueError("Informe o nome de exibição (ex.: M1).")
    if speed_m_min <= 0:
        raise ValueError("Velocidade deve ser maior que zero.")

    out = list(printers)

    if key:
        for i, pr in enumerate(out):
            if pr.key == key:
                out[i] = Printer(
                    key=pr.key, name=name, display_name=display_name,
                    speed_m_min=speed_m_min, notes=notes,
                    jpg_output_dir=jpg_output_dir, jpg_output_filename=jpg_output_filename,
                )
                _check_unique_display_name(out)
                return out
        raise ValueError("Impressora não encontrada para atualizar.")

    new_key = _slugify(display_name)
    if any(pr.key == new_key for pr in out):
        suffix = 2
        while any(pr.key == f"{new_key}_{suffix}" for pr in out):
            suffix += 1
        new_key = f"{new_key}_{suffix}"

    out.append(Printer(
        key=new_key, name=name, display_name=display_name,
        speed_m_min=speed_m_min, notes=notes,
        jpg_output_dir=jpg_output_dir, jpg_output_filename=jpg_output_filename,
    ))
    _check_unique_display_name(out)
    return out


def _check_unique_display_name(printers: List[Printer]) -> None:
    seen = {}
    for pr in printers:
        low = pr.display_name.strip().lower()
        if low in seen and seen[low] != pr.key:
            raise ValueError(f"Já existe uma impressora com o nome de exibição '{pr.display_name}'.")
        seen[low] = pr.key


def remove_printer(printers: List[Printer], key: str) -> List[Printer]:
    return [p for p in printers if p.key != key]


def find_printer_by_display_name(display_name: str, printers: Optional[List[Printer]] = None) -> Optional[Printer]:
    printers = printers if printers is not None else load_printers()
    target = (display_name or "").strip().lower()
    return next((p for p in printers if p.display_name.strip().lower() == target), None)
