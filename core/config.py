from __future__ import annotations

import hashlib
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

    # 🔐 Hash SHA1 da senha do modo dev (nunca guardar senha em texto)
    # Exemplo (SHA1 de "test"): a94a8fe5ccb19ba61c4c0873d391e987982fbbd3
    dev_password_hash: str = ""


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
    path.write_text(
        json.dumps(asdict(cfg), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _merge(cfg: PXCoreConfig, raw: dict[str, Any]) -> PXCoreConfig:
    # Atualiza campos conhecidos sem explodir em chaves desconhecidas
    if isinstance(raw, dict):
        if "base_dir" in raw and raw["base_dir"]:
            cfg.base_dir = str(raw["base_dir"])

        if "dev_mode_enabled" in raw:
            cfg.dev_mode_enabled = bool(raw["dev_mode_enabled"])

        if "dev_password_hash" in raw and raw["dev_password_hash"]:
            cfg.dev_password_hash = str(raw["dev_password_hash"])

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


# =========================
# 🔐 Dev password helpers
# =========================
def hash_password(password: str) -> str:
    return hashlib.sha1(password.encode("utf-8")).hexdigest()


def verify_dev_password(cfg: PXCoreConfig, password: str) -> bool:
    if not cfg.dev_password_hash:
        return False
    return hash_password(password) == cfg.dev_password_hash


def set_dev_password(cfg: PXCoreConfig, new_password: str) -> None:
    cfg.dev_password_hash = hash_password(new_password)
    save_config(cfg)
