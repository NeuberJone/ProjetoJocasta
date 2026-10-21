from __future__ import annotations

import os
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

from core.fabrics import load_fabrics
from core.format import fmt_m
from core.operators import normalize_operators, operator_name_for_code
from core.ui import card, dialog_header, info_banner, page_heading
from core.printers import find_printer_by_display_name
from core.print_types import (
    DEFAULT_RULES,
    DEFAULT_SUBTYPES,
    all_type_options,
    classify_document,
    normalize_rules,
    pedido_override_for_type,
    warn_duplicate_for_type,
)
from core.printlogs_db import (
    OrderRow,
    find_pedido_fabric_rolls,
    next_roll_sequence,
    save_export_transactional,
    update_roll_orders,
)
from core.version import APP_VERSION

from .config import load_cfg
from .exporters import export_pdf, mirror_and_normal_to_jpg_scaled, pdf_all_pages_to_jpg_scaled
from .m1_check import STATUS_ERROR as M1_STATUS_ERROR
from .m1_check import STATUS_LABELS as M1_STATUS_LABELS
from .m1_check import STATUS_UNKNOWN_FORMAT as M1_STATUS_UNKNOWN_FORMAT
from .m1_check import check_job as m1_check_job
from .m1_check import clear_cache as m1_clear_cache
from .models import Block, Job, PedidoSummary
from .parser import (
    build_blocks,
    build_pedido_summary,
    fabric_from_document,
    normalize_space_entries,
    operator_code_from_document,
    parse_log_txt,
    pedido_from_document,
)
from .paths import MODULE_NAME, jpg_dir, pdf_dir, sanitize_filename, temp_dir, versioned_path

try:
    from tkinterdnd2 import DND_FILES  # type: ignore
    _HAS_DND = True
except Exception:
    DND_FILES = None
    _HAS_DND = False


def _distinct_documents(jobs: List[Job]) -> List[str]:
    """Lista arquivos de origem distintos (nome do documento), com
    contagem quando repetido — usada pra mostrar ao operador QUAIS
    arquivos formam um grupo antes de renomear tecido/pedido, já que um
    nome tipo "DESCONHECIDO" pode juntar vários arquivos com erro de
    digitação diferentes."""
    from collections import Counter

    counts = Counter(j.document for j in jobs)
    return [f"{doc}  ({n}x)" if n > 1 else doc for doc, n in sorted(counts.items())]


class PXPrintLogsUI(ttk.Frame):
    def __init__(self, parent, *, preload: Optional[dict] = None):
        super().__init__(parent)

        self.mcfg = load_cfg()
        self.machine: Optional[str] = None
        self.Jobs: List[Job] = []
        self.blocks: List[Block] = []
        self.pedidos: List[PedidoSummary] = []
        self._detail_jobs: List[Job] = []
        self.edit_roll_id: Optional[int] = None

        # Container rolável: em telas pequenas o conteúdo (em especial o
        # painel "Pedidos no rolo", no fim) não cabia na altura da janela.
        canvas = tk.Canvas(self, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        body = ttk.Frame(canvas, padding=(28, 22, 28, 18))
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")

        def _on_body_configure(_evt=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(evt):
            canvas.itemconfig(body_window, width=evt.width)

        body.bind("<Configure>", _on_body_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_mousewheel(_evt=None):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(_evt=None):
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", _bind_mousewheel)
        canvas.bind("<Leave>", _unbind_mousewheel)

        page_heading(body, "Confira o que foi impresso",
                     "Importe os logs reais e gere o comprovante do rolo.",
                     action=self.on_import_files, action_text="⇧ Importar logs").pack(
                     fill="x", pady=(0, 14)
                     )
        info_banner(
            body,
            "A ordem do rolo mostra o último arquivo impresso primeiro. "
            "Avanços aparecem como ESPAÇO, separados da metragem real.",
        ).pack(fill="x", pady=(0, 14))

        top = card(body, "Rolo", padding=12)
        top.pack(fill="x", pady=(0, 14))
        top.columnconfigure(4, weight=1)

        ttk.Label(top, text="Nome do rolo").grid(row=0, column=0, sticky="w", padx=(10, 4))
        self.var_roll = tk.StringVar(value="")
        self.ent_roll = ttk.Entry(top, textvariable=self.var_roll, width=24)
        self.ent_roll.grid(row=0, column=1, padx=(0, 6), sticky="w")

        ttk.Button(top, text="Atualizar nome", command=self.on_refresh_roll_name).grid(
            row=0, column=2, padx=(0, 16), sticky="w"
        )

        self.lbl_machine = ttk.Label(top, text="Máquina do lote: (não definida)")
        self.lbl_machine.grid(row=0, column=3, sticky="w")

        more_menu = tk.Menu(self, tearoff=0)
        more_menu.add_command(label="Importar pasta…", command=self.on_import_folder)
        more_menu.add_separator()
        more_menu.add_command(label="Abrir pasta PDF (comprovantes)", command=self.open_pdf_folder)
        more_menu.add_command(label="Abrir pasta JPG (operação)", command=self.open_jpg_folder)
        more_menu.add_separator()
        more_menu.add_command(label="Limpar", command=self.on_clear)
        ttk.Menubutton(top, text="Mais ações ▾", menu=more_menu).grid(
            row=0, column=5, sticky="e", padx=(0, 10)
        )

        ttk.Button(
            top, text="▶ Exportar…", style="Accent.TButton", command=self.open_export_dialog,
        ).grid(row=0, column=6, sticky="e", padx=(0, 10))

        # Modo do PDF e JPG espelhado são padrões definidos em Configurações;
        # aqui (e no diálogo de exportação) só mostramos um resumo.
        self.var_mode = tk.StringVar(value=self.mcfg.get("report_mode_default", "full"))
        self.var_jpg_mode = tk.StringVar(value=self.mcfg.get("mirror_jpg_width_mode", "17"))
        self.var_jpg_custom = tk.StringVar(
            value=str(self.mcfg.get("mirror_jpg_width_cm_custom", 17.0))
        )
        self.var_export_dir = tk.StringVar(value=str(pdf_dir(datetime.now())))
        self.var_use_printer_jpg_path = tk.BooleanVar(
            value=bool(self.mcfg.get("use_printer_jpg_path_default", False))
        )

        self.drop_label = ttk.Label(
            top, text="Arraste e solte arquivos .txt aqui para importar", style="Muted.TLabel"
        )
        self.drop_label.grid(row=1, column=0, columnspan=6, sticky="w", padx=10, pady=(8, 2))

        if _HAS_DND:
            try:
                self.drop_label.drop_target_register(DND_FILES)  # type: ignore
                self.drop_label.dnd_bind("<<Drop>>", self.on_drop_files)  # type: ignore
            except Exception:
                pass
        else:
            self.drop_label.configure(
                text="Drag & Drop indisponível (tkinterdnd2 não carregou). Use \"Importar logs\"."
            )

        self.var_fixed_summary = tk.StringVar()
        ttk.Label(
            top, textvariable=self.var_fixed_summary, style="Muted.TLabel", justify="left"
        ).grid(row=2, column=0, columnspan=6, sticky="w", padx=10, pady=(2, 2))
        self._update_fixed_summary()

        self.var_edit_banner = tk.StringVar(value="")
        self.lbl_edit_banner = ttk.Label(
            top, textvariable=self.var_edit_banner, foreground="#8a4b00"
        )
        self.lbl_edit_banner.grid(row=3, column=0, columnspan=6, sticky="w", padx=10, pady=(4, 6))

        ops_tabs = ttk.Notebook(body)
        ops_tabs.pack(fill="both", expand=True, pady=(0, 14))
        details_tab = ttk.Frame(ops_tabs, padding=10)
        blocks_tab = ttk.Frame(ops_tabs, padding=10)
        orders_tab = ttk.Frame(ops_tabs, padding=10)
        ops_tabs.add(blocks_tab, text="Ordem do rolo")
        ops_tabs.add(details_tab, text="Detalhes do bloco")
        ops_tabs.add(orders_tab, text="Pedidos no rolo")

        details = card(details_tab, "Detalhes do bloco selecionado", padding=10)
        details.pack(fill="both", expand=True)

        self.var_detail_title = tk.StringVar(value="Selecione um tecido na lista abaixo...")
        ttk.Label(details, textvariable=self.var_detail_title).pack(
            anchor="w", padx=10, pady=(8, 6)
        )

        self.tree_Jobs = ttk.Treeview(
            details,
            columns=("end", "doc", "pedido", "tipo", "h", "v", "real_m", "m1", "obs"),
            show="headings",
            height=6,
        )
        for col, txt, w in [
            ("end", "EndTime", 140),
            ("doc", "Documento", 300),
            ("pedido", "Pedido", 150),
            ("tipo", "Tipo", 110),
            ("h", "HeightMM", 90),
            ("v", "VPosMM", 90),
            ("real_m", "Real (m)", 90),
            ("m1", "Impressão (log adicional)", 200),
            ("obs", "Observação", 200),
        ]:
            self.tree_Jobs.heading(col, text=txt)
            self.tree_Jobs.column(col, width=w, anchor="w")

        sbj = ttk.Scrollbar(details, orient="vertical", command=self.tree_Jobs.yview)
        self.tree_Jobs.configure(yscrollcommand=sbj.set)
        self.tree_Jobs.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        self.tree_Jobs.bind("<Double-1>", self.on_edit_job_observacao)
        self.tree_Jobs.bind("<Button-3>", self._show_job_context_menu)
        sbj.pack(side="right", fill="y", padx=(0, 10), pady=(0, 10))

        blocks_box = card(
            blocks_tab, "Último impresso primeiro · duplo clique ou botão direito para editar o tecido",
            padding=10,
        )
        blocks_box.pack(fill="both", expand=True)

        self.tree_blocks = ttk.Treeview(
            blocks_box,
            columns=("#", "fabric", "total_m", "Jobs", "last"),
            show="headings",
            height=8,
        )
        for col, txt, w, anchor in [
            ("#", "#", 40, "w"),
            ("fabric", "Tecido", 180, "w"),
            ("total_m", "Total (m)", 110, "e"),
            ("Jobs", "Qtd Pedidos", 90, "e"),
            ("last", "Último EndTime", 160, "w"),
        ]:
            self.tree_blocks.heading(col, text=txt)
            self.tree_blocks.column(col, width=w, anchor=anchor)

        sbb = ttk.Scrollbar(blocks_box, orient="vertical", command=self.tree_blocks.yview)
        self.tree_blocks.configure(yscrollcommand=sbb.set)
        self.tree_blocks.pack(side="left", fill="both", expand=True)
        sbb.pack(side="right", fill="y")

        self.tree_blocks.bind("<<TreeviewSelect>>", self.on_select_block)
        self.tree_blocks.bind("<Double-1>", self.on_edit_fabric)
        self.tree_blocks.bind("<Button-3>", self._show_block_context_menu)

        pedidos_box = card(
            orders_tab, "Duplo clique ou botão direito para editar o pedido/tipo", padding=10
        )
        pedidos_box.pack(fill="both", expand=True)

        self.tree_pedidos = ttk.Treeview(
            pedidos_box,
            columns=("#", "pedido", "tipo", "total_m", "Jobs", "last"),
            show="headings",
            height=8,
        )
        for col, txt, w, anchor in [
            ("#", "#", 40, "w"),
            ("pedido", "Pedido", 200, "w"),
            ("tipo", "Tipo", 110, "w"),
            ("total_m", "Total (m)", 110, "e"),
            ("Jobs", "Qtd Peças", 90, "e"),
            ("last", "Último EndTime", 160, "w"),
        ]:
            self.tree_pedidos.heading(col, text=txt)
            self.tree_pedidos.column(col, width=w, anchor=anchor)

        sbp = ttk.Scrollbar(pedidos_box, orient="vertical", command=self.tree_pedidos.yview)
        self.tree_pedidos.configure(yscrollcommand=sbp.set)
        self.tree_pedidos.pack(side="left", fill="both", expand=True)
        sbp.pack(side="right", fill="y")

        self.tree_pedidos.bind("<Double-1>", self.on_edit_pedido)
        self.tree_pedidos.bind("<Button-3>", self._show_pedido_context_menu)

        self.status = ttk.Label(body, text="Pronto.")
        self.status.pack(fill="x", pady=(0, 0))

        self._ensure_export_dir()

        if preload:
            self._apply_preload(preload)

    def _apply_preload(self, preload: dict) -> None:
        self.edit_roll_id = int(preload["edit_roll_id"])
        self.machine = str(preload.get("machine") or "") or None
        self.var_roll.set(str(preload.get("roll_name") or ""))
        self.Jobs = list(preload.get("jobs") or [])

        if self.machine:
            self.lbl_machine.configure(text=f"Máquina do lote: {self.machine}")

        self.blocks = build_blocks(self.Jobs, self.machine or "")
        self.pedidos = build_pedido_summary(self.Jobs)
        self.refresh_blocks()
        self.refresh_pedidos()
        self.clear_details()

        self.var_edit_banner.set(
            f"✏ Editando rolo já registrado (ID {self.edit_roll_id}) — ao exportar, "
            "este rolo será ATUALIZADO (não cria um novo registro)."
        )

        self.status.configure(
            text=f"Rolo carregado para edição: {len(self.Jobs)} log(s) já registrados."
        )

    # --------------------------
    # Config helpers
    # --------------------------
    def _ensure_export_dir(self):
        self.var_export_dir.set(str(pdf_dir(datetime.now())))

    def open_pdf_folder(self):
        try:
            folder = pdf_dir(datetime.now())
            os.startfile(str(folder))
        except Exception:
            messagebox.showerror("Erro", "Não foi possível abrir a pasta de PDFs.")

    def open_jpg_folder(self):
        try:
            folder = jpg_dir(datetime.now())
            os.startfile(str(folder))
        except Exception:
            messagebox.showerror("Erro", "Não foi possível abrir a pasta de JPGs.")

    def _get_mirror_target_cm(self) -> float:
        mode = (self.var_jpg_mode.get() or "").strip()
        if mode in ("17", "21"):
            return float(mode)

        s = (self.var_jpg_custom.get() or "").replace(",", ".").strip()
        try:
            value = float(s)
        except Exception:
            raise ValueError("Largura personalizada inválida.")

        if value < 8 or value > 40:
            raise ValueError("Use entre 8 cm e 40 cm.")
        return value

    # --------------------------
    # Machine / naming
    # --------------------------
    def ask_machine(self) -> Optional[str]:
        win = tk.Toplevel(self)
        win.title("Selecionar máquina")
        win.resizable(False, False)
        win.transient(self.winfo_toplevel())
        win.grab_set()
        dialog_header(win, "Selecionar máquina", "Escolha a origem dos logs importados.").pack(
            fill="x", padx=12, pady=(12, 0)
        )

        ttk.Label(win, text="Esses logs são de qual máquina?").pack(
            padx=12, pady=(12, 6), anchor="w"
        )

        from core.printers import load_printers

        machines = [p.display_name for p in load_printers()] or ["M1", "M2"]

        var = tk.StringVar(value=machines[0])
        frm = ttk.Frame(win)
        frm.pack(padx=12, pady=6, anchor="w")
        for machine in machines:
            ttk.Radiobutton(frm, text=machine, value=machine, variable=var).pack(anchor="w")

        out = {"val": None}

        def ok():
            out["val"] = var.get()
            win.destroy()

        def cancel():
            out["val"] = None
            win.destroy()

        btn = ttk.Frame(win)
        btn.pack(padx=12, pady=(6, 12), fill="x")
        ttk.Button(btn, text="OK", command=ok).pack(side="right", padx=4)
        ttk.Button(btn, text="Cancelar", command=cancel).pack(side="right", padx=4)

        win.wait_window()
        return out["val"]

    def _auto_roll_name(self) -> str:
        machine = self.machine or "M?"
        now = datetime.now()
        # Número sequencial atômico (banco compartilhado) em vez do horário —
        # evita duplicar entre computadores diferentes. Se não conseguir
        # (ex.: pasta de rede fora do ar), propaga o erro — não cai de volta
        # pro horário, que reintroduziria o risco de duplicata.
        seq = next_roll_sequence()
        return f"{machine}_{now.strftime('%d-%m-%Y')}_{seq:04d}"

    def on_refresh_roll_name(self):
        if not self.machine:
            messagebox.showwarning("Sem máquina", "Importe logs primeiro para definir a máquina.")
            return
        try:
            self.var_roll.set(self._auto_roll_name())
        except Exception as e:
            messagebox.showerror(
                "Número sequencial",
                f"Não foi possível gerar o nome do rolo.\n\n{type(e).__name__}: {e}",
            )

    def _get_roll_name(self) -> str:
        name = self.var_roll.get().strip()
        if not name:
            name = self._auto_roll_name()
            self.var_roll.set(name)
        return sanitize_filename(name)

    # --------------------------
    # Drag & drop
    # --------------------------
    def on_drop_files(self, event):
        raw = getattr(event, "data", "") or ""
        files = self._split_dnd_files(raw)
        self._import_paths(files)

    def _split_dnd_files(self, data: str) -> List[str]:
        out: List[str] = []
        buff = ""
        in_brace = False

        for ch in data:
            if ch == "{":
                in_brace = True
                buff = ""
            elif ch == "}":
                in_brace = False
                if buff:
                    out.append(buff)
                buff = ""
            elif ch == " " and not in_brace:
                if buff:
                    out.append(buff)
                    buff = ""
            else:
                buff += ch

        if buff.strip():
            out.append(buff.strip())

        return [p.strip() for p in out if p.strip()]

    # --------------------------
    # Import
    # --------------------------
    def on_import_files(self):
        paths = filedialog.askopenfilenames(
            title="Selecionar logs .txt",
            filetypes=[("Logs TXT", "*.txt")],
        )
        self._import_paths(list(paths))

    def on_import_folder(self):
        folder = filedialog.askdirectory(title="Selecionar pasta com logs .txt")
        if not folder:
            return
        p = Path(folder)
        paths = [str(x) for x in p.glob("*.txt")]
        self._import_paths(paths)

    def _import_paths(self, paths: List[str]):
        if not paths:
            return

        txts = [p for p in paths if p.lower().endswith(".txt")]
        if not txts:
            messagebox.showwarning("Sem .txt", "Solte/selecione apenas arquivos .txt.")
            return

        if self.machine:
            machine = self.machine
        else:
            machine = self.ask_machine()
            if not machine:
                self.status.configure(text="Importação cancelada.")
                return

            self.machine = machine
            self.lbl_machine.configure(text=f"Máquina do lote: {machine}")

            if not self.var_roll.get().strip():
                try:
                    self.var_roll.set(self._auto_roll_name())
                except Exception as e:
                    messagebox.showerror(
                        "Número sequencial",
                        f"Não foi possível gerar o nome do rolo.\n\n{type(e).__name__}: {e}",
                    )

        parsed: List[Job] = []
        skipped_invalid = 0

        existing_src = {j.src_file for j in self.Jobs} if self.Jobs else set()

        space_entries = normalize_space_entries(self.mcfg.get("space_filenames", []))
        type_rules = normalize_rules(self.mcfg.get("print_type_rules", DEFAULT_RULES))
        operators = normalize_operators(self.mcfg.get("operators", []))
        fabrics_map = load_fabrics()

        for path in txts:
            path_full = str(path)
            if path_full in existing_src:
                continue

            job = parse_log_txt(
                path_full,
                space_entries=space_entries,
                type_rules=type_rules,
                operators=operators,
                fabrics_map=fabrics_map,
            )
            if not job:
                skipped_invalid += 1
                continue

            if job.height_mm <= 0:
                skipped_invalid += 1
                continue

            correct_real_m = job.height_mm / 1000.0
            if abs(job.real_m - correct_real_m) > 0.001:
                skipped_invalid += 1
                continue

            parsed.append(job)
            existing_src.add(job.src_file)

        if not parsed and not self.Jobs:
            messagebox.showerror("Falha", "Nenhum log válido encontrado.")
            return

        printer = find_printer_by_display_name(machine)
        sec_enabled = bool(printer and printer.secondary_log_enabled)
        sec_alerts = 0
        sec_unknown_format = False
        if sec_enabled and parsed:
            sec_folder = str(printer.secondary_log_folder or "").strip()
            for job in parsed:
                if job.is_gap:
                    continue
                res = m1_check_job(folder=sec_folder, end_time=job.end_time)
                job.m1_status = res.status
                job.m1_detail = res.detail
                if res.status == M1_STATUS_ERROR:
                    sec_alerts += 1
                elif res.status == M1_STATUS_UNKNOWN_FORMAT:
                    sec_unknown_format = True

        if parsed:
            self.Jobs.extend(parsed)

        self.blocks = build_blocks(self.Jobs, machine)
        self.pedidos = build_pedido_summary(self.Jobs)

        self.refresh_blocks()
        self.refresh_pedidos()
        self.clear_details()

        extra = f" | Ignorados: {skipped_invalid}" if skipped_invalid else ""
        added = f" | +{len(parsed)} novos" if parsed else " | +0 novos"
        sec_extra = ""
        if sec_enabled and parsed:
            sec_folder = str(printer.secondary_log_folder or "").strip()
            if not sec_folder:
                sec_extra = " | Log adicional: configure a pasta em Gerenciar Impressoras para verificar a impressão"
            elif sec_unknown_format:
                sec_extra = (
                    " | Log adicional: ⚠ a pasta configurada não parece ser do log esperado "
                    "— confira em Gerenciar Impressoras"
                )
            elif sec_alerts:
                sec_extra = f" | Log adicional: ⚠ {sec_alerts} log(s) com possível erro de impressão — veja \"Detalhes do bloco\""
        self.status.configure(
            text=(
                f"Importado total: {len(self.Jobs)} logs{added} | "
                f"Blocos: {len(self.blocks)} | Máquina: {machine}{extra}{sec_extra}"
            )
        )

        self._warn_duplicates_on_import()

    # --------------------------
    # Clear / refresh
    # --------------------------
    def on_clear(self):
        self.machine = None
        self.Jobs = []
        self.blocks = []
        self.pedidos = []
        self.var_roll.set("")
        self.lbl_machine.configure(text="Máquina do lote: (não definida)")
        self.tree_blocks.delete(*self.tree_blocks.get_children())
        self.tree_pedidos.delete(*self.tree_pedidos.get_children())
        self.tree_Jobs.delete(*self.tree_Jobs.get_children())
        self.var_detail_title.set("Selecione um tecido na lista abaixo...")
        self.status.configure(text="Limpo.")

    def refresh_blocks(self):
        self.tree_blocks.delete(*self.tree_blocks.get_children())
        for idx, block in enumerate(self.blocks, start=1):
            self.tree_blocks.insert(
                "",
                "end",
                iid=str(idx - 1),
                values=(
                    idx,
                    block.fabric,
                    fmt_m(block.total_m),
                    block.job_count,
                    block.newest_end.strftime("%d/%m/%Y %H:%M:%S"),
                ),
            )

    def refresh_pedidos(self):
        self.tree_pedidos.delete(*self.tree_pedidos.get_children())
        for idx, pedido in enumerate(self.pedidos, start=1):
            self.tree_pedidos.insert(
                "",
                "end",
                iid=str(idx - 1),
                values=(
                    idx,
                    pedido.pedido,
                    pedido.tipo,
                    fmt_m(pedido.total_m),
                    pedido.job_count,
                    pedido.newest_end.strftime("%d/%m/%Y %H:%M:%S"),
                ),
            )

    def clear_details(self):
        self.var_detail_title.set("Selecione um tecido na lista abaixo...")
        self.tree_Jobs.delete(*self.tree_Jobs.get_children())
        self._detail_jobs = []

    def on_select_block(self, _evt=None):
        sel = self.tree_blocks.selection()
        if not sel:
            return

        block_index = int(sel[0])
        if block_index < 0 or block_index >= len(self.blocks):
            return

        block = self.blocks[block_index]

        title = (
            f"Tecido: {block.fabric} | Máquina: {block.machine} | Pedidos: {block.job_count} | "
            f"Total: {fmt_m(block.total_m)} | "
            f"{block.newest_end:%d/%m/%Y %H:%M:%S} → {block.oldest_end:%d/%m/%Y %H:%M:%S}"
        )
        self.var_detail_title.set(title)

        self.tree_Jobs.delete(*self.tree_Jobs.get_children())
        self._detail_jobs = sorted(block.Jobs, key=lambda item: item.end_time, reverse=True)
        for idx, job in enumerate(self._detail_jobs):
            doc_txt = f"— {job.fabric or 'ESPAÇO'} —" if job.is_gap else job.document
            pedido_txt = "" if job.is_gap else job.pedido
            tipo_txt = "" if job.is_gap else job.tipo
            m1_txt = M1_STATUS_LABELS.get(job.m1_status, "") if job.m1_status else ""
            obs_txt = (job.observacao or "").splitlines()[0] if job.observacao else ""
            if job.observacao:
                obs_txt = f"📝 {obs_txt}"
            self.tree_Jobs.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    job.end_time.strftime("%d/%m/%Y %H:%M:%S"),
                    doc_txt,
                    pedido_txt,
                    tipo_txt,
                    f"{job.height_mm:.1f}",
                    f"{job.vpos_mm:.1f}",
                    fmt_m(job.real_m, suffix=False),
                    m1_txt,
                    obs_txt,
                ),
            )

    def _get_detail_job(self, iid: Optional[str]) -> Optional[Job]:
        if not iid:
            return None
        try:
            idx = int(iid)
        except Exception:
            return None
        if 0 <= idx < len(getattr(self, "_detail_jobs", [])):
            return self._detail_jobs[idx]
        return None

    def _show_job_context_menu(self, event):
        iid = self.tree_Jobs.identify_row(event.y)
        if not iid:
            return
        self.tree_Jobs.selection_set(iid)

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="Observação…", command=lambda: self._open_observacao_dialog(iid)
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def on_edit_job_observacao(self, event=None):
        iid = self.tree_Jobs.identify_row(event.y) if event is not None else (
            self.tree_Jobs.selection()[0] if self.tree_Jobs.selection() else None
        )
        if iid:
            self._open_observacao_dialog(iid)

    def _open_observacao_dialog(self, iid: str) -> None:
        job = self._get_detail_job(iid)
        if job is None:
            return

        dlg = tk.Toplevel(self)
        dlg.title("Observação")
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)
        dialog_header(
            frm, "Observação",
            f"{'ESPAÇO' if job.is_gap else job.document} — anotação livre sobre este item "
            "(ex.: \"o papel manchou aqui\"). Fica salva junto do rolo.",
        ).pack(fill="x", pady=(0, 8))

        txt = tk.Text(frm, width=56, height=6, wrap="word")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", job.observacao or "")
        txt.focus_set()

        def on_save():
            job.observacao = txt.get("1.0", "end-1c").strip()
            dlg.destroy()
            self.on_select_block()

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Cancelar", command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="Salvar", command=on_save).pack(side="right", padx=(0, 8))

    def _show_block_context_menu(self, event):
        iid = self.tree_blocks.identify_row(event.y)
        if iid:
            self.tree_blocks.selection_set(iid)

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Editar tecido", command=self.on_edit_fabric)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _show_pedido_context_menu(self, event):
        iid = self.tree_pedidos.identify_row(event.y)
        if iid:
            self.tree_pedidos.selection_set(iid)

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Editar pedido", command=self.on_edit_pedido)
        menu.add_command(label="Editar tipo", command=self.on_edit_tipo)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _ask_rename_dialog(
        self, *, title: str, field_label: str, initial: str, documents: List[str]
    ) -> Optional[str]:
        """Diálogo de renomear com a lista dos arquivos de origem do grupo
        visível junto do campo — pra saber a qual arquivo um nome como
        "DESCONHECIDO" se refere antes de corrigir."""
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)
        dialog_header(
            frm, title, f'Arquivo(s) de origem deste grupo ("{initial}"):'
        ).pack(fill="x", pady=(0, 6))

        list_frame = ttk.Frame(frm)
        list_frame.pack(fill="both", expand=True)
        lb = tk.Listbox(list_frame, width=60, height=min(8, max(3, len(documents))))
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        for doc in documents:
            lb.insert("end", doc)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        ttk.Label(frm, text=field_label).pack(anchor="w", pady=(10, 2))
        var = tk.StringVar(value=initial)
        entry = ttk.Entry(frm, textvariable=var, width=60)
        entry.pack(fill="x")
        entry.focus_set()
        entry.select_range(0, "end")

        out: Dict[str, Optional[str]] = {"val": None}

        def ok(_evt=None):
            out["val"] = var.get()
            dlg.destroy()

        def cancel(_evt=None):
            out["val"] = None
            dlg.destroy()

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Cancelar", command=cancel).pack(side="right")
        ttk.Button(btns, text="Salvar", command=ok).pack(side="right", padx=(0, 8))

        entry.bind("<Return>", ok)
        dlg.bind("<Escape>", cancel)

        dlg.wait_window()
        return out["val"]

    def on_edit_fabric(self, _evt=None):
        sel = self.tree_blocks.selection()
        if not sel:
            messagebox.showwarning(
                "Nenhum tecido selecionado", "Selecione um tecido na lista para editar."
            )
            return

        block_index = int(sel[0])
        if block_index < 0 or block_index >= len(self.blocks):
            return

        block = self.blocks[block_index]

        new_name = self._ask_rename_dialog(
            title="Editar tecido",
            field_label="Novo nome do tecido:",
            initial=block.fabric,
            documents=_distinct_documents(block.Jobs),
        )
        if new_name is None:
            return

        new_name = new_name.strip().upper()
        if not new_name:
            messagebox.showwarning("Nome inválido", "O nome do tecido não pode ficar vazio.")
            return

        if new_name == block.fabric:
            return

        for job in block.Jobs:
            job.fabric = new_name
            job.fabric_manual = True

        self.blocks = build_blocks(self.Jobs, self.machine)
        self.refresh_blocks()
        self.clear_details()
        self.status.configure(
            text=self.status.cget("text") + f" | Tecido renomeado para '{new_name}'"
        )

    def on_edit_pedido(self, _evt=None):
        sel = self.tree_pedidos.selection()
        if not sel:
            messagebox.showwarning(
                "Nenhum pedido selecionado", "Selecione um pedido na lista para editar."
            )
            return

        pedido_index = int(sel[0])
        if pedido_index < 0 or pedido_index >= len(self.pedidos):
            return

        pedido = self.pedidos[pedido_index]

        jobs_in_pedido = [j for j in self.Jobs if j.pedido == pedido.pedido]
        new_name = self._ask_rename_dialog(
            title="Editar pedido",
            field_label="Novo nome do pedido:",
            initial=pedido.pedido,
            documents=_distinct_documents(jobs_in_pedido),
        )
        if new_name is None:
            return

        new_name = new_name.strip()
        if not new_name:
            messagebox.showwarning("Nome inválido", "O nome do pedido não pode ficar vazio.")
            return

        if new_name == pedido.pedido:
            return

        for job in self.Jobs:
            if job.pedido == pedido.pedido:
                job.pedido = new_name
                job.pedido_manual = True

        self.pedidos = build_pedido_summary(self.Jobs)
        self.refresh_pedidos()
        self.on_select_block()
        self.status.configure(
            text=self.status.cget("text") + f" | Pedido renomeado para '{new_name}'"
        )

    # --------------------------
    # Tipos de impressão (Pedido / Reposição / Fora do padrão...)
    # --------------------------
    def _ask_tipo(self, *, initial: str, options: List[str]) -> Optional[str]:
        win = tk.Toplevel(self)
        win.title("Editar tipo")
        win.resizable(False, False)
        win.transient(self.winfo_toplevel())
        win.grab_set()
        dialog_header(win, "Editar tipo", "Escolha ou digite o tipo deste pedido.").pack(
            fill="x", padx=12, pady=(12, 0)
        )

        ttk.Label(win, text="Tipo:").pack(padx=12, pady=(12, 4), anchor="w")
        var = tk.StringVar(value=initial)
        cmb = ttk.Combobox(win, textvariable=var, values=options, width=30)
        cmb.pack(padx=12, pady=(0, 12), anchor="w")

        out: Dict[str, Optional[str]] = {"val": None}

        def ok():
            val = var.get().strip()
            if not val:
                messagebox.showwarning("Editar tipo", "Informe um tipo.")
                return
            out["val"] = val
            win.destroy()

        def cancel():
            out["val"] = None
            win.destroy()

        btn = ttk.Frame(win)
        btn.pack(padx=12, pady=(0, 12), fill="x")
        ttk.Button(btn, text="OK", command=ok).pack(side="right", padx=4)
        ttk.Button(btn, text="Cancelar", command=cancel).pack(side="right", padx=4)

        win.wait_window()
        return out["val"]

    def on_edit_tipo(self, _evt=None):
        sel = self.tree_pedidos.selection()
        if not sel:
            messagebox.showwarning(
                "Nenhum pedido selecionado", "Selecione um pedido na lista para editar."
            )
            return

        pedido_index = int(sel[0])
        if pedido_index < 0 or pedido_index >= len(self.pedidos):
            return

        pedido = self.pedidos[pedido_index]

        options = all_type_options(
            self.mcfg.get("print_type_rules", DEFAULT_RULES),
            self.mcfg.get("print_type_subtypes", DEFAULT_SUBTYPES),
        )
        new_tipo = self._ask_tipo(initial=pedido.tipo, options=options)
        if new_tipo is None or new_tipo == pedido.tipo:
            return

        for job in self.Jobs:
            if job.pedido == pedido.pedido:
                job.tipo = new_tipo
                job.tipo_manual = True

        self.pedidos = build_pedido_summary(self.Jobs)
        self.refresh_pedidos()
        self.on_select_block()
        self.status.configure(
            text=self.status.cget("text") + f" | Tipo definido como '{new_tipo}'"
        )

    def reload_settings(self) -> None:
        """Chamado pela página Configurações: relê padrões, arquivos de espaço,
        regras de tipo e cadastro de tecidos, e reclassifica os logs abertos
        (exceto tipos/tecidos definidos à mão)."""
        self.mcfg = load_cfg()
        m1_clear_cache()
        self.var_mode.set(self.mcfg.get("report_mode_default", "full"))
        self.var_jpg_mode.set(self.mcfg.get("mirror_jpg_width_mode", "17"))
        self.var_jpg_custom.set(str(self.mcfg.get("mirror_jpg_width_cm_custom", 17.0)))
        self.var_use_printer_jpg_path.set(bool(self.mcfg.get("use_printer_jpg_path_default", False)))
        self._update_fixed_summary()

        rules = normalize_rules(self.mcfg.get("print_type_rules", DEFAULT_RULES))
        operators = normalize_operators(self.mcfg.get("operators", []))
        fabrics_map = load_fabrics()
        fabric_changed = False
        for job in self.Jobs:
            if job.is_gap:
                continue
            if not job.tipo_manual:
                job.tipo = classify_document(job.document, rules)
            job.operador = operator_name_for_code(operator_code_from_document(job.document), operators)
            if not job.fabric_manual:
                new_fabric = fabric_from_document(job.document, fabrics_map)
                if new_fabric != job.fabric:
                    job.fabric = new_fabric
                    fabric_changed = True
            if not job.pedido_manual:
                pedido_fixed = pedido_override_for_type(job.tipo, rules)
                job.pedido = pedido_fixed if pedido_fixed is not None else pedido_from_document(job.document)

        if fabric_changed:
            self.blocks = build_blocks(self.Jobs, self.machine or "")
            self.refresh_blocks()

        self.pedidos = build_pedido_summary(self.Jobs)
        self.refresh_pedidos()
        self.on_select_block()

    def _update_fixed_summary(self) -> None:
        """Resumo somente leitura do Modo do PDF e JPG espelhado — os valores
        em si são padrões definidos em Configurações."""
        mode_txt = "Completo" if self.var_mode.get() == "full" else "Resumido"
        jpg_mode = self.var_jpg_mode.get()
        if jpg_mode == "custom":
            jpg_txt = f"{self.var_jpg_custom.get()} cm (personalizado)"
        else:
            jpg_txt = f"{jpg_mode} cm"
        printer_txt = "pasta da impressora" if self.var_use_printer_jpg_path.get() else "pasta padrão"
        self.var_fixed_summary.set(
            f"Modo do PDF: {mode_txt} · JPG espelhado: {jpg_txt} ({printer_txt})"
            "  —  altere em Configurações"
        )

    # --------------------------
    # Duplicidade entre rolos
    # --------------------------
    def _find_cross_roll_duplicates(self) -> dict:
        rules = normalize_rules(self.mcfg.get("print_type_rules", DEFAULT_RULES))
        pairs = {
            (j.pedido, j.fabric)
            for j in self.Jobs
            if not j.is_gap and warn_duplicate_for_type(j.tipo, rules)
        }
        try:
            return find_pedido_fabric_rolls(pairs)
        except Exception:
            return {}

    def _format_duplicate_message(self, matches: dict) -> str:
        lines = []
        for (pedido, fabric), rolls in matches.items():
            rolls_txt = ", ".join(
                f"{r['roll_name']} ({r['machine']}, {(r['created_at'] or '')[:16].replace('T', ' ')})"
                for r in rolls
            )
            lines.append(f"- Pedido \"{pedido}\" + Tecido \"{fabric}\" já impresso em: {rolls_txt}")
        return "\n".join(lines)

    def _warn_duplicates_on_import(self):
        matches = self._find_cross_roll_duplicates()
        if not matches:
            return

        messagebox.showwarning(
            "Possível duplicidade",
            "Os itens abaixo já foram impressos (mesmo pedido + mesmo tecido) em outro rolo:\n\n"
            + self._format_duplicate_message(matches),
        )

    def _confirm_duplicates_on_export(self) -> bool:
        matches = self._find_cross_roll_duplicates()
        if not matches:
            return True

        return messagebox.askyesno(
            "Possível duplicidade",
            "Os itens abaixo já foram impressos (mesmo pedido + mesmo tecido) em outro rolo:\n\n"
            + self._format_duplicate_message(matches)
            + "\n\nDeseja continuar com a exportação mesmo assim?",
        )

    # --------------------------
    # Export
    # --------------------------
    def open_export_dialog(self) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("Exportar rolo")
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=14)
        frm.pack(fill="both", expand=True)
        dialog_header(
            frm, "Exportar rolo", "Gere o comprovante do rolo em PDF e/ou JPG espelhado."
        ).pack(fill="x")

        row_dir = ttk.Frame(frm)
        row_dir.pack(fill="x", pady=(10, 4))
        ttk.Label(row_dir, text="Pasta:").pack(side="left")
        ttk.Label(row_dir, textvariable=self.var_export_dir, style="Muted.TLabel").pack(
            side="left", padx=(6, 10)
        )
        ttk.Button(row_dir, text="Abrir pasta PDF", command=self.open_pdf_folder).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(row_dir, text="Abrir pasta JPG", command=self.open_jpg_folder).pack(
            side="left"
        )

        ttk.Label(
            frm, textvariable=self.var_fixed_summary, style="Muted.TLabel", justify="left"
        ).pack(anchor="w", pady=(4, 10))

        is_editing = self.edit_roll_id is not None
        actions = ttk.Frame(frm)
        actions.pack(fill="x")
        ttk.Button(
            actions, text=("Atualizar PDF Normal" if is_editing else "Exportar PDF Normal"),
            command=lambda: self.on_export(which="normal"),
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            actions, text=("Atualizar JPG Espelhado" if is_editing else "Exportar JPG Espelhado"),
            command=lambda: self.on_export(which="mirror"),
        ).pack(side="left", padx=6)
        ttk.Button(
            actions, text=("Atualizar Ambos" if is_editing else "Exportar Ambos"),
            style="Accent.TButton", command=lambda: self.on_export(which="both"),
        ).pack(side="left", padx=6)

        ttk.Button(frm, text="Fechar", command=dlg.destroy).pack(anchor="e", pady=(12, 0))

    def _resolve_mirror_jpg_path(self, out_jpg_dir: Path, base_name: str) -> Path:
        if self.var_use_printer_jpg_path.get():
            pr = find_printer_by_display_name(self.machine or "")
            if pr and pr.jpg_output_dir.strip():
                folder = Path(pr.jpg_output_dir.strip())
                folder.mkdir(parents=True, exist_ok=True)

                filename = pr.jpg_output_filename.strip()
                if filename:
                    if not filename.lower().endswith((".jpg", ".jpeg")):
                        filename += ".jpg"
                    return folder / filename

                return versioned_path(folder / f"{base_name}.jpg")

        return versioned_path(out_jpg_dir / f"{base_name}.jpg")

    def on_export(self, which: str):
        if not self.blocks or not self.machine:
            messagebox.showwarning("Nada para exportar", "Importe logs primeiro.")
            return

        if not self._confirm_duplicates_on_export():
            self.status.configure(text="Exportação cancelada (duplicidade).")
            return

        try:
            roll = self._get_roll_name()
        except Exception as e:
            messagebox.showerror(
                "Número sequencial",
                f"Não foi possível gerar o número sequencial do rolo.\n\n{type(e).__name__}: {e}",
            )
            return
        mode = self.var_mode.get()
        mode_tag = "FULL" if mode == "full" else "SUMMARY"

        dt = datetime.now()
        out_pdf_dir = pdf_dir(dt)
        out_jpg_dir = jpg_dir(dt)
        out_temp_dir = temp_dir()

        date_iso = dt.strftime("%Y-%m-%d")
        roll_safe = sanitize_filename(roll)
        base_name = f"{date_iso}_{self.machine}_{roll_safe}_{mode_tag}"

        normal_path = str(versioned_path(out_pdf_dir / f"{base_name}.pdf"))
        mirror_path = str(self._resolve_mirror_jpg_path(out_jpg_dir, base_name))
        tmp_mirror_pdf = str(out_temp_dir / f"{base_name}.tmp.pdf")
        tmp_normal_pdf = str(out_temp_dir / f"{base_name}.normal.tmp.pdf")

        try:
            target_cm = float(self._get_mirror_target_cm())
        except Exception as e:
            messagebox.showerror("JPG", str(e))
            return

        dpi = int(self.mcfg.get("mirror_jpg_dpi", 300))

        # Quando a pasta/arquivo da impressora está configurado, esse é o
        # único arquivo que ela recebe — por isso ele traz o espelhado
        # seguido do normal (não espelhado), em vez de só o espelhado.
        use_printer_folder = self.var_use_printer_jpg_path.get()

        for job in self.Jobs:
            if job.height_mm <= 0:
                messagebox.showerror("Dados inválidos", f"HeightMM inválido no job: {job.document}")
                return
            if abs(job.real_m - (job.height_mm / 1000.0)) > 0.001:
                messagebox.showerror("Dados inválidos", "Inconsistência em real_m detectada.")
                return

        try:
            if which == "normal":
                export_pdf(
                    normal_path, self.blocks, roll, self.machine,
                    mode=mode, mirrored=False, pedidos=self.pedidos,
                )

            elif which == "mirror":
                export_pdf(
                    tmp_mirror_pdf, self.blocks, roll, self.machine,
                    mode=mode, mirrored=True, pedidos=self.pedidos,
                )
                if use_printer_folder:
                    export_pdf(
                        tmp_normal_pdf, self.blocks, roll, self.machine,
                        mode=mode, mirrored=False, pedidos=self.pedidos,
                    )
                    mirror_and_normal_to_jpg_scaled(
                        tmp_normal_pdf,
                        tmp_mirror_pdf,
                        mirror_path,
                        target_width_cm=target_cm,
                        dpi=dpi,
                        quality=95,
                    )
                    Path(tmp_normal_pdf).unlink(missing_ok=True)
                else:
                    pdf_all_pages_to_jpg_scaled(
                        tmp_mirror_pdf,
                        mirror_path,
                        target_width_cm=target_cm,
                        dpi=dpi,
                        quality=95,
                    )
                Path(tmp_mirror_pdf).unlink(missing_ok=True)

            elif which == "both":
                export_pdf(
                    normal_path, self.blocks, roll, self.machine,
                    mode=mode, mirrored=False, pedidos=self.pedidos,
                )

                export_pdf(
                    tmp_mirror_pdf, self.blocks, roll, self.machine,
                    mode=mode, mirrored=True, pedidos=self.pedidos,
                )
                if use_printer_folder:
                    mirror_and_normal_to_jpg_scaled(
                        normal_path,
                        tmp_mirror_pdf,
                        mirror_path,
                        target_width_cm=target_cm,
                        dpi=dpi,
                        quality=95,
                    )
                else:
                    pdf_all_pages_to_jpg_scaled(
                        tmp_mirror_pdf,
                        mirror_path,
                        target_width_cm=target_cm,
                        dpi=dpi,
                        quality=95,
                    )
                Path(tmp_mirror_pdf).unlink(missing_ok=True)

            else:
                return

        except Exception as e:
            try:
                Path(tmp_mirror_pdf).unlink(missing_ok=True)
                Path(tmp_normal_pdf).unlink(missing_ok=True)
            except Exception:
                pass
            messagebox.showerror("Erro ao exportar", str(e))
            return

        try:
            orders = [
                OrderRow(
                    end_time=job.end_time.isoformat(timespec="seconds"),
                    document=job.document,
                    fabric=job.fabric,
                    pedido=job.pedido,
                    height_mm=float(job.height_mm),
                    vpos_mm=float(job.vpos_mm),
                    real_m=float(job.real_m),
                    source_path=job.src_file,
                    tipo=job.tipo,
                    observacao=job.observacao,
                )
                for job in self.Jobs
                if not job.is_gap
            ]

            payload = {
                "which": which,
                "pdf_dir": str(out_pdf_dir),
                "jpg_dir": str(out_jpg_dir),
                "normal_path": normal_path if which in ("normal", "both") else None,
                "mirror_path": mirror_path if which in ("mirror", "both") else None,
                "mirror_width_cm": (target_cm if which in ("mirror", "both") else None),
                "mirror_dpi": (dpi if which in ("mirror", "both") else None),
                "module": MODULE_NAME,
            }

            if self.edit_roll_id is not None:
                update_roll_orders(
                    self.edit_roll_id,
                    machine=self.machine,
                    roll_name=roll,
                    export_mode=mode,
                    app_version=APP_VERSION,
                    orders=orders,
                    event_type="UPDATE_ROLL",
                    event_payload=payload,
                )
                roll_id = self.edit_roll_id
                self.status.configure(
                    text=self.status.cget("text") + f" | DB atualizado (roll_id={roll_id})"
                )
            else:
                roll_id, _is_new = save_export_transactional(
                    machine=self.machine,
                    roll_name=roll,
                    export_mode=mode,
                    app_version=APP_VERSION,
                    orders=orders,
                    event_type="EXPORT_ROLL",
                    event_payload=payload,
                )
                self.status.configure(text=self.status.cget("text") + f" | DB ok (roll_id={roll_id})")

        except Exception as e:
            self.status.configure(text=self.status.cget("text") + f" | DB erro: {type(e).__name__}")

        if which == "both":
            messagebox.showinfo(
                "Exportado",
                f"PDF (comprovante):\n{out_pdf_dir}\n"
                f"JPG (operação):\n{out_jpg_dir}\n\n"
                f"{Path(normal_path).name}\n"
                f"{Path(mirror_path).name}",
            )
        elif which == "normal":
            messagebox.showinfo(
                "Exportado",
                f"PDF (comprovante):\n{out_pdf_dir}\n\n{Path(normal_path).name}",
            )
        else:
            messagebox.showinfo(
                "Exportado",
                f"JPG (operação):\n{out_jpg_dir}\n\n{Path(mirror_path).name}",
            )
