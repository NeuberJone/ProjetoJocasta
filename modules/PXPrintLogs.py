# PXPrintLogs.py
# --------------------------------------------------------------------
# Projeto Jocasta — PXPrintLogs
#
# Regras:
# - Ordena Pedidos por EndTime desc (último impresso primeiro)
# - Agrupa em blocos por TECIDO consecutivo (se entrou outro tecido no meio, quebra)
# - Metragem REAL (m) = HeightMM / 1000  (VPositionMM é deslocamento/offset)
#
# Exportação:
# - PDF Resumido: tabela de blocos (Total centralizado 2 casas + "m", Qtd Pedidos centralizada) + Total geral
# - PDF Completo:
#   1) Lista de Pedidos: EndTime | Arquivo (completo + wrap) | Tecido (completo + wrap) | Tamanho
#      + linha separadora quando mudar tecido (entre blocos)
#   2) Separação
#   3) Resumo igual ao Resumido + Total geral
#
# Extras:
# - Exporta por padrão em C:\Registro (configurável)
# - Evita sobrescrever: sufixo FULL/SUMMARY no nome do PDF
# - Botão "Atualizar nome" para atualizar hhmmss do nome do rolo
# - Botão "Definir como padrão" para modo do PDF
# - Import por botão ou Drag&Drop (apenas .txt)
# - Import incremental: importar outra pasta NÃO apaga o primeiro import
# - Espelhado: exporta JPG (com largura 17cm / 21cm / personalizado)
# --------------------------------------------------------------------

from __future__ import annotations

import os
import re
import json
import math
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from tkinter import ttk, messagebox, filedialog

from core.printlogs_db import save_export_transactional, OrderRow


def _round_up_cm(value_m: float) -> float:
    """
    Arredonda para cima em centímetros (0.01 m).
    Ex: 6.361 -> 6.37
    """
    return math.ceil(value_m * 100) / 100


# ---- PDF (reportlab) ----
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
except Exception:
    canvas = None
    A4 = None
    pdfmetrics = None


# ---- JPG (PyMuPDF) ----
try:
    import fitz  # PyMuPDF
    _HAS_PYMUPDF = True
except Exception:
    fitz = None
    _HAS_PYMUPDF = False


# ---- Drag & drop (tkinterdnd2) ----
try:
    from tkinterdnd2 import DND_FILES  # type: ignore
    _HAS_DND = True
except Exception:
    DND_FILES = None
    _HAS_DND = False

# ---- JPG export (PyMuPDF + Pillow) ----
try:
    import fitz  # PyMuPDF
    _HAS_PYMUPDF = True
except Exception:
    fitz = None
    _HAS_PYMUPDF = False

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    Image = None
    _HAS_PIL = False

# --------------------------
# Config / storage
# --------------------------
APP_DIR = Path(os.environ.get("APPDATA") or str(Path.home())) / "ProjetoJocasta" / "PXPrintLogs"
APP_DIR.mkdir(parents=True, exist_ok=True)
CFG_PATH = APP_DIR / "config.json"

DEFAULT_CFG = {
    "report_mode_default": "full",     # "full" | "summary"
    "export_dir": r"C:\Registro",      # pasta padrão de exportação

    # JPG espelhado (tamanho final)
    "mirror_jpg_width_mode": "17",     # "17" | "21" | "custom"
    "mirror_jpg_width_cm_custom": 17.0,
    "mirror_jpg_dpi": 300,             # usado para converter cm->px (qualidade)
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
    src_file: str  # caminho completo (ajuda no dedupe)

    @property
    def real_m(self) -> float:
        return self.real_mm / 1000.0


@dataclass
class Block:
    fabric: str
    machine: str
    Jobs: List[Job]

    @property
    def total_m(self) -> float:
        return sum(j.real_m for j in self.Jobs)

    @property
    def job_count(self) -> int:
        return len(self.Jobs)

    @property
    def newest_end(self) -> datetime:
        return max(j.end_time for j in self.Jobs)

    @property
    def oldest_end(self) -> datetime:
        return min(j.end_time for j in self.Jobs)


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

    # Real é apenas o comprimento impresso (HeightMM), não soma deslocamento
    real_mm = height_mm

    fabric = _fabric_from_document(document)

    return Job(
        end_time=end_dt,
        document=document,
        fabric=fabric,
        height_mm=height_mm,
        vpos_mm=vpos_mm,
        real_mm=real_mm,
        src_file=str(path),  # caminho completo
    )


def build_blocks(Jobs: List[Job], machine: str) -> List[Block]:
    Jobs_sorted = sorted(Jobs, key=lambda j: j.end_time, reverse=True)

    blocks: List[Block] = []
    current_Jobs: List[Job] = []
    current_fabric: Optional[str] = None

    for j in Jobs_sorted:
        if current_fabric is None:
            current_fabric = j.fabric
            current_Jobs = [j]
            continue

        if j.fabric == current_fabric:
            current_Jobs.append(j)
        else:
            blocks.append(Block(fabric=current_fabric, machine=machine, Jobs=current_Jobs))
            current_fabric = j.fabric
            current_Jobs = [j]

    if current_fabric is not None and current_Jobs:
        blocks.append(Block(fabric=current_fabric, machine=machine, Jobs=current_Jobs))

    return blocks


# --------------------------
# JPG helpers
# --------------------------
def _cm_to_px(cm: float, dpi: int) -> int:
    return max(1, int(round((cm / 2.54) * dpi)))


def pdf_first_page_to_jpg_sized(pdf_path: str, jpg_path: str, target_width_cm: float, dpi: int = 300) -> None:
    """
    Converte a primeira página de um PDF para JPG com largura física desejada (em cm).
    Mantém proporção automaticamente.
    """
    if not _HAS_PYMUPDF or fitz is None:
        raise RuntimeError("PyMuPDF não instalado. Instale: pip install pymupdf")

    if target_width_cm <= 0:
        raise ValueError("target_width_cm deve ser > 0")

    width_px = _cm_to_px(float(target_width_cm), int(dpi))

    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(0)
        page_width_pt = float(page.rect.width)  # pontos (1/72")
        if page_width_pt <= 0:
            raise RuntimeError("Página inválida para renderizar.")

        # zoom: pixels = points * zoom
        zoom = width_px / page_width_pt
        mat = fitz.Matrix(zoom, zoom)

        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img.save(jpg_path, "JPEG", dpi=(dpi, dpi), quality=95)
        from PIL import Image
    finally:
        doc.close()

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
    Wrap por largura real (stringWidth).
    """
    text = (text or "").strip()
    if not text:
        return [""]

    if pdfmetrics is None:
        # fallback simples (evita crash)
        return [text]

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

            if pdfmetrics.stringWidth(w, font_name, font_size) <= max_width:
                current = w
            else:
                # quebra por caracteres se uma palavra for maior que a coluna
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


def _draw_wrapped_cell(c, x: float, y_top: float, lines: List[str], font_name: str, font_size: int, line_h: float):
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
    Resumo:
    - Total (m) centralizado, 2 casas, com "m"
    - Qtd Pedidos centralizado
    - Total geral no final
    """
    # Larguras FIXAS (A4 com margem 40)
    # total útil = 595 - 80 = 515
    w_num = 30
    w_fab = 180
    w_total = 90
    w_Jobs = 70
    w_last = 145  # soma = 515

    def _reprint_summary_header(y0: float) -> float:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y0, "Resumo (ordem do rolo)")
        y0 -= 16
        c.setFont("Helvetica", 10)
        c.line(40, y0, page_w - 40, y0)
        y0 -= 18

        # Cabeçalho colunas
        c.setFont("Helvetica-Bold", 10)
        x = 40
        c.drawString(x, y0, "#")
        x += w_num
        c.drawString(x, y0, "Tecido")
        x += w_fab

        # Centraliza também o TÍTULO dessas colunas
        c.drawCentredString(x + (w_total / 2), y0, "Total (m)")
        x += w_total
        c.drawCentredString(x + (w_Jobs / 2), y0, "Qtd Pedidos")
        x += w_Jobs

        c.drawString(x, y0, "Último fim")
        y0 -= 14
        c.setFont("Helvetica", 10)
        return y0

    y = _reprint_summary_header(y)

    for i, b in enumerate(blocks, start=1):
        if _pdf_need_new_page(y, min_y=85):
            if mirrored:
                c.restoreState()
            c.showPage()
            if mirrored:
                c.saveState()
                c.transform(-1, 0, 0, 1, page_w, 0)

            y = page_h - 40
            y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)
            y = _reprint_summary_header(y)

        x = 40
        c.drawString(x, y, str(i))
        x += w_num
        c.drawString(x, y, b.fabric)
        x += w_fab

        # Total centralizado (centro real da coluna)
        c.drawCentredString(x + (w_total / 2), y, f"{_round_up_cm(b.total_m):.2f} m")

        # Qtd Pedidos centralizado (centro real da coluna)
        c.drawCentredString(x + (w_Jobs / 2), y, str(b.job_count))
        x += w_Jobs

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
    c.drawRightString(page_w - 40, y, f"{_round_up_cm(total_roll):.2f} m")
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
    # --------------------

    # Larguras FIXAS (A4 com margem 40) => 515 úteis
    w_end = 120
    w_doc = 260
    w_fab = 95
    w_size = 40  # soma = 515

    font = "Helvetica"
    font_bold = "Helvetica-Bold"
    fs_head = 10
    fs_row = 10
    line_h = 12

    def _reprint_Jobs_header(y0: float) -> float:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y0, "Pedidos (último impresso primeiro)")
        y0 -= 16
        c.setFont("Helvetica", 10)
        c.line(40, y0, page_w - 40, y0)
        y0 -= 18

        c.setFont(font_bold, fs_head)
        xh = 40
        c.drawString(xh, y0, "EndTime")
        xh += w_end
        c.drawString(xh, y0, "Arquivo")
        xh += w_doc
        c.drawString(xh, y0, "Tecido")
        xh += w_fab
        c.drawString(xh, y0, "Tamanho")
        y0 -= 14
        c.setFont(font, fs_row)
        return y0

    # imprime cabeçalho das colunas na primeira página
    y = _reprint_Jobs_header(y)

    for bi, b in enumerate(blocks):
        # separador entre blocos (mudou tecido)
        if bi > 0:
            if _pdf_need_new_page(y, min_y=95):
                _end_page()
                _begin_page()
                y = page_h - 40
                y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)
                y = _reprint_Jobs_header(y)

            c.setLineWidth(1)
            c.line(40, y + 6, page_w - 40, y + 6)
            y -= 8

        # Pedidos do bloco (mais recente primeiro)
        for j in sorted(b.Jobs, key=lambda jj: jj.end_time, reverse=True):
            end_txt = j.end_time.strftime("%d/%m/%Y %H:%M:%S")
            doc_txt = j.document  # COMPLETO (SEM "...")
            fab_txt = j.fabric    # COMPLETO (SEM "...")
            size_txt = f"{_round_up_cm(j.real_m):.2f} m"

            doc_lines = _wrap_text(doc_txt, w_doc - 6, font, fs_row)
            fab_lines = _wrap_text(fab_txt, w_fab - 6, font, fs_row)

            row_lines = max(len(doc_lines), len(fab_lines), 1)
            row_h = row_lines * line_h

            if _pdf_need_new_page(y - row_h, min_y=95):
                _end_page()
                _begin_page()
                y = page_h - 40
                y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)
                y = _reprint_Jobs_header(y)

            x0 = 40
            c.setFont(font, fs_row)

            # EndTime (topo)
            c.drawString(x0, y, end_txt)

            # Arquivo com wrap
            _draw_wrapped_cell(c, x0 + w_end, y, doc_lines, font, fs_row, line_h)

            # Tecido com wrap
            _draw_wrapped_cell(c, x0 + w_end + w_doc, y, fab_lines, font, fs_row, line_h)

            # Tamanho (direita)
            c.drawRightString(x0 + w_end + w_doc + w_fab + w_size - 2, y, size_txt)

            y -= row_h

    # separação + resumo
    y -= 6
    if _pdf_need_new_page(y, min_y=120):
        _end_page()
        _begin_page()
        y = page_h - 40
        y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)

    c.setLineWidth(1.5)
    c.line(40, y, page_w - 40, y)
    y -= 22

    _pdf_draw_summary_table(c, blocks, y, page_w, page_h, roll_name, machine, mode, mirrored)

    _end_page()
    c.save()

def pdf_first_page_to_jpg_scaled(
    pdf_path: str,
    jpg_path: str,
    *,
    target_width_cm: float,
    dpi: int = 300,
    quality: int = 95,
) -> None:
    """
    Renderiza a 1ª página do PDF em JPG com LARGURA física alvo (cm).
    - Gera pixels suficientes para bater a largura em cm no DPI informado
    - Salva o JPG com metadata dpi=(dpi,dpi) pra impressão sair no tamanho certo
    """
    if not _HAS_PYMUPDF:
        raise RuntimeError("PyMuPDF não instalado. Instale: pip install pymupdf")
    if not _HAS_PIL:
        raise RuntimeError("Pillow não instalado. Instale: pip install pillow")

    # largura em pixels que corresponde a target_width_cm no dpi desejado
    width_in = float(target_width_cm) / 2.54
    target_width_px = int(round(width_in * dpi))

    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(0)

        # page.rect.width está em pontos (pt). 1 pt = 1/72 inch.
        page_width_pt = float(page.rect.width)

        # PyMuPDF: pixels = pt * zoom  (onde zoom= dpi/72 se for 1:1 no dpi)
        # Aqui a gente força a largura final: zoom = target_px / page_width_pt
        zoom = target_width_px / page_width_pt
        mat = fitz.Matrix(zoom, zoom)

        pix = page.get_pixmap(matrix=mat, alpha=False)

        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        img.save(jpg_path, "JPEG", dpi=(dpi, dpi), quality=int(quality))
    finally:
        doc.close()

# --------------------------
# UI
# --------------------------
class PXPrintLogsUI(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.cfg = load_cfg()
        self.machine: Optional[str] = None
        self.Jobs: List[Job] = []
        self.blocks: List[Block] = []

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

        # ---- JPG espelhado: tamanho ----
        ttk.Label(top, text="JPG espelhado").grid(row=3, column=0, sticky="w", pady=(6, 0))

        self.var_jpg_mode = tk.StringVar(value=self.cfg.get("mirror_jpg_width_mode", "17"))
        self.var_jpg_custom = tk.StringVar(value=str(self.cfg.get("mirror_jpg_width_cm_custom", 17.0)))

        ttk.Radiobutton(top, text="17 cm", value="17", variable=self.var_jpg_mode)\
            .grid(row=3, column=1, padx=(6, 0), sticky="w", pady=(6, 0))
        ttk.Radiobutton(top, text="21 cm", value="21", variable=self.var_jpg_mode)\
            .grid(row=3, column=2, padx=(6, 0), sticky="w", pady=(6, 0))
        ttk.Radiobutton(top, text="Personalizado", value="custom", variable=self.var_jpg_mode)\
            .grid(row=3, column=3, padx=(6, 0), sticky="w", pady=(6, 0))

        self.ent_jpg_custom = ttk.Entry(top, textvariable=self.var_jpg_custom, width=6)
        self.ent_jpg_custom.grid(row=3, column=4, padx=(6, 0), sticky="w", pady=(6, 0))
        ttk.Label(top, text="cm").grid(row=3, column=5, padx=(4, 0), sticky="w", pady=(6, 0))

        ttk.Button(top, text="Definir JPG como padrão", command=self.on_set_default_jpg)\
            .grid(row=3, column=6, padx=(12, 0), sticky="w", pady=(6, 0))

        def _update_custom_state(*_):
            self.ent_jpg_custom.configure(state=("normal" if self.var_jpg_mode.get() == "custom" else "disabled"))

        _update_custom_state()
        self.var_jpg_mode.trace_add("write", _update_custom_state)

        btns = ttk.Frame(top)
        btns.grid(row=2, column=4, columnspan=3, sticky="e", pady=(6, 0))

        # Linha 1: ações
        row_actions = ttk.Frame(btns)
        row_actions.pack(anchor="e", pady=(0, 4))

        ttk.Button(row_actions, text="Importar logs", command=self.on_import_files).pack(side="left", padx=4)
        ttk.Button(row_actions, text="Importar pasta", command=self.on_import_folder).pack(side="left", padx=4)
        ttk.Button(row_actions, text="Limpar", command=self.on_clear).pack(side="left", padx=4)

        # Linha 2: exportação
        row_export = ttk.Frame(btns)
        row_export.pack(anchor="e")

        ttk.Button(row_export, text="Exportar PDF Normal", command=lambda: self.on_export(which="normal")).pack(side="left", padx=4)
        ttk.Button(row_export, text="Exportar JPG Espelhado", command=lambda: self.on_export(which="mirror")).pack(side="left", padx=4)
        ttk.Button(row_export, text="Exportar Ambos", command=lambda: self.on_export(which="both")).pack(side="left", padx=4)

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

        details = ttk.LabelFrame(self, text="Detalhes do bloco selecionado")
        details.pack(fill="both", expand=False, padx=10, pady=(0, 10))

        self.var_detail_title = tk.StringVar(value="Selecione um tecido na lista abaixo...")
        ttk.Label(details, textvariable=self.var_detail_title).pack(anchor="w", padx=10, pady=(8, 6))

        self.tree_Jobs = ttk.Treeview(details, columns=("end", "doc", "h", "v", "real_m"), show="headings", height=6)
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

        self.tree_blocks = ttk.Treeview(blocks_box, columns=("#", "fabric", "total_m", "Jobs", "last"), show="headings", height=12)
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

    def _get_mirror_target_cm(self) -> float:
        mode = (self.var_jpg_mode.get() or "").strip()
        if mode in ("17", "21"):
            return float(mode)

        # custom
        s = (self.var_jpg_custom.get() or "").replace(",", ".").strip()
        try:
            v = float(s)
        except Exception:
            raise ValueError("Largura personalizada inválida.")

        # limites anti-erro
        if v < 8 or v > 40:
            raise ValueError("Use entre 8 cm e 40 cm.")
        return v

    def on_set_default_jpg(self):
        try:
            cm = self._get_mirror_target_cm()
        except Exception as e:
            messagebox.showerror("JPG", str(e))
            return

        self.cfg["mirror_jpg_width_mode"] = self.var_jpg_mode.get()
        self.cfg["mirror_jpg_width_cm_custom"] = float(cm)
        save_cfg(self.cfg)
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

        ttk.Label(win, text="Esses logs são de qual máquina?").pack(padx=12, pady=(12, 6), anchor="w")

        var = tk.StringVar(value="M1")
        frm = ttk.Frame(win)
        frm.pack(padx=12, pady=6, anchor="w")
        for m in ("M1", "M2"):
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

    # --------------------------
    # Drag & drop
    # --------------------------
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
            messagebox.showwarning("Sem .txt", "Solte/seleciona apenas arquivos .txt.")
            return

        # Import incremental:
        # - Se já existe máquina definida, não pergunta de novo
        # - Não apaga import anterior
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

        # Dedupe por caminho completo (evita reimportar o mesmo arquivo)
        existing_src = set(j.src_file for j in self.Jobs) if self.Jobs else set()

        for p in txts:
            p_full = str(p)
            if p_full in existing_src:
                continue

            j = parse_log_txt(p_full)
            if not j:
                skipped_invalid += 1
                continue

            # Valida HeightMM
            if j.height_mm <= 0:
                skipped_invalid += 1
                continue

            # Recalcula real_m (sanity check explícita)
            correct_real_m = j.height_mm / 1000.0
            if abs(j.real_m - correct_real_m) > 0.001:
                skipped_invalid += 1
                continue

            parsed.append(j)
            existing_src.add(j.src_file)

        if not parsed and not self.Jobs:
            messagebox.showerror("Falha", "Nenhum log válido encontrado.")
            return

        # Merge incremental
        if parsed:
            self.Jobs.extend(parsed)

        self.blocks = build_blocks(self.Jobs, machine)

        self.refresh_blocks()
        self.clear_details()

        extra = f" | Ignorados: {skipped_invalid}" if skipped_invalid else ""
        added = f" | +{len(parsed)} novos" if parsed else " | +0 novos"
        self.status.configure(
            text=f"Importado total: {len(self.Jobs)} logs{added} | Blocos: {len(self.blocks)} | Máquina: {machine}{extra}"
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
        for idx, b in enumerate(self.blocks, start=1):
            self.tree_blocks.insert(
                "",
                "end",
                iid=str(idx - 1),
                values=(
                    idx,
                    b.fabric,
                    f"{_round_up_cm(b.total_m):.2f} m",
                    b.job_count,
                    b.newest_end.strftime("%d/%m/%Y %H:%M:%S"),
                ),
            )

    def clear_details(self):
        self.var_detail_title.set("Selecione um tecido na lista abaixo...")
        self.tree_Jobs.delete(*self.tree_Jobs.get_children())

    def on_select_block(self, _evt=None):
        sel = self.tree_blocks.selection()
        if not sel:
            return
        bi = int(sel[0])
        if bi < 0 or bi >= len(self.blocks):
            return
        b = self.blocks[bi]

        title = (
            f"Tecido: {b.fabric} | Máquina: {b.machine} | Pedidos: {b.job_count} | "
            f"Total: {_round_up_cm(b.total_m):.2f} m | "
            f"{b.newest_end.strftime('%d/%m/%Y %H:%M:%S')} → {b.oldest_end.strftime('%d/%m/%Y %H:%M:%S')}"
        )
        self.var_detail_title.set(title)

        self.tree_Jobs.delete(*self.tree_Jobs.get_children())
        for j in sorted(b.Jobs, key=lambda jj: jj.end_time, reverse=True):
            self.tree_Jobs.insert(
                "",
                "end",
                values=(
                    j.end_time.strftime("%d/%m/%Y %H:%M:%S"),
                    j.document,
                    f"{j.height_mm:.1f}",
                    f"{j.vpos_mm:.1f}",
                    f"{_round_up_cm(j.real_m):.2f}",
                ),
            )

    # --------------------------
    # Export
    # --------------------------
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

        if not _HAS_PYMUPDF:
            messagebox.showerror("Dependência faltando", "Instale pymupdf: pip install pymupdf")
            return

        if not _HAS_PIL:
            messagebox.showerror("Dependência faltando", "Instale pillow: pip install pillow")
            return

        roll = self._get_roll_name()
        mode = self.var_mode.get()
        mode_tag = "FULL" if mode == "full" else "SUMMARY"

        out_dir = self._get_export_dir()

        # Nomes finais
        normal_path = str(out_dir / f"{roll}_{mode_tag}_roll.pdf")
        mirror_path = str(out_dir / f"{roll}_{mode_tag}_roll.jpg")  # espelhado é JPG

        # PDF temporário (espelhado) para gerar JPG
        tmp_mirror_pdf = str(out_dir / f"{roll}_{mode_tag}_roll.tmp.pdf")

        # parâmetros do JPG (calcula 1 vez e reutiliza)
        target_cm = float(self._get_mirror_target_cm())
        dpi = int(self.cfg.get("mirror_jpg_dpi", 300))

        # Validação de integridade
        for j in self.Jobs:
            if j.height_mm <= 0:
                messagebox.showerror("Dados inválidos", f"HeightMM inválido no job: {j.document}")
                return
            if abs(j.real_m - (j.height_mm / 1000.0)) > 0.001:
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
            messagebox.showerror("Erro ao exportar", str(e))
            return

        # -------------------------
        # Registro no banco
        # -------------------------
        try:
            orders = [
                OrderRow(
                    end_time=j.end_time.isoformat(timespec="seconds"),
                    document=j.document,
                    fabric=j.fabric,
                    height_mm=float(j.height_mm),
                    vpos_mm=float(j.vpos_mm),
                    real_m=float(j.real_m),
                    source_path=j.src_file,
                )
                for j in self.Jobs
            ]

            payload = {
                "which": which,
                "output_dir": str(out_dir),
                "normal_path": normal_path if which in ("normal", "both") else None,
                "mirror_path": mirror_path if which in ("mirror", "both") else None,
                "mirror_width_cm": (target_cm if which in ("mirror", "both") else None),
                "mirror_dpi": (dpi if which in ("mirror", "both") else None),
            }

            roll_id = save_export_transactional(
                machine=self.machine,
                roll_name=roll,
                export_mode=mode,
                app_version="dev",
                orders=orders,
                event_type="EXPORT_ROLL",
                event_payload=payload,
            )

            self.status.configure(text=self.status.cget("text") + f" | DB ok (roll_id={roll_id})")

        except Exception as e:
            self.status.configure(text=self.status.cget("text") + f" | DB erro: {type(e).__name__}")

        # -------------------------
        # Mensagem final
        # -------------------------
        if which == "both":
            messagebox.showinfo(
                "Exportado",
                f"Arquivos gerados em:\n{out_dir}\n\n"
                f"{Path(normal_path).name}\n"
                f"{Path(mirror_path).name}"
            )
        elif which == "normal":
            messagebox.showinfo("Exportado", f"Arquivo gerado em:\n{out_dir}\n\n{Path(normal_path).name}")
        else:
            messagebox.showinfo("Exportado", f"Arquivo gerado em:\n{out_dir}\n\n{Path(mirror_path).name}")

def build_ui(parent):
    return PXPrintLogsUI(parent)