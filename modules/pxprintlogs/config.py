from __future__ import annotations

import json
import os
from pathlib import Path

MODULE_NAME = "PXPrintLogs"

APP_DIR = Path(os.environ.get("APPDATA") or str(Path.home())) / "ProjetoJocasta" / MODULE_NAME
APP_DIR.mkdir(parents=True, exist_ok=True)

CFG_PATH = APP_DIR / "config.json"

DEFAULT_CFG = {
    "report_mode_default": "full",
    "mirror_jpg_width_mode": "17",
    "mirror_jpg_width_cm_custom": 17.0,
    "mirror_jpg_dpi": 300,
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