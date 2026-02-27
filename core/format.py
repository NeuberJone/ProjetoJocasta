# core/format.py
from __future__ import annotations

import math


def round_up_cm_m(value_m: float) -> float:
    """
    Arredonda para cima em centímetros (0.01 m).
    Ex: 6.361 -> 6.37
    """
    try:
        v = float(value_m)
    except Exception:
        v = 0.0
    return math.ceil(v * 100.0) / 100.0


def format_m(value_m: float, *, suffix: str = " m") -> str:
    """
    Formata metros com 2 casas.
    Mantém negativo se existir (não faz clamp).
    """
    try:
        v = float(value_m)
    except Exception:
        v = 0.0
    return f"{v:.2f}{suffix}"


def format_m_rounded_cm(value_m: float, *, suffix: str = " m") -> str:
    """
    Arredonda por centímetro (pra cima) e formata com 2 casas.
    """
    return format_m(round_up_cm_m(value_m), suffix=suffix)