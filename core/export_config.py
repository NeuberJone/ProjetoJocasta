"""Padrões de exportação (PDF/JPG) compartilhados entre Operação e
Planejador.

Antes cada módulo guardava sua própria cópia desses valores (Modo do PDF,
largura do JPG espelhado, DPI), o que fazia a mesma configuração aparecer
duas vezes em Configurações e podia ficar dessincronizada entre os dois
módulos. Agora é uma única configuração, usada pelos dois."""
from __future__ import annotations

from core.config import read_module_cfg, write_module_cfg

EXPORT_MODULE = "Exportacao"

REPORT_STYLE_CLASSIC = "classic"
REPORT_STYLE_PRISMA = "prisma"
VALID_REPORT_STYLES = {REPORT_STYLE_CLASSIC, REPORT_STYLE_PRISMA}

EXPORT_DEFAULTS: dict = {
    "report_mode_default": "full",
    "mirror_jpg_width_mode": "17",
    "mirror_jpg_width_cm_custom": 17.0,
    "mirror_jpg_dpi": 300,
    # Estilo do comprovante (ver especificação "Prisma"): instalações
    # existentes e novas sempre começam em Clássico — só muda se o usuário
    # escolher Prisma explicitamente em Configurações (read_module_cfg
    # preenche este campo a partir daqui quando ausente do JSON salvo, então
    # uma config antiga sem este campo também cai em Clássico automaticamente).
    "report_style": REPORT_STYLE_CLASSIC,
}


def load_export_cfg() -> dict:
    return read_module_cfg(EXPORT_MODULE, dict(EXPORT_DEFAULTS))


def save_export_cfg(cfg: dict) -> None:
    write_module_cfg(EXPORT_MODULE, cfg)


def report_filename_tag(mode: str, report_style: str) -> str:
    """Sufixo de modo usado no nome dos arquivos de comprovante (PDF e
    JPG) — compartilhado entre Operação e Planejador. Modo completo não
    leva sufixo nenhum (removendo o antigo "_FULL" dos novos arquivos;
    rolos já exportados antes continuam com o nome antigo, intocados).
    Resumido continua marcado com "_SUMMARY".

    `report_style` é aceito só por compatibilidade de assinatura com os
    chamadores (Operação/Planejador) — não entra mais no nome do arquivo
    (pedido explícito do usuário: nunca gerar "_PRISMA" no nome). Clássico
    e Prisma do mesmo rolo/modo geram o mesmo nome; exportar os dois estilos
    pro mesmo rolo sobrescreve o arquivo anterior."""
    parts = []
    if mode != "full":
        parts.append("SUMMARY")
    return "_".join(parts)
