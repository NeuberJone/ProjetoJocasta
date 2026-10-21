# core/print_pattern_analyzer.py
"""Analisador de exemplos de nome de arquivo: a partir de um ou mais
exemplos, sugere uma sequência de componentes (`core.print_pattern.Component`)
— nunca decide sozinho e definitivamente; só sugere. A UI é responsável por
pedir confirmação de cada bloco antes de salvar.

Regras de prioridade (por posição, depois de alinhar os exemplos):
1) 2+ exemplos alinhados e idênticos nessa posição         -> texto fixo (alta)
2) todos batem com o cadastro de tecidos                   -> tecido (alta)
3) todos seguem um padrão estrutural (data/letras+número/…) -> esse tipo (alta)
4) 2+ exemplos e nenhuma das regras acima bateu             -> texto variável (média)
5) só 1 exemplo nessa posição:
   - bate no cadastro de tecidos                            -> tecido (alta)
   - segue um padrão estrutural                             -> esse tipo (média)
   - é uma única palavra (sem espaço)                       -> texto fixo (baixa)
   - tem espaço interno (frase)                              -> texto variável (baixa)

Confiança "baixa" vem sempre acompanhada de uma nota explicando que o
usuário precisa escolher o tipo do bloco — não tentamos parecer mais
confiantes do que realmente estamos.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.fabrics import known_fabric_names_with_aliases
from core.print_pattern import (
    KIND_DATE,
    KIND_FABRIC,
    KIND_FIXED,
    KIND_LETTERS_NUMBER,
    KIND_NUMBER,
    KIND_NUMBER_LETTERS,
    KIND_SEPARATOR,
    KIND_VARIABLE,
    MATCH_MODE_EXACT,
    MATCH_MODE_START,
    Component,
    strip_extension,
)

LOW_CONFIDENCE_NOTE = "Não foi possível identificar esta parte com segurança. Escolha o tipo do bloco."

CONFIDENCE_HIGH = "alta"
CONFIDENCE_MEDIUM = "media"
CONFIDENCE_LOW = "baixa"

# Separador: qualquer trecho com ao menos um '-', '/' ou '_' (com espaços
# opcionais em volta). Espaço puro NÃO é separador estrutural por padrão —
# "Nome do Pedido" é um bloco só, não três. Isso é consistente com todos os
# exemplos de referência do Nexor (o separador de campo é sempre " - ", " / "
# ou similar, nunca um espaço isolado).
_SEP_RUN = re.compile(r"\s*[-/_]\s*")
_DATE_RUN = re.compile(r"\d{1,2}[-/.]\d{1,2}")

_RE_DATE_FULL = re.compile(r"^\d{1,2}[-/.]\d{1,2}$")
_RE_LETTERS_NUMBER_FULL = re.compile(r"^[A-Za-z]+\s*\d+$")
_RE_NUMBER_LETTERS_FULL = re.compile(r"^\d+\s*[A-Za-z]+$")
_RE_NUMBER_FULL = re.compile(r"^\d+$")


@dataclass
class ScannedBlock:
    role: str  # "content" | "sep"
    text: str
    sep_char: Optional[str] = None


def scan_example(example: str) -> List[ScannedBlock]:
    """Quebra um exemplo (sem extensão) em blocos de conteúdo e separador,
    preservando datas como um bloco único (ex.: '26-10') mesmo usando '-' ou
    '/' internamente."""
    text = (example or "").strip()
    n = len(text)
    protected = [m.span() for m in _DATE_RUN.finditer(text)]
    blocks: List[ScannedBlock] = []
    pos = 0
    pi = 0
    while pos < n:
        if pi < len(protected) and protected[pi][0] == pos:
            start, end = protected[pi]
            blocks.append(ScannedBlock(role="content", text=text[start:end]))
            pos = end
            pi += 1
            continue

        limit = protected[pi][0] if pi < len(protected) else n
        chunk = text[pos:limit]

        m = _SEP_RUN.match(chunk)
        if m and m.end() > 0:
            sep_text = m.group(0)
            char = next((c for c in sep_text if c != " "), " ")
            blocks.append(ScannedBlock(role="sep", text=sep_text, sep_char=char))
            pos += m.end()
            continue

        m2 = _SEP_RUN.search(chunk)
        end_rel = m2.start() if m2 else len(chunk)
        if end_rel <= 0:
            end_rel = 1
        blocks.append(ScannedBlock(role="content", text=chunk[:end_rel]))
        pos += end_rel
    return blocks


def _shape_signature(blocks: List[ScannedBlock]) -> Tuple[object, ...]:
    return tuple(("sep", b.sep_char) if b.role == "sep" else ("content",) for b in blocks)


def _most_common_shape(shapes: List[Tuple[object, ...]]) -> Tuple[object, ...]:
    counts: Dict[Tuple[object, ...], int] = {}
    order: List[Tuple[object, ...]] = []
    for s in shapes:
        if s not in counts:
            counts[s] = 0
            order.append(s)
        counts[s] += 1
    best = order[0]
    for s in order[1:]:
        if counts[s] > counts[best]:
            best = s
    return best


def _fabric_lookup(fabric_names: Optional[Dict[str, List[str]]]) -> Dict[str, str]:
    names = fabric_names if fabric_names is not None else known_fabric_names_with_aliases()
    out: Dict[str, str] = {}
    for canonical, aliases in names.items():
        out[canonical.strip().casefold()] = canonical
        for a in aliases:
            a = (a or "").strip()
            if a:
                out[a.casefold()] = canonical
    return out


@dataclass
class BlockSuggestion:
    position: int
    sample_text: str
    kind: str
    value: Optional[str] = None
    confidence: str = CONFIDENCE_MEDIUM
    note: Optional[str] = None
    matched_fabric: Optional[str] = None


def _suggest_kind(texts: List[str], fabric_index: Dict[str, str], *, is_sole_block: bool) -> BlockSuggestion:
    sample = texts[0]
    if len(texts) >= 2:
        if len(set(texts)) == 1:
            return BlockSuggestion(0, sample, KIND_FIXED, value=sample, confidence=CONFIDENCE_HIGH)
        if all(t.casefold() in fabric_index for t in texts):
            return BlockSuggestion(0, sample, KIND_FABRIC, confidence=CONFIDENCE_HIGH,
                                    matched_fabric=fabric_index[sample.casefold()])
        if all(_RE_DATE_FULL.match(t) for t in texts):
            return BlockSuggestion(0, sample, KIND_DATE, confidence=CONFIDENCE_HIGH)
        if all(_RE_LETTERS_NUMBER_FULL.match(t) for t in texts):
            return BlockSuggestion(0, sample, KIND_LETTERS_NUMBER, confidence=CONFIDENCE_HIGH)
        if all(_RE_NUMBER_LETTERS_FULL.match(t) for t in texts):
            return BlockSuggestion(0, sample, KIND_NUMBER_LETTERS, confidence=CONFIDENCE_HIGH)
        if all(_RE_NUMBER_FULL.match(t) for t in texts):
            return BlockSuggestion(0, sample, KIND_NUMBER, confidence=CONFIDENCE_HIGH)
        return BlockSuggestion(0, sample, KIND_VARIABLE, confidence=CONFIDENCE_MEDIUM)

    # exatamente 1 exemplo alinhado nesta posição
    if sample.casefold() in fabric_index:
        return BlockSuggestion(0, sample, KIND_FABRIC, confidence=CONFIDENCE_HIGH,
                                matched_fabric=fabric_index[sample.casefold()])
    if _RE_DATE_FULL.match(sample):
        return BlockSuggestion(0, sample, KIND_DATE, confidence=CONFIDENCE_MEDIUM)
    if _RE_LETTERS_NUMBER_FULL.match(sample):
        return BlockSuggestion(0, sample, KIND_LETTERS_NUMBER, confidence=CONFIDENCE_MEDIUM)
    if _RE_NUMBER_LETTERS_FULL.match(sample):
        return BlockSuggestion(0, sample, KIND_NUMBER_LETTERS, confidence=CONFIDENCE_MEDIUM)
    if _RE_NUMBER_FULL.match(sample):
        return BlockSuggestion(0, sample, KIND_NUMBER, confidence=CONFIDENCE_MEDIUM)
    # Bloco único (o exemplo inteiro, sem nenhum separador estrutural) lê
    # como uma frase fixa (ex.: "Teste de cor"), mesmo com espaços internos.
    # Já um bloco de texto entre outros separadores (ex.: "Nome do Pedido"
    # em "Amostra - Nome do Pedido - Tecido") lê como campo variável.
    if is_sole_block:
        return BlockSuggestion(0, sample, KIND_FIXED, value=sample, confidence=CONFIDENCE_LOW, note=LOW_CONFIDENCE_NOTE)
    if " " in sample:
        return BlockSuggestion(0, sample, KIND_VARIABLE, confidence=CONFIDENCE_LOW, note=LOW_CONFIDENCE_NOTE)
    return BlockSuggestion(0, sample, KIND_FIXED, value=sample, confidence=CONFIDENCE_LOW, note=LOW_CONFIDENCE_NOTE)


@dataclass
class AnalysisResult:
    components: List[Component] = field(default_factory=list)
    blocks: List[BlockSuggestion] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    consistent: bool = True
    suggested_match_mode: str = MATCH_MODE_START


def analyze_examples(
    examples: List[str], *, fabric_names: Optional[Dict[str, List[str]]] = None
) -> AnalysisResult:
    """Sugere uma estrutura (sequência de componentes) a partir de 1+
    exemplos de nome de arquivo. Sempre uma SUGESTÃO — quem decide é quem
    chama (a UI), confirmando ou trocando cada bloco antes de salvar."""
    cleaned = [strip_extension(e).strip() for e in (examples or []) if e and e.strip()]
    if not cleaned:
        return AnalysisResult(warnings=["Informe ao menos um exemplo de nome de arquivo."])

    scans = [scan_example(e) for e in cleaned]
    shapes = [_shape_signature(s) for s in scans]
    primary_shape = _most_common_shape(shapes)

    aligned_scans: List[List[ScannedBlock]] = []
    warnings: List[str] = []
    primary_scan: Optional[List[ScannedBlock]] = None
    for text, scan, shape in zip(cleaned, scans, shapes):
        if shape == primary_shape:
            aligned_scans.append(scan)
            if primary_scan is None:
                primary_scan = scan
        else:
            warnings.append(
                f'O exemplo "{text}" não segue a mesma estrutura dos demais e foi ignorado '
                "na sugestão (mas continua disponível para testar a regra)."
            )

    assert primary_scan is not None
    fabric_index = _fabric_lookup(fabric_names)

    content_block_indexes = [i for i, b in enumerate(primary_scan) if b.role == "content"]
    is_sole_block = len(content_block_indexes) == 1
    block_suggestions: List[BlockSuggestion] = []
    for pos, block_idx in enumerate(content_block_indexes):
        texts = [scan[block_idx].text.strip() for scan in aligned_scans]
        sug = _suggest_kind(texts, fabric_index, is_sole_block=is_sole_block)
        sug.position = pos
        block_suggestions.append(sug)

    components: List[Component] = []
    cursor = 0
    for block in primary_scan:
        if block.role == "sep":
            components.append(Component(kind=KIND_SEPARATOR, value=block.sep_char or "-"))
        else:
            sug = block_suggestions[cursor]
            cursor += 1
            components.append(Component(kind=sug.kind, value=sug.value))

    # Um único bloco fixo (ex.: "Teste de cor") lê melhor como "exatamente
    # igual" por padrão — qualquer outro caso mantém o histórico "começa com".
    suggested_mode = MATCH_MODE_START
    if is_sole_block and block_suggestions and block_suggestions[0].kind == KIND_FIXED:
        suggested_mode = MATCH_MODE_EXACT

    return AnalysisResult(
        components=components,
        blocks=block_suggestions,
        warnings=warnings,
        consistent=not warnings,
        suggested_match_mode=suggested_mode,
    )
