from __future__ import annotations

import os
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from core.format import fmt_m
from core.printlogs_db import OrderRow, save_export_transactional
from core.version import APP_VERSION

from .config import load_cfg, save_cfg
from .exporters import export_pdf, pdf_first_page_to_jpg_scaled
from .models import Block, Job
from .parser import build_blocks, parse_log_txt
from .paths import MODULE_NAME, jpg_dir, pdf_dir, sanitize_filename, temp_dir, versioned_path

try:
    from tkinterdnd2 import DND_FILES  # type: ignore
    _HAS_DND = True
except Exception:
    DND_FILES = None
    _HAS_DND = False


class PXPrintLogsUI(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.mcfg = load_cfg()
        self.machine: Optional[str] = None
        self.Jobs: List[Job] = []
        self.blocks: List[Block] = []

        top = ttk.Frame(self)
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

        row_export = ttk.Frame(btns)
        row_export.pack(anchor="e")

        ttk.Button(
            row_export,
            text="Exportar PDF Normal",
            command=lambda: self.on_export(which="normal"),
        ).pack(side="left", padx=4)
        ttk.Button(
            row_export,
            text="Exportar JPG Espelhado",
            command=lambda: self.on_export(which="mirror"),
        ).pack(side="left", padx=4)
        ttk.Button(
            row_export,
            text="Exportar Ambos",
            command=lambda: self.on_export(which="both"),
        ).pack(side="left", padx=4)

        drop_frame = ttk.LabelFrame(self, text="Arraste e solte logs .txt aqui")
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

        details = ttk.LabelFrame(self, text="Detalhes do bloco selecionado")
        details.pack(fill="both", expand=False, padx=10, pady=(0, 10))

        self.var_detail_title = tk.StringVar(value="Selecione um tecido na lista abaixo...")
        ttk.Label(details, textvariable=self.var_detail_title).pack(
            anchor="w", padx=10, pady=(8, 6)
        )

        self.tree_Jobs = ttk.Treeview(
            details,
            columns=("end", "doc", "h", "v", "real_m"),
            show="headings",
            height=6,
        )
        for col, txt, w in [
            ("end", "EndTime", 140),
            ("doc", "Documento", 420),
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

        blocks_box = ttk.LabelFrame(self, text="Ordem do rolo (último impresso primeiro)")
        blocks_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.tree_blocks = ttk.Treeview(
            blocks_box,
            columns=("#", "fabric", "total_m", "Jobs", "last"),
            show="headings",
            height=12,
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

        self.status = ttk.Label(self, text="Pronto.")
        self.status.pack(fill="x", padx=10, pady=(0, 10))

        self._ensure_export_dir()

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

        var = tk.StringVar(value="M1")
        frm = ttk.Frame(win)
        frm.pack(padx=12, pady=6, anchor="w")
        for machine in ("M1", "M2"):
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
        return f"{machine}_{now.strftime('%d-%m-%Y')}_{now.strftime('%H%M%S')}"

    def on_refresh_roll_name(self):
        if not self.machine:
            messagebox.showwarning("Sem máquina", "Importe logs primeiro para definir a máquina.")
            return
        self.var_roll.set(self._auto_roll_name())

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
                self.var_roll.set(self._auto_roll_name())

        parsed: List[Job] = []
        skipped_invalid = 0

        existing_src = {j.src_file for j in self.Jobs} if self.Jobs else set()

        for path in txts:
            path_full = str(path)
            if path_full in existing_src:
                continue

            job = parse_log_txt(path_full)
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

        self.refresh_blocks()
        self.clear_details()

        extra = f" | Ignorados: {skipped_invalid}" if skipped_invalid else ""
        added = f" | +{len(parsed)} novos" if parsed else " | +0 novos"
        self.status.configure(
            text=(
                f"Importado total: {len(self.Jobs)} logs{added} | "
                f"Blocos: {len(self.blocks)} | Máquina: {machine}{extra}"
            )
        )

    # --------------------------
    # Clear / refresh
    # --------------------------
    def on_clear(self):
        self.machine = None
        self.Jobs = []
        self.blocks = []
        self.var_roll.set("")
        self.lbl_machine.configure(text="Máquina do lote: (não definida)")
        self.tree_blocks.delete(*self.tree_blocks.get_children())
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
            self.tree_Jobs.insert(
                "",
                "end",
                values=(
                    job.end_time.strftime("%d/%m/%Y %H:%M:%S"),
                    job.document,
                    f"{job.height_mm:.1f}",
                    f"{job.vpos_mm:.1f}",
                    fmt_m(job.real_m, suffix=False),
                ),
            )

    # --------------------------
    # Export
    # --------------------------
    def on_export(self, which: str):
        if not self.blocks or not self.machine:
            messagebox.showwarning("Nada para exportar", "Importe logs primeiro.")
            return

        roll = self._get_roll_name()
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
        mirror_path = str(versioned_path(out_jpg_dir / f"{base_name}.jpg"))
        tmp_mirror_pdf = str(out_temp_dir / f"{base_name}.tmp.pdf")

        try:
            target_cm = float(self._get_mirror_target_cm())
        except Exception as e:
            messagebox.showerror("JPG", str(e))
            return

        dpi = int(self.mcfg.get("mirror_jpg_dpi", 300))

        for job in self.Jobs:
            if job.height_mm <= 0:
                messagebox.showerror("Dados inválidos", f"HeightMM inválido no job: {job.document}")
                return
            if abs(job.real_m - (job.height_mm / 1000.0)) > 0.001:
                messagebox.showerror("Dados inválidos", "Inconsistência em real_m detectada.")
                return

        try:
            if which == "normal":
                export_pdf(normal_path, self.blocks, roll, self.machine, mode=mode, mirrored=False)

            elif which == "mirror":
                export_pdf(tmp_mirror_pdf, self.blocks, roll, self.machine, mode=mode, mirrored=True)
                pdf_first_page_to_jpg_scaled(
                    tmp_mirror_pdf,
                    mirror_path,
                    target_width_cm=target_cm,
                    dpi=dpi,
                    quality=95,
                )
                Path(tmp_mirror_pdf).unlink(missing_ok=True)

            elif which == "both":
                export_pdf(normal_path, self.blocks, roll, self.machine, mode=mode, mirrored=False)

                export_pdf(tmp_mirror_pdf, self.blocks, roll, self.machine, mode=mode, mirrored=True)
                pdf_first_page_to_jpg_scaled(
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
                    height_mm=float(job.height_mm),
                    vpos_mm=float(job.vpos_mm),
                    real_m=float(job.real_m),
                    source_path=job.src_file,
                )
                for job in self.Jobs
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

            roll_id = save_export_transactional(
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