from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

from core.fabrics import known_fabric_names_with_aliases
from core.print_pattern import (
    MATCH_MODE_CONTAINS,
    MATCH_MODE_START,
    PEDIDO_MODE_FIXED,
    migrate_rule_dict,
    new_rule_id,
    resolve_pattern,
    rule_uses_fabric,
    strip_extension,
)

FALLBACK_TYPE = "Fora do padrão"

# Regras padrão — comparam o padrão (regex) ao começo do nome do
# documento/arquivo; a primeira regra que combinar define o tipo.
# "Pedido": "16-10 - Dryfit - Nome do pedido" (começa com dia-mês, sem ano).
# "Reposição": "N2 - Aeroready" (iniciais do operador + número, sem data).
#
# Estas duas regras são as únicas "de fábrica" do Nexor e são preservadas
# como regex avançada/personalizada (sem estrutura visual) na migração para
# o modelo estruturado — ver core/print_pattern.migrate_rule_dict. Não
# tentamos reconstruir a interpretação visual delas "adivinhando" blocos;
# continuam funcionando exatamente como antes.
DEFAULT_RULES: List[dict] = [
    {"name": "Pedido", "pattern": r"^\s*\d{1,2}[-/.]\d{1,2}\s*-", "warn_duplicate": True},
    {"name": "Reposição", "pattern": r"^\s*[A-Za-z]{1,3}\s*\d+\s*-", "warn_duplicate": False},
]

# Padrões padrão de versões anteriores, trocados ao carregar. O de Pedido
# exigia ano na data e por isso não reconhecia "16-10 - Dryfit - ...".
_LEGACY_PATTERNS = {
    r"^\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s*-": DEFAULT_RULES[0]["pattern"],
    r"^\s*[A-Za-z]{1,3}\d+\s*-": DEFAULT_RULES[1]["pattern"],
}

DEFAULT_SUBTYPES: List[str] = ["Teste", "Terceirizado"]


def normalize_rules(raw: Optional[Iterable[object]]) -> List[dict]:
    """Normaliza a lista de regras salva em configuração para o formato
    completo (id, nome, padrão, modo de correspondência, estrutura visual
    opcional, exemplos, se é regex personalizada, ativo/inativo).

    Aceita tanto o formato legado ({"name", "pattern"}) quanto o novo —
    regras legadas são migradas automaticamente (ver `migrate_rule_dict`),
    sempre preservando o padrão (regex) original."""
    out: List[dict] = []
    for item in (raw or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        pattern = str(item.get("pattern", "")).strip()
        pattern = _LEGACY_PATTERNS.get(pattern, pattern)
        if not name or not pattern:
            continue
        migrated = dict(item)
        migrated["name"] = name
        migrated["pattern"] = pattern
        out.append(migrate_rule_dict(migrated))
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


def _ensure_fabric_names(
    rules: List[dict], fabric_names: Optional[Dict[str, List[str]]]
) -> Optional[Dict[str, List[str]]]:
    if fabric_names is not None:
        return fabric_names
    if any(rule_uses_fabric(r.get("components")) for r in rules):
        return known_fabric_names_with_aliases()
    return None


def _rule_matches(rule: dict, doc: str, fabric_names: Optional[Dict[str, List[str]]]) -> bool:
    pattern = resolve_pattern(rule, fabric_names=fabric_names)
    if not pattern:
        return False
    mode = rule.get("match_mode", MATCH_MODE_START)
    try:
        if mode == MATCH_MODE_CONTAINS:
            return bool(re.search(pattern, doc, flags=re.IGNORECASE))
        return bool(re.match(pattern, doc, flags=re.IGNORECASE))
    except re.error:
        return False


def classify_document(
    document: str,
    rules: Optional[Iterable[dict]],
    *,
    fabric_names: Optional[Dict[str, List[str]]] = None,
) -> str:
    """Classifica o documento pela primeira regra (nome + padrão/regex) que
    combinar — ordem importa. Sem nenhuma regra correspondente, cai em
    FALLBACK_TYPE ('Fora do padrão'), que o usuário pode marcar manualmente
    com um subtipo (Teste, Terceirizado, ...) depois.

    A extensão do arquivo (ex.: '.jpeg') é removida antes de comparar —
    a classificação é sempre sobre o nome lógico do arquivo. Regras com
    um bloco "Tecido" na estrutura visual são recompiladas a cada chamada
    contra o cadastro de tecidos atual (`fabric_names`, ou o cadastro vivo se
    omitido), então nunca ficam "congeladas" com uma lista antiga."""
    doc = strip_extension(document or "").strip()
    normalized = normalize_rules(rules)
    fabric_names = _ensure_fabric_names(normalized, fabric_names)
    for rule in normalized:
        if rule.get("active", True) and _rule_matches(rule, doc, fabric_names):
            return rule["name"]
    return FALLBACK_TYPE


def matching_rules(
    document: str,
    rules: Optional[Iterable[dict]],
    *,
    fabric_names: Optional[Dict[str, List[str]]] = None,
) -> List[dict]:
    """Todas as regras ativas (na ordem de prioridade) cujo padrão combina
    com `document` — não só a vencedora. Usado pelo testador de regra (pra
    avisar quando mais de uma bate) e pelo detector de conflito."""
    doc = strip_extension(document or "").strip()
    normalized = normalize_rules(rules)
    fabric_names = _ensure_fabric_names(normalized, fabric_names)
    return [r for r in normalized if r.get("active", True) and _rule_matches(r, doc, fabric_names)]


def classify_with_detail(
    document: str,
    rules: Optional[Iterable[dict]],
    *,
    fabric_names: Optional[Dict[str, List[str]]] = None,
) -> dict:
    """Como `classify_document`, mas também informa a regra vencedora e
    quais outras regras também combinariam (relevante porque a ordem decide
    quem vence)."""
    hits = matching_rules(document, rules, fabric_names=fabric_names)
    return {
        "type": hits[0]["name"] if hits else FALLBACK_TYPE,
        "winner": hits[0] if hits else None,
        "also_matches": hits[1:],
    }


def detect_conflicts(
    examples: Iterable[str],
    other_rules: Optional[Iterable[dict]],
    *,
    fabric_names: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, List[str]]:
    """Para cada exemplo informado, quais das OUTRAS regras (não a que está
    sendo criada/editada) também combinam com ele — {exemplo: [nomes das
    regras em conflito]}. Não bloqueia nada; só informa, pra UI avisar antes
    de salvar."""
    normalized_others = normalize_rules(other_rules)
    fabric_names = _ensure_fabric_names(normalized_others, fabric_names)
    out: Dict[str, List[str]] = {}
    for ex in examples or []:
        ex = (ex or "").strip()
        if not ex:
            continue
        doc = strip_extension(ex).strip()
        hits = [
            r["name"]
            for r in normalized_others
            if r.get("active", True) and _rule_matches(r, doc, fabric_names)
        ]
        if hits:
            out[ex] = hits
    return out


def warn_duplicate_for_type(tipo: str, rules: Optional[Iterable[dict]]) -> bool:
    """Se itens desse tipo (ex.: 'Pedido', 'Reposição') devem entrar na
    verificação de duplicidade entre rolos (mesmo pedido + tecido já
    impresso em outro rolo) — configurável por regra em 'Tipos de
    impressão…'. Tipos sem regra correspondente (Fora do padrão, subtipos
    manuais) avisam por padrão, já que não têm esse campo."""
    for rule in normalize_rules(rules):
        if rule["name"] == tipo:
            return bool(rule.get("warn_duplicate", True))
    return True


def pedido_override_for_type(tipo: str, rules: Optional[Iterable[dict]]) -> Optional[str]:
    """Nome fixo do pedido configurado pra esse tipo (ex.: Reposição ->
    "Variados"), ou None se o tipo deve continuar detectando o pedido pelo
    nome do arquivo — o comportamento padrão, igual a sempre foi."""
    for rule in normalize_rules(rules):
        if rule["name"] == tipo:
            if rule.get("pedido_mode") == PEDIDO_MODE_FIXED:
                fixed = (rule.get("pedido_fixed") or "").strip()
                return fixed or None
            return None
    return None


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


__all__ = [
    "FALLBACK_TYPE",
    "DEFAULT_RULES",
    "DEFAULT_SUBTYPES",
    "normalize_rules",
    "normalize_subtypes",
    "validate_pattern",
    "classify_document",
    "matching_rules",
    "classify_with_detail",
    "detect_conflicts",
    "all_type_options",
    "warn_duplicate_for_type",
    "pedido_override_for_type",
    "new_rule_id",
]
