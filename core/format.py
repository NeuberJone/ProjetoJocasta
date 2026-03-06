from __future__ import annotations

import math


def round_up_cm_m(m: float) -> float:
    """
    Arredonda METROS para cima ao nível de centímetro (0,01 m).
    Retorna float (cru) para cálculos ou armazenamento.
    """
    try:
        v = float(m)
    except Exception:
        return 0.0
    if v <= 0:
        return 0.0
    return math.ceil(v * 100.0) / 100.0


def fmt_m(m: float, *, suffix: bool = True, round_cm: bool = True) -> str:
    """
    Formata metros com 2 casas.
    Por padrão arredonda para cima ao centímetro apenas na EXIBIÇÃO.
    """
    v = round_up_cm_m(m) if round_cm else float(m)
    s = f"{v:.2f}"
    return f"{s} m" if suffix else s