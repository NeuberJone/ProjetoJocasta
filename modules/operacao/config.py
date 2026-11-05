from __future__ import annotations

import json
import os
from pathlib import Path

from core.migrate import migrate_legacy_path
from core.print_types import DEFAULT_RULES, DEFAULT_SUBTYPES

MODULE_NAME = "Operacao"

_APPDATA = Path(os.environ.get("APPDATA") or str(Path.home()))
APP_DIR = _APPDATA / "Nexor" / MODULE_NAME
migrate_legacy_path(_APPDATA / "ProjetoJocasta" / "PXPrintLogs", APP_DIR)
APP_DIR.mkdir(parents=True, exist_ok=True)

CFG_PATH = APP_DIR / "config.json"

DEFAULT_CFG = {
    "space_filenames": [],
    "group_consecutive_spaces": False,
    "print_type_rules": [dict(r) for r in DEFAULT_RULES],
    "print_type_subtypes": list(DEFAULT_SUBTYPES),
    "operators": [],
    # Pasta usada pro diálogo de "Importar logs" quando a impressora do
    # lote ainda não é conhecida (primeira importação da sessão), ou
    # quando a impressora já conhecida não tem uma pasta própria cadastrada
    # (ver core.printers.Printer.log_import_dir) — fallback geral, não por
    # máquina.
    "general_log_dir": "",
}


def load_cfg() -> dict:
    if CFG_PATH.exists():
        try:
            raw = json.loads(CFG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {**DEFAULT_CFG, **raw}
        except Exception:
            pass
    return dict(DEFAULT_CFG)


def save_cfg(cfg: dict) -> None:
    try:
        CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass