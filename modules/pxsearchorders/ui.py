from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional

from .helpers import format_m, payload_summary, safe_int
from .repository import (
    load_roll_events,
    load_roll_orders,
    load_roll_summary,
    search_rolls,
)


class PXSearchOrdersUI(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self._current_roll_id: Optional[int] = None

        # ------------------------
        # Filtros
        # ------------------------
        filtros = ttk.LabelFrame(self, text="Filtros")
        filtros.pack(fill="x", padx=10, pady=(10, 8))

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

        ttk.Label(filtros, text="Limite").grid(row=0, column=6, sticky="w", padx=(0, 6), pady=8)
        self.var_limit = tk.StringVar(value="300")
        self.ent_limit = ttk.Entry(filtros, textvariable=self.var_limit, width=6)
        self.ent_limit.grid(row=0, column=7, sticky="w", padx=(0, 14), pady=8)

        ttk.Button(filtros, text="Recarregar", command=self.reload).grid(
            row=0, column=8, sticky="w", padx=(0, 8), pady=8
        )
        ttk.Button(filtros, text="Limpar filtros", command=self.clear_filters).grid(
            row=0, column=9, sticky="w", padx=(0, 10), pady=8
        )

        filtros.columnconfigure(10, weight=1)

        self.ent_name_like.bind("<Return>", lambda _e: self.reload())
        self.ent_order_like.bind("<Return>", lambda _e: self.reload())
        self.ent_limit.bind("<Return>", lambda _e: self.reload())

        # ------------------------
        # Lista de rolos
        # ------------------------
        box_rolls = ttk.LabelFrame(self, text="Rolos exportados")
        box_rolls.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        cols = ("id", "roll", "machine", "created", "total_m", "orders", "events")
        self.tree_rolls = ttk.Treeview(box_rolls, columns=cols, show="headings", height=10)

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

        sb_rolls = ttk.Scrollbar(box_rolls, orient="vertical", command=self.tree_rolls.yview)
        self.tree_rolls.configure(yscrollcommand=sb_rolls.set)

        self.tree_rolls.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        sb_rolls.pack(side="right", fill="y", padx=(0, 10), pady=10)

        self.tree_rolls.bind("<<TreeviewSelect>>", self.on_select_roll)
        self.tree_rolls.bind("<Double-1>", self.on_double_click_roll)

        # ------------------------
        # Detalhes
        # ------------------------
        box_details = ttk.LabelFrame(self, text="Detalhes do roll selecionado")
        box_details.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.nb = ttk.Notebook(box_details)
        self.nb.pack(fill="both", expand=True, padx=10, pady=10)

        # Aba Resumo
        self.tab_summary = ttk.Frame(self.nb)
        self.nb.add(self.tab_summary, text="Resumo")

        self.txt_summary = tk.Text(self.tab_summary, wrap="word", height=8)
        self.txt_summary.pack(fill="both", expand=True)
        self.txt_summary.configure(state="disabled")

        # Aba Pedidos
        self.tab_orders = ttk.Frame(self.nb)
        self.nb.add(self.tab_orders, text="Pedidos")

        order_cols = ("end_time", "document", "fabric", "height_mm", "vpos_mm", "real_m", "source")
        self.tree_orders = ttk.Treeview(self.tab_orders, columns=order_cols, show="headings", height=8)

        self.tree_orders.heading("end_time", text="EndTime")
        self.tree_orders.column("end_time", width=160, anchor="w")

        self.tree_orders.heading("document", text="Documento")
        self.tree_orders.column("document", width=420, anchor="w")

        self.tree_orders.heading("fabric", text="Tecido")
        self.tree_orders.column("fabric", width=140, anchor="w")

        self.tree_orders.heading("height_mm", text="HeightMM")
        self.tree_orders.column("height_mm", width=90, anchor="e")

        self.tree_orders.heading("vpos_mm", text="VPosMM")
        self.tree_orders.column("vpos_mm", width=90, anchor="e")

        self.tree_orders.heading("real_m", text="Real (m)")
        self.tree_orders.column("real_m", width=90, anchor="e")

        self.tree_orders.heading("source", text="Arquivo")
        self.tree_orders.column("source", width=220, anchor="w")

        sb_orders = ttk.Scrollbar(self.tab_orders, orient="vertical", command=self.tree_orders.yview)
        self.tree_orders.configure(yscrollcommand=sb_orders.set)

        self.tree_orders.pack(side="left", fill="both", expand=True)
        sb_orders.pack(side="right", fill="y")

        # Aba Eventos
        self.tab_events = ttk.Frame(self.nb)
        self.nb.add(self.tab_events, text="Eventos")

        ev_cols = ("created_at", "event_type", "summary")
        self.tree_events = ttk.Treeview(self.tab_events, columns=ev_cols, show="headings", height=8)

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
        self.status = ttk.Label(self, text="Pronto.")
        self.status.pack(fill="x", padx=10, pady=(0, 10))

        self.reload()

    # ------------------------
    # Actions
    # ------------------------
    def clear_filters(self) -> None:
        self.var_machine.set("")
        self.var_name_like.set("")
        self.var_order_like.set("")
        self.var_limit.set("300")
        self.reload()

    def reload(self) -> None:
        limit = safe_int(self.var_limit.get(), default=300)
        machine = (self.var_machine.get() or "").strip() or None
        name_like = (self.var_name_like.get() or "").strip() or None
        order_like = (self.var_order_like.get() or "").strip() or None

        try:
            rows = search_rolls(
                limit=limit,
                machine=machine,
                name_like=name_like,
                order_like=order_like,
            )
        except Exception as e:
            messagebox.showerror(
                "PXSearchOrders",
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
            except Exception:
                continue

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

    def on_select_roll(self, _evt=None) -> None:
        sel = self.tree_rolls.selection()
        if not sel:
            return

        roll_id = int(sel[0])
        self._current_roll_id = roll_id

        self._load_summary(roll_id)
        self._load_orders(roll_id)
        self._load_events(roll_id)

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
        self.tree_events.delete(*self.tree_events.get_children())

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

        self._set_summary_text("\n".join(lines))

    def _set_summary_text(self, text: str) -> None:
        self.txt_summary.configure(state="normal")
        self.txt_summary.delete("1.0", "end")
        self.txt_summary.insert("1.0", text)
        self.txt_summary.configure(state="disabled")

    def _load_orders(self, roll_id: int) -> None:
        self.tree_orders.delete(*self.tree_orders.get_children())

        try:
            orders = load_roll_orders(roll_id)
        except Exception as e:
            self.status.configure(text=f"Falha ao carregar pedidos: {type(e).__name__}")
            return

        for order in orders:
            end_time = str(order.get("end_time", "") or "")
            document = str(order.get("document", "") or "")
            fabric = str(order.get("fabric", "") or "")
            height_mm = order.get("height_mm", 0) or 0
            vpos_mm = order.get("vpos_mm", 0) or 0
            real_m = order.get("real_m", 0) or 0
            source_path = str(order.get("source_path", "") or "")

            try:
                source_path = Path(source_path).name
            except Exception:
                pass

            self.tree_orders.insert(
                "",
                "end",
                values=(
                    end_time,
                    document,
                    fabric,
                    f"{float(height_mm):.1f}",
                    f"{float(vpos_mm):.1f}",
                    format_m(real_m, suffix=False),
                    source_path,
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