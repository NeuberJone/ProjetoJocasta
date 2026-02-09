from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


APP_NAME = "PXCore"


@dataclass
class PXCoreConfig:
    base_dir: str = r"C:\PXCore" if os.name == "nt" else str(Path.home() / "PXCore")
    dev_mode_enabled: bool = False


def _config_path() -> Path:
    """
    Caminho gravável do config do PXCore:
      - Windows: %APPDATA%\\PXCore\\config.json
      - Linux: ~/.config/PXCore/config.json
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME / "config.json"
    return Path.home() / ".config" / APP_NAME / "config.json"


def _ensure_dirs(cfg: PXCoreConfig) -> None:
    base = Path(cfg.base_dir)
    # Estrutura padrão
    (base / "lists").mkdir(parents=True, exist_ok=True)
    (base / "json").mkdir(parents=True, exist_ok=True)
    (base / "logs").mkdir(parents=True, exist_ok=True)
    (base / "exports").mkdir(parents=True, exist_ok=True)
    (base / "temp").mkdir(parents=True, exist_ok=True)


def save_config(cfg: PXCoreConfig) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), encoding="utf-8")


def _merge(cfg: PXCoreConfig, raw: dict[str, Any]) -> PXCoreConfig:
    # Atualiza campos conhecidos sem explodir em chaves desconhecidas
    if isinstance(raw, dict):
        if "base_dir" in raw and raw["base_dir"]:
            cfg.base_dir = str(raw["base_dir"])
        if "dev_mode_enabled" in raw:
            cfg.dev_mode_enabled = bool(raw["dev_mode_enabled"])
    return cfg


def load_config() -> PXCoreConfig:
    """
    SEMPRE retorna um PXCoreConfig válido.
    Se config.json não existir, ou estiver vazio/corrompido, recria.
    """
    path = _config_path()
    cfg = PXCoreConfig()

    if not path.exists():
        save_config(cfg)
        _ensure_dirs(cfg)
        return cfg

    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            # arquivo vazio
            save_config(cfg)
            _ensure_dirs(cfg)
            return cfg

        raw = json.loads(text)
        cfg = _merge(cfg, raw)

        # garante dirs mesmo se o usuário mudou base_dir
        _ensure_dirs(cfg)
        return cfg

    except Exception:
        # JSON corrompido / erro de leitura → recria
        save_config(cfg)
        _ensure_dirs(cfg)
        return cfg
