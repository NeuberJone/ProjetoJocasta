from __future__ import annotations

import os
import re
from collections import OrderedDict
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import List, Optional, Tuple

from core.migrate import migrate_legacy_path
from core.json_store import (
    ConfigurationWriteError, finite_number, preserve_entry_fields, read_json_config, require, write_json_config,
)
from core.logging_config import get_logger, log_exception

_logger = get_logger(__name__)


def _store_path() -> Path:
    appdata = Path(os.environ.get("APPDATA") or str(Path.home()))
    base = appdata / "Nexor" / "Planejador"
    migrate_legacy_path(appdata / "ProjetoJocasta" / "PXPrintCalc", base)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log_exception(_logger, "Scrap configuration directory unavailable", exc)
        raise ConfigurationWriteError(base / "scraps.json", "Não foi possível acessar a pasta de pedaços de tecido.") from exc
    return base / "scraps.json"


@dataclass
class FabricScrap:
    key: str
    name: str
    fabric: str
    length_m: float
    used: bool = False
    tipo: str = ""
    observacao: str = ""


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
        tipo=str(d.get("tipo", "") or ""),
        observacao=str(d.get("observacao", "") or ""),
    )


def _save_raw(data: List[dict]) -> None:
    path = _store_path()
    previous = read_json_config(path, [], validator=_validate_scraps)
    previous = [{**item, "key": _coerce(item).key} for item in previous]
    write_json_config(path, preserve_entry_fields(previous, data), validator=_validate_scraps)


def _validate_scraps(raw: object, path: Path) -> None:
    require(isinstance(raw, list), path, "$", "Esperada uma lista de pedaços de tecido.")
    seen = set()
    for index, item in enumerate(raw):
        field = f"[{index}]"
        require(isinstance(item, dict), path, field, "Esperado um objeto de pedaço de tecido.")
        for name in ("key", "name", "fabric", "tipo", "observacao"):
            if name in item:
                require(isinstance(item[name], str), path, f"{field}.{name}", "Esperado texto.")
        length = item.get("length_m", 0)
        require(finite_number(length) and float(length) >= 0, path, f"{field}.length_m", "Esperada metragem finita não negativa.")
        if "used" in item:
            require(isinstance(item["used"], bool), path, f"{field}.used", "Esperado verdadeiro ou falso.")
        identity = _coerce(item).key
        require(identity not in seen, path, f"{field}.key", "Identificador de pedaço repetido.")
        seen.add(identity)


def load_scraps() -> List[FabricScrap]:
    p = _store_path()
    if not p.exists():
        _save_raw([])
        return []
    raw = read_json_config(p, [], validator=_validate_scraps)
    return [_coerce(d) for d in raw]


def save_scraps(scraps: List[FabricScrap]) -> None:
    _save_raw([asdict(s) for s in scraps])


def add_or_update_scrap(
    scraps: List[FabricScrap],
    *,
    key: Optional[str],
    name: str,
    fabric: str,
    length_m: float,
    tipo: str = "",
    observacao: str = "",
) -> List[FabricScrap]:
    name = name.strip()
    fabric = fabric.strip()
    tipo = tipo.strip()
    observacao = observacao.strip()
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
                    tipo=tipo, observacao=observacao,
                )
                return out
        raise ValueError("Pedaço não encontrado para atualizar.")

    new_key = _slugify(name)
    if any(sc.key == new_key for sc in out):
        suffix = 2
        while any(sc.key == f"{new_key}_{suffix}" for sc in out):
            suffix += 1
        new_key = f"{new_key}_{suffix}"

    out.append(FabricScrap(
        key=new_key, name=name, fabric=fabric, length_m=length_m, used=False,
        tipo=tipo, observacao=observacao,
    ))
    return out


def remove_scrap(scraps: List[FabricScrap], key: str) -> List[FabricScrap]:
    return [s for s in scraps if s.key != key]


def set_scrap_used(scraps: List[FabricScrap], key: str, used: bool) -> List[FabricScrap]:
    out = list(scraps)
    for i, sc in enumerate(out):
        if sc.key == key:
            out[i] = replace(sc, used=used)
            break
    return out


def unused_scraps_for_fabric(scraps: List[FabricScrap], fabric: str) -> List[FabricScrap]:
    """Pedaços não usados de um tecido, maior metragem primeiro — usado pelo planejador de fila."""
    items = [s for s in scraps if not s.used and s.fabric == fabric and s.length_m > 0]
    return sorted(items, key=lambda s: s.length_m, reverse=True)


def unused_lengths_for_fabric(scraps: List[FabricScrap], fabric: str) -> List[float]:
    """Metragens (desc.) dos pedaços não usados de um tecido — usado pelo planejador de fila."""
    return [s.length_m for s in unused_scraps_for_fabric(scraps, fabric)]


def scrap_label(fabric: str, tipo: str) -> str:
    """Rótulo do grupo tecido+tipo, ex.: 'Dryfit tipo Novo'. Sem tipo, só o tecido."""
    tipo = (tipo or "").strip()
    return f"{fabric} tipo {tipo}" if tipo else fabric


def totals_by_fabric_tipo(
    scraps: List[FabricScrap], *, only_unused: bool = False
) -> List[Tuple[str, float]]:
    """Resumo com a metragem total por combinação tecido+tipo, ex.:
    [('Dryfit tipo Novo', 12.5), ('Dryfit tipo Antigo', 3.0)].
    Ordenado pela ordem de aparição (tecido, depois tipo)."""
    totals: "OrderedDict[Tuple[str, str], float]" = OrderedDict()
    for sc in scraps:
        if only_unused and sc.used:
            continue
        group = (sc.fabric, sc.tipo)
        totals[group] = totals.get(group, 0.0) + sc.length_m
    return [(scrap_label(fabric, tipo), total) for (fabric, tipo), total in totals.items()]
