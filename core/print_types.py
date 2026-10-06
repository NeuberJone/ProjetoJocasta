from __future__ import annotations

import re
from typing import Iterable, List, Optional

FALLBACK_TYPE = "Fora do padrão"

# Regras padrão — comparam o padrão (regex) ao começo do nome do
# documento/arquivo; a primeira regra que combinar define o tipo.
# "Pedido": "05/10/2026 - Dryfit - Nome do pedido" (começa com data).
# "Reposição": "N2 - Aeroready" (iniciais do operador + número, sem data).
DEFAULT_RULES: List[dict] = [
    {"name": "Pedido", "pattern": r"^\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s*-"},
    {"name": "Reposição", "pattern": r"^\s*[A-Za-z]{1,3}\d+\s*-"},
]

DEFAULT_SUBTYPES: List[str] = ["Teste", "Terceirizado"]


def normalize_rules(raw: Optional[Iterable[object]]) -> List[dict]:
    out: List[dict] = []
    for item in (raw or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        pattern = str(item.get("pattern", "")).strip()
        if name and pattern:
            out.append({"name": name, "pattern": pattern})
    return out


def normalize_subtypes(raw: Optional[Iterable[object]]) -> List[str]:
    out: List[str] = []
    for item in (raw or []):
        name = str(item or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def validate_pattern(pattern: str) -> None:
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Padrão inválido: {e}")


def classify_document(document: str, rules: Optional[Iterable[dict]]) -> str:
    """Classifica o documento pela primeira regra (nome + padrão/regex) que
    combinar — ordem importa. Sem nenhuma regra correspondente, cai em
    FALLBACK_TYPE ('Fora do padrão'), que o usuário pode marcar manualmente
    com um subtipo (Teste, Terceirizado, ...) depois."""
    doc = (document or "").strip()
    for rule in normalize_rules(rules):
        try:
            if re.match(rule["pattern"], doc, flags=re.IGNORECASE):
                return rule["name"]
        except re.error:
            continue
    return FALLBACK_TYPE


def all_type_options(
    rules: Optional[Iterable[dict]], subtypes: Optional[Iterable[str]]
) -> List[str]:
    """Lista completa de tipos conhecidos (regras + Fora do padrão + subtipos
    manuais), sem repetir — usada para preencher o seletor de 'Editar tipo'."""
    out: List[str] = []
    for rule in normalize_rules(rules):
        if rule["name"] not in out:
            out.append(rule["name"])
    if FALLBACK_TYPE not in out:
        out.append(FALLBACK_TYPE)
    for name in normalize_subtypes(subtypes):
        if name not in out:
            out.append(name)
    return out
