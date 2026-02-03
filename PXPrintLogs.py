# PXPrintLogs.py
# --------------------------------------------------------------------
# Projeto Jocasta — PXPrintLogs
#
# Regras:
# - Ordena jobs por EndTime desc (último impresso primeiro)
# - Agrupa em blocos por TECIDO consecutivo (se entrou outro tecido no meio, quebra)
# - Metragem REAL (m) = (HeightMM + VPositionMM) / 1000
#
# Exportação:
# - PDF Resumido: tabela de blocos (Total com 2 casas + "m", Qtd jobs centralizada) + Total geral do rolo
# - PDF Completo:
#   1) Lista de jobs: EndTime | Arquivo (completo, quebra em linhas) | Tecido (completo, quebra em linhas) | Tamanho
#      + linha separadora quando mudar tecido (entre blocos)
#   2) Separação
#   3) Resumo igual ao Resumido + Total geral do rolo
#
# Extras:
# - Exporta por padrão em C:\Registro (configurável)
# - Evita sobrescrever: sufixo FULL/SUMMARY no nome do PDF
# - Botão "Atualizar nome" para atualizar o hhmmss do nome do rolo
# - Botão "Definir como padrão" para modo do PDF
# - Import por botão ou Drag&Drop (apenas .txt)
#
# Dependências:
# - reportlab
# - tkinterdnd2 (opcional para DnD)
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
from typing import List, Optional

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ---- PDF (reportlab) ----
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
except Exception:
    canvas = None
    A4 = None
    pdfmetrics = None

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
    parts = [p.strip() for p in (doc or "").split(" - ")]
    if len(parts) >= 2 and parts[1].strip():
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
# PDF helpers
# --------------------------
def _sanitize_filename(name: str) -> str:
    bad = r'\/:*?"<>|'
    for ch in bad:
        name = name.replace(ch, "_")
    name = re.sub(r"\s+", " ", name).strip()
    return name

def _pdf_need_new_page(y: float, min_y: float = 60) -> bool:
    return y < min_y

def _roll_total_m(blocks: List[Block]) -> float:
    return sum(b.total_m for b in blocks)

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

def _wrap_text(text: str, max_width: float, font_name: str, font_size: int) -> List[str]:
    """
    Quebra o texto em várias linhas para caber em max_width.
    Mantém palavras inteiras quando possível; quebra por caracteres se necessário.
    """
    if pdfmetrics is None:
        # fallback simples (não ideal, mas evita crash se pdfmetrics não carregou)
        return [text]

    text = (text or "").strip()
    if not text:
        return [""]

    words = text.split()
    lines: List[str] = []
    current = ""

    for w in words:
        test = w if not current else f"{current} {w}"
        if pdfmetrics.stringWidth(test, font_name, font_size) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)

            # palavra cabe inteira?
            if pdfmetrics.stringWidth(w, font_name, font_size) <= max_width:
                current = w
            else:
                # quebra na marra
                chunk = ""
                for ch in w:
                    test2 = chunk + ch
                    if pdfmetrics.stringWidth(test2, font_name, font_size) <= max_width:
                        chunk = test2
                    else:
                        if chunk:
                            lines.append(chunk)
                        chunk = ch
                current = chunk

    if current:
        lines.append(current)

    return lines

def _draw_wrapped_cell(
    c,
    x: float,
    y_top: float,
    lines: List[str],
    font_name: str,
    font_size: int,
    line_h: float,
):
    c.setFont(font_name, font_size)
    yy = y_top
    for ln in lines:
        c.drawString(x, yy, ln)
        yy -= line_h


def _pdf_draw_summary_table(
    c,
    blocks: List[Block],
    y: float,
    page_w: float,
    page_h: float,
    roll_name: str,
    machine: str,
    mode: str,
    mirrored: bool,
) -> float:
    """
    Tabela resumo (igual ao modo resumido), com:
    - Total (m): centralizado, 2 casas, com "m"
    - Qtd jobs: centralizado
    - Total geral do rolo no final
    """
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Resumo (ordem do rolo)")
    y -= 16
    c.setFont("Helvetica", 10)
    c.line(40, y, page_w - 40, y)
    y -= 18

    cols = [("#", 30), ("Tecido", 160), ("Total (m)", 90), ("Qtd jobs", 70), ("Último fim", 140)]
    c.setFont("Helvetica-Bold", 10)
    x = 40
    for title, w in cols:
        c.drawString(x, y, title)
        x += w
    y -= 14
    c.setFont("Helvetica", 10)

    for i, b in enumerate(blocks, start=1):
        if _pdf_need_new_page(y, min_y=75):
            # nova página + cabeçalho
            if mirrored:
                c.restoreState()
            c.showPage()
            if mirrored:
                c.saveState()
                c.transform(-1, 0, 0, 1, page_w, 0)

            y = page_h - 40
            y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)

            # reimprime título e colunas
            c.setFont("Helvetica-Bold", 12)
            c.drawString(40, y, "Resumo (ordem do rolo)")
            y -= 16
            c.setFont("Helvetica", 10)
            c.line(40, y, page_w - 40, y)
            y -= 18

            c.setFont("Helvetica-Bold", 10)
            x = 40
            for title, w in cols:
                c.drawString(x, y, title)
                x += w
            y -= 14
            c.setFont("Helvetica", 10)

        x = 40
        c.drawString(x, y, str(i)); x += 30
        c.drawString(x, y, b.fabric); x += 160

        c.drawCentredString(x + 45, y, f"{b.total_m:.2f} m")
        x += 90

        c.drawCentredString(x + 35, y, str(b.job_count))
        x += 70

        c.drawString(x, y, b.newest_end.strftime("%d/%m/%Y %H:%M:%S"))
        y -= 14

    # Total geral
    if _pdf_need_new_page(y, min_y=85):
        if mirrored:
            c.restoreState()
        c.showPage()
        if mirrored:
            c.saveState()
            c.transform(-1, 0, 0, 1, page_w, 0)

        y = page_h - 40
        y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)

    y -= 6
    c.setLineWidth(1)
    c.line(40, y, page_w - 40, y)
    y -= 18

    total_roll = _roll_total_m(blocks)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Total geral do rolo:")
    c.drawRightString(page_w - 40, y, f"{total_roll:.2f} m")
    c.setFont("Helvetica", 10)
    y -= 18

    return y


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
            c.saveState()
            c.transform(-1, 0, 0, 1, page_w, 0)

    def _end_page():
        if mirrored:
            c.restoreState()
        c.showPage()

    # primeira página
    y = page_h - 40
    _begin_page()
    y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)

    # --------------------
    # RESUMIDO
    # --------------------
    if mode == "summary":
        _pdf_draw_summary_table(c, blocks, y, page_w, page_h, roll_name, machine, mode, mirrored)
        _end_page()
        c.save()
        return

    # --------------------
    # COMPLETO
    # 1) Jobs (com wrap em Arquivo e Tecido)
    # --------------------
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Jobs (último impresso primeiro)")
    y -= 16
    c.setFont("Helvetica", 10)
    c.line(40, y, page_w - 40, y)
    y -= 18

    # Larguras (A4) — ajustadas para caber bem e permitir wrap
    w_end = 120
    w_doc = 300
    w_fab = 120
    w_size = 70

    font = "Helvetica"
    font_bold = "Helvetica-Bold"
    fs_head = 10
    fs_row = 10
    line_h = 12

    # Cabeçalho das colunas
    c.setFont(font_bold, fs_head)
    xh = 40
    c.drawString(xh, y, "EndTime"); xh += w_end
    c.drawString(xh, y, "Arquivo"); xh += w_doc
    c.drawString(xh, y, "Tecido");  xh += w_fab
    c.drawString(xh, y, "Tamanho")
    y -= 14
    c.setFont(font, fs_row)

    # imprime jobs por bloco para manter separador por mudança de tecido
    for bi, b in enumerate(blocks):
        # separador visual entre blocos (mudou tecido)
        if bi > 0:
            if _pdf_need_new_page(y, min_y=80):
                _end_page()
                _begin_page()
                y = page_h - 40
                y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)

                c.setFont("Helvetica-Bold", 12)
                c.drawString(40, y, "Jobs (último impresso primeiro)")
                y -= 16
                c.setFont("Helvetica", 10)
                c.line(40, y, page_w - 40, y)
                y -= 18

                c.setFont(font_bold, fs_head)
                xh = 40
                c.drawString(xh, y, "EndTime"); xh += w_end
                c.drawString(xh, y, "Arquivo"); xh += w_doc
                c.drawString(xh, y, "Tecido");  xh += w_fab
                c.drawString(xh, y, "Tamanho")
                y -= 14
                c.setFont(font, fs_row)

            c.setLineWidth(1)
            c.line(40, y + 6, page_w - 40, y + 6)
            y -= 6

        # jobs (mais recente primeiro)
        for j in sorted(b.jobs, key=lambda jj: jj.end_time, reverse=True):
            end_txt = j.end_time.strftime("%d/%m/%Y %H:%M:%S")
            doc_txt = j.document  # COMPLETO (sem cortar)
            fab_txt = j.fabric    # COMPLETO (sem cortar)
            size_txt = f"{j.real_m:.2f} m"

            doc_lines = _wrap_text(doc_txt, w_doc - 8, font, fs_row)
            fab_lines = _wrap_text(fab_txt, w_fab - 8, font, fs_row)
            row_lines = max(len(doc_lines), len(fab_lines), 1)
            row_h = row_lines * line_h

            # quebra de página considerando a altura real da linha
            if _pdf_need_new_page(y - row_h, min_y=80):
                _end_page()
                _begin_page()
                y = page_h - 40
                y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)

                c.setFont("Helvetica-Bold", 12)
                c.drawString(40, y, "Jobs (último impresso primeiro)")
                y -= 16
                c.setFont("Helvetica", 10)
                c.line(40, y, page_w - 40, y)
                y -= 18

                c.setFont(font_bold, fs_head)
                xh = 40
                c.drawString(xh, y, "EndTime"); xh += w_end
                c.drawString(xh, y, "Arquivo"); xh += w_doc
                c.drawString(xh, y, "Tecido");  xh += w_fab
                c.drawString(xh, y, "Tamanho")
                y -= 14
                c.setFont(font, fs_row)

            x0 = 40
            c.setFont(font, fs_row)
            c.drawString(x0, y, end_txt)

            _draw_wrapped_cell(c, x0 + w_end, y, doc_lines, font, fs_row, line_h)
            _draw_wrapped_cell(c, x0 + w_end + w_doc, y, fab_lines, font, fs_row, line_h)

            # tamanho no topo (direita)
            c.drawRightString(x0 + w_end + w_doc + w_fab + w_size - 6, y, size_txt)

            y -= row_h

    # 2) separação
    y -= 6
    if _pdf_need_new_page(y, min_y=110):
        _end_page()
        _begin_page()
        y = page_h - 40
        y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)

    c.setLineWidth(1.5)
    c.line(40, y, page_w - 40, y)
    y -= 22

    # 3) resumo + total geral
    _pdf_draw_summary_table(c, blocks, y, page_w, page_h, roll_name, machine, mode, mirrored)

    _end_page()
    c.save()


# --------------------------
# UI
# --------------------------
class PXPrintLogsUI(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.cfg = load_cfg()

        self.machine: Optional[str] = None
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

        self.status = ttk.Label(self, text="Pronto.")
        self.status.pack(fill="x", padx=10, pady=(0, 10))

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
                iid=str(idx - 1),
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
