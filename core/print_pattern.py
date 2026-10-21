# core/print_pattern.py
"""Modelo estruturado de uma regra de 'Tipo de impressão' e o compilador que
a transforma em regex.

Uma regra deixa de ser "só uma regex digitada à mão" e passa a ser,
preferencialmente, uma sequência de blocos (`Component`) com um significado
conhecido (texto fixo, data, tecido, separador...). Essa sequência é
compilada para uma regex (`build_pattern`) sempre que a regra não foi
"personalizada" (regex editada manualmente pelo usuário no modo Avançado).

Este módulo não sabe nada de UI nem de Tkinter — é só modelo + compilador.
A análise de exemplos (sugestão de estrutura) está em
`core/print_pattern_analyzer.py`; a detecção de conflito entre regras está em
`core/print_pattern_conflicts.py`; a classificação em si continua em
`core/print_types.py`.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from core.fabrics import known_fabric_names_with_aliases

# ---------------------------------------------------------------------------
# Tipos de bloco (componentes)
# ---------------------------------------------------------------------------
KIND_FIXED = "texto_fixo"
KIND_VARIABLE = "texto_variavel"
KIND_DATE = "data"
KIND_NUMBER = "numero"
KIND_LETTERS = "letras"
KIND_LETTERS_NUMBER = "letras_numero"
KIND_NUMBER_LETTERS = "numero_letras"
KIND_FABRIC = "tecido"
KIND_SEPARATOR = "separador"
KIND_OPTIONAL = "opcional"

# Ordem usada nos seletores da UI.
ALL_KINDS: List[str] = [
    KIND_FIXED,
    KIND_VARIABLE,
    KIND_DATE,
    KIND_NUMBER,
    KIND_LETTERS,
    KIND_LETTERS_NUMBER,
    KIND_NUMBER_LETTERS,
    KIND_FABRIC,
    KIND_OPTIONAL,
    KIND_SEPARATOR,
]

KIND_LABELS: Dict[str, str] = {
    KIND_FIXED: "Texto fixo",
    KIND_VARIABLE: "Texto variável",
    KIND_DATE: "Data (dia-mês)",
    KIND_NUMBER: "Número",
    KIND_LETTERS: "Letras",
    KIND_LETTERS_NUMBER: "Letras + número",
    KIND_NUMBER_LETTERS: "Número + letras",
    KIND_FABRIC: "Tecido cadastrado",
    KIND_SEPARATOR: "Separador",
    KIND_OPTIONAL: "Opcional",
}

# Blocos de conteúdo (tudo que não é separador) — usados pelo analisador.
CONTENT_KINDS: List[str] = [k for k in ALL_KINDS if k != KIND_SEPARATOR]

MATCH_MODE_START = "start"       # começa com (comportamento histórico)
MATCH_MODE_EXACT = "exact"       # exatamente igual
MATCH_MODE_CONTAINS = "contains"  # contém

MATCH_MODE_LABELS: Dict[str, str] = {
    MATCH_MODE_START: "Começa com",
    MATCH_MODE_EXACT: "Exatamente igual",
    MATCH_MODE_CONTAINS: "Contém",
}

# Como detectar o "pedido" (nome do trabalho) pra arquivos deste tipo:
# PEDIDO_MODE_AUTO lê do nome do arquivo (comportamento padrão, igual a
# sempre foi); PEDIDO_MODE_FIXED usa sempre o mesmo nome configurado na
# regra (ex.: Reposição -> "Variados"), pra tipos cujo nome de arquivo não
# carrega um pedido de verdade.
PEDIDO_MODE_AUTO = "auto"
PEDIDO_MODE_FIXED = "fixed"

PEDIDO_MODE_LABELS: Dict[str, str] = {
    PEDIDO_MODE_AUTO: "Detectar pelo nome do arquivo",
    PEDIDO_MODE_FIXED: "Nome fixo",
}

SEPARATOR_CHARS = ("-", "/", "_", " ")

SEPARATOR_LABELS: Dict[str, str] = {
    "-": "- (hífen)",
    "/": "/ (barra)",
    "_": "_ (underline)",
    " ": "espaço",
}

_SEP_FRAGMENTS: Dict[str, str] = {
    "-": r"\s*-\s*",
    "/": r"\s*/\s*",
    "_": r"\s*_\s*",
    " ": r"\s+",
}

# Extensão de arquivo: removida antes de qualquer análise/classificação —
# a classificação é sempre sobre o "nome lógico" do arquivo.
_RE_FILE_EXT = re.compile(r"\.[A-Za-z0-9]{2,5}$")


def strip_extension(name: str) -> str:
    """Remove a extensão do nome do arquivo (ex.: '.jpeg', '.png'), se houver.
    Não assume nenhuma extensão específica — qualquer sufixo curto alfanumérico
    depois de um ponto é tratado como extensão."""
    return _RE_FILE_EXT.sub("", (name or "").strip())


# ---------------------------------------------------------------------------
# Componente
# ---------------------------------------------------------------------------
@dataclass
class Component:
    kind: str
    value: Optional[str] = None  # texto literal (texto_fixo) ou caractere do separador
    inner: Optional["Component"] = None  # usado só por 'opcional'

    def to_dict(self) -> dict:
        out = {"kind": self.kind}
        if self.value is not None:
            out["value"] = self.value
        if self.inner is not None:
            out["inner"] = self.inner.to_dict()
        return out

    @staticmethod
    def from_dict(d: dict) -> "Component":
        if not isinstance(d, dict) or not d.get("kind"):
            raise ValueError("Bloco inválido na estrutura do padrão.")
        inner_raw = d.get("inner")
        inner = Component.from_dict(inner_raw) if isinstance(inner_raw, dict) else None
        return Component(kind=str(d["kind"]), value=d.get("value"), inner=inner)

    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


def components_from_list(raw: Optional[List[dict]]) -> List[Component]:
    if not raw:
        return []
    out: List[Component] = []
    for item in raw:
        try:
            out.append(Component.from_dict(item))
        except ValueError:
            continue
    return out


def components_to_list(components: List[Component]) -> List[dict]:
    return [c.to_dict() for c in components]


def rule_uses_fabric(components: Optional[List[dict]]) -> bool:
    """True se algum bloco (direto ou dentro de um 'opcional') é do tipo Tecido —
    usado para decidir se vale a pena consultar o cadastro de tecidos."""
    for raw in (components or []):
        if not isinstance(raw, dict):
            continue
        if raw.get("kind") == KIND_FABRIC:
            return True
        inner = raw.get("inner")
        if isinstance(inner, dict) and inner.get("kind") == KIND_FABRIC:
            return True
    return False


# ---------------------------------------------------------------------------
# Compilador: componente(s) -> regex
# ---------------------------------------------------------------------------
def _compile_fabric_fragment(fabric_names: Optional[Dict[str, List[str]]]) -> str:
    names = fabric_names if fabric_names is not None else known_fabric_names_with_aliases()
    aliases: List[str] = []
    for canonical, alias_list in names.items():
        aliases.append(canonical)
        aliases.extend(alias_list)
    uniq = sorted({a.strip() for a in aliases if a and a.strip()}, key=len, reverse=True)
    if not uniq:
        # Sem cadastro de tecidos disponível: cai para texto variável, documentado
        # como limitação conhecida (ver relatório da funcionalidade).
        return r".+"
    return "(?:" + "|".join(re.escape(a) for a in uniq) + ")"


def compile_component(comp: Component, *, fabric_names: Optional[Dict[str, List[str]]] = None) -> str:
    kind = comp.kind
    if kind == KIND_FIXED:
        return re.escape((comp.value or "").strip())
    if kind == KIND_SEPARATOR:
        char = comp.value or "-"
        return _SEP_FRAGMENTS.get(char, re.escape(char))
    if kind == KIND_VARIABLE:
        return r".+"
    if kind == KIND_DATE:
        return r"\d{1,2}[-/.]\d{1,2}"
    if kind == KIND_NUMBER:
        return r"\d+"
    if kind == KIND_LETTERS:
        return r"[A-Za-z]+"
    if kind == KIND_LETTERS_NUMBER:
        return r"[A-Za-z]+\s*\d+"
    if kind == KIND_NUMBER_LETTERS:
        return r"\d+\s*[A-Za-z]+"
    if kind == KIND_FABRIC:
        return _compile_fabric_fragment(fabric_names)
    if kind == KIND_OPTIONAL:
        inner_fragment = (
            compile_component(comp.inner, fabric_names=fabric_names) if comp.inner else r".*"
        )
        return f"(?:{inner_fragment})?"
    raise ValueError(f"Tipo de bloco desconhecido: {kind!r}")


def compile_components(
    components: List[Component], *, fabric_names: Optional[Dict[str, List[str]]] = None
) -> str:
    return "".join(compile_component(c, fabric_names=fabric_names) for c in components)


def build_pattern(
    components: List[Component],
    match_mode: str = MATCH_MODE_START,
    *,
    fabric_names: Optional[Dict[str, List[str]]] = None,
) -> str:
    """Gera a regex final (com âncoras) a partir da estrutura visual."""
    body = compile_components(components, fabric_names=fabric_names)
    if match_mode == MATCH_MODE_EXACT:
        return f"^\\s*{body}\\s*$"
    if match_mode == MATCH_MODE_CONTAINS:
        return body
    return f"^\\s*{body}"


# ---------------------------------------------------------------------------
# Regra (persistência) — dict com chaves estáveis, compatível com o formato
# legado {"name", "pattern"}.
# ---------------------------------------------------------------------------
def _deterministic_id(name: str, pattern: str) -> str:
    digest = hashlib.sha1(f"{name}:{pattern}".encode("utf-8")).hexdigest()
    return f"legacy-{digest[:12]}"


def new_rule_id() -> str:
    """Id novo para uma regra criada do zero pelo editor visual (regras
    migradas de um formato antigo recebem um id determinístico em vez
    disso, ver `_deterministic_id`, pra não mudar de id a cada carregamento)."""
    return uuid.uuid4().hex[:12]


def migrate_rule_dict(raw: dict) -> dict:
    """Converte uma regra no formato antigo {'name','pattern'} (ou já no
    formato novo, possivelmente faltando campos) para o formato completo.

    Regras antigas não ganham estrutura visual (`components=None`) e são
    marcadas como `custom_regex=True` — o regex original é preservado
    exatamente como estava, sem tentar "adivinhar" os blocos. Isso evita
    reinterpretar incorretamente uma regra que já funcionava."""
    name = str(raw.get("name", "")).strip()
    pattern = str(raw.get("pattern", "")).strip()

    has_id = bool(raw.get("id"))
    components = raw.get("components")
    if not isinstance(components, list) or not components:
        components = None

    # "Avisar duplicidade entre rolos" (mesmo pedido + tecido já impresso em
    # outro rolo): padrão é avisar, EXCETO pra uma regra "Reposição" que
    # ainda não tem esse campo salvo (config antiga, de antes dele existir)
    # — reposição reaproveita o mesmo nome de arquivo quase sempre, então o
    # aviso seria só ruído. Uma vez salva pela tela de configurações, essa
    # regra já vem com o campo explícito e esse fallback não se aplica mais.
    if "warn_duplicate" in raw:
        warn_duplicate = bool(raw.get("warn_duplicate"))
    else:
        warn_duplicate = name.strip().casefold() != "reposição"

    # Como detectar o pedido pra arquivos deste tipo: pelo nome do arquivo
    # (padrão, igual a sempre foi) ou um nome fixo configurado na regra.
    pedido_mode = str(raw.get("pedido_mode") or PEDIDO_MODE_AUTO)
    if pedido_mode not in (PEDIDO_MODE_AUTO, PEDIDO_MODE_FIXED):
        pedido_mode = PEDIDO_MODE_AUTO
    pedido_fixed = str(raw.get("pedido_fixed") or "").strip()

    out = {
        "id": str(raw["id"]) if has_id else _deterministic_id(name, pattern),
        "name": name,
        "pattern": pattern,
        "match_mode": str(raw.get("match_mode") or MATCH_MODE_START),
        "components": components,
        "examples": [str(x) for x in (raw.get("examples") or []) if str(x).strip()],
        # Regra sem "components" é, por definição, regex personalizada (não há
        # estrutura visual para regenerá-la a partir dela).
        "custom_regex": bool(raw.get("custom_regex", components is None)),
        "active": bool(raw.get("active", True)),
        "warn_duplicate": warn_duplicate,
        "pedido_mode": pedido_mode,
        "pedido_fixed": pedido_fixed,
    }
    return out


def resolve_pattern(rule: dict, *, fabric_names: Optional[Dict[str, List[str]]] = None) -> str:
    """Pattern final a usar na classificação: se a regra tem estrutura visual
    e não foi marcada como personalizada, a regex é SEMPRE regerada a partir
    dos componentes (consultando o cadastro de tecidos atual) — nunca fica
    "congelada" com uma lista de tecidos antiga. Caso contrário, usa o regex
    guardado (personalizado ou regra legada)."""
    components = rule.get("components")
    if rule.get("custom_regex") or not components:
        return rule.get("pattern", "")
    try:
        comps = components_from_list(components)
        return build_pattern(comps, rule.get("match_mode", MATCH_MODE_START), fabric_names=fabric_names)
    except ValueError:
        return rule.get("pattern", "")
