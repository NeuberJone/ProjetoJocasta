from __future__ import annotations

from core.printlogs_db import (
    get_roll_events,
    get_roll_orders,
    get_roll_summary,
    list_rolls,
)


def search_rolls(
    *,
    limit: int,
    machine: str | None = None,
    name_like: str | None = None,
    order_like: str | None = None,
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
        )
    except TypeError:
        return list_rolls(  # type: ignore[misc]
            limit=limit,
            machine=machine,
            name_like=name_like,
        )


def load_roll_summary(roll_id: int):
    return get_roll_summary(int(roll_id))


def load_roll_orders(roll_id: int):
    return get_roll_orders(int(roll_id))


def load_roll_events(roll_id: int):
    return get_roll_events(int(roll_id))