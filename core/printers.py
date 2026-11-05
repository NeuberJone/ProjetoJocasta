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
    # Nome do computador que gera os logs desta impressora (campo
    # "ComputerName" no log .txt) — quando cadastrado, a Operação usa isso
    # pra sugerir automaticamente qual impressora é a dona dos logs
    # importados, em vez do operador ter que escolher na mão toda vez.
    computer_name: str = ""
    jpg_output_dir: str = ""
    jpg_output_filename: str = ""
    # Pasta onde esta impressora grava os logs .txt — quando cadastrada, a
    # Operação abre o diálogo de "Importar logs" já nessa pasta (em vez da
    # última pasta usada no Windows), bastando selecionar os arquivos.
    log_import_dir: str = ""
    # "Log adicional": algumas máquinas (ex.: M1) só registram o
    # processamento no log por-arquivo — quem imprime de fato é outro
    # programa, que grava um log diário separado nessa pasta. Quando
    # marcado, a Operação cruza os dois logs pra confirmar a impressão real.
    secondary_log_enabled: bool = False
    secondary_log_folder: str = ""
    # Orientação (0/90/180/270) do JPG de registro gerado para esta
    # impressora — cada máquina pode precisar receber o arquivo girado
    # de um jeito diferente.
    jpg_rotation: int = 0


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
        computer_name=str(d.get("computer_name", "") or ""),
        jpg_output_dir=str(d.get("jpg_output_dir", "") or ""),
        jpg_output_filename=str(d.get("jpg_output_filename", "") or ""),
        log_import_dir=str(d.get("log_import_dir", "") or ""),
        secondary_log_enabled=bool(d.get("secondary_log_enabled", False)),
        secondary_log_folder=str(d.get("secondary_log_folder", "") or ""),
        jpg_rotation=_coerce_rotation(d.get("jpg_rotation", 0)),
    )


def _coerce_rotation(value: object) -> int:
    try:
        rotation = int(value) % 360
    except (TypeError, ValueError):
        return 0
    return rotation if rotation in (0, 90, 180, 270) else 0


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
    computer_name: str = "",
    jpg_output_dir: str = "",
    jpg_output_filename: str = "",
    log_import_dir: str = "",
    secondary_log_enabled: bool = False,
    secondary_log_folder: str = "",
    jpg_rotation: int = 0,
) -> List[Printer]:
    """
    Retorna uma NOVA lista com o printer adicionado (key vazio/None) ou
    atualizado (key existente). Não grava em disco — use save_printers().
    """
    name = name.strip()
    display_name = display_name.strip()
    computer_name = (computer_name or "").strip()
    jpg_output_dir = (jpg_output_dir or "").strip()
    jpg_output_filename = (jpg_output_filename or "").strip()
    log_import_dir = (log_import_dir or "").strip()
    secondary_log_folder = (secondary_log_folder or "").strip()
    if not name:
        raise ValueError("Informe o nome da impressora.")
    if not display_name:
        raise ValueError("Informe o nome de exibição (ex.: M1).")
    if speed_m_min <= 0:
        raise ValueError("Velocidade deve ser maior que zero.")
    if secondary_log_enabled and not secondary_log_folder:
        raise ValueError("Informe a pasta do log adicional, ou desmarque a opção.")
    jpg_rotation = _coerce_rotation(jpg_rotation)

    out = list(printers)

    if key:
        for i, pr in enumerate(out):
            if pr.key == key:
                out[i] = Printer(
                    key=pr.key, name=name, display_name=display_name,
                    speed_m_min=speed_m_min, notes=notes, computer_name=computer_name,
                    jpg_output_dir=jpg_output_dir, jpg_output_filename=jpg_output_filename,
                    log_import_dir=log_import_dir,
                    secondary_log_enabled=secondary_log_enabled,
                    secondary_log_folder=secondary_log_folder,
                    jpg_rotation=jpg_rotation,
                )
                _check_unique_display_name(out)
                _check_unique_computer_name(out)
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
        speed_m_min=speed_m_min, notes=notes, computer_name=computer_name,
        jpg_output_dir=jpg_output_dir, jpg_output_filename=jpg_output_filename,
        log_import_dir=log_import_dir,
        secondary_log_enabled=secondary_log_enabled,
        secondary_log_folder=secondary_log_folder,
        jpg_rotation=jpg_rotation,
    ))
    _check_unique_display_name(out)
    _check_unique_computer_name(out)
    return out


def _check_unique_display_name(printers: List[Printer]) -> None:
    seen = {}
    for pr in printers:
        low = pr.display_name.strip().lower()
        if low in seen and seen[low] != pr.key:
            raise ValueError(f"Já existe uma impressora com o nome de exibição '{pr.display_name}'.")
        seen[low] = pr.key


def _check_unique_computer_name(printers: List[Printer]) -> None:
    """Campo opcional, mas se duas impressoras tiverem o mesmo computador
    cadastrado, a detecção automática (ver find_printer_by_computer_name)
    fica ambígua — bloqueia pra evitar isso."""
    seen = {}
    for pr in printers:
        low = pr.computer_name.strip().lower()
        if not low:
            continue
        if low in seen and seen[low] != pr.key:
            raise ValueError(
                f"Já existe uma impressora com o computador '{pr.computer_name}' cadastrado."
            )
        seen[low] = pr.key


def remove_printer(printers: List[Printer], key: str) -> List[Printer]:
    return [p for p in printers if p.key != key]


def find_printer_by_display_name(display_name: str, printers: Optional[List[Printer]] = None) -> Optional[Printer]:
    printers = printers if printers is not None else load_printers()
    target = (display_name or "").strip().lower()
    return next((p for p in printers if p.display_name.strip().lower() == target), None)


def find_printer_by_computer_name(computer_name: str, printers: Optional[List[Printer]] = None) -> Optional[Printer]:
    printers = printers if printers is not None else load_printers()
    target = (computer_name or "").strip().lower()
    if not target:
        return None
    return next((p for p in printers if p.computer_name.strip().lower() == target), None)
