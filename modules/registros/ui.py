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
from core.ui import card, page_heading
from modules.operacao.models import Job as OperacaoJob
from modules.operacao.parser import build_blocks
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

# Mapeia tanto os nomes antigos (rolos já exportados antes do rebrand pra
# Nexor) quanto os novos — sem isso, "Editar rolo" quebraria pra todo o
# histórico de rolos exportados com payload["module"] = "PXPrintCalc"/"PXPrintLogs".
_EDIT_ROUTES = {
    "PXPrintCalc": "modules.planejador",
    "Planejador": "modules.planejador",
    "PXPrintLogs": "modules.operacao",
    "Operacao": "modules.operacao",
}

_DISPLAY_NAMES = {
    "modules.planejador": "Planejador",
    "modules.operacao": "Operação",
}


def _parse_order_end_time(raw: object) -> datetime:
    try:
        return datetime.fromisoformat(str(raw))
    except Exception:
        return datetime.now()


class PXSearchOrdersUI(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        page_heading(self, "Registros de produção",
                     "Encontre rolos, pedidos e o histórico de cada exportação.",
                     action=self.reload, action_text="⟳ Recarregar").pack(
                         fill="x", padx=22, pady=(22, 0)
                     )

        self._current_roll_id: Optional[int] = None
        self._current_order_id: Optional[int] = None
        self._viewing_live_version: bool = True

        # ------------------------
        # Filtros
        # ------------------------
        filtros = card(self, "Filtros", padding=14)
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

        ttk.Label(filtros, text="Pedido contém").grid(row=0, column=4, sticky="w", padx=(0, 6), pady=8)
        self.var_order_like = tk.StringVar(value="")
        self.ent_order_like = ttk.Entry(filtros, textvariable=self.var_order_like, width=26)
        self.ent_order_like.grid(row=0, column=5, sticky="w", padx=(0, 14), pady=8)

        ttk.Label(filtros, text="Tipo").grid(row=0, column=6, sticky="w", padx=(0, 6), pady=8)
        self.var_tipo = tk.StringVar(value="")
        self.cmb_tipo = ttk.Combobox(
            filtros, textvariable=self.var_tipo, values=[""], width=16, state="readonly"
        )
        self.cmb_tipo.grid(row=0, column=7, sticky="w", padx=(0, 14), pady=8)

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

        filtros.columnconfigure(11, weight=1)

        self.ent_name_like.bind("<Return>", lambda _e: self.reload())
        self.ent_order_like.bind("<Return>", lambda _e: self.reload())
        self.ent_limit.bind("<Return>", lambda _e: self.reload())
        self.cmb_tipo.bind("<<ComboboxSelected>>", lambda _e: self.reload())

        # ------------------------
        # Lista de rolos
        # ------------------------
        box_rolls = card(self, "Rolos exportados", padding=10)
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
        box_details = card(self, "Detalhes do rolo selecionado", padding=10)
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
            text='Afeta as abas "Pedidos" e "Lista do rolo" — Resumo e Eventos sempre mostram o estado atual.',
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

        # Aba Pedidos
        self.tab_orders = ttk.Frame(self.nb)
        self.nb.add(self.tab_orders, text="Pedidos")

        order_cols = ("end_time", "document", "fabric", "tipo", "height_mm", "vpos_mm", "real_m", "source", "observacao")
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

        self.tree_orders.heading("end_time", text="EndTime")
        self.tree_orders.column("end_time", width=160, anchor="w")

        self.tree_orders.heading("document", text="Documento")
        self.tree_orders.column("document", width=360, anchor="w")

        self.tree_orders.heading("fabric", text="Tecido")
        self.tree_orders.column("fabric", width=120, anchor="w")

        self.tree_orders.heading("tipo", text="Tipo")
        self.tree_orders.column("tipo", width=110, anchor="w")

        self.tree_orders.heading("height_mm", text="HeightMM")
        self.tree_orders.column("height_mm", width=90, anchor="e")

        self.tree_orders.heading("vpos_mm", text="VPosMM")
        self.tree_orders.column("vpos_mm", width=90, anchor="e")

        self.tree_orders.heading("real_m", text="Real (m)")
        self.tree_orders.column("real_m", width=90, anchor="e")

        self.tree_orders.heading("source", text="Arquivo")
        self.tree_orders.column("source", width=220, anchor="w")

        self.tree_orders.heading("observacao", text="Observação")
        self.tree_orders.column("observacao", width=220, anchor="w")

        sb_orders = ttk.Scrollbar(self.tab_orders, orient="vertical", command=self.tree_orders.yview)
        self.tree_orders.configure(yscrollcommand=sb_orders.set)

        self.tree_orders.pack(side="left", fill="both", expand=True)
        sb_orders.pack(side="right", fill="y")

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

        # ------------------------
        # Status
        # ------------------------
        self.status = ttk.Label(self, text="Pronto.", style="Muted.TLabel")
        self.status.pack(side="bottom", fill="x", padx=22, pady=(0, 8), before=box_details)

        self.reload()

    # ------------------------
    # Actions
    # ------------------------
    def clear_filters(self) -> None:
        self.var_machine.set("")
        self.var_name_like.set("")
        self.var_order_like.set("")
        self.var_tipo.set("")
        self.var_limit.set("300")
        self.reload()

    def _refresh_tipo_options(self) -> None:
        try:
            tipos = load_distinct_tipos()
        except Exception:
            tipos = []
        self.cmb_tipo.configure(values=[""] + tipos)

    def reload_settings(self) -> None:
        """Chamado pela página Configurações após reclassificar os registros."""
        self.reload()

    def reload(self) -> None:
        self._refresh_tipo_options()

        limit = safe_int(self.var_limit.get(), default=300)
        machine = (self.var_machine.get() or "").strip() or None
        name_like = (self.var_name_like.get() or "").strip() or None
        order_like = (self.var_order_like.get() or "").strip() or None
        tipo = (self.var_tipo.get() or "").strip() or None

        try:
            rows = search_rolls(
                limit=limit,
                machine=machine,
                name_like=name_like,
                order_like=order_like,
                tipo=tipo,
            )
        except Exception as e:
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
            messagebox.showerror(
                "Editar rolo",
                f"Falha ao preparar os dados do rolo para edição.\n\n{traceback.format_exc()}",
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
        self.btn_export_order_context.configure(state="normal" if self._current_order_id else "disabled")

    def on_select_order_version(self, _evt=None) -> None:
        label = self.var_order_version.get()
        option = next((o for o in self._order_version_options if o["label"] == label), None)
        if option is None or self._current_roll_id is None:
            return
        self._render_orders_tree(self._current_roll_id, option["value"])
        self._render_roll_list(self._current_roll_id, option["value"])

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

        try:
            orders = load_roll_orders_for_version(roll_id, version_no)
        except Exception as e:
            self.status.configure(text=f"Falha ao carregar pedidos: {type(e).__name__}")
            return

        for idx, order in enumerate(orders):
            end_time = str(order.get("end_time", "") or "")
            document = str(order.get("document", "") or "")
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
            iid = str(order["id"]) if self._viewing_live_version else f"v{version_no}_{idx}"
            self.tree_orders.insert(
                "",
                "end",
                iid=iid,
                values=(
                    end_time,
                    document,
                    fabric,
                    tipo,
                    f"{float(height_mm):.1f}",
                    f"{float(vpos_mm):.1f}",
                    format_m(real_m, suffix=False),
                    source_path,
                    observacao,
                ),
            )

    def _render_roll_list(self, roll_id: int, version_no: Optional[int]) -> None:
        """Aba "Lista do rolo" — mesma visão da aba de mesmo nome na
        Operação: todos os itens (incluindo ESPAÇO) numa lista só, na
        ordem do comprovante (blocos na ordem de build_blocks, mais
        recente pro mais antigo dentro de cada bloco)."""
        self.tree_roll_list.delete(*self.tree_roll_list.get_children())

        try:
            module = load_roll_module(roll_id)
            summary = load_roll_summary(roll_id)
            orders = load_roll_orders_for_version(roll_id, version_no)
        except Exception as e:
            self.status.configure(text=f"Falha ao carregar lista do rolo: {type(e).__name__}")
            return

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
