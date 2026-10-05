from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from core.migrate import migrate_legacy_path


def _store_path() -> Path:
    appdata = Path(os.environ.get("APPDATA") or str(Path.home()))
    base = appdata / "Nexor" / "Planejador"
    migrate_legacy_path(appdata / "ProjetoJocasta" / "PXPrintCalc", base)
    base.mkdir(parents=True, exist_ok=True)
    return base / "scraps.json"


@dataclass
class FabricScrap:
    key: str
    name: str
    fabric: str
    length_m: float
    used: bool = False


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "pedaco"


def _coerce(d: dict) -> FabricScrap:
    return FabricScrap(
        key=str(d.get("key") or _slugify(str(d.get("name", "")))),
        name=str(d.get("name", "")),
        fabric=str(d.get("fabric", "")),
        length_m=float(d.get("length_m", 0.0) or 0.0),
        used=bool(d.get("used", False)),
    )


def _save_raw(data: List[dict]) -> None:
    _store_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_scraps() -> List[FabricScrap]:
    p = _store_path()
    if not p.exists():
        _save_raw([])
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [_coerce(d) for d in raw if isinstance(d, dict)]
    except Exception:
        pass
    return []


def save_scraps(scraps: List[FabricScrap]) -> None:
    _save_raw([asdict(s) for s in scraps])


def add_or_update_scrap(
    scraps: List[FabricScrap],
    *,
    key: Optional[str],
    name: str,
    fabric: str,
    length_m: float,
) -> List[FabricScrap]:
    name = name.strip()
    fabric = fabric.strip()
    if not name:
        raise ValueError("Informe um nome para o pedaço.")
    if not fabric:
        raise ValueError("Informe o tecido do pedaço.")
    if length_m <= 0:
        raise ValueError("Metragem deve ser maior que zero.")

    out = list(scraps)

    if key:
        for i, sc in enumerate(out):
            if sc.key == key:
                out[i] = FabricScrap(
                    key=sc.key, name=name, fabric=fabric,
                    length_m=length_m, used=sc.used,
                )
                return out
        raise ValueError("Pedaço não encontrado para atualizar.")

    new_key = _slugify(name)
    if any(sc.key == new_key for sc in out):
        suffix = 2
        while any(sc.key == f"{new_key}_{suffix}" for sc in out):
            suffix += 1
        new_key = f"{new_key}_{suffix}"

    out.append(FabricScrap(key=new_key, name=name, fabric=fabric, length_m=length_m, used=False))
    return out


def remove_scrap(scraps: List[FabricScrap], key: str) -> List[FabricScrap]:
    return [s for s in scraps if s.key != key]


def set_scrap_used(scraps: List[FabricScrap], key: str, used: bool) -> List[FabricScrap]:
    out = list(scraps)
    for i, sc in enumerate(out):
        if sc.key == key:
            out[i] = FabricScrap(key=sc.key, name=sc.name, fabric=sc.fabric, length_m=sc.length_m, used=used)
            break
    return out


def unused_scraps_for_fabric(scraps: List[FabricScrap], fabric: str) -> List[FabricScrap]:
    """Pedaços não usados de um tecido, maior metragem primeiro — usado pelo planejador de fila."""
    items = [s for s in scraps if not s.used and s.fabric == fabric and s.length_m > 0]
    return sorted(items, key=lambda s: s.length_m, reverse=True)


def unused_lengths_for_fabric(scraps: List[FabricScrap], fabric: str) -> List[float]:
    """Metragens (desc.) dos pedaços não usados de um tecido — usado pelo planejador de fila."""
    return [s.length_m for s in unused_scraps_for_fabric(scraps, fabric)]
