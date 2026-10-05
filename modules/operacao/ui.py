from __future__ import annotations

import os
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Dict, List, Optional

from core.format import fmt_m
from core.printers import find_printer_by_display_name
from core.printlogs_db import (
    OrderRow,
    find_pedido_fabric_rolls,
    next_roll_sequence,
    save_export_transactional,
    update_roll_orders,
)
from core.version import APP_VERSION

from .config import load_cfg, save_cfg
from .exporters import export_pdf, mirror_and_normal_to_jpg_scaled, pdf_all_pages_to_jpg_scaled
from .models import Block, Job, PedidoSummary
from .parser import build_blocks, build_pedido_summary, normalize_space_entries, parse_log_txt
from .paths import MODULE_NAME, jpg_dir, pdf_dir, sanitize_filename, temp_dir, versioned_path

try:
    from tkinterdnd2 import DND_FILES  # type: ignore
    _HAS_DND = True
except Exception:
    DND_FILES = None
    _HAS_DND = False


class PXPrintLogsUI(ttk.Frame):
    def __init__(self, parent, *, preload: Optional[dict] = None):
        super().__init__(parent)

        self.mcfg = load_cfg()
        self.machine: Optional[str] = None
        self.Jobs: List[Job] = []
        self.blocks: List[Block] = []
        self.pedidos: List[PedidoSummary] = []
        self.edit_roll_id: Optional[int] = None

        # Container rolável: em telas pequenas o conteúdo (em especial o
        # painel "Pedidos no rolo", no fim) não cabia na altura da janela.
        canvas = tk.Canvas(self, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        body = ttk.Frame(canvas)
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

        top = ttk.Frame(body)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="Nome do rolo").grid(row=0, column=0, sticky="w")
        self.var_roll = tk.StringVar(value="")
        self.ent_roll = ttk.Entry(top, textvariable=self.var_roll, width=28)
        self.ent_roll.grid(row=0, column=1, padx=(6, 6), sticky="w")

        ttk.Button(top, text="Atualizar nome", command=self.on_refresh_roll_name).grid(
            row=0, column=2, padx=(0, 12), sticky="w"
        )

        ttk.Label(top, text="Modo do PDF").grid(row=0, column=3, sticky="w")
        self.var_mode = tk.StringVar(value=self.mcfg.get("report_mode_default", "full"))
        ttk.Radiobutton(top, text="Completo", value="full", variable=self.var_mode).grid(
            row=0, column=4, padx=(6, 0), sticky="w"
        )
        ttk.Radiobutton(top, text="Resumido", value="summary", variable=self.var_mode).grid(
            row=0, column=5, padx=(6, 12), sticky="w"
        )

        ttk.Button(top, text="Definir como padrão", command=self.on_set_default_mode).grid(
            row=0, column=6, padx=(0, 12), sticky="w"
        )

        ttk.Label(top, text="Pasta").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.var_export_dir = tk.StringVar(value=str(pdf_dir(datetime.now())))
        self.lbl_export_dir = ttk.Label(top, textvariable=self.var_export_dir)
        self.lbl_export_dir.grid(
            row=1, column=1, columnspan=5, sticky="w", padx=(6, 0), pady=(6, 0)
        )

        ttk.Button(top, text="Abrir pastas", command=self.on_open_folders_menu).grid(
            row=1, column=6, sticky="w", pady=(6, 0)
        )

        self.lbl_machine = ttk.Label(top, text="Máquina do lote: (não definida)")
        self.lbl_machine.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

        ttk.Label(top, text="JPG espelhado").grid(row=3, column=0, sticky="w", pady=(6, 0))

        self.var_jpg_mode = tk.StringVar(value=self.mcfg.get("mirror_jpg_width_mode", "17"))
        self.var_jpg_custom = tk.StringVar(
            value=str(self.mcfg.get("mirror_jpg_width_cm_custom", 17.0))
        )

        ttk.Radiobutton(top, text="17 cm", value="17", variable=self.var_jpg_mode).grid(
            row=3, column=1, padx=(6, 0), sticky="w", pady=(6, 0)
        )
        ttk.Radiobutton(top, text="21 cm", value="21", variable=self.var_jpg_mode).grid(
            row=3, column=2, padx=(6, 0), sticky="w", pady=(6, 0)
        )
        ttk.Radiobutton(top, text="Personalizado", value="custom", variable=self.var_jpg_mode).grid(
            row=3, column=3, padx=(6, 0), sticky="w", pady=(6, 0)
        )

        self.ent_jpg_custom = ttk.Entry(top, textvariable=self.var_jpg_custom, width=6)
        self.ent_jpg_custom.grid(row=3, column=4, padx=(6, 0), sticky="w", pady=(6, 0))
        ttk.Label(top, text="cm").grid(row=3, column=5, padx=(4, 0), sticky="w", pady=(6, 0))

        ttk.Button(top, text="Definir JPG como padrão", command=self.on_set_default_jpg).grid(
            row=3, column=6, padx=(12, 0), sticky="w", pady=(6, 0)
        )

        def _update_custom_state(*_):
            self.ent_jpg_custom.configure(
                state=("normal" if self.var_jpg_mode.get() == "custom" else "disabled")
            )

        _update_custom_state()
        self.var_jpg_mode.trace_add("write", _update_custom_state)

        self.var_use_printer_jpg_path = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            top,
            text="Usar pasta/arquivo da impressora para o JPG espelhado",
            variable=self.var_use_printer_jpg_path,
        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(4, 0))

        btns = ttk.Frame(top)
        btns.grid(row=2, column=4, columnspan=3, sticky="e", pady=(6, 0))

        row_actions = ttk.Frame(btns)
        row_actions.pack(anchor="e", pady=(0, 4))

        ttk.Button(row_actions, text="Importar logs", command=self.on_import_files).pack(
            side="left", padx=4
        )
        ttk.Button(row_actions, text="Importar pasta", command=self.on_import_folder).pack(
            side="left", padx=4
        )
        ttk.Button(row_actions, text="Limpar", command=self.on_clear).pack(
            side="left", padx=4
        )
        ttk.Button(row_actions, text="Editar tecido", command=self.on_edit_fabric).pack(
            side="left", padx=4
        )
        ttk.Button(
            row_actions, text="Arquivo(s) de espaço…", command=self.on_edit_space_filenames
        ).pack(side="left", padx=4)

        row_export = ttk.Frame(btns)
        row_export.pack(anchor="e")

        self.btn_export_normal = ttk.Button(
            row_export,
            text="Exportar PDF Normal",
            command=lambda: self.on_export(which="normal"),
        )
        self.btn_export_normal.pack(side="left", padx=4)
        self.btn_export_mirror = ttk.Button(
            row_export,
            text="Exportar JPG Espelhado",
            command=lambda: self.on_export(which="mirror"),
        )
        self.btn_export_mirror.pack(side="left", padx=4)
        self.btn_export_both = ttk.Button(
            row_export,
            text="Exportar Ambos",
            command=lambda: self.on_export(which="both"),
        )
        self.btn_export_both.pack(side="left", padx=4)

        self.var_edit_banner = tk.StringVar(value="")
        self.lbl_edit_banner = ttk.Label(
            top, textvariable=self.var_edit_banner, foreground="#8a4b00"
        )
        self.lbl_edit_banner.grid(row=5, column=0, columnspan=7, sticky="w", pady=(6, 0))

        drop_frame = ttk.LabelFrame(body, text="Arraste e solte logs .txt aqui")
        drop_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.drop_label = ttk.Label(drop_frame, text="Solte arquivos .txt (apenas) para importar")
        self.drop_label.pack(fill="x", padx=10, pady=12)

        if _HAS_DND:
            try:
                self.drop_label.drop_target_register(DND_FILES)  # type: ignore
                self.drop_label.dnd_bind("<<Drop>>", self.on_drop_files)  # type: ignore
            except Exception:
                pass
        else:
            self.drop_label.configure(
                text="Drag & Drop indisponível (tkinterdnd2 não carregou). Use o botão Importar."
            )

        details = ttk.LabelFrame(body, text="Detalhes do bloco selecionado")
        details.pack(fill="both", expand=False, padx=10, pady=(0, 10))

        self.var_detail_title = tk.StringVar(value="Selecione um tecido na lista abaixo...")
        ttk.Label(details, textvariable=self.var_detail_title).pack(
            anchor="w", padx=10, pady=(8, 6)
        )

        self.tree_Jobs = ttk.Treeview(
            details,
            columns=("end", "doc", "pedido", "h", "v", "real_m"),
            show="headings",
            height=6,
        )
        for col, txt, w in [
            ("end", "EndTime", 140),
            ("doc", "Documento", 320),
            ("pedido", "Pedido", 160),
            ("h", "HeightMM", 90),
            ("v", "VPosMM", 90),
            ("real_m", "Real (m)", 90),
        ]:
            self.tree_Jobs.heading(col, text=txt)
            self.tree_Jobs.column(col, width=w, anchor="w")

        sbj = ttk.Scrollbar(details, orient="vertical", command=self.tree_Jobs.yview)
        self.tree_Jobs.configure(yscrollcommand=sbj.set)
        self.tree_Jobs.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        sbj.pack(side="right", fill="y", padx=(0, 10), pady=(0, 10))

        blocks_box = ttk.LabelFrame(body, text="Ordem do rolo (último impresso primeiro)")
        blocks_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

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

        pedidos_box = ttk.LabelFrame(body, text="Pedidos no rolo (duplo clique para editar)")
        pedidos_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.tree_pedidos = ttk.Treeview(
            pedidos_box,
            columns=("#", "pedido", "total_m", "Jobs", "last"),
            show="headings",
            height=8,
        )
        for col, txt, w, anchor in [
            ("#", "#", 40, "w"),
            ("pedido", "Pedido", 220, "w"),
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

        self.status = ttk.Label(body, text="Pronto.")
        self.status.pack(fill="x", padx=10, pady=(0, 10))

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
        for btn, label in (
            (self.btn_export_normal, "Atualizar PDF Normal"),
            (self.btn_export_mirror, "Atualizar JPG Espelhado"),
            (self.btn_export_both, "Atualizar Ambos"),
        ):
            btn.configure(text=label)

        self.status.configure(
            text=f"Rolo carregado para edição: {len(self.Jobs)} log(s) já registrados."
        )

    # --------------------------
    # Config helpers
    # --------------------------
    def _ensure_export_dir(self):
        self.var_export_dir.set(str(pdf_dir(datetime.now())))

    def on_open_folders_menu(self):
        try:
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(label="Abrir pasta PDF (comprovantes)", command=self.open_pdf_folder)
            menu.add_command(label="Abrir pasta JPG (operação)", command=self.open_jpg_folder)

            x = self.winfo_pointerx()
            y = self.winfo_pointery()
            menu.tk_popup(x, y)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

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

    def on_set_default_mode(self):
        self.mcfg["report_mode_default"] = self.var_mode.get()
        save_cfg(self.mcfg)
        messagebox.showinfo("Padrão salvo", "O modo de PDF foi definido como padrão.")

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

    def on_set_default_jpg(self):
        try:
            cm = self._get_mirror_target_cm()
        except Exception as e:
            messagebox.showerror("JPG", str(e))
            return

        self.mcfg["mirror_jpg_width_mode"] = self.var_jpg_mode.get()
        self.mcfg["mirror_jpg_width_cm_custom"] = float(cm)
        save_cfg(self.mcfg)
        messagebox.showinfo("JPG", f"Padrão salvo: {cm:.1f} cm")

    # --------------------------
    # Machine / naming
    # --------------------------
    def ask_machine(self) -> Optional[str]:
        win = tk.Toplevel(self)
        win.title("Selecionar máquina")
        win.resizable(False, False)
        win.transient(self.winfo_toplevel())
        win.grab_set()

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

    def on_edit_space_filenames(self) -> None:
        win = tk.Toplevel(self)
        win.title("Arquivo(s) de espaço")
        win.resizable(False, False)
        win.transient(self.winfo_toplevel())
        win.grab_set()

        ttk.Label(
            win,
            text=(
                "Nome(s) de arquivo/job que a máquina imprime como espaço entre\n"
                "tecidos (quando não há gap automático) — ao importar, esses logs\n"
                "são identificados e não entram em \"Pedidos no rolo\". O \"Nome de\n"
                "exibição\" aparece nas listagens no lugar do nome do arquivo —\n"
                "útil quando há arquivos de espaço diferentes."
            ),
            justify="left",
        ).pack(padx=12, pady=(12, 6), anchor="w")

        entries: List[dict] = normalize_space_entries(self.mcfg.get("space_filenames", []))

        cols = ("filename", "display_name")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=8)
        tree.heading("filename", text="Arquivo/job")
        tree.column("filename", width=220, anchor="w")
        tree.heading("display_name", text="Nome de exibição")
        tree.column("display_name", width=160, anchor="w")
        tree.pack(padx=12, pady=6, fill="both", expand=True)

        def refresh_tree(select_index: Optional[int] = None):
            tree.delete(*tree.get_children())
            for i, e in enumerate(entries):
                tree.insert("", "end", iid=str(i), values=(e["filename"], e["display_name"]))
            if select_index is not None and 0 <= select_index < len(entries):
                tree.selection_set(str(select_index))

        refresh_tree()

        form = ttk.Frame(win)
        form.pack(padx=12, pady=(0, 6), fill="x")

        ttk.Label(form, text="Arquivo/job:").grid(row=0, column=0, sticky="w")
        var_filename = tk.StringVar(value="")
        ttk.Entry(form, textvariable=var_filename, width=26).grid(row=0, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(form, text="Nome de exibição:").grid(row=1, column=0, sticky="w")
        var_display = tk.StringVar(value="")
        ttk.Entry(form, textvariable=var_display, width=26).grid(row=1, column=1, sticky="w", padx=6, pady=2)

        selected_index: Dict[str, Optional[int]] = {"value": None}

        def clear_form():
            selected_index["value"] = None
            var_filename.set("")
            var_display.set("")
            tree.selection_remove(*tree.selection())

        def on_select(_evt=None):
            sel = tree.selection()
            if not sel:
                return
            idx = int(sel[0])
            selected_index["value"] = idx
            var_filename.set(entries[idx]["filename"])
            var_display.set(entries[idx]["display_name"])

        tree.bind("<<TreeviewSelect>>", on_select)

        def add_or_update():
            filename = var_filename.get().strip()
            if not filename:
                messagebox.showwarning("Arquivo de espaço", "Informe o nome do arquivo/job.")
                return
            display_name = var_display.get().strip() or "ESPAÇO"
            idx = selected_index["value"]
            was_new = idx is None
            if idx is not None:
                entries[idx] = {"filename": filename, "display_name": display_name}
            else:
                entries.append({"filename": filename, "display_name": display_name})
                idx = len(entries) - 1
            refresh_tree(select_index=idx)
            selected_index["value"] = idx
            if was_new:
                # Limpa o formulário para o próximo "Adicionar" não sobrescrever
                # este item sem querer.
                clear_form()

        form_btns = ttk.Frame(form)
        form_btns.grid(row=2, column=1, sticky="w", pady=(6, 0))
        ttk.Button(form_btns, text="Novo", command=clear_form).pack(side="left")
        ttk.Button(form_btns, text="Adicionar / Atualizar", command=add_or_update).pack(
            side="left", padx=(6, 0)
        )

        def remove_selected():
            idx = selected_index["value"]
            if idx is None:
                messagebox.showwarning("Arquivo de espaço", "Selecione um item na lista.")
                return
            del entries[idx]
            clear_form()
            refresh_tree()

        ttk.Button(win, text="Remover selecionado", command=remove_selected).pack(
            padx=12, pady=(0, 6), anchor="w"
        )

        def save():
            self.mcfg["space_filenames"] = list(entries)
            save_cfg(self.mcfg)
            win.destroy()

        btn = ttk.Frame(win)
        btn.pack(padx=12, pady=(6, 12), fill="x")
        ttk.Button(btn, text="Salvar", command=save).pack(side="right", padx=4)
        ttk.Button(btn, text="Cancelar", command=win.destroy).pack(side="right", padx=4)

        win.wait_window()

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

        for path in txts:
            path_full = str(path)
            if path_full in existing_src:
                continue

            job = parse_log_txt(
                path_full,
                space_entries=normalize_space_entries(self.mcfg.get("space_filenames", [])),
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

        if parsed:
            self.Jobs.extend(parsed)

        self.blocks = build_blocks(self.Jobs, machine)
        self.pedidos = build_pedido_summary(self.Jobs)

        self.refresh_blocks()
        self.refresh_pedidos()
        self.clear_details()

        extra = f" | Ignorados: {skipped_invalid}" if skipped_invalid else ""
        added = f" | +{len(parsed)} novos" if parsed else " | +0 novos"
        self.status.configure(
            text=(
                f"Importado total: {len(self.Jobs)} logs{added} | "
                f"Blocos: {len(self.blocks)} | Máquina: {machine}{extra}"
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
                    fmt_m(pedido.total_m),
                    pedido.job_count,
                    pedido.newest_end.strftime("%d/%m/%Y %H:%M:%S"),
                ),
            )

    def clear_details(self):
        self.var_detail_title.set("Selecione um tecido na lista abaixo...")
        self.tree_Jobs.delete(*self.tree_Jobs.get_children())

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
        for job in sorted(block.Jobs, key=lambda item: item.end_time, reverse=True):
            doc_txt = f"— {job.fabric or 'ESPAÇO'} —" if job.is_gap else job.document
            pedido_txt = "" if job.is_gap else job.pedido
            self.tree_Jobs.insert(
                "",
                "end",
                values=(
                    job.end_time.strftime("%d/%m/%Y %H:%M:%S"),
                    doc_txt,
                    pedido_txt,
                    f"{job.height_mm:.1f}",
                    f"{job.vpos_mm:.1f}",
                    fmt_m(job.real_m, suffix=False),
                ),
            )

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

        new_name = simpledialog.askstring(
            "Editar tecido",
            "Novo nome do tecido:",
            initialvalue=block.fabric,
            parent=self.winfo_toplevel(),
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

        new_name = simpledialog.askstring(
            "Editar pedido",
            "Novo nome do pedido:",
            initialvalue=pedido.pedido,
            parent=self.winfo_toplevel(),
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

        self.pedidos = build_pedido_summary(self.Jobs)
        self.refresh_pedidos()
        self.on_select_block()
        self.status.configure(
            text=self.status.cget("text") + f" | Pedido renomeado para '{new_name}'"
        )

    # --------------------------
    # Duplicidade entre rolos
    # --------------------------
    def _find_cross_roll_duplicates(self) -> dict:
        pairs = {(j.pedido, j.fabric) for j in self.Jobs if not j.is_gap}
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