from __future__ import annotations

import json
import os
from pathlib import Path

from core.migrate import migrate_legacy_path

MODULE_NAME = "Operacao"

_APPDATA = Path(os.environ.get("APPDATA") or str(Path.home()))
APP_DIR = _APPDATA / "Nexor" / MODULE_NAME
migrate_legacy_path(_APPDATA / "ProjetoJocasta" / "PXPrintLogs", APP_DIR)
APP_DIR.mkdir(parents=True, exist_ok=True)

CFG_PATH = APP_DIR / "config.json"

DEFAULT_CFG = {
    "report_mode_default": "full",
    "mirror_jpg_width_mode": "17",
    "mirror_jpg_width_cm_custom": 17.0,
    "mirror_jpg_dpi": 300,
    "space_filenames": [],
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