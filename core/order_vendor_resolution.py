"""Etapa C — associação: identificação automática do vendedor de um pedido
e confirmação/correção manual (ver especificação original, seção 7 —
"Identificação automática do vendedor").

Camada que fica ACIMA de core/order_files.py (Etapa B — índice + motor de
correspondência, que não decide nem grava nada por conta própria) e de
core/printlogs_db.py (Etapa A — persistência do vínculo pedido<->vendedor).
Ainda independente de interface (a integração em Operação/Registros é a
Etapa E) — tudo aqui são funções síncronas e puras o quanto possível, com
efeito colateral apenas na gravação explícita do vínculo.

Prioridade de resolução (ver especificação, seção 6 — "Prioridade da
correspondência" — e seção 7 — "Comportamento"):

1. Vínculo manual confirmado anteriormente — tem precedência absoluta; uma
   nova resolução NUNCA sobrescreve silenciosamente uma correção manual.
2. Correspondência exata única no índice — pode ser atribuída automaticamente.
3. Correspondência exata em mais de um vendedor (ambiguidade) — nunca decide
   por conta própria; exige confirmação manual.
4. Nenhuma correspondência exata (só aproximada, ou nenhuma) — pedido fica
   "não identificado"; aproximações são só sugestões, nunca vínculo definitivo.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from core.order_files import MATCH_EXACT, OrderCandidate, VendorIndexState, find_order_candidates, load_order_index
from core.printlogs_db import (
    VENDOR_LINK_ORIGIN_AUTO,
    VENDOR_LINK_ORIGIN_MANUAL,
    VENDOR_LINK_STATUS_ACTIVE,
    clear_vendor_link,
    get_vendor_link,
    upsert_vendor_link,
)
from core.vendedores import Vendedor, load_vendedores

# Estados possíveis de identificação de um pedido (ver especificação, seção 7 — "Estados").
RESOLUTION_AUTO = "auto_identified"
RESOLUTION_MANUAL = "confirmed_manual"
RESOLUTION_NOT_FOUND = "not_identified"
RESOLUTION_AMBIGUOUS = "ambiguous"


@dataclass
class OrderVendorResolution:
    state: str
    vendor_key: str = ""
    vendor_name: str = ""
    candidates: List[OrderCandidate] = field(default_factory=list)
    link: Optional[dict] = None
    # True quando o vínculo atual depende de uma pasta raiz que está
    # reportando erro na rodada mais recente do índice (ver
    # core.order_files.refresh_order_index) — não impede nada, é só um aviso
    # pra quem for exibir isto na interface (seção 7 — "Vínculo com origem
    # indisponível"): o vínculo em si é preservado, nunca apagado por isso.
    source_unavailable: bool = False


def _vendor_root_unavailable(vendor_key: str, vendedores: List[Vendedor], index: VendorIndexState) -> bool:
    if not vendor_key or not index.errors:
        return False
    vendor = next((v for v in vendedores if v.key == vendor_key), None)
    if not vendor:
        return False
    # `core.order_files._walk_vendor_root` monta cada erro como "<path>: <motivo>",
    # onde <path> é a própria pasta raiz do vendedor OU uma pasta de
    # cliente um nível abaixo dela — nunca comparar com startswith() puro
    # no caminho (uma raiz "...\Loja" é prefixo de string de "...\LojaNova",
    # marcando o vendedor errado como indisponível por um erro que é de
    # outro vendedor). Comparação sem diferenciar caixa: caminho de pasta no
    # Windows é case-insensitive, e o cadastro do vendedor pode ter sido
    # editado (ex.: corrigindo a caixa da letra da unidade) entre uma
    # rodada do índice e a próxima checagem deste vínculo.
    errors_lower = [str(error).lower() for error in index.errors]
    return any(
        any(
            error_lower.startswith(f"{folder.path.lower()}:") or error_lower.startswith(f"{folder.path.lower()}{os.sep}")
            for error_lower in errors_lower
        )
        for folder in vendor.folders
    )


def resolve_order_vendor(
    order_id: int,
    pedido_name: str,
    *,
    index: Optional[VendorIndexState] = None,
    vendedores: Optional[List[Vendedor]] = None,
) -> OrderVendorResolution:
    """Identifica (ou confirma) o vendedor de um pedido já registrado no
    Nexor (`order_id`, de core.printlogs_db). Só GRAVA um vínculo novo
    quando encontra exatamente uma correspondência exata e não existir um
    vínculo manual ativo — qualquer outro caso é só informativo (nada é
    escrito), pra quem chamar decidir o que fazer (ver docstring do módulo)."""
    vendedores = vendedores if vendedores is not None else load_vendedores()
    index = index if index is not None else load_order_index()

    existing = get_vendor_link(order_id)
    if existing and existing["origin"] == VENDOR_LINK_ORIGIN_MANUAL and existing["status"] == VENDOR_LINK_STATUS_ACTIVE:
        return OrderVendorResolution(
            state=RESOLUTION_MANUAL,
            vendor_key=existing["vendor_key"],
            vendor_name=existing["vendor_name_snapshot"],
            link=existing,
            source_unavailable=_vendor_root_unavailable(existing["vendor_key"], vendedores, index),
        )

    candidates = find_order_candidates(pedido_name, index)
    exact = [c for c in candidates if c.match_kind == MATCH_EXACT]

    if len(exact) == 1:
        chosen = exact[0]
        already_linked = (
            existing
            and existing["status"] == VENDOR_LINK_STATUS_ACTIVE
            and existing["origin"] == VENDOR_LINK_ORIGIN_AUTO
            and existing["vendor_key"] == chosen.vendor_key
        )
        link = existing if already_linked else upsert_vendor_link(
            order_id,
            vendor_key=chosen.vendor_key,
            vendor_name_snapshot=chosen.vendor_name_snapshot,
            origin=VENDOR_LINK_ORIGIN_AUTO,
        )
        return OrderVendorResolution(
            state=RESOLUTION_AUTO,
            vendor_key=chosen.vendor_key,
            vendor_name=chosen.vendor_name_snapshot,
            candidates=exact,
            link=link,
            source_unavailable=_vendor_root_unavailable(chosen.vendor_key, vendedores, index),
        )

    source_unavailable = bool(existing) and _vendor_root_unavailable(existing["vendor_key"], vendedores, index)

    if len(exact) > 1:
        # Ambíguo: nunca escolhe por conta própria (seção 6 — "Não
        # selecionar arbitrariamente o primeiro resultado"). Um vínculo
        # automático anterior (de uma rodada em que ainda não havia
        # ambiguidade) é preservado, não apagado.
        return OrderVendorResolution(state=RESOLUTION_AMBIGUOUS, candidates=exact, link=existing, source_unavailable=source_unavailable)

    # Nenhuma correspondência exata — aproximadas (se houver) são só
    # sugestões (seção 6 — "Uma correspondência aproximada nunca deve gerar
    # vínculo definitivo sem confirmação"). Um vínculo anterior também não é
    # apagado só porque o índice não achou mais o pedido nesta rodada.
    return OrderVendorResolution(state=RESOLUTION_NOT_FOUND, candidates=candidates, link=existing, source_unavailable=source_unavailable)


def confirm_order_vendor(order_id: int, vendor_key: str, vendor_name: str, *, note: str = "") -> dict:
    """Confirmação (ou correção) manual — origem 'manual', que passa a ter
    precedência sobre qualquer resolução automática futura (ver
    especificação, seção 7: "A identificação manual deverá ter precedência
    sobre a automática.")."""
    return upsert_vendor_link(
        order_id, vendor_key=vendor_key, vendor_name_snapshot=vendor_name, origin=VENDOR_LINK_ORIGIN_MANUAL, note=note,
    )


def clear_order_vendor(order_id: int, *, note: str = "") -> bool:
    """Remove (sem apagar o histórico) o vínculo atual de um pedido — depois
    disso, a próxima chamada de resolve_order_vendor volta a poder atribuir
    automaticamente, mesmo que o vínculo removido fosse manual."""
    return clear_vendor_link(order_id, note=note)


@dataclass
class VendorPreview:
    """Pré-visualização SOMENTE LEITURA do vendedor de um pedido, sem
    `order_id` — usada no painel de Operação (Parte 1 da conclusão do
    recurso) e, indiretamente, pelo comprovante Prisma via
    `guess_vendor_name_for_pedido`. Nunca lê nem grava nenhum vínculo."""
    state: str
    vendor_key: str = ""
    vendor_name: str = ""
    candidates: List[OrderCandidate] = field(default_factory=list)


def preview_order_vendor(pedido_name: str, *, index: Optional[VendorIndexState] = None) -> VendorPreview:
    """Mesma prioridade de `resolve_order_vendor` (seção 6: correspondência
    exata única > ambíguo > não encontrado), mas sem `order_id` e sem nunca
    ler/gravar nenhum vínculo — o pedido ainda não existe no banco quando
    isto é chamado (painel de Operação, antes de salvar o rolo). Uma
    correspondência aproximada nunca aparece como estado "auto", só como
    candidato dentro de `NOT_FOUND` (mesma regra de `resolve_order_vendor`:
    nunca vira vínculo definitivo sem confirmação)."""
    index = index if index is not None else load_order_index()
    candidates = find_order_candidates(pedido_name, index)
    exact = [c for c in candidates if c.match_kind == MATCH_EXACT]

    if len(exact) == 1:
        chosen = exact[0]
        return VendorPreview(state=RESOLUTION_AUTO, vendor_key=chosen.vendor_key, vendor_name=chosen.vendor_name_snapshot, candidates=exact)
    if len(exact) > 1:
        return VendorPreview(state=RESOLUTION_AMBIGUOUS, candidates=exact)
    return VendorPreview(state=RESOLUTION_NOT_FOUND, candidates=candidates)


def guess_vendor_name_for_pedido(
    pedido_name: str,
    *,
    index: Optional[VendorIndexState] = None,
) -> str:
    """Pré-visualização SOMENTE LEITURA do vendedor de um pedido, sem
    `order_id` — usada no comprovante Prisma (ver core/prisma_report.py),
    gerado ANTES do rolo ser salvo (o pedido ainda não tem `order_id`
    persistido; ver limitação já documentada do painel de Operação).

    Aplica só a parte seguramente automática da mesma prioridade de
    `resolve_order_vendor` (seção 6 da especificação): uma única
    correspondência exata vira o nome mostrado; ambiguidade, correspondência
    só aproximada ou nenhuma correspondência retornam "" (o comprovante
    então omite a linha "Vendedor", nunca mostra um palpite). Nunca lê nem
    grava nenhum vínculo — a persistência real (com todos os estados e a
    precedência do vínculo manual) continua sendo responsabilidade de
    `resolve_order_vendor`, chamada depois que o rolo é salvo."""
    preview = preview_order_vendor(pedido_name, index=index)
    return preview.vendor_name if preview.state == RESOLUTION_AUTO else ""
