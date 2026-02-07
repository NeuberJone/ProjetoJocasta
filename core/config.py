# core/config.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from core.paths import config_path, default_base_dir, ensure_dir


def _normalize_alias(text: str) -> str:
    # normalização simples (vamos evoluir depois com acentos, etc.)
    return " ".join(text.strip().lower().replace("-", " ").split())


@dataclass
class PXCoreConfig:
    base_dir: str
    export_naming: str  # ex: "{ident}_{date}_{time}"
    dev_mode_enabled: bool

    theme: str  # "light" | "dark" | "auto"

    # Cadastros
    machines: List[Dict[str, Any]]
    fabrics: List[Dict[str, Any]]
    sizes: Dict[str, List[str]]  # {"MA": [...], "FE": [...], "C": [...]}

    def as_dict(self) -> Dict[str, Any]:
        return {
            "base_dir": self.base_dir,
            "export_naming": self.export_naming,
            "dev_mode_enabled": self.dev_mode_enabled,
            "theme": self.theme,
            "machines": self.machines,
            "fabrics": self.fabrics,
            "sizes": self.sizes,
        }


def default_config() -> PXCoreConfig:
    return PXCoreConfig(
        base_dir=str(default_base_dir()),
        export_naming="{ident}_{date}_{time}",  # IDENTIFICACAO_DDMMYYYY_HHMMSS
        dev_mode_enabled=False,
        theme="auto",
        machines=[
            {
                "id": "M1",
                "name": "Impressora Sublimação 1",
                "type": "sublimacao",
                "model": "",
                "serial": "",
                "active": True,
            },
            {
                "id": "M2",
                "name": "Impressora Sublimação 2",
                "type": "sublimacao",
                "model": "",
                "serial": "",
                "active": True,
            },
        ],
        fabrics=[
            {
                "name": "Dry Fit",
                "aliases": ["dry", "dryfit", "dry fit"],
                "active": True,
            }
        ],
        sizes={
            "MA": ["PP", "P", "M", "G", "GG"],
            "FE": ["PP", "P", "M", "G", "GG"],
            "C": ["2", "4", "6", "8", "10", "12", "14", "16"],
        },
    )


def load_config() -> PXCoreConfig:
    path = config_path()
    if not path.exists():
        cfg = default_config()
        save_config(cfg)
        ensure_dirs(cfg)
        return cfg

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    cfg = default_config()

    # Merge simples (sem quebrar config antigo quando você adicionar campos novos)
    cfg.base_dir = str(raw.get("base_dir", cfg.base_dir))
    cfg.export_naming = str(raw.get("export_naming", cfg.export_naming))
    cfg.dev_mode_enabled = bool(raw.get("dev_mode_enabled", cfg.dev_mode_enabled))
    cfg.theme = str(raw.get("theme", cfg.theme))

    cfg.machines = list(raw.get("machines", cfg.machines))
    cfg.fabrics = list(raw.get("fabrics", cfg.fabrics))
    cfg.sizes = dict(raw.get("sizes", cfg.sizes))

    ensure_dirs(cfg)
    return cfg


def save_config(cfg: PXCoreConfig) -> None:
    path = config_path()
    with path.open("w", encoding="utf-8") as f:
        json.dump(cfg.as_dict(), f, ensure_ascii=False, indent=2)


def ensure_dirs(cfg: PXCoreConfig) -> None:
    """
    Cria a estrutura padrão:
    C:\PXCore\
      lists\
      json\
      logs\
      exports\
      temp\
    """
    base = Path(cfg.base_dir)
    ensure_dir(base)
    ensure_dir(base / "lists")
    ensure_dir(base / "json")
    ensure_dir(base / "logs")
    ensure_dir(base / "exports")
    ensure_dir(base / "temp")


def build_export_name(ident: str, *, ddmmyyyy: str, hhmmss: str, cfg: PXCoreConfig) -> str:
    """
    Gera nome padrão IDENTIFICACAO_DDMMYYYY_HHMMSS (sem extensão).
    """
    ident_clean = _normalize_alias(ident).replace(" ", "_").upper()
    return f"{ident_clean}_{ddmmyyyy}_{hhmmss}"


def resolve_fabric_name(input_text: str, cfg: PXCoreConfig) -> str | None:
    """
    Resolve variações (aliases) -> nome principal.
    Retorna None se não encontrar.
    """
    key = _normalize_alias(input_text)
    for fab in cfg.fabrics:
        name = str(fab.get("name", "")).strip()
        aliases = fab.get("aliases", []) or []
        all_keys = [_normalize_alias(name)] + [_normalize_alias(a) for a in aliases]
        if key in all_keys:
            return name
    return None
