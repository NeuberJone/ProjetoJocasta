"""Parte 1 da conclusão do recurso de identificação de vendedor/PDF original
(ver especificação final, "Concluir rastreabilidade de vendedores e PDFs
originais"): aplica, depois que um rolo é salvo em Operação (quando cada
pedido já tem um `order_id` real), as decisões tomadas pelo operador no
painel de pré-visualização — ANTES disso, enquanto o rolo ainda está sendo
editado, não existe `order_id` nenhum (ver core/order_vendor_resolution.py
e core/order_pdfs.py), então nada ali grava no banco.

Extraído para fora de modules/operacao/ui.py (que não tem suíte de testes
própria por depender de Tkinter) justamente para que esta lógica — a parte
com real risco de regressão silenciosa — seja testável isoladamente, com
SQLite temporário, sem precisar abrir nenhuma janela.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.order_files import VendorIndexState, folder_for_vendor, load_order_index
from core.order_pdfs import link_order_pdf, resolve_order_pdf
from core.order_vendor_resolution import confirm_order_vendor, resolve_order_vendor
from core.printlogs_db import get_roll_orders
from core.vendedores import Vendedor, load_vendedores


@dataclass
class PedidoSessionDecision:
    """Estado de sessão de um pedido (chaveado pelo nome do pedido — ver
    módulo docstring de modules/operacao/ui.py: dentro de uma única edição
    de rolo, PedidoSummary já agrupa por nome, então não há ambiguidade
    aqui) no painel de pré-visualização, ANTES do rolo ser salvo.

    `vendor_confirmed`/`pdf_confirmed` só ficam True quando o operador
    escolheu explicitamente algo no painel (um diálogo de "Escolher
    vendedor..."/"Escolher PDF..." concluído) — uma sugestão automática
    ainda não confirmada nunca seta isso, pra `apply_session_decisions`
    saber a diferença entre "o operador confirmou isto" e "é só o que a
    tela estava sugerindo quando o rolo foi salvo"."""
    pedido: str
    vendor_state: str = ""  # "" = ainda não calculado; senão RESOLUTION_AUTO/AMBIGUOUS/NOT_FOUND
    vendor_key: str = ""
    vendor_name: str = ""
    vendor_confirmed: bool = False
    folder: str = ""
    pdf_state: str = ""  # "" = ainda não calculado; senão PDF_RESOLUTION_AUTO/AMBIGUOUS/NOT_FOUND
    pdf_path: str = ""
    pdf_confirmed: bool = False
    candidates_vendor: List[object] = field(default_factory=list)
    candidates_pdf: List[object] = field(default_factory=list)


def apply_session_decisions(
    roll_id: int,
    decisions: Dict[str, PedidoSessionDecision],
    *,
    index: Optional[VendorIndexState] = None,
    vendedores: Optional[List[Vendedor]] = None,
) -> None:
    """Chamada depois que `save_export_transactional`/`update_roll_orders`
    já salvou o rolo (ver modules/operacao/ui.py:on_export) — para cada
    pedido real (nunca avanço/espaço, que nunca tem vendedor), aplica a
    decisão de sessão se houver uma confirmada; senão, cai no mesmo
    comportamento automático que já existia (Etapa F: `resolve_order_vendor`
    por `order_id`) — e agora também tenta resolver o PDF automaticamente
    (antes disso só acontecia manualmente, pelos Registros).

    Uma decisão de vendedor confirmada tem precedência (via
    `confirm_order_vendor`, mesma origem "manual" de uma correção feita
    depois pelos Registros). Uma decisão de PDF confirmada é aplicada
    (`link_order_pdf`) independente do estado do vendedor — o operador pode
    ter escolhido o PDF manualmente mesmo sem vendedor identificado."""
    index = index if index is not None else load_order_index()
    vendedores = vendedores if vendedores is not None else load_vendedores()

    for order_row in get_roll_orders(roll_id):
        if not order_row.get("tipo"):
            continue  # avanço/espaço — nunca tem vendedor nem PDF

        pedido = str(order_row["pedido"])
        order_id = int(order_row["id"])
        decision = decisions.get(pedido)

        vendor_key = ""
        if decision and decision.vendor_confirmed and decision.vendor_key:
            confirm_order_vendor(order_id, decision.vendor_key, decision.vendor_name)
            vendor_key = decision.vendor_key
        else:
            result = resolve_order_vendor(order_id, pedido, index=index, vendedores=vendedores)
            vendor_key = result.vendor_key

        if decision and decision.pdf_confirmed and decision.pdf_path:
            link_order_pdf(order_id, decision.pdf_path)
        elif vendor_key:
            folder = (decision.folder if decision else "") or folder_for_vendor(pedido, index, vendor_key)
            if folder:
                resolve_order_pdf(order_id, folder)
