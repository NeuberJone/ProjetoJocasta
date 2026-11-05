from __future__ import annotations

from core.printlogs_db import (
    get_order_context,
    get_roll_events,
    get_roll_latest_payload,
    get_roll_module,
    get_roll_order_version,
    get_roll_order_version_count,
    get_roll_orders,
    get_roll_original_payload,
    get_roll_summary,
    list_distinct_tipos,
    list_rolls,
    was_roll_edited,
)
from modules.operacao.config import load_cfg as load_operacao_cfg


def search_rolls(
    *,
    limit: int,
    machine: str | None = None,
    name_like: str | None = None,
    order_like: str | None = None,
    tipo: str | None = None,
):
    """
    Wrapper fino sobre list_rolls, com fallback para versões antigas
    que ainda não aceitam todos os parâmetros.
    """
    try:
        return list_rolls(
            limit=limit,
            machine=machine,
            export_mode=None,
            name_like=name_like,
            order_like=order_like,
            tipo=tipo,
        )
    except TypeError:
        return list_rolls(  # type: ignore[misc]
            limit=limit,
            machine=machine,
            name_like=name_like,
        )


def load_distinct_tipos() -> list[str]:
    return list_distinct_tipos()


def load_roll_summary(roll_id: int):
    group_spaces = bool(load_operacao_cfg().get("group_consecutive_spaces", False))
    return get_roll_summary(int(roll_id), group_consecutive_spaces=group_spaces)


def load_roll_orders(roll_id: int):
    return get_roll_orders(int(roll_id))


def load_order_context(order_id: int):
    """Pedido individual + rolo correspondente, para a exportação do contexto de pedido ao
    PX Tool Box (ver modules/registros/px_export.py) — None se o id não existir."""
    return get_order_context(int(order_id))


def load_roll_events(roll_id: int):
    return get_roll_events(int(roll_id))


def load_roll_module(roll_id: int) -> str:
    return get_roll_module(int(roll_id))


def load_roll_pdf_path(roll_id: int) -> str:
    """Caminho do PDF (comprovante) salvo no evento mais recente de
    exportação/atualização desse rolo, ou "" se nunca foi exportado em PDF
    (ex.: rolo exportado só como JPG)."""
    return str(get_roll_latest_payload(int(roll_id)).get("normal_path") or "")


def load_roll_original_pdf_path(roll_id: int) -> str:
    """Caminho do PDF (comprovante) de quando o rolo foi fechado a
    PRIMEIRA vez — igual a load_roll_pdf_path quando o rolo nunca foi
    editado (os dois apontam pro mesmo evento)."""
    return str(get_roll_original_payload(int(roll_id)).get("normal_path") or "")


def load_roll_was_edited(roll_id: int) -> bool:
    return was_roll_edited(int(roll_id))


def load_roll_order_version_options(roll_id: int) -> list[dict]:
    """Lista de versões das orders desse rolo, pra popular o combobox de
    versão em "Detalhes do rolo selecionado" → Pedidos — cada item é
    {"value": version_no ou None, "label": "Original"/"Edição N"/"Atual"},
    na ordem em que foram feitas (a mais antiga primeiro). `value=None` é a
    versão ATUAL (o que está em orders agora, sem cópia própria — ver
    update_roll_orders); as demais são cópias guardadas de antes de cada
    "Atualizar Rolo". Rolo nunca editado = uma única opção ("Original",
    value=None), igual já era antes dessa tela ter o conceito de versão."""
    n = get_roll_order_version_count(int(roll_id))
    options = [
        {"value": v, "label": "Original" if v == 0 else f"Edição {v}"}
        for v in range(n)
    ]
    options.append({"value": None, "label": f"Edição {n}" if n > 0 else "Original"})
    return options


def load_roll_orders_for_version(roll_id: int, version_no: int | None):
    """Orders de uma versão específica — version_no=None é a versão ATUAL
    (equivalente a load_roll_orders); um inteiro busca a cópia guardada
    correspondente (ver load_roll_order_version_options)."""
    if version_no is None:
        return get_roll_orders(int(roll_id))
    return get_roll_order_version(int(roll_id), int(version_no))