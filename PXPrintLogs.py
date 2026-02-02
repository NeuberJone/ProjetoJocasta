# PXPrintLogs.py
# --------------------------------------------------------------------
# Projeto Jocasta — PXPrintLogs
# Importa logs .txt, gera "ordem do rolo" (último impresso primeiro),
# agrupa tecidos iguais consecutivos, soma metragem REAL (HeightMM + VPositionMM),
# e exporta PDF Normal / Espelhado (espelhamento horizontal).
#
# Recursos:
# - Importar por botão ou Drag & Drop (apenas .txt)
# - Seleção manual da máquina por lote (M1/M2/Calandra)
# - Dois modos de relatório: Completo (padrão) e Resumido
# - Botão "Definir como padrão" para o modo do PDF (salva em config)
# - Nome do rolo automático: MAQUINA_dd-mm-aaaa_hhmmss
# - Botão "Atualizar nome" (atualiza apenas o horário do nome do rolo)
# - Exportação padrão em C:\Registro (configurável via botão "Alterar pasta")
# - Exporta sem sobrescrever: sufixo FULL/SUMMARY + NORMAL/ESPELHO
#
# Dependências:
# - reportlab (PDF): pip install reportlab
# - tkinterdnd2 (DnD): você já usa no build do Hub
#
# Interface esperada pelo JocastaHub:
#   def build_ui(parent): return widget
# --------------------------------------------------------------------

from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ---- PDF (reportlab) ----
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
except Exception:
    canvas = None
    A4 = None

# ---- Drag & drop (tkinterdnd2) ----
try:
    from tkinterdnd2 import DND_FILES  # type: ignore
    _HAS_DND = True
except Exception:
    DND_FILES = None
    _HAS_DND = False


# --------------------------
# Config / storage
# --------------------------
APP_DIR = Path(os.environ.get("APPDATA") or str(Path.home())) / "ProjetoJocasta" / "PXPrintLogs"
APP_DIR.mkdir(parents=True, exist_ok=True)
CFG_PATH = APP_DIR / "config.json"

DEFAULT_CFG = {
    "report_mode_default": "full",     # "full" | "summary"
    "export_dir": r"C:\Registro",      # pasta padrão de exportação
}

def load_cfg() -> dict:
    if CFG_PATH.exists():
        try:
            return {**DEFAULT_CFG, **json.loads(CFG_PATH.read_text(encoding="utf-8"))}
        except Exception:
            return dict(DEFAULT_CFG)
    return dict(DEFAULT_CFG)

def save_cfg(cfg: dict) -> None:
    try:
        CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# --------------------------
# Domain models
# --------------------------
@dataclass
class Job:
    end_time: datetime
    document: str
    fabric: str
    height_mm: float
    vpos_mm: float
    real_mm: float
    src_file: str

    @property
    def real_m(self) -> float:
        return self.real_mm / 1000.0


@dataclass
class Block:
    fabric: str
    machine: str
    jobs: List[Job]

    @property
    def total_m(self) -> float:
        return sum(j.real_m for j in self.jobs)

    @property
    def job_count(self) -> int:
        return len(self.jobs)

    @property
    def newest_end(self) -> datetime:
        return max(j.end_time for j in self.jobs)

    @property
    def oldest_end(self) -> datetime:
        return min(j.end_time for j in self.jobs)


# --------------------------
# Parsing helpers
# --------------------------
_RE_KV = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*)\s*$")
_RE_SECTION = re.compile(r"^\s*\[(.+?)\]\s*$")

def _parse_datetime(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None

def _fabric_from_document(doc: str) -> str:
    parts = [p.strip() for p in doc.split(" - ")]
    if len(parts) >= 2:
        return parts[1].strip().upper()
    return "DESCONHECIDO"

def parse_log_txt(path: str) -> Optional[Job]:
    """
    Extrai de cada .txt:
      - EndTime (do [General])
      - Document (do [General])
      - HeightMM e VPositionMM (do [1])
    """
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None

    section = None
    general = {}
    item1 = {}

    for line in txt:
        msec = _RE_SECTION.match(line)
        if msec:
            section = msec.group(1).strip()
            continue
        mkv = _RE_KV.match(line)
        if not mkv:
            continue
        k, v = mkv.group(1).strip(), mkv.group(2).strip()
        if section == "General":
            general[k] = v
        elif section == "1":
            item1[k] = v

    end_dt = _parse_datetime(general.get("EndTime", ""))
    if not end_dt:
        return None

    document = general.get("Document") or item1.get("Name") or Path(path).stem

    def _f(x: str) -> float:
        x = (x or "").strip().replace(",", ".")
        try:
            return float(x)
        except Exception:
            return 0.0

    height_mm = _f(item1.get("HeightMM", "0"))
    vpos_mm = _f(item1.get("VPositionMM", "0"))
    real_mm = height_mm + vpos_mm  # regra do "real impresso"

    fabric = _fabric_from_document(document)

    return Job(
        end_time=end_dt,
        document=document,
        fabric=fabric,
        height_mm=height_mm,
        vpos_mm=vpos_mm,
        real_mm=real_mm,
        src_file=os.path.basename(path),
    )

def build_blocks(jobs: List[Job], machine: str) -> List[Block]:
    # Ordena do mais recente pro mais antigo (ordem do rolo invertida)
    jobs_sorted = sorted(jobs, key=lambda j: j.end_time, reverse=True)

    blocks: List[Block] = []
    current_jobs: List[Job] = []
    current_fabric: Optional[str] = None

    for j in jobs_sorted:
        if current_fabric is None:
            current_fabric = j.fabric
            current_jobs = [j]
            continue

        if j.fabric == current_fabric:
            current_jobs.append(j)
        else:
            blocks.append(Block(fabric=current_fabric, machine=machine, jobs=current_jobs))
            current_fabric = j.fabric
            current_jobs = [j]

    if current_fabric is not None and current_jobs:
        blocks.append(Block(fabric=current_fabric, machine=machine, jobs=current_jobs))

    return blocks


# --------------------------
# PDF generation
# --------------------------
def _sanitize_filename(name: str) -> str:
    bad = r'\/:*?"<>|'
    for ch in bad:
        name = name.replace(ch, "_")
    name = re.sub(r"\s+", " ", name).strip()
    return name

def _pdf_draw_header(c, roll_name: str, machine: str, mode: str, page_w: float, top_y: float) -> float:
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, top_y, f"Ordem do Rolo - {roll_name}")
    c.setFont("Helvetica", 10)
    c.drawString(
        40,
        top_y - 18,
        f"Máquina: {machine}    Modo: {'Completo' if mode=='full' else 'Resumido'}    Gerado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
    )
    c.line(40, top_y - 26, page_w - 40, top_y - 26)
    return top_y - 40

def _pdf_draw_table_header(c, y: float, cols: List[Tuple[str, int]]) -> float:
    c.setFont("Helvetica-Bold", 10)
    x = 40
    for title, w in cols:
        c.drawString(x, y, title)
        x += w
    c.setFont("Helvetica", 10)
    return y - 14

def _pdf_need_new_page(y: float, min_y: float = 60) -> bool:
    return y < min_y

def export_pdf(
    out_path: str,
    blocks: List[Block],
    roll_name: str,
    machine: str,
    mode: str = "full",
    mirrored: bool = False,
) -> None:
    if canvas is None or A4 is None:
        raise RuntimeError("reportlab não está instalado. Instale: pip install reportlab")

    page_w, page_h = A4
    c = canvas.Canvas(out_path, pagesize=A4)

    def _begin_page():
        if mirrored:
            # Espelhamento horizontal
            c.saveState()
            c.transform(-1, 0, 0, 1, page_w, 0)

    def _end_page():
        if mirrored:
            c.restoreState()
        c.showPage()

    y = page_h - 40
    _begin_page()
    y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)

    cols = [("#", 30), ("Tecido", 140), ("Total (m)", 80), ("Qtd jobs", 70), ("Último fim", 120)]
    y = _pdf_draw_table_header(c, y, cols)

    c.setFont("Helvetica", 10)
    for i, b in enumerate(blocks, start=1):
        if _pdf_need_new_page(y):
            _end_page()
            _begin_page()
            y = page_h - 40
            y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)
            y = _pdf_draw_table_header(c, y, cols)

        x = 40
        c.drawString(x, y, str(i)); x += 30
        c.drawString(x, y, b.fabric); x += 140
        c.drawRightString(x + 70, y, f"{b.total_m:.3f}"); x += 80
        c.drawRightString(x + 60, y, str(b.job_count)); x += 70
        c.drawString(x, y, b.newest_end.strftime("%d/%m/%Y %H:%M:%S"))
        y -= 14

        if mode == "full":
            y -= 6
            detail_cols = [("EndTime", 120), ("Documento", 250), ("Real (m)", 60)]
            c.setFont("Helvetica-Bold", 9)
            x2 = 60
            for title, w in detail_cols:
                c.drawString(x2, y, title)
                x2 += w
            y -= 12
            c.setFont("Helvetica", 9)

            for j in sorted(b.jobs, key=lambda jj: jj.end_time, reverse=True):
                if _pdf_need_new_page(y):
                    _end_page()
                    _begin_page()
                    y = page_h - 40
                    y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)
                    c.setFont("Helvetica-Bold", 10)
                    c.drawString(40, y, "Detalhes (continuação)")
                    y -= 18
                    c.setFont("Helvetica", 9)

                c.drawString(60, y, j.end_time.strftime("%d/%m/%Y %H:%M:%S"))
                doc = j.document
                if len(doc) > 55:
                    doc = doc[:52] + "..."
                c.drawString(180, y, doc)
                c.drawRightString(470, y, f"{j.real_m:.3f}")
                y -= 12

            y -= 10
            c.setFont("Helvetica", 10)

    _end_page()
    c.save()


# --------------------------
# UI
# --------------------------
class PXPrintLogsUI(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.cfg = load_cfg()

        self.machine: Optional[str] = None  # "M1" | "M2" | "Calandra"
        self.jobs: List[Job] = []
        self.blocks: List[Block] = []

        # ---- Top bar ----
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="Nome do rolo").grid(row=0, column=0, sticky="w")
        self.var_roll = tk.StringVar(value="")
        self.ent_roll = ttk.Entry(top, textvariable=self.var_roll, width=28)
        self.ent_roll.grid(row=0, column=1, padx=(6, 6), sticky="w")

        ttk.Button(top, text="Atualizar nome", command=self.on_refresh_roll_name)\
            .grid(row=0, column=2, padx=(0, 12), sticky="w")

        ttk.Label(top, text="Modo do PDF").grid(row=0, column=3, sticky="w")
        self.var_mode = tk.StringVar(value=self.cfg.get("report_mode_default", "full"))
        ttk.Radiobutton(top, text="Completo", value="full", variable=self.var_mode)\
            .grid(row=0, column=4, padx=(6, 0), sticky="w")
        ttk.Radiobutton(top, text="Resumido", value="summary", variable=self.var_mode)\
            .grid(row=0, column=5, padx=(6, 12), sticky="w")

        ttk.Button(top, text="Definir como padrão", command=self.on_set_default_mode)\
            .grid(row=0, column=6, padx=(0, 12), sticky="w")

        # Export dir controls
        ttk.Label(top, text="Pasta").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.var_export_dir = tk.StringVar(value=self.cfg.get("export_dir", r"C:\Registro"))
        self.lbl_export_dir = ttk.Label(top, textvariable=self.var_export_dir)
        self.lbl_export_dir.grid(row=1, column=1, columnspan=5, sticky="w", padx=(6, 0), pady=(6, 0))

        ttk.Button(top, text="Alterar pasta", command=self.on_change_export_dir)\
            .grid(row=1, column=6, sticky="w", pady=(6, 0))

        self.lbl_machine = ttk.Label(top, text="Máquina do lote: (não definida)")
        self.lbl_machine.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

        btns = ttk.Frame(top)
        btns.grid(row=2, column=4, columnspan=3, sticky="e", pady=(6, 0))

        ttk.Button(btns, text="Importar logs", command=self.on_import_files).pack(side="left", padx=4)
        ttk.Button(btns, text="Importar pasta", command=self.on_import_folder).pack(side="left", padx=4)
        ttk.Button(btns, text="Limpar", command=self.on_clear).pack(side="left", padx=4)

        ttk.Button(btns, text="Exportar PDF Normal", command=lambda: self.on_export(which="normal")).pack(side="left", padx=8)
        ttk.Button(btns, text="Exportar PDF Espelhado", command=lambda: self.on_export(which="mirror")).pack(side="left", padx=4)
        ttk.Button(btns, text="Exportar Ambos", command=lambda: self.on_export(which="both")).pack(side="left", padx=4)

        # ---- Drag & Drop area ----
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
            self.drop_label.configure(text="Drag & Drop indisponível (tkinterdnd2 não carregou). Use o botão Importar.")

        # ---- Details (selected block) ----
        details = ttk.LabelFrame(self, text="Detalhes do bloco selecionado")
        details.pack(fill="both", expand=False, padx=10, pady=(0, 10))

        self.var_detail_title = tk.StringVar(value="Selecione um tecido na lista abaixo...")
        ttk.Label(details, textvariable=self.var_detail_title).pack(anchor="w", padx=10, pady=(8, 6))

        self.tree_jobs = ttk.Treeview(details, columns=("end", "doc", "h", "v", "real_m"), show="headings", height=6)
        for col, txt, w in [
            ("end", "EndTime", 140),
            ("doc", "Documento", 420),
            ("h", "HeightMM", 90),
            ("v", "VPosMM", 90),
            ("real_m", "Real (m)", 90),
        ]:
            self.tree_jobs.heading(col, text=txt)
            self.tree_jobs.column(col, width=w, anchor="w")
        sbj = ttk.Scrollbar(details, orient="vertical", command=self.tree_jobs.yview)
        self.tree_jobs.configure(yscrollcommand=sbj.set)
        self.tree_jobs.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        sbj.pack(side="right", fill="y", padx=(0, 10), pady=(0, 10))

        # ---- Blocks list ----
        blocks_box = ttk.LabelFrame(self, text="Ordem do rolo (último impresso primeiro)")
        blocks_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.tree_blocks = ttk.Treeview(blocks_box, columns=("#", "fabric", "total_m", "jobs", "last"), show="headings", height=12)
        for col, txt, w, anchor in [
            ("#", "#", 40, "w"),
            ("fabric", "Tecido", 180, "w"),
            ("total_m", "Total (m)", 110, "e"),
            ("jobs", "Qtd jobs", 90, "e"),
            ("last", "Último EndTime", 160, "w"),
        ]:
            self.tree_blocks.heading(col, text=txt)
            self.tree_blocks.column(col, width=w, anchor=anchor)
        sbb = ttk.Scrollbar(blocks_box, orient="vertical", command=self.tree_blocks.yview)
        self.tree_blocks.configure(yscrollcommand=sbb.set)
        self.tree_blocks.pack(side="left", fill="both", expand=True)
        sbb.pack(side="right", fill="y")

        self.tree_blocks.bind("<<TreeviewSelect>>", self.on_select_block)

        # status
        self.status = ttk.Label(self, text="Pronto.")
        self.status.pack(fill="x", padx=10, pady=(0, 10))

        # garante pasta export padrão
        self._ensure_export_dir()

    # ----------------------
    # Config actions
    # ----------------------
    def _ensure_export_dir(self):
        export_dir = Path(self.cfg.get("export_dir", r"C:\Registro"))
        try:
            export_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self.var_export_dir.set(str(export_dir))

    def on_change_export_dir(self):
        folder = filedialog.askdirectory(title="Escolher pasta de exportação")
        if not folder:
            return
        self.cfg["export_dir"] = folder
        save_cfg(self.cfg)
        self._ensure_export_dir()
        messagebox.showinfo("Pasta atualizada", f"Nova pasta padrão:\n{folder}")

    def on_set_default_mode(self):
        self.cfg["report_mode_default"] = self.var_mode.get()
        save_cfg(self.cfg)
        messagebox.showinfo("Padrão salvo", "O modo de PDF foi definido como padrão.")

    # ----------------------
    # Machine picker
    # ----------------------
    def ask_machine(self) -> Optional[str]:
        win = tk.Toplevel(self)
        win.title("Selecionar máquina")
        win.resizable(False, False)
        win.transient(self.winfo_toplevel())
        win.grab_set()

        ttk.Label(win, text="Esses logs são de qual máquina?").pack(padx=12, pady=(12, 6), anchor="w")

        var = tk.StringVar(value="M1")
        frm = ttk.Frame(win)
        frm.pack(padx=12, pady=6, anchor="w")
        for m in ("M1", "M2", "Calandra"):
            ttk.Radiobutton(frm, text=m, value=m, variable=var).pack(anchor="w")

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

    # ----------------------
    # Roll name
    # ----------------------
    def _auto_roll_name(self) -> str:
        m = self.machine or "M?"
        now = datetime.now()
        return f"{m}_{now.strftime('%d-%m-%Y')}_{now.strftime('%H%M%S')}"

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
        return _sanitize_filename(name)

    # ----------------------
    # Import
    # ----------------------
    def on_drop_files(self, event):
        raw = getattr(event, "data", "") or ""
        files = self._split_dnd_files(raw)
        self._import_paths(files)

    def _split_dnd_files(self, data: str) -> List[str]:
        out = []
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
            messagebox.showwarning("Sem .txt", "Solte/seleciona apenas arquivos .txt.")
            return

        machine = self.ask_machine()
        if not machine:
            self.status.configure(text="Importação cancelada.")
            return

        parsed: List[Job] = []
        for p in txts:
            j = parse_log_txt(p)
            if j:
                parsed.append(j)

        if not parsed:
            messagebox.showerror("Falha", "Nenhum log válido encontrado.")
            return

        self.machine = machine
        self.lbl_machine.configure(text=f"Máquina do lote: {machine}")

        # nome do rolo automático quando importar (se campo estiver vazio)
        if not self.var_roll.get().strip():
            self.var_roll.set(self._auto_roll_name())

        self.jobs = parsed
        self.blocks = build_blocks(parsed, machine)

        self.refresh_blocks()
        self.clear_details()

        self.status.configure(text=f"Importado: {len(parsed)} logs | Blocos: {len(self.blocks)} | Máquina: {machine}")

    def on_clear(self):
        self.machine = None
        self.jobs = []
        self.blocks = []
        self.var_roll.set("")
        self.lbl_machine.configure(text="Máquina do lote: (não definida)")
        self.tree_blocks.delete(*self.tree_blocks.get_children())
        self.tree_jobs.delete(*self.tree_jobs.get_children())
        self.var_detail_title.set("Selecione um tecido na lista abaixo...")
        self.status.configure(text="Limpo.")

    # ----------------------
    # UI updates
    # ----------------------
    def refresh_blocks(self):
        self.tree_blocks.delete(*self.tree_blocks.get_children())
        for idx, b in enumerate(self.blocks, start=1):
            self.tree_blocks.insert(
                "",
                "end",
                iid=str(idx - 1),  # index do bloco
                values=(
                    idx,
                    b.fabric,
                    f"{b.total_m:.3f}",
                    b.job_count,
                    b.newest_end.strftime("%d/%m/%Y %H:%M:%S"),
                ),
            )

    def clear_details(self):
        self.var_detail_title.set("Selecione um tecido na lista abaixo...")
        self.tree_jobs.delete(*self.tree_jobs.get_children())

    def on_select_block(self, _evt=None):
        sel = self.tree_blocks.selection()
        if not sel:
            return
        bi = int(sel[0])
        if bi < 0 or bi >= len(self.blocks):
            return
        b = self.blocks[bi]

        title = (
            f"Tecido: {b.fabric} | Máquina: {b.machine} | Jobs: {b.job_count} | "
            f"Total: {b.total_m:.3f} m | "
            f"{b.newest_end.strftime('%d/%m/%Y %H:%M:%S')} → {b.oldest_end.strftime('%d/%m/%Y %H:%M:%S')}"
        )
        self.var_detail_title.set(title)

        self.tree_jobs.delete(*self.tree_jobs.get_children())
        for j in sorted(b.jobs, key=lambda jj: jj.end_time, reverse=True):
            self.tree_jobs.insert(
                "",
                "end",
                values=(
                    j.end_time.strftime("%d/%m/%Y %H:%M:%S"),
                    j.document,
                    f"{j.height_mm:.1f}",
                    f"{j.vpos_mm:.1f}",
                    f"{j.real_m:.3f}",
                ),
            )

    # ----------------------
    # Export
    # ----------------------
    def _get_export_dir(self) -> Path:
        export_dir = Path(self.cfg.get("export_dir", r"C:\Registro"))
        export_dir.mkdir(parents=True, exist_ok=True)
        return export_dir

    def on_export(self, which: str):
        if not self.blocks or not self.machine:
            messagebox.showwarning("Nada para exportar", "Importe logs primeiro.")
            return
        if canvas is None:
            messagebox.showerror("Dependência faltando", "Instale reportlab: pip install reportlab")
            return

        roll = self._get_roll_name()
        mode = self.var_mode.get()  # "full" | "summary"
        mode_tag = "FULL" if mode == "full" else "SUMMARY"

        out_dir = self._get_export_dir()

        normal_path = str(out_dir / f"{roll}_{mode_tag}_NORMAL.pdf")
        mirror_path = str(out_dir / f"{roll}_{mode_tag}_ESPELHO.pdf")

        try:
            if which == "normal":
                export_pdf(normal_path, self.blocks, roll, self.machine, mode=mode, mirrored=False)
            elif which == "mirror":
                export_pdf(mirror_path, self.blocks, roll, self.machine, mode=mode, mirrored=True)
            elif which == "both":
                export_pdf(normal_path, self.blocks, roll, self.machine, mode=mode, mirrored=False)
                export_pdf(mirror_path, self.blocks, roll, self.machine, mode=mode, mirrored=True)
            else:
                return
        except Exception as e:
            messagebox.showerror("Erro ao exportar", str(e))
            return

        if which == "both":
            messagebox.showinfo("Exportado", f"PDFs gerados em:\n{out_dir}\n\n{Path(normal_path).name}\n{Path(mirror_path).name}")
        elif which == "normal":
            messagebox.showinfo("Exportado", f"PDF gerado em:\n{out_dir}\n\n{Path(normal_path).name}")
        else:
            messagebox.showinfo("Exportado", f"PDF gerado em:\n{out_dir}\n\n{Path(mirror_path).name}")


def build_ui(parent):
    return PXPrintLogsUI(parent)
