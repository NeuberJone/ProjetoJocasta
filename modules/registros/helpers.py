from __future__ import annotations

import json
from typing import Any

from core.format import fmt_m


def format_m(value: Any, *, suffix: bool = False) -> str:
    """
    Wrapper tolerante para core.format.fmt_m.

    Tenta usar suffix=False quando suportado.
    Se a assinatura do core ainda não aceitar, faz fallback seguro.
    """
    try:
        return fmt_m(value, suffix=suffix)  # type: ignore[misc]
    except TypeError:
        rendered = str(fmt_m(value))
        if suffix:
            return rendered
        return rendered.replace(" m", "").replace("m", "").strip()
    except Exception:
        return "0.00" if not suffix else "0.00 m"


def payload_summary(payload_json: str) -> str:
    if not payload_json:
        return ""

    try:
        payload = json.loads(payload_json)
        parts: list[str] = []

        which = payload.get("which")
        if which:
            parts.append(f"which={which}")

        if "reexport" in payload:
            parts.append(f"reexport={bool(payload.get('reexport'))}")

        if "orders_count" in payload:
            parts.append(f"orders={payload.get('orders_count')}")

        return " | ".join(parts)
    except Exception:
        return ""


def safe_int(value: str, default: int = 200) -> int:
    try:
        parsed = int(str(value).strip())
        return parsed if parsed > 0 else default
    except Exception:
        return default