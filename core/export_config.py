"""Padrões de exportação (PDF/JPG) compartilhados entre Operação e
Planejador.

Antes cada módulo guardava sua própria cópia desses valores (Modo do PDF,
largura do JPG espelhado, DPI), o que fazia a mesma configuração aparecer
duas vezes em Configurações e podia ficar dessincronizada entre os dois
módulos. Agora é uma única configuração, usada pelos dois."""
from __future__ import annotations

from core.config import read_module_cfg, write_module_cfg

EXPORT_MODULE = "Exportacao"

EXPORT_DEFAULTS: dict = {
    "report_mode_default": "full",
    "mirror_jpg_width_mode": "17",
    "mirror_jpg_width_cm_custom": 17.0,
    "mirror_jpg_dpi": 300,
}


def load_export_cfg() -> dict:
    return read_module_cfg(EXPORT_MODULE, dict(EXPORT_DEFAULTS))


def save_export_cfg(cfg: dict) -> None:
    write_module_cfg(EXPORT_MODULE, cfg)
