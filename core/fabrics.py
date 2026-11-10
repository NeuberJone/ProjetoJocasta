# core/fabrics.py
"""Cadastro de tecidos e aliases — extraído de modules/planejador.py para a
camada core, para que outros módulos (ex.: a classificação de tipos de
impressão em modules/operacao) possam consultar tecidos/aliases sem criar um
import circular com modules/planejador (que já importa de modules/operacao).

modules/planejador.py reexporta estes nomes para manter compatibilidade com
o código existente."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List

from core.migrate import migrate_legacy_path
from core.json_store import ConfigurationWriteError, finite_number, read_json_config, require, validate_object, write_json_config
from core.logging_config import get_logger, log_exception

_logger = get_logger(__name__)


def _fabrics_store_path() -> Path:
    appdata = Path(os.environ.get("APPDATA") or str(Path.home()))
    base = appdata / "Nexor" / "Planejador"
    migrate_legacy_path(appdata / "ProjetoJocasta" / "PXPrintCalc", base)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log_exception(_logger, "Fabric configuration directory unavailable", exc)
        raise ConfigurationWriteError(base / "fabrics.json", "Não foi possível acessar a pasta de tecidos.") from exc
    return base / "fabrics.json"


DEFAULT_ROLL_LENGTH_M = 60.0

# Cada tecido é um dict: {"aliases": [...], "roll_length_m": float}
FabricEntry = Dict[str, object]


def fabric_aliases(entry: FabricEntry) -> List[str]:
    v = entry.get("aliases") if isinstance(entry, dict) else None
    return [str(x) for x in v] if isinstance(v, list) else []


def fabric_roll_length(entry: FabricEntry) -> float:
    v = entry.get("roll_length_m") if isinstance(entry, dict) else None
    try:
        v = float(v)
        return v if v > 0 else DEFAULT_ROLL_LENGTH_M
    except Exception:
        return DEFAULT_ROLL_LENGTH_M


def _default_fabrics() -> Dict[str, FabricEntry]:
    base = {
        "Dryfit": (["dryfit", "dry fit", "dry-fit", "drifit"], 90.0),
        "Ribana": (["ribana"], DEFAULT_ROLL_LENGTH_M),
        "Elastano": (["elastano"], 60.0),
        "Poliamida": (["poliamida"], DEFAULT_ROLL_LENGTH_M),
        "Crepe": (["crepe"], DEFAULT_ROLL_LENGTH_M),
        "Malha": (["malha"], DEFAULT_ROLL_LENGTH_M),
        "Helanca": (["helanca"], DEFAULT_ROLL_LENGTH_M),
        "Tactel": (["tactel"], DEFAULT_ROLL_LENGTH_M),
        "Microfibra": (["microfibra"], DEFAULT_ROLL_LENGTH_M),
        "Aeroready": (["aeroready", "aero ready", "aero-ready"], DEFAULT_ROLL_LENGTH_M),
        "Oxford": (["oxford"], DEFAULT_ROLL_LENGTH_M),
        "Faixa de Capitão": (["Faixa de Capitão", "faixa cap"], DEFAULT_ROLL_LENGTH_M),
        "DryX": (["dryx", "dry x"], DEFAULT_ROLL_LENGTH_M),
        "Jaquard Corinthians": (["CORINTHIANS"], DEFAULT_ROLL_LENGTH_M),
        "Telinha": (["telinha"], DEFAULT_ROLL_LENGTH_M),
    }
    return {
        name: {"aliases": aliases, "roll_length_m": roll_m}
        for name, (aliases, roll_m) in base.items()
    }


def _normalize_fabrics(data: Dict[str, object]) -> Dict[str, FabricEntry]:
    """Aceita o formato antigo (lista de aliases) e o novo (dict com aliases/roll_length_m)."""
    out: Dict[str, FabricEntry] = {}
    for k, v in data.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, dict):
            out[k] = {
                "aliases": fabric_aliases(v),
                "roll_length_m": fabric_roll_length(v),
            }
        elif isinstance(v, list):
            default_roll = 90.0 if k.strip().lower() == "dryfit" else DEFAULT_ROLL_LENGTH_M
            out[k] = {
                "aliases": [str(x) for x in v if str(x).strip()],
                "roll_length_m": default_roll,
            }
        else:
            out[k] = {"aliases": [], "roll_length_m": DEFAULT_ROLL_LENGTH_M}
    return out


def save_fabrics(data: Dict[str, FabricEntry]) -> None:
    p = _fabrics_store_path()
    previous = read_json_config(p, {}, validator=_validate_fabrics)
    merged = {}
    for name, entry in data.items():
        old_entry = previous.get(name)
        merged[name] = {**old_entry, **entry} if isinstance(old_entry, dict) and isinstance(entry, dict) else entry
    write_json_config(p, merged, validator=_validate_fabrics)


def _validate_fabrics(raw: object, path: Path) -> None:
    validate_object(raw, path)
    for name, entry in raw.items():
        require(isinstance(name, str) and bool(name.strip()), path, "$", "Esperado nome de tecido não vazio.")
        require(isinstance(entry, (dict, list)), path, name, "Esperado um cadastro de tecido ou lista legada de aliases.")
        aliases = entry if isinstance(entry, list) else entry.get("aliases", [])
        require(isinstance(aliases, list) and all(isinstance(alias, str) for alias in aliases), path, f"{name}.aliases", "Esperada uma lista de textos.")
        if isinstance(entry, dict) and "roll_length_m" in entry:
            length = entry["roll_length_m"]
            require(finite_number(length) and float(length) > 0, path, f"{name}.roll_length_m", "Esperada metragem positiva e finita.")


def _legacy_fabrics_path() -> Path:
    # Local antigo (quebrava em build congelado via PyInstaller; mantido só para migração).
    # Era Path(modules/planejador.py).with_suffix(".fabrics.json") — preservado aqui mesmo
    # após a extração deste módulo para core/, para não perder a migração de instalações antigas.
    return Path(__file__).resolve().parent.parent / "modules" / "planejador.fabrics.json"


def load_fabrics() -> Dict[str, FabricEntry]:
    p = _fabrics_store_path()
    if not p.exists():
        legacy = _legacy_fabrics_path()
        if legacy.exists():
            legacy_data = read_json_config(legacy, {}, validator=_validate_fabrics)
            normalized = _normalize_fabrics(legacy_data)
            # Preserve extension fields in the initial migration as well.
            for name, entry in legacy_data.items():
                if isinstance(entry, dict):
                    normalized[name] = {**entry, **normalized[name]}
            save_fabrics(normalized)
            return normalized

        data = _default_fabrics()
        save_fabrics(data)
        return data
    raw = read_json_config(p, {}, validator=_validate_fabrics)
    return _normalize_fabrics(raw)


_DASHES = ["–", "—", "-", "-"]  # en dash, em dash, hyphen, non-breaking hyphen


def _normalize_name(s: str) -> str:
    s = (s or "").lower()
    for d in _DASHES:
        s = s.replace(d, "-")
    s = s.replace("_", " ")
    s = s.replace(".", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def infer_fabric_from_filename(filename: str, fabrics_map: Dict[str, FabricEntry]) -> str:
    s = _normalize_name(filename)
    parts = re.split(r"[\s\-]+", s)
    tokens = [p.strip() for p in parts if p.strip()]

    alias_index: Dict[str, str] = {}
    for canonical, entry in fabrics_map.items():
        alias_index[_normalize_name(canonical)] = canonical
        for a in fabric_aliases(entry):
            alias_index[_normalize_name(a)] = canonical

    # token exato
    for t in tokens:
        if t in alias_index:
            return alias_index[t]

    # substring
    for alias, canonical in alias_index.items():
        if alias and alias in s:
            return canonical

    return "Outro"


def canonical_fabric_name(raw: str, fabrics_map: Dict[str, FabricEntry]) -> str:
    """Nome canônico cadastrado para `raw` (nome ou alias do tecido, ex.:
    "Dry Fit", "dryfit", "DRIFIT"), comparando por igualdade (não substring)
    após normalizar espaços/traços/maiúsculas — usado para que nomes com a
    mesma identidade cadastrada em 'Tecidos e variações' (ex.: Dryfit/Dry
    Fit/Drifit) sejam sempre agrupados sob um único nome. Retorna "" se não
    houver correspondência (tecido não cadastrado)."""
    norm = _normalize_name(raw)
    if not norm:
        return ""
    for canonical, entry in fabrics_map.items():
        if _normalize_name(canonical) == norm:
            return canonical
        for alias in fabric_aliases(entry):
            if _normalize_name(alias) == norm:
                return canonical
    return ""


def known_fabric_names_with_aliases() -> Dict[str, List[str]]:
    """{nome canônico: [aliases...]} — usado pelo compilador do componente
    'Tecido' dos padrões de impressão (core/print_types.py), para montar uma
    alternância regex a partir do cadastro atual, sem acoplar core/print_types
    a modules/planejador."""
    fabrics_map = load_fabrics()
    out: Dict[str, List[str]] = {}
    for canonical, entry in fabrics_map.items():
        out[canonical] = [canonical] + fabric_aliases(entry)
    return out
