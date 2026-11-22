from __future__ import annotations

import importlib
import os
import traceback
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from .helpers import format_m, payload_summary, safe_int
from core.paths import reveal_file_in_explorer
from core.logging_config import get_logger, log_exception
from core.order_files import folder_for_vendor, load_order_index
from core.order_pdfs import (
    PDF_RESOLUTION_AMBIGUOUS,
    PDF_RESOLUTION_NOT_FOUND,
    link_order_pdf,
    open_order_folder,
    open_order_pdf,
    reveal_order_pdf,
    resolve_order_pdf,
)
from core.order_vendor_resolution import (
    RESOLUTION_AMBIGUOUS,
    RESOLUTION_AUTO,
    RESOLUTION_MANUAL,
    clear_order_vendor,
    confirm_order_vendor,
    resolve_order_vendor,
)
from core.printlogs_db import (
    OCCURRENCE_STATUS_OPEN,
    OCCURRENCE_STATUSES,
    PDF_LINK_STATUS_ACTIVE,
    VENDOR_LINK_STATUS_ACTIVE,
    _OPERACAO_MODULE_NAMES,
    _PLANEJADOR_MODULE_NAMES,
    add_occurrence_entry,
    compute_machine_metrics,
    create_occurrence,
    get_occurrence_history,
    get_pdf_link,
    get_vendor_link,
    is_test_roll_name,
    list_duplicate_export_groups,
    list_occurrences_for_roll,
    list_rework_candidates,
    reconcile_planned_vs_logged,
)
from core.ui import ask_pick_from_list, card, dialog_header, page_heading
from core.vendedores import load_vendedores
from modules.operacao.models import Job as OperacaoJob
from modules.operacao.parser import build_blocks, build_pedido_summary
from .px_export import build_order_context_document, write_order_context_document
from .repository import (
    load_distinct_tipos,
    load_roll_events,
    load_roll_module,
    load_roll_order_version_options,
    load_roll_orders,
    load_roll_orders_for_version,
    load_roll_original_pdf_path,
    load_roll_pdf_path,
    load_roll_summary,
    load_roll_was_edited,
    search_rolls,
)

_logger = get_logger(__name__)

# Mapeia tanto os nomes antigos (rolos já exportados antes do rebrand pra
# Nexor) quanto os novos — sem isso, "Editar rolo" quebraria pra todo o
# histórico de rolos exportados com payload["module"] = "PXPrintCalc"/"PXPrintLogs".
# Derivado dos mesmos conjuntos canônicos de core/printlogs_db.py (achado de
# revisão de código: antes era um dict reescrito à mão aqui, podendo
# divergir silenciosamente se um alias novo fosse adicionado só lá — ver
# `is_operacao` mais abaixo, que decide "avanço/espaço" a partir disto).
_EDIT_ROUTES = {
    **{name: "modules.planejador" for name in _PLANEJADOR_MODULE_NAMES},
    **{name: "modules.operacao" for name in _OPERACAO_MODULE_NAMES},
}

_DISPLAY_NAMES = {
    "modules.planejador": "Planejador",
    "modules.operacao": "Operação",
}

# Opção do filtro "Vendedor" pra rolos sem vínculo ativo — nunca é o nome
# real de um vendedor cadastrado (ver core/vendedores.py:_slugify — nomes
# de vendedor nunca têm "—"), então não há ambiguidade na combobox.
_VENDOR_FILTER_UNIDENTIFIED = "— Sem vendedor identificado —"


def _parse_order_end_time(raw: object) -> datetime:
    try:
        return datetime.fromisoformat(str(raw))
    except Exception:
        return datetime.now()


def _vendor_status_text(order_id: int) -> str:
    """Texto da coluna "Vendedor" — só lê o vínculo já persistido (ver
    Etapa C: core.order_vendor_resolution/core.printlogs_db), nunca
    pesquisa pastas aqui: isso só acontece quando o operador pede
    explicitamente ("Localizar vendedor/PDF"), pra não deixar esta tela
    lenta/travada toda vez que uma lista é recarregada."""
    link = get_vendor_link(order_id)
    if not link or link["status"] != VENDOR_LINK_STATUS_ACTIVE:
        return "Não identificado"
    suffix = " (manual)" if link["origin"] == "manual" else ""
    return f'{link["vendor_name_snapshot"]}{suffix}'


def _pdf_status_text(order_id: int) -> str:
    """Texto da coluna "PDF" — mesmo princípio de _vendor_status_text:
    só leitura do vínculo já persistido (Etapa D)."""
    link = get_pdf_link(order_id)
    if not link or link["status"] != PDF_LINK_STATUS_ACTIVE:
        return "Sem PDF"
    try:
        return Path(link["pdf_path"]).name
    except Exception:
        return link["pdf_path"]


def _format_duration_minutes(minutes: float) -> str:
    """"Xh Ymin" (ou só "Ymin" com menos de uma hora) — usado na aba
    "Métricas"; `core.format.fmt_m` é só pra metros, não serve aqui."""
    total_minutes = max(0, round(minutes))
    hours, mins = divmod(total_minutes, 60)
    return f"{hours}h {mins:02d}min" if hours else f"{mins}min"


class PXSearchOrdersUI(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        page_heading(self, "Registros de produção",
                     "Encontre rolos, pedidos e o histórico de cada exportação.",
                     action=self.reload, action_text="⟳ Recarregar").pack(
                         fill="x", padx=22, pady=(22, 0)
                     )

        self.top_nb = ttk.Notebook(self)
        self.top_nb.pack(fill="both", expand=True)

        self.tab_panel = ttk.Frame(self.top_nb)
        self.top_nb.add(self.tab_panel, text="Painel")

        self.tab_search = ttk.Frame(self.top_nb)
        self.top_nb.add(self.tab_search, text="Pesquisar")

        # Rolável (mesma técnica já usada em modules/planejador.py:build_ui)
        # — "Pesquisar" acumulou abas e seções ao longo de várias etapas
        # (filtros, rolos exportados, "Detalhes do rolo selecionado" com
        # várias abas internas) até passar do que cabe no tamanho mínimo de
        # janela já suportado (980x600 — Nexor.py:self.minsize), espremendo
        # "Rolos exportados" à altura zero. Em vez de encolher conteúdo até
        # caber hoje (e quebrar de novo na próxima aba acrescentada), a aba
        # toda rola — nunca mais depende de ajustar alturas à mão.
        search_canvas = tk.Canvas(self.tab_search, highlightthickness=0)
        search_vsb = ttk.Scrollbar(self.tab_search, orient="vertical", command=search_canvas.yview)
        search_canvas.configure(yscrollcommand=search_vsb.set)
        search_canvas.pack(side="left", fill="both", expand=True)
        search_vsb.pack(side="right", fill="y")

        search_body = ttk.Frame(search_canvas)
        search_body_window = search_canvas.create_window((0, 0), window=search_body, anchor="nw")

        def _on_search_body_configure(_evt=None):
            search_canvas.configure(scrollregion=search_canvas.bbox("all"))

        def _on_search_canvas_configure(evt):
            search_canvas.itemconfig(search_body_window, width=evt.width)

        search_body.bind("<Configure>", _on_search_body_configure)
        search_canvas.bind("<Configure>", _on_search_canvas_configure)

        def _on_search_mousewheel(event):
            # Mesma guarda do Planejador: ignora o scroll enquanto algum
            # diálogo modal tiver o grab do Tk.
            if search_canvas.grab_current() is not None:
                return
            search_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_search_mousewheel(_evt=None):
            search_canvas.bind_all("<MouseWheel>", _on_search_mousewheel)

        def _unbind_search_mousewheel(_evt=None):
            search_canvas.unbind_all("<MouseWheel>")

        search_canvas.bind("<Enter>", _bind_search_mousewheel)
        search_canvas.bind("<Leave>", _unbind_search_mousewheel)

        self.tab_reconciliation = ttk.Frame(self.top_nb)
        self.top_nb.add(self.tab_reconciliation, text="Reconciliação")

        self.tab_metrics = ttk.Frame(self.top_nb)
        self.top_nb.add(self.tab_metrics, text="Métricas")

        self.tab_rework = ttk.Frame(self.top_nb)
        self.top_nb.add(self.tab_rework, text="Retrabalho")

        self.tab_duplicates = ttk.Frame(self.top_nb)
        self.top_nb.add(self.tab_duplicates, text="Duplicatas")

        self._current_roll_id: Optional[int] = None
        self._current_order_id: Optional[int] = None
        self._viewing_live_version: bool = True

        # ------------------------
        # Filtros
        # ------------------------
        filtros = card(search_body, "Filtros", padding=14)
        filtros.pack(fill="x", padx=22, pady=(0, 10))

        ttk.Label(filtros, text="Máquina").grid(row=0, column=0, sticky="w", padx=(10, 4), pady=8)
        self.var_machine = tk.StringVar(value="")
        self.cmb_machine = ttk.Combobox(
            filtros,
            textvariable=self.var_machine,
            values=["", "M1", "M2"],
            width=8,
            state="readonly",
        )
        self.cmb_machine.grid(row=0, column=1, sticky="w", padx=(0, 14), pady=8)

        ttk.Label(filtros, text="Rolo contém").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=8)
        self.var_name_like = tk.StringVar(value="")
        self.ent_name_like = ttk.Entry(filtros, textvariable=self.var_name_like, width=22)
        self.ent_name_like.grid(row=0, column=3, sticky="w", padx=(0, 14), pady=8)

        # Dois identificadores diferentes, de propósito nunca o mesmo campo:
        # "Arquivo contém" busca o nome real do arquivo importado (pode ser
        # bem diferente do pedido quando o tipo tem pedido fixo configurado,
        # ex.: Reposição -> "Variados" — ver core.print_types); "Pedido
        # contém" busca o pedido já normalizado, o mesmo valor mostrado em
        # "Pedidos no rolo" e na aba Reconciliação. Buscar "Variados" em
        # "Arquivo contém" não encontra nada mesmo que existam itens de
        # Reposição — é o campo errado pra essa busca; "Pedido contém" é o
        # certo.
        ttk.Label(filtros, text="Arquivo contém").grid(row=0, column=4, sticky="w", padx=(0, 6), pady=8)
        self.var_order_like = tk.StringVar(value="")
        self.ent_order_like = ttk.Entry(filtros, textvariable=self.var_order_like, width=22)
        self.ent_order_like.grid(row=0, column=5, sticky="w", padx=(0, 14), pady=8)

        ttk.Label(filtros, text="Pedido contém").grid(row=0, column=6, sticky="w", padx=(0, 6), pady=8)
        self.var_pedido_like = tk.StringVar(value="")
        self.ent_pedido_like = ttk.Entry(filtros, textvariable=self.var_pedido_like, width=22)
        self.ent_pedido_like.grid(row=0, column=7, sticky="w", padx=(0, 14), pady=8)

        ttk.Label(filtros, text="Tipo").grid(row=0, column=8, sticky="w", padx=(0, 6), pady=8)
        self.var_tipo = tk.StringVar(value="")
        self.cmb_tipo = ttk.Combobox(
            filtros, textvariable=self.var_tipo, values=[""], width=16, state="readonly"
        )
        self.cmb_tipo.grid(row=0, column=9, sticky="w", padx=(0, 14), pady=8)

        # Filtro por vendedor (ver core/order_vendor_resolution.py — Etapas A/C) — mesma
        # granularidade dos filtros acima: um rolo aparece se TIVER ao menos um pedido que
        # combine (não filtra pedido a pedido). _VENDOR_FILTER_UNIDENTIFIED nunca é o nome
        # de um vendedor real (ver _refresh_vendor_options), então não há ambiguidade.
        ttk.Label(filtros, text="Vendedor").grid(row=0, column=10, sticky="w", padx=(0, 6), pady=8)
        self.var_vendor_filter = tk.StringVar(value="")
        self._vendor_name_to_key: dict[str, str] = {}
        self.cmb_vendor_filter = ttk.Combobox(
            filtros, textvariable=self.var_vendor_filter, values=[""], width=18, state="readonly"
        )
        self.cmb_vendor_filter.grid(row=0, column=11, sticky="w", padx=(0, 14), pady=8)

        ttk.Label(filtros, text="Limite").grid(row=1, column=0, sticky="w", padx=(10, 4), pady=(0, 8))
        self.var_limit = tk.StringVar(value="300")
        self.ent_limit = ttk.Entry(filtros, textvariable=self.var_limit, width=6)
        self.ent_limit.grid(row=1, column=1, sticky="w", padx=(0, 14), pady=(0, 8))

        # "Recarregar" já existe como ação principal no cabeçalho da página
        # ("⟳ Recarregar"), sempre visível — sem duplicar o botão aqui.
        ttk.Button(filtros, text="Limpar filtros", command=self.clear_filters).grid(
            row=1, column=2, sticky="w", padx=(0, 8), pady=(0, 8)
        )
        ttk.Button(filtros, text="Editar rolo", command=self.on_edit_roll).grid(
            row=1, column=3, sticky="w", padx=(0, 10), pady=(0, 8)
        )
        ttk.Button(filtros, text="Abrir comprovante", command=self.on_open_comprovante).grid(
            row=1, column=4, sticky="w", padx=(0, 10), pady=(0, 8)
        )

        filtros.columnconfigure(13, weight=1)

        self.ent_name_like.bind("<Return>", lambda _e: self.reload())
        self.ent_order_like.bind("<Return>", lambda _e: self.reload())
        self.ent_pedido_like.bind("<Return>", lambda _e: self.reload())
        self.ent_limit.bind("<Return>", lambda _e: self.reload())
        self.cmb_tipo.bind("<<ComboboxSelected>>", lambda _e: self.reload())
        self.cmb_vendor_filter.bind("<<ComboboxSelected>>", lambda _e: self.reload())

        # ------------------------
        # Lista de rolos
        # ------------------------
        box_rolls = card(search_body, "Rolos exportados", padding=10)
        box_rolls.pack(fill="both", expand=True, padx=22, pady=(0, 10))

        cols = ("id", "roll", "machine", "created", "total_m", "orders", "events", "obs", "edited")
        self.tree_rolls = ttk.Treeview(box_rolls, columns=cols, show="headings", height=5)

        self.tree_rolls.heading("id", text="ID")
        self.tree_rolls.column("id", width=60, anchor="w")

        self.tree_rolls.heading("roll", text="Rolo")
        self.tree_rolls.column("roll", width=260, anchor="w")

        self.tree_rolls.heading("machine", text="Máquina")
        self.tree_rolls.column("machine", width=80, anchor="center")

        self.tree_rolls.heading("created", text="Criado")
        self.tree_rolls.column("created", width=170, anchor="w")

        self.tree_rolls.heading("total_m", text="Total (m)")
        self.tree_rolls.column("total_m", width=100, anchor="e")

        self.tree_rolls.heading("orders", text="Pedidos")
        self.tree_rolls.column("orders", width=90, anchor="e")

        self.tree_rolls.heading("events", text="Eventos")
        self.tree_rolls.column("events", width=90, anchor="e")

        self.tree_rolls.heading("obs", text="Observações")
        self.tree_rolls.column("obs", width=100, anchor="e")

        self.tree_rolls.heading("edited", text="Editado")
        self.tree_rolls.column("edited", width=70, anchor="center")

        sb_rolls = ttk.Scrollbar(box_rolls, orient="vertical", command=self.tree_rolls.yview)
        self.tree_rolls.configure(yscrollcommand=sb_rolls.set)

        self.tree_rolls.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        sb_rolls.pack(side="right", fill="y", padx=(0, 10), pady=10)

        self.tree_rolls.bind("<<TreeviewSelect>>", self.on_select_roll)
        self.tree_rolls.bind("<Double-1>", self.on_double_click_roll)

        self._roll_menu = tk.Menu(self.tree_rolls, tearoff=False)
        self._roll_menu.add_command(label="Editar rolo", command=self.on_edit_roll)
        self._roll_menu.add_command(label="Abrir comprovante", command=self.on_open_comprovante)
        self.tree_rolls.bind("<Button-3>", self._on_roll_right_click)

        # ------------------------
        # Detalhes
        # ------------------------
        # A página não rola: os detalhes entram na fila do pack antes da lista
        # de rolos para não ficarem sem altura em janelas de 800 px.
        box_details = card(search_body, "Detalhes do rolo selecionado", padding=10)
        box_details.pack(side="bottom", fill="both", expand=True, padx=22, pady=(0, 8),
                         before=box_rolls)

        # Versão do rolo (Original, Edição 1, Edição 2... ou a versão
        # atual) — um rolo nunca editado tem só a opção "Original", que já
        # é a atual (ver modules/registros/repository.py,
        # load_roll_order_version_options). Fica acima das abas porque
        # afeta tanto "Pedidos" quanto "Lista do rolo"; "Resumo" e
        # "Eventos" sempre mostram o estado atual/histórico completo.
        version_row = ttk.Frame(box_details)
        version_row.pack(fill="x", padx=10, pady=(0, 4))
        # Pedido do usuário: visualizar os detalhes do rolo numa janela
        # maior/própria — mesmo padrão de "⤢ Abrir em janela" já usado em
        # Planejador (modules/planejador.py). Abre uma segunda tela de
        # Registros inteira, já saltada pra este rolo (reaproveita o mesmo
        # salto de _open_roll_from_reconciliation), em vez de tentar
        # "arrancar" os widgets já criados pra outra janela (Tkinter não
        # tem reparentamento de verdade pra isso).
        ttk.Button(
            version_row, text="⤢ Abrir em janela", command=self._open_roll_details_window,
        ).pack(side="right")
        ttk.Label(version_row, text="Versão do rolo:").pack(side="left", padx=(0, 4))
        self._order_version_options: list[dict] = []
        self.var_order_version = tk.StringVar()
        self.cmb_order_version = ttk.Combobox(
            version_row, textvariable=self.var_order_version, state="readonly", width=16,
        )
        self.cmb_order_version.pack(side="left")
        self.cmb_order_version.bind("<<ComboboxSelected>>", self.on_select_order_version)
        ttk.Label(
            version_row,
            text=(
                'Afeta "Ordem do rolo", "Detalhes do bloco", "Pedidos no rolo", "Pedidos" e '
                '"Lista do rolo" — Resumo e Eventos sempre mostram o estado atual.'
            ),
            style="Muted.TLabel",
        ).pack(side="left", padx=(10, 0))

        self.nb = ttk.Notebook(box_details)
        self.nb.pack(fill="both", expand=True, padx=10, pady=10)

        # Aba Resumo
        self.tab_summary = ttk.Frame(self.nb)
        self.nb.add(self.tab_summary, text="Resumo")

        self.txt_summary = tk.Text(self.tab_summary, wrap="word", height=4)
        self.txt_summary.pack(fill="both", expand=True)
        self.txt_summary.configure(state="disabled")

        # Aba Ordem do rolo — mesma visão agrupada por tecido que a
        # Operação mostra durante a importação (modules/operacao/ui.py,
        # tree_blocks), só que a partir das orders já salvas no banco
        # (qualquer rolo, de qualquer sessão, não só o que está sendo
        # editado agora). Pedido do usuário. Selecionar um tecido aqui
        # mostra os itens dele na aba "Detalhes do bloco".
        self.tab_blocks = ttk.Frame(self.nb)
        self.nb.add(self.tab_blocks, text="Ordem do rolo")

        blocks_box = card(self.tab_blocks, "Último impresso primeiro", padding=10)
        blocks_box.pack(fill="both", expand=True)

        self.tree_blocks = ttk.Treeview(
            blocks_box, columns=("idx", "fabric", "total_m", "jobs", "last"),
            show="headings", height=4,
        )
        for col, txt, w, anchor in [
            ("idx", "#", 40, "w"),
            ("fabric", "Tecido", 180, "w"),
            ("total_m", "Total (m)", 110, "e"),
            ("jobs", "Arquivos", 90, "e"),
            ("last", "Último EndTime", 160, "w"),
        ]:
            self.tree_blocks.heading(col, text=txt)
            self.tree_blocks.column(col, width=w, anchor=anchor)

        sb_blocks = ttk.Scrollbar(blocks_box, orient="vertical", command=self.tree_blocks.yview)
        self.tree_blocks.configure(yscrollcommand=sb_blocks.set)
        self.tree_blocks.pack(side="left", fill="both", expand=True)
        sb_blocks.pack(side="right", fill="y")
        self.tree_blocks.bind("<<TreeviewSelect>>", self.on_select_block)
        self._current_blocks: list = []

        # Aba Detalhes do bloco
        self.tab_block_details = ttk.Frame(self.nb)
        self.nb.add(self.tab_block_details, text="Detalhes do bloco")

        # Título do card mostra qual tecido está selecionado — direto no
        # LabelFrame, sem um Label próprio a mais: numa janela no tamanho
        # mínimo suportado (980x600 — ver Nexor.py:self.minsize), cada
        # linha extra de altura conta pra não espremer "Rolos exportados"
        # a zero (mesmo cuidado já documentado onde box_details/box_rolls
        # são empacotados).
        self._block_details_card = card(
            self.tab_block_details, 'Selecione um tecido na aba "Ordem do rolo"...', padding=10
        )
        self._block_details_card.pack(fill="both", expand=True)

        self.tree_block_details = ttk.Treeview(
            self._block_details_card,
            columns=("end", "doc", "pedido", "tipo", "h", "v", "real_m", "obs"),
            show="headings", height=4,
        )
        for col, txt, w in [
            ("end", "EndTime", 140),
            ("doc", "Documento", 300),
            ("pedido", "Pedido", 150),
            ("tipo", "Tipo", 110),
            ("h", "HeightMM", 90),
            ("v", "VPosMM", 90),
            ("real_m", "Real (m)", 90),
            ("obs", "Observação", 220),
        ]:
            self.tree_block_details.heading(col, text=txt)
            self.tree_block_details.column(col, width=w, anchor="w")

        sb_block_details = ttk.Scrollbar(
            self._block_details_card, orient="vertical", command=self.tree_block_details.yview
        )
        self.tree_block_details.configure(yscrollcommand=sb_block_details.set)
        self.tree_block_details.pack(side="left", fill="both", expand=True)
        sb_block_details.pack(side="right", fill="y")

        # Aba Pedidos no rolo — resumo agrupado por pedido (mesma visão da
        # Operação, tree_pedidos), sem vendedor/PDF (isso já é por pedido
        # INDIVIDUAL na aba "Pedidos" existente, não faz sentido agregado).
        self.tab_pedidos_summary = ttk.Frame(self.nb)
        self.nb.add(self.tab_pedidos_summary, text="Pedidos no rolo")

        pedidos_summary_box = card(self.tab_pedidos_summary, "Resumo por pedido", padding=10)
        pedidos_summary_box.pack(fill="both", expand=True)

        self.tree_pedidos_summary = ttk.Treeview(
            pedidos_summary_box, columns=("idx", "pedido", "tipo", "total_m", "jobs", "last"),
            show="headings", height=4,
        )
        for col, txt, w, anchor in [
            ("idx", "#", 36, "w"),
            ("pedido", "Pedido", 220, "w"),
            ("tipo", "Tipo", 110, "w"),
            ("total_m", "Total (m)", 100, "e"),
            ("jobs", "Arquivos", 85, "e"),
            ("last", "Último EndTime", 160, "w"),
        ]:
            self.tree_pedidos_summary.heading(col, text=txt)
            self.tree_pedidos_summary.column(col, width=w, anchor=anchor)

        sb_pedidos_summary = ttk.Scrollbar(
            pedidos_summary_box, orient="vertical", command=self.tree_pedidos_summary.yview
        )
        self.tree_pedidos_summary.configure(yscrollcommand=sb_pedidos_summary.set)
        self.tree_pedidos_summary.pack(side="left", fill="both", expand=True)
        sb_pedidos_summary.pack(side="right", fill="y")

        # Aba Pedidos
        self.tab_orders = ttk.Frame(self.nb)
        self.nb.add(self.tab_orders, text="Pedidos")

        order_cols = (
            "end_time", "document", "pedido", "fabric", "tipo", "height_mm", "vpos_mm", "real_m",
            "source", "observacao", "vendedor", "pdf",
        )
        self.tree_orders = ttk.Treeview(self.tab_orders, columns=order_cols, show="headings", height=4)

        order_actions = ttk.Frame(self.tab_orders)
        order_actions.pack(side="top", fill="x", pady=(0, 6))
        self.btn_export_order_context = ttk.Button(
            order_actions,
            text="Exportar contexto de produção...",
            command=self.on_export_order_context,
            state="disabled",
        )
        self.btn_export_order_context.pack(side="left")

        # Localização do arquivo original/vendedor (Etapa E, ver core/order_vendor_resolution.py
        # e core/order_pdfs.py — Etapas C/D). "Localizar vendedor/PDF" só lê o índice local já
        # salvo (core.order_files.load_order_index) — nunca pesquisa a rede aqui; "Atualizar
        # índice" fica em Configurações · Vendedores, a única ação que varre as pastas de fato.
        self.btn_locate_vendor = ttk.Button(
            order_actions, text="Localizar vendedor/PDF", command=self.on_locate_vendor_pdf, state="disabled",
        )
        self.btn_locate_vendor.pack(side="left", padx=(10, 0))

        self.btn_change_vendor = ttk.Button(
            order_actions, text="Alterar vendedor...", command=self.on_change_vendor, state="disabled",
        )
        self.btn_change_vendor.pack(side="left", padx=(6, 0))

        self.btn_choose_pdf = ttk.Button(
            order_actions, text="Vincular PDF...", command=self.on_choose_pdf, state="disabled",
        )
        self.btn_choose_pdf.pack(side="left", padx=(6, 0))

        self.btn_open_order_pdf = ttk.Button(
            order_actions, text="Abrir PDF", command=self.on_open_order_pdf, state="disabled",
        )
        self.btn_open_order_pdf.pack(side="left", padx=(6, 0))

        self.btn_open_order_folder = ttk.Button(
            order_actions, text="Abrir pasta", command=self.on_open_order_folder, state="disabled",
        )
        self.btn_open_order_folder.pack(side="left", padx=(6, 0))

        self.btn_reveal_order_pdf = ttk.Button(
            order_actions, text="Mostrar no Explorador", command=self.on_reveal_order_pdf, state="disabled",
        )
        self.btn_reveal_order_pdf.pack(side="left", padx=(6, 0))

        self.tree_orders.heading("end_time", text="EndTime")
        self.tree_orders.column("end_time", width=140, anchor="w")

        self.tree_orders.heading("document", text="Documento")
        self.tree_orders.column("document", width=240, anchor="w")

        self.tree_orders.heading("pedido", text="Pedido")
        self.tree_orders.column("pedido", width=170, anchor="w")

        self.tree_orders.heading("fabric", text="Tecido")
        self.tree_orders.column("fabric", width=110, anchor="w")

        self.tree_orders.heading("tipo", text="Tipo")
        self.tree_orders.column("tipo", width=100, anchor="w")

        self.tree_orders.heading("height_mm", text="HeightMM")
        self.tree_orders.column("height_mm", width=80, anchor="e")

        self.tree_orders.heading("vpos_mm", text="VPosMM")
        self.tree_orders.column("vpos_mm", width=80, anchor="e")

        self.tree_orders.heading("real_m", text="Real (m)")
        self.tree_orders.column("real_m", width=80, anchor="e")

        self.tree_orders.heading("source", text="Arquivo")
        self.tree_orders.column("source", width=160, anchor="w")

        self.tree_orders.heading("observacao", text="Observação")
        self.tree_orders.column("observacao", width=160, anchor="w")

        self.tree_orders.heading("vendedor", text="Vendedor")
        self.tree_orders.column("vendedor", width=150, anchor="w")

        self.tree_orders.heading("pdf", text="PDF")
        self.tree_orders.column("pdf", width=150, anchor="w")

        sb_orders = ttk.Scrollbar(self.tab_orders, orient="vertical", command=self.tree_orders.yview)
        self.tree_orders.configure(yscrollcommand=sb_orders.set)

        self.tree_orders.pack(side="left", fill="both", expand=True)
        sb_orders.pack(side="right", fill="y")

        self.tree_orders.tag_configure("busca_match", foreground="#0a58ca")

        self.tree_orders.bind("<<TreeviewSelect>>", self.on_select_order)

        # Aba Lista do rolo — igual à aba de mesmo nome na Operação: todos
        # os itens numa lista só, na ordem do comprovante (blocos na ordem
        # de self.blocks, mais recente pro mais antigo dentro de cada um),
        # incluindo ESPAÇO. Só existe esse jeito pra rolos da Operação —
        # rolos do Planejador não têm ESPAÇO salvo nem essa noção de bloco
        # por tecido entre arquivos.
        self.tab_roll_list = ttk.Frame(self.nb)
        self.nb.add(self.tab_roll_list, text="Lista do rolo")

        roll_list_cols = ("idx", "end_time", "document", "fabric", "pedido", "tipo", "real_m", "observacao")
        self.tree_roll_list = ttk.Treeview(
            self.tab_roll_list, columns=roll_list_cols, show="headings", height=4
        )
        for col, text, width, anchor in [
            ("idx", "#", 40, "e"),
            ("end_time", "EndTime", 150, "w"),
            ("document", "Documento", 280, "w"),
            ("fabric", "Tecido", 110, "w"),
            ("pedido", "Pedido", 160, "w"),
            ("tipo", "Tipo", 100, "w"),
            ("real_m", "Real (m)", 80, "e"),
            ("observacao", "Observação", 180, "w"),
        ]:
            self.tree_roll_list.heading(col, text=text)
            self.tree_roll_list.column(col, width=width, anchor=anchor)

        sb_roll_list = ttk.Scrollbar(
            self.tab_roll_list, orient="vertical", command=self.tree_roll_list.yview
        )
        self.tree_roll_list.configure(yscrollcommand=sb_roll_list.set)
        self.tree_roll_list.pack(side="left", fill="both", expand=True)
        sb_roll_list.pack(side="right", fill="y")

        # Aba Eventos
        self.tab_events = ttk.Frame(self.nb)
        self.nb.add(self.tab_events, text="Eventos")

        ev_cols = ("created_at", "event_type", "summary")
        self.tree_events = ttk.Treeview(self.tab_events, columns=ev_cols, show="headings", height=4)

        self.tree_events.heading("created_at", text="Data/Hora")
        self.tree_events.column("created_at", width=170, anchor="w")

        self.tree_events.heading("event_type", text="Tipo")
        self.tree_events.column("event_type", width=140, anchor="w")

        self.tree_events.heading("summary", text="Resumo")
        self.tree_events.column("summary", width=520, anchor="w")

        sb_events = ttk.Scrollbar(self.tab_events, orient="vertical", command=self.tree_events.yview)
        self.tree_events.configure(yscrollcommand=sb_events.set)

        self.tree_events.pack(side="left", fill="both", expand=True)
        sb_events.pack(side="right", fill="y")

        # Aba Ocorrências — pedido do usuário: item de roadmap (Fase 3)
        # "registrar ocorrências operacionais com vínculo aos itens/rolos
        # e histórico de alterações". Vinculada ao ROLO inteiro, não a um
        # pedido/item específico (decisão confirmada com o usuário) — ver
        # core/printlogs_db.py (create_occurrence/add_occurrence_entry/
        # list_occurrences_for_roll/get_occurrence_history). Diferente da
        # "Observação" livre já existente em orders.observacao: ocorrência
        # tem status (Aberta/Resolvida) e histórico de edição append-only
        # próprio, nunca sobrescrito.
        self.tab_occurrences = ttk.Frame(self.nb)
        self.nb.add(self.tab_occurrences, text="Ocorrências")

        occ_actions = ttk.Frame(self.tab_occurrences)
        occ_actions.pack(side="top", fill="x", pady=(0, 6))
        ttk.Button(
            occ_actions, text="Nova ocorrência…", command=self._open_new_occurrence_dialog
        ).pack(side="left")
        ttk.Label(
            occ_actions, text="Duplo clique numa linha para ver o histórico completo.",
            style="Muted.TLabel",
        ).pack(side="left", padx=(10, 0))

        occ_cols = ("created_at", "status", "description")
        self.tree_occurrences = ttk.Treeview(
            self.tab_occurrences, columns=occ_cols, show="headings", height=4
        )
        self.tree_occurrences.heading("created_at", text="Criada em")
        self.tree_occurrences.column("created_at", width=150, anchor="w")
        self.tree_occurrences.heading("status", text="Status")
        self.tree_occurrences.column("status", width=90, anchor="w")
        self.tree_occurrences.heading("description", text="Descrição (estado atual)")
        self.tree_occurrences.column("description", width=440, anchor="w")

        sb_occurrences = ttk.Scrollbar(
            self.tab_occurrences, orient="vertical", command=self.tree_occurrences.yview
        )
        self.tree_occurrences.configure(yscrollcommand=sb_occurrences.set)
        self.tree_occurrences.pack(side="left", fill="both", expand=True)
        sb_occurrences.pack(side="right", fill="y")
        self.tree_occurrences.bind("<Double-1>", self._on_double_click_occurrence)

        # ------------------------
        # Status
        # ------------------------
        self.status = ttk.Label(search_body, text="Pronto.", style="Muted.TLabel")
        self.status.pack(side="bottom", fill="x", padx=22, pady=(0, 8), before=box_details)

        self._build_reconciliation_tab()
        self._build_metrics_tab()
        self._build_rework_tab()
        self._build_duplicates_tab()
        self._build_panel_tab()

        self.reload()
        self.reload_reconciliation()
        self.reload_metrics()
        self.reload_rework()
        self.reload_duplicates()
        self.reload_panel()

    # ------------------------
    # Actions
    # ------------------------
    def clear_filters(self) -> None:
        self.var_machine.set("")
        self.var_name_like.set("")
        self.var_order_like.set("")
        self.var_pedido_like.set("")
        self.var_tipo.set("")
        self.var_vendor_filter.set("")
        self.var_limit.set("300")
        self.reload()

    def _refresh_tipo_options(self) -> None:
        try:
            tipos = load_distinct_tipos()
        except Exception:
            tipos = []
        self.cmb_tipo.configure(values=[""] + tipos)

    def _refresh_vendor_options(self) -> None:
        try:
            vendedores = [v for v in load_vendedores() if v.active]
        except Exception:
            vendedores = []
        vendedores = sorted(vendedores, key=lambda v: v.name.lower())
        self._vendor_name_to_key = {v.name: v.key for v in vendedores}
        names = [v.name for v in vendedores]
        # Preserva a seleção atual mesmo que o vendedor tenha sido desativado
        # nesse meio-tempo — não força o filtro a resetar sozinho.
        current = self.var_vendor_filter.get()
        values = [""] + names + [_VENDOR_FILTER_UNIDENTIFIED]
        if current and current not in values:
            values.append(current)
        self.cmb_vendor_filter.configure(values=values)

    def reload_settings(self) -> None:
        """Chamado pela página Configurações após reclassificar os registros."""
        self.reload()

    def reload(self) -> None:
        self._refresh_tipo_options()
        self._refresh_vendor_options()

        limit = safe_int(self.var_limit.get(), default=300)
        machine = (self.var_machine.get() or "").strip() or None
        name_like = (self.var_name_like.get() or "").strip() or None
        order_like = (self.var_order_like.get() or "").strip() or None
        pedido_like = (self.var_pedido_like.get() or "").strip() or None
        tipo = (self.var_tipo.get() or "").strip() or None

        vendor_sel = (self.var_vendor_filter.get() or "").strip()
        vendor_unidentified = vendor_sel == _VENDOR_FILTER_UNIDENTIFIED
        vendor_key = None if vendor_unidentified else self._vendor_name_to_key.get(vendor_sel)

        try:
            rows = search_rolls(
                limit=limit,
                machine=machine,
                name_like=name_like,
                order_like=order_like,
                pedido_like=pedido_like,
                tipo=tipo,
                vendor_key=vendor_key,
                vendor_unidentified=vendor_unidentified,
            )
        except Exception as e:
            log_exception(_logger, "Production records read failed", e)
            messagebox.showerror(
                "Registros",
                f"Falha ao carregar rolos.\n\n{type(e).__name__}: {e}",
            )
            return

        self.tree_rolls.delete(*self.tree_rolls.get_children())

        count = 0
        for row in rows:
            try:
                roll_id = int(row.get("id", 0))
                roll_name = str(row.get("roll_name", ""))
                machine_name = str(row.get("machine", ""))
                created_at = str(row.get("created_at", ""))
                total_m = float(row.get("total_m", 0.0) or 0.0)
                orders_count = int(row.get("orders_count", 0) or 0)
                events_count = int(row.get("events_count", 0) or 0)
                obs_count = int(row.get("obs_count", 0) or 0)
            except Exception:
                continue

            try:
                edited = load_roll_was_edited(roll_id)
            except Exception:
                edited = False

            self.tree_rolls.insert(
                "",
                "end",
                iid=str(roll_id),
                values=(
                    roll_id,
                    roll_name,
                    machine_name,
                    created_at,
                    format_m(total_m, suffix=False),
                    orders_count,
                    events_count,
                    f"📝 {obs_count}" if obs_count else "",
                    "✏ Sim" if edited else "",
                ),
            )
            count += 1

        self.status.configure(text=f"Total listados: {count}")
        self._clear_details()

        if count:
            first = self.tree_rolls.get_children()[0]
            self.tree_rolls.selection_set(first)
            self.tree_rolls.focus(first)
            self.on_select_roll()

    # ------------------------
    # Reconciliação (planejado × log real)
    # ------------------------
    def _build_reconciliation_tab(self) -> None:
        """Aba "Reconciliação" — pedido+tecido planejado no Planejador
        (estimativa por pixels/DPI) contra pedido+tecido confirmado pelo
        log real na Operação, lado a lado, com a diferença — ver
        `core/printlogs_db.py:reconcile_planned_vs_logged` (só leitura,
        nunca corrige nada)."""
        header = ttk.Frame(self.tab_reconciliation)
        header.pack(fill="x", padx=22, pady=(16, 0))
        ttk.Label(
            header,
            text=(
                "Compara, por pedido + tecido, a metragem planejada (Planejador, estimativa "
                "por pixels/DPI da imagem) com a metragem confirmada pelo log real da "
                "impressora (Operação). Só leitura — nada aqui corrige os registros de origem."
            ),
            style="Muted.TLabel",
            wraplength=760,
            justify="left",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(header, text="⟳ Atualizar", command=self.reload_reconciliation).pack(side="right")

        filtro_row = ttk.Frame(self.tab_reconciliation)
        filtro_row.pack(fill="x", padx=22, pady=(10, 0))
        ttk.Label(filtro_row, text="Pedido/tecido contém").pack(side="left", padx=(0, 6))
        self.var_reconciliation_filter = tk.StringVar(value="")
        ent_reconciliation_filter = ttk.Entry(filtro_row, textvariable=self.var_reconciliation_filter, width=30)
        ent_reconciliation_filter.pack(side="left", padx=(0, 14))
        ent_reconciliation_filter.bind("<KeyRelease>", lambda _e: self._apply_reconciliation_filter())

        self.var_reconciliation_only_divergent = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filtro_row,
            text="Só com diferença",
            variable=self.var_reconciliation_only_divergent,
            command=self._apply_reconciliation_filter,
        ).pack(side="left")

        box = card(self.tab_reconciliation, "Pedido + tecido", padding=10)
        box.pack(fill="both", expand=True, padx=22, pady=(10, 8))

        cols = ("pedido", "fabric", "planned_m", "logged_m", "delta_m")
        self.tree_reconciliation = ttk.Treeview(box, columns=cols, show="headings", height=12)

        for col, txt, w, anchor in [
            ("pedido", "Pedido", 220, "w"),
            ("fabric", "Tecido", 140, "w"),
            ("planned_m", "Planejado (m)", 120, "e"),
            ("logged_m", "Log real (m)", 120, "e"),
            ("delta_m", "Diferença (m)", 120, "e"),
        ]:
            self.tree_reconciliation.heading(col, text=txt)
            self.tree_reconciliation.column(col, width=w, anchor=anchor)

        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree_reconciliation.yview)
        self.tree_reconciliation.configure(yscrollcommand=sb.set)
        self.tree_reconciliation.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        sb.pack(side="right", fill="y", padx=(0, 10), pady=10)

        self.tree_reconciliation.tag_configure("divergente", foreground="#b00020")
        self.tree_reconciliation.bind("<Button-3>", self._show_reconciliation_context_menu)
        self._reconciliation_rows: dict[str, dict] = {}
        self._reconciliation_all_rows: list = []

        self.status_reconciliation = ttk.Label(
            self.tab_reconciliation, text="", style="Muted.TLabel"
        )
        self.status_reconciliation.pack(fill="x", padx=22, pady=(0, 10))

    def reload_reconciliation(self) -> None:
        try:
            result = reconcile_planned_vs_logged()
        except Exception as e:
            log_exception(_logger, "Reconciliation read failed", e)
            self._reconciliation_all_rows = []
            self.tree_reconciliation.delete(*self.tree_reconciliation.get_children())
            self.status_reconciliation.configure(
                text=f"Falha ao consultar reconciliação: {type(e).__name__}: {e}"
            )
            return

        # Maiores divergências (em módulo) primeiro — é o que mais vale a
        # pena o operador olhar primeiro numa lista que pode crescer muito.
        # Guardado por completo (sem filtro) pra "Pedido/tecido contém" e
        # "Só com diferença" filtrarem na hora, sem consultar o banco de novo.
        self._reconciliation_all_rows = sorted(
            result.items(), key=lambda item: abs(item[1]["delta_m"]), reverse=True
        )
        self._apply_reconciliation_filter()

    def _apply_filterable_list(
        self,
        tree: "ttk.Treeview",
        rows_all: list,
        rows_cache: dict,
        *,
        predicate,
        row_values,
        status_label: "ttk.Label",
        status_prefix,
        row_tags=None,
    ) -> None:
        """Esqueleto comum às abas "Reconciliação"/"Retrabalho"/"Duplicatas":
        limpa a árvore, filtra `rows_all` com `predicate`, reconstrói linha a
        linha (iid sequencial, nunca o id de origem — mesmo padrão de sempre
        nestas três abas, pra nunca colidir com o id de outra sessão de
        filtro) e atualiza o status com o total e, só quando o filtro
        reduziu alguma coisa, quantos ficaram visíveis. Cada aba continua
        decidindo sozinha o que é "corresponder" (`predicate`), as colunas
        (`row_values`) e o texto fixo do status (`status_prefix`) — só o
        laço em si é compartilhado."""
        tree.delete(*tree.get_children())
        rows_cache.clear()

        shown = 0
        for item in rows_all:
            if not predicate(item):
                continue
            iid = str(shown)
            kwargs = {"tags": row_tags(item)} if row_tags is not None else {}
            tree.insert("", "end", iid=iid, values=row_values(item), **kwargs)
            rows_cache[iid] = item
            shown += 1

        total = len(rows_all)
        filtered_note = f" | Exibindo: {shown}" if shown != total else ""
        status_label.configure(text=f"{status_prefix(total)}{filtered_note}")

    def _apply_reconciliation_filter(self) -> None:
        needle = (self.var_reconciliation_filter.get() or "").strip().lower()
        only_divergent = self.var_reconciliation_only_divergent.get()

        def predicate(item):
            (pedido, fabric), info = item
            if only_divergent and abs(info["delta_m"]) <= 0.01:
                return False
            return not (needle and needle not in pedido.lower() and needle not in fabric.lower())

        def row_values(item):
            (pedido, fabric), info = item
            # Nunca format_m aqui: fmt_m/round_up_cm_m trata qualquer valor <= 0
            # como 0.0 (correto pra metragem física, que nunca é negativa) — mas
            # delta_m É assinado de propósito (negativo = logado abaixo do
            # planejado), então precisa do próprio sinal visível, não um "0.00"
            # escondendo isso.
            return (
                pedido,
                fabric,
                format_m(info["planned_m"], suffix=False),
                format_m(info["logged_m"], suffix=False),
                f"{info['delta_m']:+.2f}",
            )

        def row_tags(item):
            _, info = item
            return ("divergente",) if abs(info["delta_m"]) > 0.01 else ()

        divergent_count = sum(1 for _, info in self._reconciliation_all_rows if abs(info["delta_m"]) > 0.01)
        self._apply_filterable_list(
            self.tree_reconciliation, self._reconciliation_all_rows, self._reconciliation_rows,
            predicate=predicate, row_values=row_values, row_tags=row_tags,
            status_label=self.status_reconciliation,
            status_prefix=lambda total: f"Total de pares: {total} | Com diferença: {divergent_count}",
        )

    def _show_reconciliation_context_menu(self, event) -> None:
        """Botão direito num par divergente — abre direto o(s) rolo(s) que
        contribuíram pra aquele lado (Planejador/Operação) na aba
        "Pesquisar", em vez do operador ter que copiar o nome do rolo e
        procurar na mão."""
        iid = self.tree_reconciliation.identify_row(event.y)
        if not iid:
            return
        self.tree_reconciliation.selection_set(iid)
        info = self._reconciliation_rows.get(iid)

        menu = tk.Menu(self, tearoff=0)
        any_roll = False
        if info:
            for module_label, rolls in (("Planejador", info["planned_rolls"]), ("Operação", info["logged_rolls"])):
                for roll in rolls:
                    any_roll = True
                    roll_name = roll["roll_name"]
                    menu.add_command(
                        label=f"Abrir rolo: {roll_name} ({module_label})",
                        command=lambda name=roll_name: self._open_roll_from_reconciliation(name),
                    )
        if not any_roll:
            menu.add_command(label="(nenhum rolo associado)", state="disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_roll_from_reconciliation(self, roll_name: str) -> None:
        self.var_machine.set("")
        self.var_name_like.set(roll_name)
        self.var_order_like.set("")
        self.var_pedido_like.set("")
        self.var_tipo.set("")
        self.var_vendor_filter.set("")
        self.top_nb.select(self.tab_search)
        self.reload()

    def _open_roll_details_window(self) -> None:
        """"⤢ Abrir em janela" — pedido do usuário pra ver os detalhes do
        rolo selecionado numa janela maior/própria. Abre uma segunda tela
        de Registros completa, numa janela maior, já saltada direto pro
        mesmo rolo (mesmo salto de `_open_roll_from_reconciliation`) —
        janela independente, nunca compartilha estado com a principal."""
        if self._current_roll_id is None:
            messagebox.showinfo("Abrir em janela", "Selecione um rolo na lista acima.")
            return

        sel = self.tree_rolls.selection()
        roll_name = self.tree_rolls.item(sel[0], "values")[1] if sel else ""
        if not roll_name:
            return

        win = tk.Toplevel(self)
        win.title(f"Registros — {roll_name}")
        win.geometry("1200x800")

        detail_ui = PXSearchOrdersUI(win)
        detail_ui.pack(fill="both", expand=True)
        detail_ui._open_roll_from_reconciliation(roll_name)

    # ------------------------
    # Métricas por máquina
    # ------------------------
    def _build_metrics_tab(self) -> None:
        """Aba "Métricas" — metragem produzida, avanço entre tecidos
        (ESPAÇO), contagens e duração por máquina, só a partir do log real
        confirmado (Operação) — ver
        `core/printlogs_db.py:compute_machine_metrics`, que nunca mistura
        com a estimativa do Planejador (isso já tem lugar próprio: aba
        "Reconciliação")."""
        header = ttk.Frame(self.tab_metrics)
        header.pack(fill="x", padx=22, pady=(16, 0))
        ttk.Label(
            header,
            text=(
                "Metragem produzida, avanço entre tecidos (ESPAÇO), contagens e duração por "
                "máquina — só a partir do log real confirmado na Operação (nunca inclui a "
                "estimativa do Planejador, que já tem a aba \"Reconciliação\" pra isso)."
            ),
            style="Muted.TLabel",
            wraplength=760,
            justify="left",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(header, text="⟳ Atualizar", command=self.reload_metrics).pack(side="right")

        box = card(self.tab_metrics, "Por máquina", padding=10)
        box.pack(fill="both", expand=True, padx=22, pady=(10, 8))

        cols = ("machine", "produced_m", "gap_m", "order_count", "gap_count", "duration", "roll_count")
        self.tree_metrics = ttk.Treeview(box, columns=cols, show="headings", height=10)

        for col, txt, w, anchor in [
            ("machine", "Máquina", 100, "w"),
            ("produced_m", "Produzido (m)", 120, "e"),
            ("gap_m", "Espaço (m)", 110, "e"),
            ("order_count", "Pedidos", 90, "e"),
            ("gap_count", "Avanços", 90, "e"),
            ("duration", "Duração", 110, "e"),
            ("roll_count", "Rolos", 80, "e"),
        ]:
            self.tree_metrics.heading(col, text=txt)
            self.tree_metrics.column(col, width=w, anchor=anchor)

        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree_metrics.yview)
        self.tree_metrics.configure(yscrollcommand=sb.set)
        self.tree_metrics.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        sb.pack(side="right", fill="y", padx=(0, 10), pady=10)

        self.status_metrics = ttk.Label(self.tab_metrics, text="", style="Muted.TLabel")
        self.status_metrics.pack(fill="x", padx=22, pady=(0, 10))

    def reload_metrics(self) -> None:
        try:
            result = compute_machine_metrics()
        except Exception as e:
            log_exception(_logger, "Machine metrics read failed", e)
            self.tree_metrics.delete(*self.tree_metrics.get_children())
            self.status_metrics.configure(text=f"Falha ao consultar métricas: {type(e).__name__}: {e}")
            return

        self.tree_metrics.delete(*self.tree_metrics.get_children())

        total_order_count = 0
        total_timed_count = 0
        for machine, metrics in sorted(result.items()):
            self.tree_metrics.insert(
                "",
                "end",
                iid=machine or "—",
                values=(
                    machine or "—",
                    format_m(metrics["produced_m"], suffix=False),
                    format_m(metrics["gap_m"], suffix=False),
                    metrics["order_count"],
                    metrics["gap_count"],
                    _format_duration_minutes(metrics["duration_minutes"]),
                    metrics["roll_count"],
                ),
            )
            total_order_count += metrics["order_count"]
            total_timed_count += metrics["timed_order_count"]

        # Rastreabilidade: nunca deixar a coluna "Duração" parecer completa
        # quando só uma fração dos pedidos tem o horário real gravado (ver
        # docstring de compute_machine_metrics — start_time é uma coluna
        # nova; rolos salvos antes dela existir não contribuem).
        coverage_note = ""
        if total_order_count:
            coverage_note = (
                f" | Duração calculada a partir de {total_timed_count} de {total_order_count} "
                "pedido(s) com horário real registrado"
            )
        self.status_metrics.configure(
            text=f"Máquinas: {len(result)}{coverage_note}"
        )

    # ------------------------
    # Retrabalho (ver core/printlogs_db.py:list_rework_candidates)
    # ------------------------
    def _build_rework_tab(self) -> None:
        """Aba "Retrabalho" — pedido do usuário, item de roadmap (Fase 3)
        "acompanhar retrabalho de forma explícita, distinguindo-o da
        impressão original". Candidatos: mesmo pedido+tecido em rolos
        DIFERENTES da Operação — o mais antigo é a impressão original, os
        demais são possível retrabalho. Só um RELATÓRIO pro operador
        conferir — decisão confirmada com o usuário: não muda nenhuma
        métrica já existente (Painel/Métricas continuam somando tudo)."""
        header = ttk.Frame(self.tab_rework)
        header.pack(fill="x", padx=22, pady=(16, 0))
        ttk.Label(
            header,
            text=(
                "Pedido + tecido que aparece em mais de um rolo da Operação — o rolo mais "
                "antigo é tratado como a impressão original, os demais como possível "
                "retrabalho (reimpressão por defeito/erro). Critério amplo por pedido+tecido "
                "(não pelo nome do arquivo) — confira antes de concluir qualquer coisa; só "
                "leitura, nunca corrige nada e nunca muda \"Métricas\"/\"Painel\"."
            ),
            style="Muted.TLabel",
            wraplength=760,
            justify="left",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(header, text="⟳ Atualizar", command=self.reload_rework).pack(side="right")

        filtro_row = ttk.Frame(self.tab_rework)
        filtro_row.pack(fill="x", padx=22, pady=(10, 0))
        ttk.Label(filtro_row, text="Pedido/tecido contém").pack(side="left", padx=(0, 6))
        self.var_rework_filter = tk.StringVar(value="")
        ent_rework_filter = ttk.Entry(filtro_row, textvariable=self.var_rework_filter, width=30)
        ent_rework_filter.pack(side="left", padx=(0, 14))
        ent_rework_filter.bind("<KeyRelease>", lambda _e: self._apply_rework_filter())

        box = card(self.tab_rework, "Possível retrabalho", padding=10)
        box.pack(fill="both", expand=True, padx=22, pady=(10, 8))

        cols = ("pedido", "fabric", "original_roll", "original_date", "original_m", "rework_roll", "rework_date", "rework_m")
        self.tree_rework = ttk.Treeview(box, columns=cols, show="headings", height=12)
        for col, txt, w, anchor in [
            ("pedido", "Pedido", 170, "w"),
            ("fabric", "Tecido", 110, "w"),
            ("original_roll", "Rolo original", 190, "w"),
            ("original_date", "Data original", 140, "w"),
            ("original_m", "Metros (original)", 110, "e"),
            ("rework_roll", "Rolo retrabalho", 190, "w"),
            ("rework_date", "Data retrabalho", 140, "w"),
            ("rework_m", "Metros (retrabalho)", 120, "e"),
        ]:
            self.tree_rework.heading(col, text=txt)
            self.tree_rework.column(col, width=w, anchor=anchor)

        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree_rework.yview)
        self.tree_rework.configure(yscrollcommand=sb.set)
        self.tree_rework.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        sb.pack(side="right", fill="y", padx=(0, 10), pady=10)

        self.tree_rework.bind("<Button-3>", self._show_rework_context_menu)
        self._rework_rows: dict[str, dict] = {}
        self._rework_all_rows: list = []

        self.status_rework = ttk.Label(self.tab_rework, text="", style="Muted.TLabel")
        self.status_rework.pack(fill="x", padx=22, pady=(0, 10))

    def reload_rework(self) -> None:
        try:
            self._rework_all_rows = list_rework_candidates()
        except Exception as e:
            log_exception(_logger, "Rework candidates read failed", e)
            self._rework_all_rows = []
            self.tree_rework.delete(*self.tree_rework.get_children())
            self.status_rework.configure(
                text=f"Falha ao consultar retrabalho: {type(e).__name__}: {e}"
            )
            return
        self._apply_rework_filter()

    def _apply_rework_filter(self) -> None:
        needle = (self.var_rework_filter.get() or "").strip().lower()

        def predicate(info):
            return not (needle and needle not in info["pedido"].lower() and needle not in info["fabric"].lower())

        def row_values(info):
            return (
                info["pedido"],
                info["fabric"],
                info["original_roll_name"],
                info["original_created_at"],
                format_m(info["original_real_m"], suffix=False),
                info["rework_roll_name"],
                info["rework_created_at"],
                format_m(info["rework_real_m"], suffix=False),
            )

        self._apply_filterable_list(
            self.tree_rework, self._rework_all_rows, self._rework_rows,
            predicate=predicate, row_values=row_values,
            status_label=self.status_rework,
            status_prefix=lambda total: f"Total de candidatos: {total}",
        )

    def _show_rework_context_menu(self, event) -> None:
        iid = self.tree_rework.identify_row(event.y)
        if not iid:
            return
        self.tree_rework.selection_set(iid)
        info = self._rework_rows.get(iid)

        menu = tk.Menu(self, tearoff=0)
        if info:
            menu.add_command(
                label=f"Abrir rolo original: {info['original_roll_name']}",
                command=lambda name=info["original_roll_name"]: self._open_roll_from_reconciliation(name),
            )
            menu.add_command(
                label=f"Abrir rolo de retrabalho: {info['rework_roll_name']}",
                command=lambda name=info["rework_roll_name"]: self._open_roll_from_reconciliation(name),
            )
        else:
            menu.add_command(label="(nenhum rolo associado)", state="disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _build_duplicates_tab(self) -> None:
        """Aba "Duplicatas" — achado real durante a investigação do item de
        roadmap de retrabalho (ver aba "Retrabalho"): reexportação
        duplicada do mesmo lote, mesmo `roll_name` salvo mais de uma vez
        como rolos DIFERENTES, com o MESMO conteúdo (não só mesmo
        pedido+tecido — isso é "Retrabalho"; aqui é conteúdo idêntico, byte
        a byte). Só um RELATÓRIO pro operador conferir — decisão
        confirmada com o usuário: não muda nenhuma métrica já existente
        (Painel/Métricas/Reconciliação continuam contando cada cópia)."""
        header = ttk.Frame(self.tab_duplicates)
        header.pack(fill="x", padx=22, pady=(16, 0))
        ttk.Label(
            header,
            text=(
                "Mesmo nome de rolo salvo mais de uma vez com conteúdo idêntico — "
                "reexportação duplicada do mesmo lote, nunca retrabalho de verdade. Conta em "
                "dobro em \"Métricas\"/\"Reconciliação\" hoje; só leitura, nunca corrige nada "
                "nem exclui nenhuma cópia automaticamente — confira antes de decidir o que fazer."
            ),
            style="Muted.TLabel",
            wraplength=760,
            justify="left",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(header, text="⟳ Atualizar", command=self.reload_duplicates).pack(side="right")

        filtro_row = ttk.Frame(self.tab_duplicates)
        filtro_row.pack(fill="x", padx=22, pady=(10, 0))
        ttk.Label(filtro_row, text="Nome do rolo contém").pack(side="left", padx=(0, 6))
        self.var_duplicates_filter = tk.StringVar(value="")
        ent_duplicates_filter = ttk.Entry(filtro_row, textvariable=self.var_duplicates_filter, width=30)
        ent_duplicates_filter.pack(side="left", padx=(0, 14))
        ent_duplicates_filter.bind("<KeyRelease>", lambda _e: self._apply_duplicates_filter())

        box = card(self.tab_duplicates, "Exportações duplicadas", padding=10)
        box.pack(fill="both", expand=True, padx=22, pady=(10, 8))

        cols = ("roll_name", "module", "order_count", "real_m", "copy_count", "first_seen", "last_seen")
        self.tree_duplicates = ttk.Treeview(box, columns=cols, show="headings", height=12)
        for col, txt, w, anchor in [
            ("roll_name", "Nome do rolo", 260, "w"),
            ("module", "Módulo", 100, "w"),
            ("order_count", "Pedidos", 70, "e"),
            ("real_m", "Metros (por cópia)", 130, "e"),
            ("copy_count", "Cópias", 70, "e"),
            ("first_seen", "1ª exportação", 150, "w"),
            ("last_seen", "Última exportação", 150, "w"),
        ]:
            self.tree_duplicates.heading(col, text=txt)
            self.tree_duplicates.column(col, width=w, anchor=anchor)

        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree_duplicates.yview)
        self.tree_duplicates.configure(yscrollcommand=sb.set)
        self.tree_duplicates.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        sb.pack(side="right", fill="y", padx=(0, 10), pady=10)

        self.tree_duplicates.bind("<Button-3>", self._show_duplicates_context_menu)
        self._duplicates_rows: dict[str, dict] = {}
        self._duplicates_all_rows: list = []

        self.status_duplicates = ttk.Label(self.tab_duplicates, text="", style="Muted.TLabel")
        self.status_duplicates.pack(fill="x", padx=22, pady=(0, 10))

    def reload_duplicates(self) -> None:
        try:
            self._duplicates_all_rows = list_duplicate_export_groups()
        except Exception as e:
            log_exception(_logger, "Duplicate export groups read failed", e)
            self._duplicates_all_rows = []
            self.tree_duplicates.delete(*self.tree_duplicates.get_children())
            self.status_duplicates.configure(
                text=f"Falha ao consultar duplicatas: {type(e).__name__}: {e}"
            )
            return
        self._apply_duplicates_filter()

    def _apply_duplicates_filter(self) -> None:
        needle = (self.var_duplicates_filter.get() or "").strip().lower()

        def predicate(info):
            return not (needle and needle not in info["roll_name"].lower())

        def row_values(info):
            copies = info["copies"]
            return (
                info["roll_name"],
                info["module"],
                info["order_count"],
                format_m(info["real_m_per_copy"], suffix=False),
                len(copies),
                copies[0]["created_at"],
                copies[-1]["created_at"],
            )

        self._apply_filterable_list(
            self.tree_duplicates, self._duplicates_all_rows, self._duplicates_rows,
            predicate=predicate, row_values=row_values,
            status_label=self.status_duplicates,
            status_prefix=lambda total: f"Total de grupos duplicados: {total}",
        )

    def _show_duplicates_context_menu(self, event) -> None:
        iid = self.tree_duplicates.identify_row(event.y)
        if not iid:
            return
        self.tree_duplicates.selection_set(iid)
        info = self._duplicates_rows.get(iid)

        menu = tk.Menu(self, tearoff=0)
        if info:
            menu.add_command(
                label=f"Abrir rolos: {info['roll_name']} ({len(info['copies'])} cópias)",
                command=lambda name=info["roll_name"]: self._open_roll_from_reconciliation(name),
            )
        else:
            menu.add_command(label="(nenhum rolo associado)", state="disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ------------------------
    # Painel operacional
    # ------------------------
    def _build_panel_tab(self) -> None:
        """Aba "Painel" — resumo de tudo que as abas "Métricas" e
        "Reconciliação" já validam, numa única tela: primeiro lugar que o
        operador vê ao abrir Registros. Não calcula nada por conta
        própria — só agrega os mesmos `compute_machine_metrics`/
        `reconcile_planned_vs_logged` já usados nas outras duas abas."""
        header = ttk.Frame(self.tab_panel)
        header.pack(fill="x", padx=22, pady=(16, 0))
        ttk.Label(
            header,
            text="Resumo da produção confirmada por log real e das divergências contra o planejado.",
            style="Muted.TLabel",
            wraplength=760,
            justify="left",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(header, text="⟳ Atualizar", command=self.reload_panel).pack(side="right")

        resumo = card(self.tab_panel, "Resumo", padding=14)
        resumo.pack(fill="x", padx=22, pady=(10, 8))

        self._panel_summary_vars = {
            key: tk.StringVar(value="—")
            for key in ("produced_m", "gap_m", "machines", "rolls", "divergent_pairs", "duration_coverage")
        }
        labels = [
            ("produced_m", "Metros produzidos"),
            ("gap_m", "Metros de avanço"),
            ("machines", "Máquinas ativas"),
            ("rolls", "Rolos confirmados"),
            ("divergent_pairs", "Pares com divergência"),
            ("duration_coverage", "Duração calculada"),
        ]
        for idx, (key, label) in enumerate(labels):
            row, col = divmod(idx, 3)
            cell = ttk.Frame(resumo)
            cell.grid(row=row, column=col, sticky="w", padx=14, pady=8)
            ttk.Label(cell, text=label, style="Muted.TLabel").pack(anchor="w")
            ttk.Label(cell, textvariable=self._panel_summary_vars[key], font=("", 14, "bold")).pack(anchor="w")

        split = ttk.Frame(self.tab_panel)
        split.pack(fill="both", expand=True, padx=22, pady=(0, 8))

        machines_box = card(split, "Produção por máquina", padding=10)
        machines_box.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.tree_panel_machines = ttk.Treeview(
            machines_box, columns=("machine", "produced_m", "roll_count"), show="headings", height=6
        )
        for col, txt, w in [("machine", "Máquina", 90), ("produced_m", "Produzido (m)", 110), ("roll_count", "Rolos", 70)]:
            self.tree_panel_machines.heading(col, text=txt)
            self.tree_panel_machines.column(col, width=w, anchor="w" if col == "machine" else "e")
        self.tree_panel_machines.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        ttk.Button(
            machines_box, text="Ver métricas completas →", command=lambda: self.top_nb.select(self.tab_metrics)
        ).pack(anchor="e", padx=8, pady=(0, 8))

        divergences_box = card(split, "Maiores divergências", padding=10)
        divergences_box.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self.tree_panel_divergences = ttk.Treeview(
            divergences_box, columns=("pedido", "fabric", "delta_m"), show="headings", height=6
        )
        for col, txt, w in [("pedido", "Pedido", 150), ("fabric", "Tecido", 100), ("delta_m", "Diferença (m)", 100)]:
            self.tree_panel_divergences.heading(col, text=txt)
            self.tree_panel_divergences.column(col, width=w, anchor="w" if col != "delta_m" else "e")
        self.tree_panel_divergences.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        ttk.Button(
            divergences_box, text="Ver reconciliação completa →",
            command=lambda: self.top_nb.select(self.tab_reconciliation),
        ).pack(anchor="e", padx=8, pady=(0, 8))

    def reload_panel(self) -> None:
        try:
            metrics_by_machine = compute_machine_metrics()
        except Exception as e:
            log_exception(_logger, "Panel metrics read failed", e)
            metrics_by_machine = {}

        try:
            reconciliation = reconcile_planned_vs_logged()
        except Exception as e:
            log_exception(_logger, "Panel reconciliation read failed", e)
            reconciliation = {}

        total_produced_m = sum(m["produced_m"] for m in metrics_by_machine.values())
        total_gap_m = sum(m["gap_m"] for m in metrics_by_machine.values())
        total_rolls = sum(m["roll_count"] for m in metrics_by_machine.values())
        total_order_count = sum(m["order_count"] for m in metrics_by_machine.values())
        total_timed_count = sum(m["timed_order_count"] for m in metrics_by_machine.values())

        self._panel_summary_vars["produced_m"].set(format_m(total_produced_m, suffix=False))
        self._panel_summary_vars["gap_m"].set(format_m(total_gap_m, suffix=False))
        self._panel_summary_vars["machines"].set(str(len(metrics_by_machine)))
        self._panel_summary_vars["rolls"].set(str(total_rolls))
        divergent_pairs = [item for item in reconciliation.items() if abs(item[1]["delta_m"]) > 0.01]
        self._panel_summary_vars["divergent_pairs"].set(f"{len(divergent_pairs)} de {len(reconciliation)}")
        self._panel_summary_vars["duration_coverage"].set(
            f"{total_timed_count} de {total_order_count} pedido(s)" if total_order_count else "—"
        )

        self.tree_panel_machines.delete(*self.tree_panel_machines.get_children())
        for machine, metrics in sorted(metrics_by_machine.items()):
            self.tree_panel_machines.insert(
                "", "end", iid=machine or "—",
                values=(machine or "—", format_m(metrics["produced_m"], suffix=False), metrics["roll_count"]),
            )

        self.tree_panel_divergences.delete(*self.tree_panel_divergences.get_children())
        top_divergent = sorted(divergent_pairs, key=lambda item: abs(item[1]["delta_m"]), reverse=True)[:5]
        for idx, ((pedido, fabric), info) in enumerate(top_divergent):
            self.tree_panel_divergences.insert(
                "", "end", iid=str(idx), values=(pedido, fabric, f"{info['delta_m']:+.2f}"),
            )

    def _on_roll_right_click(self, event) -> None:
        iid = self.tree_rolls.identify_row(event.y)
        if iid:
            self.tree_rolls.selection_set(iid)
            self.tree_rolls.focus(iid)
            self.on_select_roll()
        try:
            self._roll_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._roll_menu.grab_release()

    def on_double_click_roll(self, _evt=None) -> None:
        sel = self.tree_rolls.selection()
        if not sel:
            return

        iid = sel[0]
        values = self.tree_rolls.item(iid, "values")
        if not values:
            return

        roll_name = values[1]
        try:
            self.clipboard_clear()
            self.clipboard_append(str(roll_name))
            self.status.configure(text=f"Copiado: {roll_name}")
        except Exception:
            pass

    def on_edit_roll(self) -> None:
        roll_id = self._current_roll_id
        if roll_id is None:
            messagebox.showinfo("Editar rolo", "Selecione um rolo na lista acima.")
            return

        try:
            module = load_roll_module(roll_id)
        except Exception as e:
            messagebox.showerror("Editar rolo", f"Falha ao identificar o módulo de origem.\n\n{type(e).__name__}: {e}")
            return

        module_path = _EDIT_ROUTES.get(module)
        if not module_path:
            messagebox.showerror(
                "Editar rolo",
                "Não foi possível identificar em qual módulo este rolo foi gerado "
                "(rolo antigo ou sem essa informação registrada).",
            )
            return

        try:
            summary = load_roll_summary(roll_id)
            orders = load_roll_orders(roll_id)
        except Exception as e:
            messagebox.showerror("Editar rolo", f"Falha ao carregar o rolo.\n\n{type(e).__name__}: {e}")
            return

        if not summary:
            messagebox.showerror("Editar rolo", "Rolo não encontrado.")
            return

        roll_name = str(summary.get("roll_name", ""))
        machine = str(summary.get("machine", ""))

        try:
            mod = importlib.import_module(module_path)
            build_ui = getattr(mod, "build_ui", None)
            if not callable(build_ui):
                raise RuntimeError(f"{module_path} não possui build_ui(parent).")

            if module_path == "modules.planejador":
                preload = {
                    "edit_roll_id": roll_id,
                    "batch_name": roll_name,
                    "jobs": [
                        {
                            "name": str(o.get("document", "")),
                            "path": str(o.get("source_path") or "") or None,
                            "fabric": str(o.get("fabric", "Outro")),
                            "length_m": float(o.get("real_m", 0.0) or 0.0),
                            "observacao": str(o.get("observacao") or ""),
                        }
                        for o in orders
                    ],
                }
            else:
                preload = {
                    "edit_roll_id": roll_id,
                    "roll_name": roll_name,
                    "machine": machine,
                    "jobs": [
                        OperacaoJob(
                            end_time=_parse_order_end_time(o.get("end_time")),
                            document=str(o.get("document", "")),
                            fabric=str(o.get("fabric", "")),
                            pedido=str(o.get("pedido") or ""),
                            height_mm=float(o.get("height_mm", 0.0) or 0.0),
                            vpos_mm=float(o.get("vpos_mm", 0.0) or 0.0),
                            real_mm=float(o.get("real_m", 0.0) or 0.0) * 1000.0,
                            src_file=str(o.get("source_path") or ""),
                            tipo=str(o.get("tipo") or ""),
                            observacao=str(o.get("observacao") or ""),
                            # Avanço/espaço sempre tem tipo vazio (ver
                            # modules.operacao.parser) — sem isso, reabrir
                            # um rolo editado mostrava ESPAÇO como se fosse
                            # um tecido/pedido real.
                            is_gap=not str(o.get("tipo") or "").strip(),
                            # Já veio resolvido do banco — não deixa o botão
                            # "Salvar" do diálogo de regras reclassificar
                            # história já exportada sem o usuário pedir.
                            tipo_manual=True,
                        )
                        for o in orders
                    ],
                }
        except Exception as e:
            log_exception(_logger, "Could not prepare roll for editing", e)
            messagebox.showerror(
                "Editar rolo",
                f"Falha ao preparar os dados do rolo para edição.\n\n{type(e).__name__}: {e}",
            )
            return

        win = tk.Toplevel(self)
        win.title(f"Editar rolo #{roll_id} — {_DISPLAY_NAMES.get(module_path, module)}")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.focus_force()

        try:
            ui = build_ui(win, preload=preload)
            # Alguns módulos (ex.: Planejador) já se empacotam sozinhos; outros
            # (ex.: PXPrintLogsUI/Operação) retornam o próprio frame esperando
            # que quem chamou faça o pack — igual ao que o Nexor faz ao montar
            # a página de cada módulo no menu lateral.
            if isinstance(ui, tk.Widget) and not ui.winfo_manager():
                ui.pack(fill="both", expand=True)
        except Exception:
            win.destroy()
            messagebox.showerror(
                "Editar rolo",
                f"Falha ao abrir o módulo para edição.\n\n{traceback.format_exc()}",
            )
            return

        # Geometry só DEPOIS de montar e empacotar o conteúdo — setar antes
        # do pack deixa o Tk recalcular o tamanho pelo conteúdo ainda vazio
        # na primeira renderização, e a janela abre pequena demais.
        win.minsize(1200, 800)
        win.update_idletasks()
        win.geometry("1200x800")

        def _on_close():
            win.destroy()
            self.reload()

        win.protocol("WM_DELETE_WINDOW", _on_close)

    def _open_pdf(self, pdf_path: str) -> None:
        if not pdf_path:
            messagebox.showwarning(
                "Abrir comprovante", "Esse rolo não tem um PDF de comprovante registrado."
            )
            return
        if not Path(pdf_path).exists():
            messagebox.showerror("Abrir comprovante", f"Arquivo não encontrado:\n{pdf_path}")
            return
        try:
            os.startfile(pdf_path)
        except Exception as e:
            messagebox.showerror(
                "Abrir comprovante", f"Falha ao abrir o PDF.\n\n{type(e).__name__}: {e}"
            )

    def _choose_comprovante(self, original_path: str, latest_path: str) -> None:
        """Rolo editado com comprovantes diferentes — pergunta qual abrir
        em vez de abrir um dos dois sem avisar que existe o outro."""
        win = tk.Toplevel(self)
        win.title("Abrir comprovante")
        win.resizable(False, False)
        win.transient(self.winfo_toplevel())
        win.grab_set()

        ttk.Label(
            win,
            text=(
                "Esse rolo foi editado depois de fechado — existe o comprovante "
                "ORIGINAL (de quando fechou a primeira vez) e o ATUAL (depois da "
                "edição). Qual você quer abrir?"
            ),
            wraplength=360, justify="left",
        ).pack(padx=16, pady=(16, 10))

        btns = ttk.Frame(win)
        btns.pack(padx=16, pady=(0, 16), fill="x")

        def _open_original():
            win.destroy()
            self._open_pdf(original_path)

        def _open_latest():
            win.destroy()
            self._open_pdf(latest_path)

        def _open_both():
            win.destroy()
            self._open_pdf(original_path)
            self._open_pdf(latest_path)

        ttk.Button(btns, text="Original", command=_open_original).pack(side="left", padx=4)
        ttk.Button(btns, text="Atual", command=_open_latest).pack(side="left", padx=4)
        ttk.Button(btns, text="Os dois", command=_open_both).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancelar", command=win.destroy).pack(side="right", padx=4)

    def on_open_comprovante(self) -> None:
        roll_id = self._current_roll_id
        if roll_id is None:
            messagebox.showinfo("Abrir comprovante", "Selecione um rolo na lista acima.")
            return

        try:
            latest_path = load_roll_pdf_path(roll_id)
            edited = load_roll_was_edited(roll_id)
            original_path = load_roll_original_pdf_path(roll_id) if edited else latest_path
        except Exception as e:
            messagebox.showerror(
                "Abrir comprovante", f"Falha ao localizar o PDF.\n\n{type(e).__name__}: {e}"
            )
            return

        if edited and original_path and latest_path and original_path != latest_path:
            self._choose_comprovante(original_path, latest_path)
            return

        self._open_pdf(latest_path or original_path)

    def on_select_roll(self, _evt=None) -> None:
        sel = self.tree_rolls.selection()
        if not sel:
            return

        roll_id = int(sel[0])
        self._current_roll_id = roll_id

        self._load_summary(roll_id)
        self._load_orders(roll_id)
        self._load_events(roll_id)
        self._load_occurrences(roll_id)

    def on_select_order(self, _evt=None) -> None:
        sel = self.tree_orders.selection()
        # Linhas de uma versão histórica (não a atual) têm iid sintético —
        # exportar contexto de produção só faz sentido pra um registro real
        # (orders.id) do estado ATUAL, não pra uma cópia congelada de uma
        # edição antiga. Um avanço/espaço (coluna "Tipo" vazia) também não
        # tem contexto de produção pra exportar (ver on_export_order_context).
        is_gap_row = bool(sel) and not str(self.tree_orders.set(sel[0], "tipo") or "").strip()
        if not sel or not self._viewing_live_version or is_gap_row:
            self._current_order_id = None
        else:
            try:
                self._current_order_id = int(sel[0])
            except ValueError:
                self._current_order_id = None
        has_order = bool(self._current_order_id)
        self.btn_export_order_context.configure(state="normal" if has_order else "disabled")
        self.btn_locate_vendor.configure(state="normal" if has_order else "disabled")
        self.btn_change_vendor.configure(state="normal" if has_order else "disabled")
        self.btn_choose_pdf.configure(state="normal" if has_order else "disabled")

        # "Abrir PDF"/"Abrir pasta"/"Mostrar no Explorador" dependem do PDF
        # vinculado (Etapa D) — a pasta do pedido é derivada dele (o vínculo
        # de vendedor, por si só, não grava um caminho de pasta).
        pdf_link = get_pdf_link(self._current_order_id) if has_order else None
        has_pdf = bool(pdf_link and pdf_link["status"] == PDF_LINK_STATUS_ACTIVE)
        self.btn_open_order_pdf.configure(state="normal" if has_pdf else "disabled")
        self.btn_open_order_folder.configure(state="normal" if has_pdf else "disabled")
        self.btn_reveal_order_pdf.configure(state="normal" if has_pdf else "disabled")

    def on_select_order_version(self, _evt=None) -> None:
        label = self.var_order_version.get()
        option = next((o for o in self._order_version_options if o["label"] == label), None)
        if option is None or self._current_roll_id is None:
            return
        self._render_orders_tree(self._current_roll_id, option["value"])
        self._render_roll_list(self._current_roll_id, option["value"])
        self._render_blocks_tree(self._current_roll_id, option["value"])
        self._render_pedidos_summary_tree(self._current_roll_id, option["value"])

    def on_export_order_context(self) -> None:
        """"Exportar contexto de produção..." — ver modules/registros/px_export.py e, no
        repositório PXToolBox, docs/integrations/nexor-order-context.md. SOMENTE LEITURA:
        nunca altera o rolo/trabalho de impressão, nunca abre o PX/Corel automaticamente.
        O Nexor não tem pedido comercial formal (sem número/cliente/status) — por isso o
        texto aqui diz "trabalho de impressão"/"contexto de produção", nunca "pedido" como
        identificador."""
        order_id = self._current_order_id
        if not order_id:
            messagebox.showinfo("Exportar contexto de produção", "Selecione um trabalho de impressão na lista acima.")
            return

        try:
            document = build_order_context_document(order_id)
        except Exception as e:
            messagebox.showerror(
                "Exportar contexto de produção", f"Falha ao ler o registro.\n\n{type(e).__name__}: {e}"
            )
            return

        if document is None:
            messagebox.showerror(
                "Exportar contexto de produção", "Este registro não foi encontrado (pode ter sido removido)."
            )
            return

        # Avanço/espaço (ver core.operacao.parser) tem "tipo" vazio (nunca
        # "Pedido"/"Reposição"/"Fora do padrão"/etc.) mesmo quando o nome de
        # exibição (pedidoLabel) não é vazio (ex.: "ESPAÇO") — por isso o
        # tipo, não só o pedido, decide se há contexto de produção real.
        tipo = str(document["job"].get("tipo") or "").strip()
        pedido_label = str(document["job"]["pedidoLabel"]).strip()
        if not tipo or not pedido_label:
            messagebox.showwarning(
                "Exportar contexto de produção",
                "Este registro não tem um pedido informado (ex.: um avanço/espaço) — "
                "não há contexto de produção para exportar.",
            )
            return

        # Rolo de teste (nome terminado em "_TESTE" — ver Operação · "Rolo de
        # teste" e core.printlogs_db.is_test_roll_name): não representa
        # produção real, então não gera contexto de produção pro PX Tool Box.
        if is_test_roll_name(str(document["source"].get("rollName") or "")):
            messagebox.showwarning(
                "Exportar contexto de produção",
                "Este trabalho pertence a um rolo de TESTE — não representa produção real, "
                "por isso não há contexto de produção para exportar.",
            )
            return

        safe_label = "".join(c if c.isalnum() or c in " -_" else "_" for c in pedido_label).strip() or "trabalho"
        default_name = f"{safe_label}-contexto-producao-px.json"

        destination = filedialog.asksaveasfilename(
            title="Exportar contexto de produção para o PX Tool Box",
            defaultextension=".json",
            filetypes=[("Arquivo JSON", "*.json")],
            initialfile=default_name,
        )
        if not destination:
            return

        try:
            write_order_context_document(document, destination)
        except Exception as e:
            log_exception(_logger, "Production context export failed", e)
            messagebox.showerror(
                "Exportar contexto de produção", f"Falha ao gravar o arquivo.\n\n{type(e).__name__}: {e}"
            )
            return

        self.status.configure(text=f"Contexto de produção exportado: {destination}")
        self._show_export_confirmation(destination)

    def _show_export_confirmation(self, destination: str) -> None:
        """Janela de confirmação pós-exportação do contexto de produção — mostra o caminho e
        oferece "Mostrar arquivo na pasta"/"Copiar caminho" (ver core.paths.reveal_file_in_explorer).
        Só aparece depois de uma gravação bem-sucedida (chamado só pelo caminho de sucesso de
        on_export_order_context) — cancelamento ou falha de gravação nunca chegam aqui. As duas
        ações são auxiliares: uma falha nelas nunca desfaz a confirmação de que o arquivo foi
        exportado, só soma um aviso à parte."""
        win = tk.Toplevel(self)
        win.title("Contexto de produção exportado")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.resizable(False, False)

        frame = ttk.Frame(win, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Contexto de produção exportado com sucesso.", font=("", 10, "bold")).pack(
            anchor="w"
        )

        path_entry = ttk.Entry(frame, width=70)
        path_entry.insert(0, destination)
        path_entry.configure(state="readonly")
        path_entry.pack(fill="x", pady=(8, 4))

        aux_status = ttk.Label(frame, text="", foreground="#1a7a1a")
        aux_status.pack(anchor="w", pady=(0, 8))

        def _on_reveal():
            try:
                reveal_file_in_explorer(Path(destination))
                aux_status.configure(text="Pasta aberta com o arquivo selecionado.", foreground="#1a7a1a")
            except Exception as e:
                aux_status.configure(
                    text=f"Não foi possível abrir a pasta ({type(e).__name__}: {e}).",
                    foreground="#b00020",
                )

        def _on_copy():
            try:
                self.clipboard_clear()
                self.clipboard_append(destination)
                aux_status.configure(text="Caminho copiado.", foreground="#1a7a1a")
            except Exception as e:
                aux_status.configure(
                    text=f"Não foi possível copiar o caminho ({type(e).__name__}: {e}).",
                    foreground="#b00020",
                )

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=(0, 8))
        ttk.Button(btn_row, text="Mostrar arquivo na pasta", command=_on_reveal).pack(side="left")
        ttk.Button(btn_row, text="Copiar caminho", command=_on_copy).pack(side="left", padx=(8, 0))

        ttk.Label(
            frame,
            text='No PX Tool Box DEV, use Produção > "Carregar contexto de produção".',
            foreground="#6a6a6a",
            wraplength=420,
        ).pack(anchor="w", pady=(4, 8))

        ttk.Button(frame, text="Fechar", command=win.destroy).pack(anchor="e")

        win.focus_force()

    # ------------------------
    # Vendedor / PDF original do pedido (Etapa E, ver core/order_vendor_resolution.py
    # e core/order_pdfs.py — Etapas C/D). Só o pedido selecionado na aba "Pedidos",
    # na versão ATUAL do rolo (ver on_select_order) — uma cópia histórica nunca tem
    # order_id real pra vincular.
    # ------------------------
    def _ask_pick_from_list(self, title: str, prompt: str, items: list, label_fn) -> Optional[object]:
        return ask_pick_from_list(self, title, prompt, items, label_fn)

    def _selected_pedido_name(self) -> str:
        order_id = self._current_order_id
        if not order_id:
            return ""
        return str(self.tree_orders.set(str(order_id), "pedido") or "").strip()

    def _folder_for_vendor(self, pedido_name: str, index, vendor_key: str) -> Optional[str]:
        return folder_for_vendor(pedido_name, index, vendor_key)

    def _refresh_selected_order_row(self) -> None:
        order_id = self._current_order_id
        if order_id and self.tree_orders.exists(str(order_id)):
            self.tree_orders.set(str(order_id), "vendedor", _vendor_status_text(order_id))
            self.tree_orders.set(str(order_id), "pdf", _pdf_status_text(order_id))
        self.on_select_order()

    def on_locate_vendor_pdf(self) -> None:
        """"Localizar vendedor/PDF" — resolve com o índice JÁ salvo em disco
        (core.order_files.load_order_index): rápido, nunca varre a rede
        aqui (isso só acontece em Configurações · Vendedores · "Atualizar
        índice"). Ambiguidade de vendedor OU de PDF nunca escolhe por conta
        própria — pede confirmação (ver core/order_vendor_resolution.py e
        core/order_pdfs.py)."""
        order_id = self._current_order_id
        if not order_id:
            messagebox.showinfo("Localizar vendedor/PDF", "Selecione um pedido na lista acima.")
            return
        pedido_name = self._selected_pedido_name()
        if not pedido_name:
            messagebox.showwarning("Localizar vendedor/PDF", "Este registro não tem um pedido informado.")
            return

        vendedores = load_vendedores()
        index = load_order_index()
        vendor_result = resolve_order_vendor(order_id, pedido_name, index=index, vendedores=vendedores)

        vendor_folder: Optional[str] = None
        if vendor_result.state == RESOLUTION_AMBIGUOUS:
            chosen = self._ask_pick_from_list(
                "Vendedor ambíguo",
                f'O pedido "{pedido_name}" foi encontrado em mais de um vendedor. Escolha o correto:',
                vendor_result.candidates, lambda c: f"{c.vendor_name_snapshot} — {c.path}",
            )
            if chosen is None:
                self._refresh_selected_order_row()
                return
            confirm_order_vendor(order_id, chosen.vendor_key, chosen.vendor_name_snapshot)
            vendor_folder = chosen.path
        elif vendor_result.state in (RESOLUTION_AUTO, RESOLUTION_MANUAL):
            if vendor_result.candidates:
                vendor_folder = vendor_result.candidates[0].path
            elif vendor_result.vendor_key:
                vendor_folder = self._folder_for_vendor(pedido_name, index, vendor_result.vendor_key)
        else:
            messagebox.showinfo(
                "Localizar vendedor/PDF",
                f'Vendedor não identificado para "{pedido_name}".\n'
                'Use "Alterar vendedor..." para escolher manualmente, ou cadastre a pasta '
                'em Configurações · Vendedores e clique em "Atualizar índice".',
            )
            self._refresh_selected_order_row()
            return

        if not vendor_folder:
            self._refresh_selected_order_row()
            return

        pdf_result = resolve_order_pdf(order_id, vendor_folder)
        if pdf_result.state == PDF_RESOLUTION_AMBIGUOUS:
            chosen_pdf = self._ask_pick_from_list(
                "PDF ambíguo",
                "Mais de um PDF foi encontrado na pasta deste pedido. Escolha qual é o arquivo impresso:",
                pdf_result.candidates,
                lambda f: f"{f.name}  ({f.page_count or '?'} pág. · {f.modified_at})",
            )
            if chosen_pdf is not None:
                link_order_pdf(order_id, chosen_pdf.path)
        elif pdf_result.state == PDF_RESOLUTION_NOT_FOUND:
            messagebox.showinfo("Localizar vendedor/PDF", "Nenhum PDF foi encontrado na pasta deste pedido.")

        self._refresh_selected_order_row()

    def on_change_vendor(self) -> None:
        """"Alterar vendedor..." — correção manual (seção 7: "A
        identificação manual deverá ter precedência sobre a automática.").
        Inclui a opção de remover o vínculo (volta a "Não identificado")."""
        order_id = self._current_order_id
        if not order_id:
            messagebox.showinfo("Alterar vendedor", "Selecione um pedido na lista acima.")
            return
        vendedores = [v for v in load_vendedores() if v.active]
        if not vendedores:
            messagebox.showwarning("Alterar vendedor", "Nenhum vendedor ativo cadastrado (ver Configurações).")
            return

        clear_sentinel = object()
        items = list(vendedores) + [clear_sentinel]

        def label(item: object) -> str:
            return "— Remover vínculo (Não identificado) —" if item is clear_sentinel else item.name  # type: ignore[union-attr]

        chosen = self._ask_pick_from_list(
            "Alterar vendedor", "Escolha o vendedor correto para este pedido:", items, label,
        )
        if chosen is None:
            return
        if chosen is clear_sentinel:
            clear_order_vendor(order_id)
        else:
            confirm_order_vendor(order_id, chosen.key, chosen.name)
        self._refresh_selected_order_row()

    def on_choose_pdf(self) -> None:
        """"Vincular PDF..." — escolha manual do arquivo, pra quando a
        localização automática não encontra nada ou encontra o errado
        (seção 9: "Não presumir que o arquivo mais recente seja
        necessariamente o correto.")."""
        order_id = self._current_order_id
        if not order_id:
            messagebox.showinfo("Vincular PDF", "Selecione um pedido na lista acima.")
            return

        initial_dir = None
        vendor_link = get_vendor_link(order_id)
        if vendor_link and vendor_link["status"] == VENDOR_LINK_STATUS_ACTIVE:
            pedido_name = self._selected_pedido_name()
            if pedido_name:
                initial_dir = self._folder_for_vendor(pedido_name, load_order_index(), vendor_link["vendor_key"])

        path = filedialog.askopenfilename(
            title="Escolher o PDF original deste pedido",
            filetypes=[("PDF", "*.pdf")],
            initialdir=initial_dir or None,
        )
        if not path:
            return
        link_order_pdf(order_id, path)
        self._refresh_selected_order_row()

    def on_open_order_pdf(self) -> None:
        link = get_pdf_link(self._current_order_id) if self._current_order_id else None
        if not link or link["status"] != PDF_LINK_STATUS_ACTIVE:
            messagebox.showinfo("Abrir PDF", "Este pedido não tem um PDF vinculado.")
            return
        try:
            open_order_pdf(link["pdf_path"])
        except Exception as e:
            messagebox.showerror("Abrir PDF", f"Falha ao abrir o PDF.\n\n{type(e).__name__}: {e}")

    def on_open_order_folder(self) -> None:
        link = get_pdf_link(self._current_order_id) if self._current_order_id else None
        if not link or link["status"] != PDF_LINK_STATUS_ACTIVE:
            messagebox.showinfo("Abrir pasta", "Este pedido não tem um PDF vinculado.")
            return
        try:
            open_order_folder(str(Path(link["pdf_path"]).parent))
        except Exception as e:
            messagebox.showerror("Abrir pasta", f"Falha ao abrir a pasta.\n\n{type(e).__name__}: {e}")

    def on_reveal_order_pdf(self) -> None:
        link = get_pdf_link(self._current_order_id) if self._current_order_id else None
        if not link or link["status"] != PDF_LINK_STATUS_ACTIVE:
            messagebox.showinfo("Mostrar no Explorador", "Este pedido não tem um PDF vinculado.")
            return
        try:
            reveal_order_pdf(link["pdf_path"])
        except Exception as e:
            messagebox.showerror("Mostrar no Explorador", f"Falha ao abrir o Explorador.\n\n{type(e).__name__}: {e}")

    # ------------------------
    # Loaders
    # ------------------------
    def _clear_details(self) -> None:
        self._current_roll_id = None

        self.txt_summary.configure(state="normal")
        self.txt_summary.delete("1.0", "end")
        self.txt_summary.insert("1.0", "Selecione um roll na lista acima...")
        self.txt_summary.configure(state="disabled")

        self.tree_orders.delete(*self.tree_orders.get_children())
        self.tree_roll_list.delete(*self.tree_roll_list.get_children())
        self.tree_events.delete(*self.tree_events.get_children())
        self.tree_blocks.delete(*self.tree_blocks.get_children())
        self.tree_block_details.delete(*self.tree_block_details.get_children())
        self.tree_pedidos_summary.delete(*self.tree_pedidos_summary.get_children())
        self.tree_occurrences.delete(*self.tree_occurrences.get_children())
        self._current_blocks = []
        self._block_details_card.configure(text='Selecione um tecido na aba "Ordem do rolo"...')

        self._order_version_options = []
        self.cmb_order_version.configure(values=[])
        self.var_order_version.set("")

    def _load_summary(self, roll_id: int) -> None:
        try:
            summary = load_roll_summary(roll_id)
        except Exception as e:
            self._set_summary_text(f"Falha ao carregar resumo.\n\n{type(e).__name__}: {e}")
            return

        if not summary:
            self._set_summary_text("Resumo indisponível.")
            return

        lines: list[str] = []
        lines.append(f"Rolo: {summary.get('roll_name', '')}")
        lines.append(f"Máquina: {summary.get('machine', '')}")
        lines.append(
            f"Criado: {summary.get('created_at', '')} | Versão: {summary.get('app_version', '')}"
        )
        lines.append("")
        lines.append(f"Pedidos: {summary.get('orders_count', 0)}")
        lines.append(f"Total (m): {format_m(summary.get('total_m', 0), suffix=False)}")
        lines.append(f"EndTime: {summary.get('oldest_end', '')} → {summary.get('newest_end', '')}")
        lines.append("")
        lines.append("Tecidos (por metragem):")

        fabrics = summary.get("fabrics", []) or []
        for fabric_row in fabrics:
            fabric = fabric_row.get("fabric", "DESCONHECIDO")
            meters = format_m(fabric_row.get("m", 0), suffix=False)
            count = fabric_row.get("n", 0)
            lines.append(f"  - {fabric}: {meters} m ({count} pedidos)")

        spaces = summary.get("spaces", []) or []
        if spaces:
            lines.append("")
            lines.append(f"Espaços ({len(spaces)}):")
            for i, space_row in enumerate(spaces, start=1):
                label = space_row.get("fabric") or "ESPAÇO"
                meters = format_m(space_row.get("real_m", 0), suffix=False)
                end_time = space_row.get("end_time", "")
                n = space_row.get("n", 1)
                tail = f" — {n} avanços seguidos" if n and n > 1 else ""
                lines.append(f"  {i}. {label}: {meters} m ({end_time}){tail}")

        self._set_summary_text("\n".join(lines))

    def _set_summary_text(self, text: str) -> None:
        self.txt_summary.configure(state="normal")
        self.txt_summary.delete("1.0", "end")
        self.txt_summary.insert("1.0", text)
        self.txt_summary.configure(state="disabled")

    def _load_orders(self, roll_id: int) -> None:
        """Popula o combobox de versão (Original/Edição N/atual — ver
        repository.load_roll_order_version_options) e mostra a lista de
        pedidos da versão ATUAL por padrão (a última da lista)."""
        try:
            self._order_version_options = load_roll_order_version_options(roll_id)
        except Exception as e:
            self.status.configure(text=f"Falha ao carregar versões do rolo: {type(e).__name__}")
            self._order_version_options = [{"value": None, "label": "Atual"}]

        labels = [o["label"] for o in self._order_version_options]
        self.cmb_order_version.configure(values=labels)
        current_label = self._order_version_options[-1]["label"] if self._order_version_options else ""
        self.var_order_version.set(current_label)

        version_value = self._order_version_options[-1]["value"] if self._order_version_options else None
        self._render_orders_tree(roll_id, version_value)
        self._render_roll_list(roll_id, version_value)
        self._render_blocks_tree(roll_id, version_value)
        self._render_pedidos_summary_tree(roll_id, version_value)

    def _build_display_jobs(self, roll_id: int, version_no: Optional[int]) -> tuple[list, str]:
        """Reconstrói os Jobs (modules.operacao.models.Job) a partir das
        orders salvas no banco pra essa versão do rolo — usado por toda
        visão agrupada por bloco/pedido ("Ordem do rolo", "Detalhes do
        bloco", "Pedidos no rolo", "Lista do rolo"), mesma técnica já usada
        em `_render_roll_list` antes desta função existir."""
        module = load_roll_module(roll_id)
        summary = load_roll_summary(roll_id)
        orders = load_roll_orders_for_version(roll_id, version_no)

        machine = str((summary or {}).get("machine") or "")
        # ESPAÇO (tipo vazio) só é um conceito real na Operação — rolos do
        # Planejador nunca salvam avanços como order, e lá tipo vazio
        # nunca significa espaço (ver o comentário real de
        # get_roll_summary em core/printlogs_db.py).
        is_operacao = _EDIT_ROUTES.get(module) == "modules.operacao"

        jobs = [
            OperacaoJob(
                end_time=_parse_order_end_time(o.get("end_time")),
                document=str(o.get("document") or ""),
                fabric=str(o.get("fabric") or ""),
                pedido=str(o.get("pedido") or ""),
                height_mm=float(o.get("height_mm", 0.0) or 0.0),
                vpos_mm=float(o.get("vpos_mm", 0.0) or 0.0),
                real_mm=float(o.get("real_m", 0.0) or 0.0) * 1000.0,
                src_file=str(o.get("source_path") or ""),
                tipo=str(o.get("tipo") or ""),
                observacao=str(o.get("observacao") or ""),
                is_gap=is_operacao and not str(o.get("tipo") or "").strip(),
            )
            for o in orders
        ]
        return jobs, machine

    def _render_blocks_tree(self, roll_id: int, version_no: Optional[int]) -> None:
        """Aba "Ordem do rolo" — mesma visão agrupada por tecido que a
        Operação mostra (tree_blocks), a partir das orders já salvas."""
        self.tree_blocks.delete(*self.tree_blocks.get_children())
        self._block_details_card.configure(text='Selecione um tecido na aba "Ordem do rolo"...')
        self.tree_block_details.delete(*self.tree_block_details.get_children())

        try:
            jobs, machine = self._build_display_jobs(roll_id, version_no)
        except Exception as e:
            self.status.configure(text=f"Falha ao carregar ordem do rolo: {type(e).__name__}")
            self._current_blocks = []
            return

        self._current_blocks = build_blocks(jobs, machine)
        for idx, block in enumerate(self._current_blocks):
            self.tree_blocks.insert(
                "", "end", iid=str(idx),
                values=(
                    idx + 1,
                    block.fabric,
                    format_m(block.total_m, suffix=False),
                    block.job_count,
                    block.newest_end.strftime("%d/%m/%Y %H:%M:%S"),
                ),
            )

    def on_select_block(self, _evt=None) -> None:
        sel = self.tree_blocks.selection()
        if not sel:
            return

        block_index = int(sel[0])
        if block_index < 0 or block_index >= len(self._current_blocks):
            return

        block = self._current_blocks[block_index]
        self._block_details_card.configure(
            text=(
                f"Tecido: {block.fabric} | Máquina: {block.machine} | Arquivos: {block.job_count} | "
                f"Total: {format_m(block.total_m, suffix=False)} m | "
                f"{block.newest_end:%d/%m/%Y %H:%M:%S} → {block.oldest_end:%d/%m/%Y %H:%M:%S}"
            )
        )

        self.tree_block_details.delete(*self.tree_block_details.get_children())
        for idx, job in enumerate(sorted(block.Jobs, key=lambda j: j.end_time, reverse=True)):
            doc_txt = f"— {job.fabric or 'ESPAÇO'} —" if job.is_gap else job.document
            pedido_txt = "" if job.is_gap else job.pedido
            tipo_txt = "" if job.is_gap else job.tipo
            obs_txt = (job.observacao or "").splitlines()[0] if job.observacao else ""
            self.tree_block_details.insert(
                "", "end", iid=str(idx),
                values=(
                    job.end_time.strftime("%d/%m/%Y %H:%M:%S"),
                    doc_txt,
                    pedido_txt,
                    tipo_txt,
                    f"{job.height_mm:.1f}",
                    f"{job.vpos_mm:.1f}",
                    format_m(job.real_m, suffix=False),
                    obs_txt,
                ),
            )

    def _render_pedidos_summary_tree(self, roll_id: int, version_no: Optional[int]) -> None:
        """Aba "Pedidos no rolo" — resumo agrupado por pedido (mesma visão
        da Operação, tree_pedidos, sem vendedor/PDF — isso já existe por
        pedido individual na aba "Pedidos")."""
        self.tree_pedidos_summary.delete(*self.tree_pedidos_summary.get_children())

        try:
            jobs, _machine = self._build_display_jobs(roll_id, version_no)
        except Exception as e:
            self.status.configure(text=f"Falha ao carregar pedidos no rolo: {type(e).__name__}")
            return

        for idx, pedido in enumerate(build_pedido_summary(jobs)):
            self.tree_pedidos_summary.insert(
                "", "end", iid=str(idx),
                values=(
                    idx + 1,
                    pedido.pedido,
                    pedido.tipo,
                    format_m(pedido.total_m, suffix=False),
                    pedido.job_count,
                    pedido.newest_end.strftime("%d/%m/%Y %H:%M:%S"),
                ),
            )

    def _render_orders_tree(self, roll_id: int, version_no: Optional[int]) -> None:
        """Mostra na aba "Pedidos" os itens da versão escolhida — `None` é
        a versão atual (orders.id reais, usáveis em "Exportar contexto de
        produção"); um inteiro é uma cópia histórica guardada (ver
        core.printlogs_db.get_roll_order_version), sem id real, iid
        sintético."""
        self.tree_orders.delete(*self.tree_orders.get_children())
        self._current_order_id = None
        self._viewing_live_version = version_no is None
        self.btn_export_order_context.configure(state="disabled")
        self.btn_locate_vendor.configure(state="disabled")
        self.btn_change_vendor.configure(state="disabled")
        self.btn_choose_pdf.configure(state="disabled")
        self.btn_open_order_pdf.configure(state="disabled")
        self.btn_open_order_folder.configure(state="disabled")
        self.btn_reveal_order_pdf.configure(state="disabled")

        try:
            orders = load_roll_orders_for_version(roll_id, version_no)
        except Exception as e:
            self.status.configure(text=f"Falha ao carregar pedidos: {type(e).__name__}")
            return

        # "Pedido contém"/"Arquivo contém" filtram quais ROLOS aparecem na
        # lista, mas o item de verdade que casou com a busca fica escondido
        # dentro da aba "Pedidos" do rolo selecionado — aqui a gente marca
        # essas linhas (mesmos campos usados no filtro: orders.document e
        # orders.pedido) e pula direto pra primeira, em vez de deixar o
        # operador procurar à mão (achado real do item "Busca unificada").
        order_like = (self.var_order_like.get() or "").strip().lower()
        pedido_like = (self.var_pedido_like.get() or "").strip().lower()
        first_match_iid: Optional[str] = None

        for idx, order in enumerate(orders):
            end_time = str(order.get("end_time", "") or "")
            document = str(order.get("document", "") or "")
            pedido = str(order.get("pedido", "") or "")
            fabric = str(order.get("fabric", "") or "")
            tipo = str(order.get("tipo", "") or "")
            height_mm = order.get("height_mm", 0) or 0
            vpos_mm = order.get("vpos_mm", 0) or 0
            real_m = order.get("real_m", 0) or 0
            source_path = str(order.get("source_path", "") or "")
            observacao = str(order.get("observacao", "") or "").splitlines()[0] if order.get("observacao") else ""

            try:
                source_path = Path(source_path).name
            except Exception:
                pass

            # Na versão atual, iid = o id REAL do registro (orders.id) —
            # sem isso, "Exportar contexto de produção" não teria como
            # saber qual linha foi selecionada. Numa versão histórica não
            # há id real (foi uma cópia congelada antes de um
            # "Atualizar Rolo" apagar as orders antigas) — iid sintético.
            # O vínculo de vendedor/PDF (Etapa C/D) também só existe pra um
            # order_id real: uma versão histórica nunca mostra esses dados
            # (mesmo que o pedido atual tenha um vínculo — seria enganoso
            # atribuí-lo a uma cópia congelada antiga).
            is_live = self._viewing_live_version
            iid = str(order["id"]) if is_live else f"v{version_no}_{idx}"
            vendor_txt = _vendor_status_text(order["id"]) if is_live else "—"
            pdf_txt = _pdf_status_text(order["id"]) if is_live else "—"

            is_match = (bool(order_like) and order_like in document.lower()) or (
                bool(pedido_like) and pedido_like in pedido.lower()
            )
            if is_match and first_match_iid is None:
                first_match_iid = iid

            self.tree_orders.insert(
                "",
                "end",
                iid=iid,
                values=(
                    end_time,
                    document,
                    pedido,
                    fabric,
                    tipo,
                    f"{float(height_mm):.1f}",
                    f"{float(vpos_mm):.1f}",
                    format_m(real_m, suffix=False),
                    source_path,
                    observacao,
                    vendor_txt,
                    pdf_txt,
                ),
                tags=("busca_match",) if is_match else (),
            )

        if first_match_iid is not None:
            self.nb.select(self.tab_orders)
            self.tree_orders.selection_set(first_match_iid)
            self.tree_orders.see(first_match_iid)

    def _render_roll_list(self, roll_id: int, version_no: Optional[int]) -> None:
        """Aba "Lista do rolo" — mesma visão da aba de mesmo nome na
        Operação: todos os itens (incluindo ESPAÇO) numa lista só, na
        ordem do comprovante (blocos na ordem de build_blocks, mais
        recente pro mais antigo dentro de cada bloco)."""
        self.tree_roll_list.delete(*self.tree_roll_list.get_children())

        try:
            jobs, machine = self._build_display_jobs(roll_id, version_no)
        except Exception as e:
            self.status.configure(text=f"Falha ao carregar lista do rolo: {type(e).__name__}")
            return

        idx = 0
        for block in build_blocks(jobs, machine):
            for job in sorted(block.Jobs, key=lambda j: j.end_time, reverse=True):
                idx += 1
                doc_txt = f"— {job.fabric or 'ESPAÇO'} —" if job.is_gap else job.document
                fabric_txt = "" if job.is_gap else job.fabric
                pedido_txt = "" if job.is_gap else job.pedido
                tipo_txt = "" if job.is_gap else job.tipo
                observacao = (job.observacao or "").splitlines()[0] if job.observacao else ""

                self.tree_roll_list.insert(
                    "", "end",
                    values=(
                        idx,
                        job.end_time.strftime("%d/%m/%Y %H:%M:%S"),
                        doc_txt,
                        fabric_txt,
                        pedido_txt,
                        tipo_txt,
                        format_m(job.real_m, suffix=False),
                        observacao,
                    ),
                )

    def _load_events(self, roll_id: int) -> None:
        self.tree_events.delete(*self.tree_events.get_children())

        try:
            events = load_roll_events(roll_id)
        except Exception as e:
            self.status.configure(text=f"Falha ao carregar eventos: {type(e).__name__}")
            return

        for event in events:
            created_at = str(event.get("created_at", "") or "")
            event_type = str(event.get("event_type", "") or "")
            payload_json = str(event.get("payload_json", "") or "")
            summary = payload_summary(payload_json)

            self.tree_events.insert(
                "",
                "end",
                values=(created_at, event_type, summary),
            )

    # ------------------------
    # Ocorrências operacionais (vinculadas ao rolo — ver core/printlogs_db.py)
    # ------------------------
    def _load_occurrences(self, roll_id: int) -> None:
        self.tree_occurrences.delete(*self.tree_occurrences.get_children())

        try:
            rows = list_occurrences_for_roll(roll_id)
        except Exception as e:
            self.status.configure(text=f"Falha ao carregar ocorrências: {type(e).__name__}")
            return

        for row in rows:
            description = str(row.get("description") or "")
            first_line = description.splitlines()[0] if description else ""
            self.tree_occurrences.insert(
                "", "end", iid=str(row["occurrence_id"]),
                values=(row.get("created_at", ""), row.get("status", ""), first_line),
            )

    def _on_double_click_occurrence(self, _evt=None) -> None:
        sel = self.tree_occurrences.selection()
        if not sel:
            return
        try:
            occurrence_id = int(sel[0])
        except ValueError:
            return
        self._open_occurrence_history_dialog(occurrence_id)

    def _open_new_occurrence_dialog(self) -> None:
        if self._current_roll_id is None:
            messagebox.showinfo("Nova ocorrência", "Selecione um rolo na lista acima.")
            return
        roll_id = self._current_roll_id

        dlg = tk.Toplevel(self)
        dlg.title("Nova ocorrência")
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)
        dialog_header(
            frm, "Nova ocorrência",
            'Problema/ocorrência vinculado a este rolo (ex.: "máquina travou", "tecido '
            'rasgado") — diferente da Observação livre, fica com histórico próprio.',
        ).pack(fill="x", pady=(0, 8))

        ttk.Label(frm, text="Descrição:").pack(anchor="w", pady=(4, 2))
        txt = tk.Text(frm, width=60, height=6, wrap="word")
        txt.pack(fill="both", expand=True)
        txt.focus_set()

        status_row = ttk.Frame(frm)
        status_row.pack(fill="x", pady=(8, 0))
        ttk.Label(status_row, text="Status:").pack(side="left")
        var_status = tk.StringVar(value=OCCURRENCE_STATUS_OPEN)
        ttk.Combobox(
            status_row, textvariable=var_status, state="readonly", width=14,
            values=OCCURRENCE_STATUSES,
        ).pack(side="left", padx=(6, 0))

        def on_save():
            description = txt.get("1.0", "end-1c").strip()
            if not description:
                messagebox.showwarning("Nova ocorrência", "Descreva a ocorrência antes de salvar.")
                return
            try:
                create_occurrence(roll_id, description, var_status.get())
            except Exception as e:
                messagebox.showerror("Nova ocorrência", f"Falha ao salvar.\n\n{type(e).__name__}: {e}")
                return
            dlg.destroy()
            self._load_occurrences(roll_id)

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Cancelar", command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="Salvar", command=on_save).pack(side="right", padx=(0, 8))

    def _open_occurrence_history_dialog(self, occurrence_id: int) -> None:
        dlg = tk.Toplevel(self)
        dlg.title(f"Ocorrência #{occurrence_id}")
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        dlg.geometry("600x480")

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)
        dialog_header(
            frm, "Histórico da ocorrência",
            "Cada edição grava uma entrada nova — nenhuma entrada anterior é sobrescrita.",
        ).pack(fill="x", pady=(0, 8))

        hist_cols = ("created_at", "status", "description")
        tree_hist = ttk.Treeview(frm, columns=hist_cols, show="headings", height=6)
        tree_hist.heading("created_at", text="Data/Hora")
        tree_hist.column("created_at", width=150, anchor="w")
        tree_hist.heading("status", text="Status")
        tree_hist.column("status", width=90, anchor="w")
        tree_hist.heading("description", text="Descrição")
        tree_hist.column("description", width=300, anchor="w")
        tree_hist.pack(fill="both", expand=True, pady=(0, 8))

        def _reload_history() -> None:
            tree_hist.delete(*tree_hist.get_children())
            for entry in get_occurrence_history(occurrence_id):
                desc = str(entry.get("description") or "")
                first_line = desc.splitlines()[0] if desc else ""
                tree_hist.insert(
                    "", "end",
                    values=(entry.get("created_at", ""), entry.get("status", ""), first_line),
                )

        _reload_history()

        ttk.Separator(frm).pack(fill="x", pady=(0, 8))
        ttk.Label(frm, text="Adicionar nova entrada (edição):").pack(anchor="w")
        txt = tk.Text(frm, width=60, height=4, wrap="word")
        txt.pack(fill="both", expand=True, pady=(4, 0))

        status_row = ttk.Frame(frm)
        status_row.pack(fill="x", pady=(8, 0))
        ttk.Label(status_row, text="Status:").pack(side="left")
        var_status = tk.StringVar(value=OCCURRENCE_STATUS_OPEN)
        ttk.Combobox(
            status_row, textvariable=var_status, state="readonly", width=14,
            values=OCCURRENCE_STATUSES,
        ).pack(side="left", padx=(6, 0))

        def on_add_entry() -> None:
            description = txt.get("1.0", "end-1c").strip()
            if not description:
                messagebox.showwarning("Ocorrência", "Descreva a entrada antes de salvar.")
                return
            try:
                add_occurrence_entry(occurrence_id, description, var_status.get())
            except Exception as e:
                messagebox.showerror("Ocorrência", f"Falha ao salvar.\n\n{type(e).__name__}: {e}")
                return
            txt.delete("1.0", "end")
            _reload_history()
            if self._current_roll_id is not None:
                self._load_occurrences(self._current_roll_id)

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Fechar", command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="Adicionar entrada", command=on_add_entry).pack(side="right", padx=(0, 8))
