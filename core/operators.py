# core/operators.py
"""Cadastro de operadores (nome + identificador) usado pela Operação para
mostrar quem imprimiu cada reposição (ex.: "N1 - Dryfit" -> identificador
"N" -> operador "Neuber") no PDF e no JPG.

Puramente modelo/validação — como core/fabrics.py, sem Tkinter nem UI."""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

# Identificador: só letras (a parte que vem antes do número no nome do
# arquivo de reposição, ex.: "N" em "N1", "NJ" em "NJ2").
_RE_IDENTIFIER = re.compile(r"^[A-Za-z]+$")


def normalize_operators(raw: Optional[Iterable[object]]) -> List[dict]:
    """Normaliza a lista de operadores salva em configuração para
    {"identifier": ..., "name": ...}, descartando entradas sem identificador
    ou sem nome. Identificadores repetidos (sem diferenciar maiúsc./minúsc.):
    o último da lista vence, os demais são descartados."""
    out: Dict[str, dict] = {}
    for item in (raw or []):
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("identifier", "")).strip()
        name = str(item.get("name", "")).strip()
        if not identifier or not name:
            continue
        if not _RE_IDENTIFIER.match(identifier):
            continue
        out[identifier.upper()] = {"identifier": identifier.upper(), "name": name}
    return list(out.values())


def operator_name_for_code(code: str, operators: Optional[Iterable[dict]]) -> str:
    """Nome do operador para um identificador (ex.: 'N' -> 'Neuber'), ou ""
    se o identificador estiver vazio ou não houver operador cadastrado com
    ele. Comparação sem diferenciar maiúsculas/minúsculas."""
    code = (code or "").strip().upper()
    if not code:
        return ""
    for entry in normalize_operators(operators):
        if entry["identifier"] == code:
            return entry["name"]
    return ""
