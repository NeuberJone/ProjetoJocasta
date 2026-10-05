# modules/planejador.py
from __future__ import annotations

import csv
import json
import os
import re
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from core.fabric_scraps import (
    FabricScrap,
    add_or_update_scrap,
    load_scraps,
    remove_scrap,
    save_scraps,
    set_scrap_used,
    unused_scraps_for_fabric,
)
from core.printers import Printer, find_printer_by_display_name, load_printers
from core.config import (
    load_config as load_pxcore_config,
    module_config_path,
    read_module_cfg,
    write_module_cfg,
)
from core.migrate import migrate_legacy_path
from core.paths import pdf_rolls_dir, print_jpg_dir, temp_module_dir
from core.printlogs_db import (
    OrderRow,
    get_roll_scrap_key,
    next_roll_sequence,
    save_export_transactional,
    update_roll_orders,
)
from core.version import APP_VERSION
from modules.operacao.exporters import mirror_and_normal_to_jpg_scaled, pdf_all_pages_to_jpg_scaled
from modules.operacao.parser import pedido_from_document

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
    Image.MAX_IMAGE_PIXELS = None  # evita "decompression bomb"
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None
    _HAS_PIL = False

try:
    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    _HAS_REPORTLAB = True
except Exception:
    pdf_canvas = None
    A4 = None
    pdfmetrics = None
    _HAS_REPORTLAB = False

try:
    from tkinterdnd2 import DND_FILES  # type: ignore
    _HAS_DND = True
except Exception:
    DND_FILES = None
    _HAS_DND = False

MODULE_NAME = "Planejador"


# -----------------------------
# Helpers
# -----------------------------
def _round_up_cm(m: float) -> float:
    if m <= 0:
        return 0.0
    cm = m * 100.0
    cm_up = int(cm) if abs(cm - int(cm)) < 1e-9 else int(cm) + 1
    return cm_up / 100.0


def fmt_m(m: float) -> str:
    return f"{_round_up_cm(m):.2f} m"


def fmt_min(minutes: float) -> str:
    if minutes <= 0:
        return "0 min"
    total = int(round(minutes))
    h = total // 60
    m = total % 60
    return f"{h}h {m:02d}m" if h else f"{m} min"


def px_to_m(px: int, dpi: float) -> float:
    return (px / dpi) * 0.0254 if dpi > 0 else 0.0


def safe_float(s: str, default: float) -> float:
    try:
        return float(str(s).replace(",", "."))
    except Exception:
        return default


# -----------------------------
# Pastas de exportação (mesma estrutura do PXPrintLogs)
# -----------------------------
def _pxcore_base_dir() -> Path:
    cfg = load_pxcore_config()
    return Path(getattr(cfg, "base_dir", None) or r"C:\PXCore")


def pdf_dir(dt: datetime) -> Path:
    return pdf_rolls_dir(_pxcore_base_dir(), MODULE_NAME, dt)


def jpg_dir(dt: datetime) -> Path:
    return print_jpg_dir(_pxcore_base_dir(), MODULE_NAME, dt)


def temp_dir() -> Path:
    return temp_module_dir(_pxcore_base_dir(), MODULE_NAME)


def sanitize_filename(name: str) -> str:
    bad = r'\/:*?"<>|'
    for ch in bad:
        name = name.replace(ch, "_")
    name = re.sub(r"\s+", " ", name).strip()
    return name


def versioned_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    m = re.search(r"_v(\d+)$", stem, flags=re.IGNORECASE)
    base = stem[: m.start()] if m else stem
    n = 2
    while True:
        cand = path.with_name(f"{base}_v{n}{path.suffix}")
        if not cand.exists():
            return cand
        n += 1


# -----------------------------
# Tecidos (cadastro + aliases)
# -----------------------------
def _fabrics_store_path() -> Path:
    appdata = Path(os.environ.get("APPDATA") or str(Path.home()))
    base = appdata / "Nexor" / "Planejador"
    migrate_legacy_path(appdata / "ProjetoJocasta" / "PXPrintCalc", base)
    base.mkdir(parents=True, exist_ok=True)
    return base / "fabrics.json"


DEFAULT_ROLL_LENGTH_M = 60.0

# Cada tecido é um dict: {"aliases": [...], "roll_length_m": float}
FabricEntry = Dict[str, object]


def fabric_aliases(entry: FabricEntry) -> List[str]:
    v = entry.get("aliases") if isinstance(entry, dict) else None
    return [str(x) for x in v] if isinstance(v, list) else []


def fabric_roll_length(entry: FabricEntry) -> float:
    v = entry.get("roll_length_m") if isinstance(entry, dict) else None
    try:
        v = float(v)
        return v if v > 0 else DEFAULT_ROLL_LENGTH_M
    except Exception:
        return DEFAULT_ROLL_LENGTH_M


def _default_fabrics() -> Dict[str, FabricEntry]:
    base = {
        "Dryfit": (["dryfit", "dry fit", "dry-fit", "drifit"], 90.0),
        "Ribana": (["ribana"], DEFAULT_ROLL_LENGTH_M),
        "Elastano": (["elastano"], 60.0),
        "Poliamida": (["poliamida"], DEFAULT_ROLL_LENGTH_M),
        "Crepe": (["crepe"], DEFAULT_ROLL_LENGTH_M),
        "Malha": (["malha"], DEFAULT_ROLL_LENGTH_M),
        "Helanca": (["helanca"], DEFAULT_ROLL_LENGTH_M),
        "Tactel": (["tactel"], DEFAULT_ROLL_LENGTH_M),
        "Microfibra": (["microfibra"], DEFAULT_ROLL_LENGTH_M),
        "Aeroready": (["aeroready", "aero ready", "aero-ready"], DEFAULT_ROLL_LENGTH_M),
        "Oxford": (["oxford"], DEFAULT_ROLL_LENGTH_M),
        "Faixa de Capitão": (["Faixa de Capitão", "faixa cap"], DEFAULT_ROLL_LENGTH_M),
        "DryX": (["dryx", "dry x"], DEFAULT_ROLL_LENGTH_M),
        "Jaquard Corinthians": (["CORINTHIANS"], DEFAULT_ROLL_LENGTH_M),
        "Telinha": (["telinha"], DEFAULT_ROLL_LENGTH_M),
    }
    return {
        name: {"aliases": aliases, "roll_length_m": roll_m}
        for name, (aliases, roll_m) in base.items()
    }


def _normalize_fabrics(data: Dict[str, object]) -> Dict[str, FabricEntry]:
    """Aceita o formato antigo (lista de aliases) e o novo (dict com aliases/roll_length_m)."""
    out: Dict[str, FabricEntry] = {}
    for k, v in data.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, dict):
            out[k] = {
                "aliases": fabric_aliases(v),
                "roll_length_m": fabric_roll_length(v),
            }
        elif isinstance(v, list):
            default_roll = 90.0 if k.strip().lower() == "dryfit" else DEFAULT_ROLL_LENGTH_M
            out[k] = {
                "aliases": [str(x) for x in v if str(x).strip()],
                "roll_length_m": default_roll,
            }
        else:
            out[k] = {"aliases": [], "roll_length_m": DEFAULT_ROLL_LENGTH_M}
    return out


def save_fabrics(data: Dict[str, FabricEntry]) -> None:
    p = _fabrics_store_path()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _legacy_fabrics_path() -> Path:
    # Local antigo (quebrava em build congelado via PyInstaller; mantido só para migração)
    return Path(__file__).with_suffix(".fabrics.json")


def load_fabrics() -> Dict[str, FabricEntry]:
    p = _fabrics_store_path()
    if not p.exists():
        legacy = _legacy_fabrics_path()
        if legacy.exists():
            try:
                legacy_data = json.loads(legacy.read_text(encoding="utf-8"))
                if isinstance(legacy_data, dict) and legacy_data:
                    normalized = _normalize_fabrics(legacy_data)
                    save_fabrics(normalized)
                    return normalized
            except Exception:
                pass

        data = _default_fabrics()
        save_fabrics(data)
        return data
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw:
            return _normalize_fabrics(raw)
        raise ValueError("vazio")
    except Exception:
        data = _default_fabrics()
        save_fabrics(data)
        return data


_DASHES = ["–", "—", "-", "-"]  # en dash, em dash, hyphen, non-breaking hyphen


def _normalize_name(s: str) -> str:
    s = (s or "").lower()
    for d in _DASHES:
        s = s.replace(d, "-")
    s = s.replace("_", " ")
    s = s.replace(".", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def infer_fabric_from_filename(filename: str, fabrics_map: Dict[str, FabricEntry]) -> str:
    s = _normalize_name(filename)
    parts = re.split(r"[\s\-]+", s)
    tokens = [p.strip() for p in parts if p.strip()]

    alias_index: Dict[str, str] = {}
    for canonical, entry in fabrics_map.items():
        alias_index[_normalize_name(canonical)] = canonical
        for a in fabric_aliases(entry):
            alias_index[_normalize_name(a)] = canonical

    # token exato
    for t in tokens:
        if t in alias_index:
            return alias_index[t]

    # substring
    for alias, canonical in alias_index.items():
        if alias and alias in s:
            return canonical

    return "Outro"


def safe_image_size(path: Path) -> Tuple[int, int]:
    if not _HAS_PIL:
        raise RuntimeError("Instale pillow: pip install pillow")
    with Image.open(path) as im:
        return im.size


# -----------------------------
# Data
# -----------------------------
@dataclass
class Job:
    name: str
    path: Optional[Path]
    fabric: str
    w_px: int
    h_px: int
    dpi_override: Optional[float] = None
    length_m: float = 0.0
    time_min: float = 0.0
    is_gap: bool = False
    roll_no: int = 0
    hidden: bool = False
    gap_index: Optional[int] = None


# Pixels "fictícios" usados para recriar um Job a partir de uma metragem já
# conhecida (ex.: vindo do banco, ao reabrir um rolo já registrado para
# edição) — o banco só guarda o comprimento final, não os pixels/DPI
# originais da imagem. w_px=h_px=_PRESERVE_PX junto com o dpi_override
# calibrado abaixo faz compute_length reproduzir exatamente esse
# comprimento, em qualquer eixo (altura/largura/maior) e sem depender do
# arquivo de imagem original ainda existir.
_PRESERVE_PX = 100_000


def job_from_known_length(name: str, path: Optional[Path], fabric: str, length_m: float) -> "Job":
    length_m = float(length_m or 0.0)
    if length_m > 0:
        dpi_override = (_PRESERVE_PX * 0.0254) / length_m
    else:
        dpi_override = None
    return Job(
        name=name,
        path=path,
        fabric=fabric,
        w_px=_PRESERVE_PX,
        h_px=_PRESERVE_PX,
        dpi_override=dpi_override,
        length_m=length_m,
    )


# -----------------------------
# Export PDF / JPG espelhado (mesmo padrão do PXPrintLogs)
# -----------------------------
def _pdf_wrap_text(text: str, max_width: float, font_name: str, font_size: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return [""]
    if pdfmetrics is None:
        return [text]

    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        test = word if not current else f"{current} {word}"
        if pdfmetrics.stringWidth(test, font_name, font_size) <= max_width:
            current = test
            continue
        if current:
            lines.append(current)
        if pdfmetrics.stringWidth(word, font_name, font_size) <= max_width:
            current = word
            continue
        chunk = ""
        for ch in word:
            test_chunk = chunk + ch
            if pdfmetrics.stringWidth(test_chunk, font_name, font_size) <= max_width:
                chunk = test_chunk
            else:
                if chunk:
                    lines.append(chunk)
                chunk = ch
        current = chunk
    if current:
        lines.append(current)
    return lines


def _pdf_truncate(text: str, max_width: float, font_name: str, font_size: int) -> str:
    text = (text or "").strip()
    if not text or pdfmetrics is None:
        return text
    if pdfmetrics.stringWidth(text, font_name, font_size) <= max_width:
        return text

    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = text[:mid] + ell
        if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + ell) if lo < len(text) else text


def _pdf_need_new_page(y: float, min_y: float = 60) -> bool:
    return y < min_y


def _pdf_draw_header(c, title: str, machine: str, mode: str, page_w: float, top_y: float) -> float:
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, top_y, title)

    c.setFont("Helvetica", 10)
    c.drawString(
        40, top_y - 18,
        f"Máquina: {machine}    Modo: {'Completo' if mode == 'full' else 'Resumido'}    "
        f"Gerado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
    )
    c.line(40, top_y - 26, page_w - 40, top_y - 26)
    return top_y - 40


def _group_by_roll(rows: List["Job"]) -> Tuple[List[int], Dict[int, List["Job"]]]:
    roll_order: List[int] = []
    by_roll: Dict[int, List[Job]] = {}
    for r in rows:
        if not r.roll_no:
            continue
        rn = int(r.roll_no)
        if rn not in by_roll:
            by_roll[rn] = []
            roll_order.append(rn)
        by_roll[rn].append(r)
    return roll_order, by_roll


def _build_order_rows(roll_rows: List["Job"], export_time_iso: str) -> Tuple[List[OrderRow], float]:
    """Monta as OrderRow (para gravar no banco) de um único rolo e retorna
    também a metragem total do rolo (itens + gaps), usada na reconciliação
    de pedaço cortado ao atualizar um rolo editado."""
    order_rows: List[OrderRow] = []
    cumulative_mm = 0.0
    total_m = 0.0
    for x in roll_rows:
        length_mm = float(x.length_m * 1000.0)
        total_m += x.length_m
        if x.is_gap:
            cumulative_mm += length_mm
            continue
        order_rows.append(OrderRow(
            end_time=export_time_iso,
            document=x.name,
            fabric=x.fabric,
            pedido=pedido_from_document(x.name),
            height_mm=length_mm,
            vpos_mm=cumulative_mm,
            real_m=float(x.length_m),
            source_path=str(x.path) if x.path else "",
        ))
        cumulative_mm += length_mm
    return order_rows, total_m


def _roll_blocks(roll_rows: List["Job"]) -> List[Tuple[str, float, float, int]]:
    blocks: List[Tuple[str, float, float, int]] = []
    cur_fab, cur_m, cur_t, cur_n = "", 0.0, 0.0, 0

    def flush():
        nonlocal cur_fab, cur_m, cur_t, cur_n
        if cur_n > 0:
            blocks.append((cur_fab, cur_m, cur_t, cur_n))
        cur_fab, cur_m, cur_t, cur_n = "", 0.0, 0.0, 0

    prev_fab: Optional[str] = None
    for x in roll_rows:
        if x.is_gap:
            flush()
            prev_fab = None
            continue
        if prev_fab is None or x.fabric != prev_fab:
            flush()
            cur_fab = x.fabric
        cur_m += x.length_m
        cur_t += x.time_min
        cur_n += 1
        prev_fab = x.fabric
    flush()
    return blocks


def _pdf_draw_roll_summary(
    c, roll_order, by_roll, y, page_w, page_h, title, machine, mode, mirrored,
    scrap_labels: Optional[Dict[int, str]] = None,
) -> float:
    scrap_labels = scrap_labels or {}
    w_num, w_fab, w_scrap, w_blocks, w_items, w_total, w_time = 28, 95, 125, 45, 40, 75, 75
    font, font_bold, fs = "Helvetica", "Helvetica-Bold", 10

    def header(y0: float) -> float:
        c.setFont(font_bold, 12)
        c.drawString(40, y0, "Resumo por rolo")
        y0 -= 16
        c.setFont(font, 10)
        c.line(40, y0, page_w - 40, y0)
        y0 -= 18
        c.setFont(font_bold, fs)
        x = 40
        c.drawString(x, y0, "Rolo"); x += w_num
        c.drawString(x, y0, "Tecido (rolo)"); x += w_fab
        c.drawString(x, y0, "Pedaço cortado"); x += w_scrap
        c.drawCentredString(x + w_blocks / 2, y0, "Blocos"); x += w_blocks
        c.drawCentredString(x + w_items / 2, y0, "Itens"); x += w_items
        c.drawCentredString(x + w_total / 2, y0, "Total (m)"); x += w_total
        c.drawCentredString(x + w_time / 2, y0, "Tempo")
        y0 -= 14
        c.setFont(font, fs)
        return y0

    def new_page(y0: float) -> float:
        if mirrored:
            c.restoreState()
        c.showPage()
        if mirrored:
            c.saveState()
            c.transform(-1, 0, 0, 1, page_w, 0)
        y0 = page_h - 40
        y0 = _pdf_draw_header(c, title, machine, mode, page_w, y0)
        return header(y0)

    y = header(y)
    total_m = 0.0
    total_t = 0.0

    for rn in roll_order:
        rr = by_roll[rn]
        jobs_only = [x for x in rr if not x.is_gap]
        roll_m = sum(x.length_m for x in rr)
        roll_t = sum(x.time_min for x in rr)
        blocks = _roll_blocks(rr)
        total_m += roll_m
        total_t += roll_t

        fab_count: Dict[str, int] = {}
        for x in jobs_only:
            fab_count[x.fabric] = fab_count.get(x.fabric, 0) + 1
        main_fab = max(fab_count.items(), key=lambda kv: kv[1])[0] if fab_count else "—"
        scrap_txt = _pdf_truncate(scrap_labels.get(rn, ""), w_scrap - 6, font, fs)

        if _pdf_need_new_page(y, min_y=85):
            y = new_page(y)

        x = 40
        c.drawString(x, y, str(rn)); x += w_num
        c.drawString(x, y, main_fab); x += w_fab
        c.drawString(x, y, scrap_txt); x += w_scrap
        c.drawCentredString(x + w_blocks / 2, y, str(len(blocks))); x += w_blocks
        c.drawCentredString(x + w_items / 2, y, str(len(jobs_only))); x += w_items
        c.drawCentredString(x + w_total / 2, y, fmt_m(roll_m)); x += w_total
        c.drawCentredString(x + w_time / 2, y, fmt_min(roll_t))
        y -= 14

    if _pdf_need_new_page(y, min_y=85):
        y = new_page(y)

    y -= 6
    c.setLineWidth(1)
    c.line(40, y, page_w - 40, y)
    y -= 18

    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Total geral:")
    c.drawRightString(page_w - 40, y, f"{fmt_m(total_m)}   |   {fmt_min(total_t)}")
    c.setFont("Helvetica", 10)
    y -= 18
    return y


def _pdf_draw_items(c, roll_order, by_roll, y, page_w, page_h, title, machine, mode, mirrored) -> float:
    w_roll, w_fab, w_doc, w_size, w_time = 40, 110, 280, 70, 70
    font, font_bold, fs, line_h = "Helvetica", "Helvetica-Bold", 10, 12

    def header(y0: float) -> float:
        c.setFont(font_bold, 12)
        c.drawString(40, y0, "Pedidos (último da fila primeiro)")
        y0 -= 16
        c.setFont(font, 10)
        c.line(40, y0, page_w - 40, y0)
        y0 -= 18
        c.setFont(font_bold, fs)
        x = 40
        c.drawString(x, y0, "Rolo"); x += w_roll
        c.drawString(x, y0, "Tecido"); x += w_fab
        c.drawString(x, y0, "Arquivo"); x += w_doc
        c.drawString(x, y0, "Tamanho"); x += w_size
        c.drawString(x, y0, "Tempo")
        y0 -= 14
        c.setFont(font, fs)
        return y0

    def new_page(y0: float) -> float:
        if mirrored:
            c.restoreState()
        c.showPage()
        if mirrored:
            c.saveState()
            c.transform(-1, 0, 0, 1, page_w, 0)
        y0 = page_h - 40
        y0 = _pdf_draw_header(c, title, machine, mode, page_w, y0)
        return header(y0)

    y = header(y)

    for ri, rn in enumerate(roll_order):
        rr = by_roll[rn]
        jobs_only = [x for x in rr if not x.is_gap]

        if ri > 0:
            if _pdf_need_new_page(y, min_y=95):
                y = new_page(y)
            c.setLineWidth(1)
            c.line(40, y + 6, page_w - 40, y + 6)
            y -= 8

        for x in jobs_only:
            doc_lines = _pdf_wrap_text(x.name, w_doc - 6, font, fs)
            row_h = max(len(doc_lines), 1) * line_h

            if _pdf_need_new_page(y - row_h, min_y=95):
                y = new_page(y)

            x0 = 40
            c.setFont(font, fs)
            c.drawString(x0, y, str(rn))
            c.drawString(x0 + w_roll, y, x.fabric)

            yy = y
            for dl in doc_lines:
                c.drawString(x0 + w_roll + w_fab, yy, dl)
                yy -= line_h

            c.drawRightString(x0 + w_roll + w_fab + w_doc + w_size - 2, y, fmt_m(x.length_m))
            c.drawRightString(x0 + w_roll + w_fab + w_doc + w_size + w_time - 2, y, fmt_min(x.time_min))
            y -= row_h

    return y


def export_queue_pdf(
    out_path: "str | Path",
    rows: List["Job"],
    title: str,
    machine: str,
    mode: str = "full",
    mirrored: bool = False,
    scrap_labels: Optional[Dict[int, str]] = None,
) -> None:
    if not _HAS_REPORTLAB or pdf_canvas is None or A4 is None:
        raise RuntimeError("reportlab não está instalado. Instale: pip install reportlab")

    # Ordem invertida no PDF (último item da fila aparece primeiro), igual ao PXPrintLogs
    roll_order, by_roll = _group_by_roll(list(reversed(rows)))
    if not roll_order:
        raise RuntimeError("Fila vazia — gere a fila (tecido/rolo) antes de exportar.")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    page_w, page_h = A4
    c = pdf_canvas.Canvas(str(out_path), pagesize=A4)

    def begin_page():
        if mirrored:
            c.saveState()
            c.transform(-1, 0, 0, 1, page_w, 0)

    def end_page():
        if mirrored:
            c.restoreState()
        c.showPage()

    y = page_h - 40
    begin_page()
    y = _pdf_draw_header(c, title, machine, mode, page_w, y)

    if mode == "summary":
        _pdf_draw_roll_summary(
            c, roll_order, by_roll, y, page_w, page_h, title, machine, mode, mirrored,
            scrap_labels=scrap_labels,
        )
        end_page()
        c.save()
        return

    y = _pdf_draw_items(c, roll_order, by_roll, y, page_w, page_h, title, machine, mode, mirrored)

    y -= 6
    if _pdf_need_new_page(y, min_y=120):
        end_page()
        begin_page()
        y = page_h - 40
        y = _pdf_draw_header(c, title, machine, mode, page_w, y)

    c.setLineWidth(1.5)
    c.line(40, y, page_w - 40, y)
    y -= 22

    _pdf_draw_roll_summary(
        c, roll_order, by_roll, y, page_w, page_h, title, machine, mode, mirrored,
        scrap_labels=scrap_labels,
    )

    end_page()
    c.save()


# -----------------------------
# MAIN ENTRY
# -----------------------------
def build_ui(parent: tk.Widget, *, preload: Optional[dict] = None):
    frame = ttk.Frame(parent, padding=10)
    frame.pack(fill="both", expand=True)

    # Container rolável: em telas pequenas o conteúdo (em especial o painel
    # "Pedidos sendo impressos", no fim) não cabia na altura da janela.
    canvas = tk.Canvas(frame, highlightthickness=0)
    vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
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

    jobs: List[Job] = []
    view_rows: List[Job] = []
    roll_scrap_labels: Dict[int, str] = {}
    roll_scrap_keys: Dict[int, str] = {}
    # None = todos os pedaços não usados são elegíveis (padrão/compatibilidade).
    # Quando o usuário usa "Selecionar pedaços a usar…", vira o conjunto exato
    # de chaves marcadas — útil quando há pedaços do mesmo tecido vindos de
    # fabricantes/lotes diferentes que não podem se misturar num rolo.
    selected_scrap_keys: Optional[set] = None
    # Override manual do tamanho de um espaço específico (duplo clique na
    # linha "— ESPAÇO —"), por posição sequencial entre os espaços visíveis
    # (gap_between/gap_endroll) — recalculado a cada "Gerar Fila".
    gap_overrides: Dict[int, float] = {}
    gap_seq: int = 0
    edit_roll_id: Optional[int] = (preload or {}).get("edit_roll_id")
    last_view: str = "base"
    last_roll_summary_rows: List[Job] = []
    last_pedidos_rows: List[Job] = []

    fabrics_map: Dict[str, List[str]] = load_fabrics()
    scraps: List[FabricScrap] = load_scraps()

    migrate_legacy_path(module_config_path("PXPrintCalc"), module_config_path(MODULE_NAME))
    mcfg = read_module_cfg(MODULE_NAME, {
        "report_mode_default": "full",
        "mirror_jpg_width_mode": "17",
        "mirror_jpg_width_cm_custom": 17.0,
        "mirror_jpg_dpi": 300,
    })

    manual_fabric_order: List[str] = []
    var_auto_fabric_order = tk.BooleanVar(value=True)
    var_use_scraps = tk.BooleanVar(value=False)
    # Sangria: ao planejar com pedaços cortados, considera cada pedaço com
    # alguns cm a mais do que a metragem cadastrada (tolerância de corte).
    var_scrap_bleed = tk.BooleanVar(value=False)
    var_scrap_bleed_cm = tk.StringVar(value="5")

    printers: List[Printer] = load_printers()

    def _printer_options() -> List[str]:
        return [p.display_name for p in printers] or ["(nenhuma cadastrada)"]

    var_printer = tk.StringVar(value=_printer_options()[0])

    var_dpi = tk.StringVar(value="150")
    var_axis = tk.StringVar(value="altura")
    var_speed = tk.StringVar(
        value=f"{printers[0].speed_m_min:.2f}" if printers else "1.50"
    )
    var_setup = tk.StringVar(value="2")

    # ✅ padrão: modo tecido
    var_mode = tk.StringVar(value="tecido")
    var_gap_between = tk.StringVar(value="1.00")
    var_gap_endroll = tk.StringVar(value="1.00")
    var_gap_files = tk.StringVar(value="0.00")
    var_roll_other = tk.StringVar(value=str(int(DEFAULT_ROLL_LENGTH_M)))

    var_batch_name = tk.StringVar(value="")
    var_report_mode = tk.StringVar(value=mcfg.get("report_mode_default", "full"))
    var_jpg_mode = tk.StringVar(value=mcfg.get("mirror_jpg_width_mode", "17"))
    var_jpg_custom = tk.StringVar(value=str(mcfg.get("mirror_jpg_width_cm_custom", 17.0)))
    var_use_printer_jpg_path = tk.BooleanVar(value=False)

    fabric_options = sorted(set(list(fabrics_map.keys()) + ["Outro"]))
    var_fabric_pick = tk.StringVar(value="Dryfit" if "Dryfit" in fabric_options else fabric_options[0])

    # ---------------- UI TOP ----------------
    top = ttk.Frame(body)
    top.pack(fill="x")

    ttk.Button(top, text="Importar imagens", command=lambda: import_images()).pack(side="left")
    ttk.Button(top, text="Recalcular (DPI/Vel/Setup)", command=lambda: recalc_all()).pack(side="left", padx=6)
    ttk.Button(top, text="Gerar Fila (Tecidos/Rolos)", command=lambda: generate_queue()).pack(side="left", padx=6)
    ttk.Button(top, text="Exportar CSV", command=lambda: export_csv()).pack(side="left", padx=6)

    ttk.Button(top, text="Salvar lista…", command=lambda: on_save_list()).pack(side="left", padx=6)
    ttk.Button(top, text="Importar lista…", command=lambda: on_import_list()).pack(side="left", padx=6)

    ttk.Button(top, text="Tecidos…", command=lambda: open_fabrics_dialog()).pack(side="left", padx=6)
    ttk.Button(top, text="Ordem dos tecidos…", command=lambda: open_fabric_order_dialog()).pack(side="left", padx=6)
    ttk.Button(top, text="Pedaços de tecido…", command=lambda: open_scraps_dialog()).pack(side="left", padx=6)
    ttk.Button(top, text="Limpar", command=lambda: clear_all()).pack(side="left", padx=6)

    var_edit_banner = tk.StringVar(value="")
    lbl_edit_banner = ttk.Label(body, textvariable=var_edit_banner, foreground="#8a4b00")
    lbl_edit_banner.pack(fill="x", pady=(4, 0))

    # ---------------- Drag & drop (arrastar imagens para importar) ----------------
    drop_frame = ttk.LabelFrame(body, text="Arraste e solte imagens aqui")
    drop_frame.pack(fill="x", pady=(8, 0))

    drop_label = ttk.Label(drop_frame, text="Solte arquivos de imagem (jpg/png/bmp/tif) para importar")
    drop_label.pack(fill="x", padx=10, pady=10)

    if _HAS_DND:
        try:
            drop_label.drop_target_register(DND_FILES)  # type: ignore
            drop_label.dnd_bind("<<Drop>>", lambda e: on_drop_files(e))  # type: ignore
        except Exception:
            pass
    else:
        drop_label.configure(
            text="Drag & Drop indisponível (tkinterdnd2 não carregou). Use o botão Importar imagens."
        )

    ttk.Separator(body).pack(fill="x", pady=10)

    # Config row
    config = ttk.Frame(body)
    config.pack(fill="x")

    ttk.Label(config, text="DPI:").pack(side="left")
    ttk.Entry(config, width=8, textvariable=var_dpi).pack(side="left", padx=5)

    ttk.Label(config, text="Eixo:").pack(side="left")
    ttk.Combobox(
        config, width=10, values=["altura", "largura", "maior"],
        state="readonly", textvariable=var_axis
    ).pack(side="left", padx=5)

    ttk.Label(config, text="Impressora:").pack(side="left")
    cb_printer = ttk.Combobox(
        config, width=14, values=_printer_options(),
        state="readonly", textvariable=var_printer
    )
    cb_printer.pack(side="left", padx=5)

    def on_printer_selected(_evt=None):
        pr = next((p for p in printers if p.display_name == var_printer.get()), None)
        if pr:
            var_speed.set(f"{pr.speed_m_min:.2f}")

    def refresh_printers():
        nonlocal printers
        printers = load_printers()
        options = _printer_options()
        cb_printer.config(values=options)
        if var_printer.get() not in options:
            var_printer.set(options[0])
        on_printer_selected()

    cb_printer.bind("<<ComboboxSelected>>", on_printer_selected)
    ttk.Button(config, text="↻", width=3, command=refresh_printers).pack(side="left", padx=(0, 5))

    ttk.Label(config, text="Vel (m/min):").pack(side="left")
    ttk.Entry(config, width=8, textvariable=var_speed).pack(side="left", padx=5)

    ttk.Label(config, text="Setup (min/job):").pack(side="left")
    ttk.Entry(config, width=8, textvariable=var_setup).pack(side="left", padx=5)

    # Fabric tools row
    tools = ttk.Frame(body)
    tools.pack(fill="x", pady=(8, 0))

    ttk.Label(tools, text="Tecido:").pack(side="left")
    cb_fab = ttk.Combobox(
        tools, width=18, values=fabric_options,
        state="readonly", textvariable=var_fabric_pick
    )
    cb_fab.pack(side="left", padx=5)

    ttk.Button(
        tools,
        text="Definir tecido (selecionados)",
        command=lambda: set_fabric_selected()
    ).pack(side="left", padx=6)

    btn_move_up = ttk.Button(tools, text="▲ Mover acima", command=lambda: move_job(-1))
    btn_move_up.pack(side="left", padx=(16, 0))
    btn_move_down = ttk.Button(tools, text="▼ Mover abaixo", command=lambda: move_job(+1))
    btn_move_down.pack(side="left", padx=4)

    def refresh_fabric_options(select: Optional[str] = None):
        nonlocal fabric_options
        fabric_options = sorted(set(list(fabrics_map.keys()) + ["Outro"]))
        cb_fab.config(values=fabric_options)
        if select and select in fabric_options:
            var_fabric_pick.set(select)
        elif var_fabric_pick.get() not in fabric_options:
            var_fabric_pick.set("Dryfit" if "Dryfit" in fabric_options else fabric_options[0])

    def register_new_fabric(
        name: str,
        aliases: Optional[List[str]] = None,
        roll_length_m: Optional[float] = None,
    ) -> str:
        """Cadastra (ou atualiza) um tecido — aliases e metragem do rolo — e persiste."""
        can = name.strip()
        if not can:
            raise ValueError("Informe o nome do tecido.")

        existing = next((k for k in fabrics_map.keys() if k.lower() == can.lower()), None)
        canonical = existing or can

        entry = dict(fabrics_map.get(canonical, {}))
        current_aliases = fabric_aliases(entry)
        merged_aliases = list(dict.fromkeys(current_aliases + (aliases or [])))

        entry["aliases"] = merged_aliases
        entry["roll_length_m"] = (
            float(roll_length_m) if roll_length_m else fabric_roll_length(entry)
        )
        fabrics_map[canonical] = entry

        save_fabrics(fabrics_map)
        refresh_fabric_options(select=canonical)
        return canonical

    # Mode and planning row
    plan = ttk.Frame(body)
    plan.pack(fill="x", pady=(8, 0))

    ttk.Label(plan, text="Modo:").pack(side="left")
    ttk.Combobox(
        plan, width=12, values=["original", "tecido"],
        state="readonly", textvariable=var_mode
    ).pack(side="left", padx=5)

    def _update_reorder_controls_state(*_):
        state = "normal" if var_mode.get().strip().lower() == "original" else "disabled"
        btn_move_up.configure(state=state)
        btn_move_down.configure(state=state)

    def _on_mode_changed(*_):
        _update_reorder_controls_state()
        # Recalcula a fila ao trocar de modo — sem isso, a tabela ficava com
        # o agrupamento/alças de arraste do modo anterior até o usuário
        # clicar manualmente em "Gerar Fila".
        generate_queue()

    var_mode.trace_add("write", _on_mode_changed)
    _update_reorder_controls_state()

    ttk.Checkbutton(
        plan,
        text="Ordem automática (menores no fim)",
        variable=var_auto_fabric_order
    ).pack(side="left", padx=10)

    ttk.Label(plan, text="Gap entre tecidos (m):").pack(side="left")
    ttk.Entry(plan, width=7, textvariable=var_gap_between).pack(side="left", padx=5)

    ttk.Label(plan, text="Gap antes fim rolo (m):").pack(side="left")
    ttk.Entry(plan, width=7, textvariable=var_gap_endroll).pack(side="left", padx=5)

    ttk.Label(plan, text="Gap entre arquivos (m):").pack(side="left")
    ttk.Entry(plan, width=7, textvariable=var_gap_files).pack(side="left", padx=5)

    ttk.Label(plan, text="Padrão p/ tecido sem metragem (m):").pack(side="left")
    ttk.Entry(plan, width=6, textvariable=var_roll_other).pack(side="left", padx=5)

    ttk.Button(plan, text="Voltar visão base", command=lambda: show_base()).pack(side="left", padx=10)

    plan2 = ttk.Frame(body)
    plan2.pack(fill="x", pady=(4, 0))

    ttk.Checkbutton(
        plan2,
        text="Priorizar pedaços de tecido cortados (não usados)",
        variable=var_use_scraps,
        command=lambda: generate_queue() if var_mode.get().strip().lower() == "tecido" else None,
    ).pack(side="left")
    ttk.Button(
        plan2, text="Selecionar pedaços a usar…", command=lambda: open_scrap_selection_dialog()
    ).pack(side="left", padx=(10, 0))

    # ---------------- Exportação (PDF / JPG espelhado) ----------------
    export_box = ttk.LabelFrame(body, text="Exportação (PDF / JPG espelhado)")
    export_box.pack(fill="x", pady=(8, 0))

    exp_row1 = ttk.Frame(export_box)
    exp_row1.pack(fill="x", padx=8, pady=(8, 4))

    ttk.Label(exp_row1, text="Nome do lote:").pack(side="left")
    ttk.Entry(exp_row1, textvariable=var_batch_name, width=26).pack(side="left", padx=(6, 6))
    ttk.Button(exp_row1, text="Atualizar nome", command=lambda: on_refresh_batch_name()).pack(
        side="left", padx=(0, 16)
    )

    ttk.Label(exp_row1, text="Modo do PDF:").pack(side="left")
    ttk.Radiobutton(exp_row1, text="Completo", value="full", variable=var_report_mode).pack(
        side="left", padx=(6, 0)
    )
    ttk.Radiobutton(exp_row1, text="Resumido", value="summary", variable=var_report_mode).pack(
        side="left", padx=(6, 12)
    )
    ttk.Button(exp_row1, text="Definir como padrão", command=lambda: on_set_default_mode()).pack(
        side="left"
    )

    exp_row2 = ttk.Frame(export_box)
    exp_row2.pack(fill="x", padx=8, pady=(0, 8))

    ttk.Label(exp_row2, text="JPG espelhado:").pack(side="left")
    ttk.Radiobutton(exp_row2, text="17 cm", value="17", variable=var_jpg_mode).pack(side="left", padx=(6, 0))
    ttk.Radiobutton(exp_row2, text="21 cm", value="21", variable=var_jpg_mode).pack(side="left", padx=(6, 0))
    ttk.Radiobutton(exp_row2, text="Personalizado", value="custom", variable=var_jpg_mode).pack(
        side="left", padx=(6, 0)
    )
    ent_jpg_custom = ttk.Entry(exp_row2, textvariable=var_jpg_custom, width=6)
    ent_jpg_custom.pack(side="left", padx=(6, 0))
    ttk.Label(exp_row2, text="cm").pack(side="left", padx=(4, 12))

    def _update_jpg_custom_state(*_):
        ent_jpg_custom.configure(state=("normal" if var_jpg_mode.get() == "custom" else "disabled"))

    _update_jpg_custom_state()
    var_jpg_mode.trace_add("write", _update_jpg_custom_state)

    ttk.Button(exp_row2, text="Definir JPG como padrão", command=lambda: on_set_default_jpg()).pack(
        side="left", padx=(0, 16)
    )

    btn_export_normal = ttk.Button(exp_row2, text="Exportar PDF Normal", command=lambda: on_export("normal"))
    btn_export_normal.pack(side="left", padx=4)
    btn_export_mirror = ttk.Button(exp_row2, text="Exportar JPG Espelhado", command=lambda: on_export("mirror"))
    btn_export_mirror.pack(side="left", padx=4)
    btn_export_both = ttk.Button(exp_row2, text="Exportar Ambos", command=lambda: on_export("both"))
    btn_export_both.pack(side="left", padx=4)

    exp_row3 = ttk.Frame(export_box)
    exp_row3.pack(fill="x", padx=8, pady=(0, 8))

    ttk.Checkbutton(
        exp_row3,
        text="Usar pasta/arquivo da impressora para o JPG espelhado",
        variable=var_use_printer_jpg_path,
    ).pack(side="left")

    # ---------------- TABLE ----------------
    table_bar = ttk.Frame(body)
    table_bar.pack(fill="x", pady=(10, 0))
    ttk.Label(table_bar, text="Fila (sequência)").pack(side="left")
    ttk.Button(
        table_bar, text="⤢ Abrir em janela", command=lambda: open_queue_window()
    ).pack(side="right")

    cols = ("drag", "roll", "fabric", "dpi", "arquivo", "w", "h", "metros", "tempo")
    tree = ttk.Treeview(body, columns=cols, show="headings")
    tree.pack(fill="both", expand=True, pady=(4, 10))

    tree.heading("drag", text="")
    tree.heading("roll", text="Rolo")
    tree.heading("fabric", text="Tecido")
    tree.heading("dpi", text="DPI(item)")
    tree.heading("arquivo", text="Arquivo")
    tree.heading("w", text="Largura px")
    tree.heading("h", text="Altura px")
    tree.heading("metros", text="Comprimento")
    tree.heading("tempo", text="Tempo")

    tree.column("drag", width=26, minwidth=26, anchor="center", stretch=False)
    tree.column("roll", width=70, anchor="center")
    tree.column("fabric", width=120, anchor="w")
    tree.column("dpi", width=70, anchor="e")
    tree.column("arquivo", width=420, anchor="w")
    tree.column("w", width=100, anchor="e")
    tree.column("h", width=100, anchor="e")
    tree.column("metros", width=120, anchor="e")
    tree.column("tempo", width=120, anchor="e")

    tree.bind("<Double-1>", lambda _e: on_double_click())
    tree.bind("<Button-3>", lambda e: show_context_menu(e))

    # ---------------- Drag & drop (reordenar pela alça à esquerda) ----------------
    drag_state: Dict[str, Optional[int]] = {"idx": None}

    def job_index_for(path: Optional[Path], name: str) -> Optional[int]:
        for i, jb in enumerate(jobs):
            if jb.path == path and jb.name == name:
                return i
        return None

    def on_tree_press(event):
        if tree.identify_region(event.x, event.y) != "cell":
            return
        if tree.identify_column(event.x) != "#1":
            return
        row_iid = tree.identify_row(event.y)
        if not row_iid:
            return
        try:
            idx = int(row_iid)
        except Exception:
            return
        if not (0 <= idx < len(view_rows)) or view_rows[idx].is_gap:
            return
        drag_state["idx"] = idx

    def on_tree_motion(event):
        if drag_state["idx"] is None:
            return
        tree.configure(cursor="fleur")
        return "break"

    def on_tree_release(event):
        start_idx = drag_state["idx"]
        drag_state["idx"] = None
        tree.configure(cursor="")
        if start_idx is None or not (0 <= start_idx < len(view_rows)):
            return

        src_row = view_rows[start_idx]
        src_job_idx = job_index_for(src_row.path, src_row.name)
        if src_job_idx is None:
            return

        target_iid = tree.identify_row(event.y)
        if not target_iid:
            dst_job_idx = len(jobs) - 1
        else:
            try:
                t_idx = int(target_iid)
            except Exception:
                return
            if t_idx == start_idx or not (0 <= t_idx < len(view_rows)):
                return
            t_row = view_rows[t_idx]
            if t_row.is_gap:
                step = 1 if t_idx > start_idx else -1
                probe = t_idx
                while 0 <= probe < len(view_rows) and view_rows[probe].is_gap:
                    probe += step
                if not (0 <= probe < len(view_rows)):
                    return
                t_row = view_rows[probe]
            dst_job_idx = job_index_for(t_row.path, t_row.name)
            if dst_job_idx is None:
                return

        if not _reorder_allowed():
            return

        item = jobs.pop(src_job_idx)
        if dst_job_idx > src_job_idx:
            dst_job_idx -= 1
        jobs.insert(dst_job_idx, item)

        if last_view == "queue":
            generate_queue()
        else:
            show_base()

        for i, row in enumerate(view_rows):
            if row.path == item.path and row.name == item.name:
                iid = str(i)
                tree.selection_set(iid)
                tree.see(iid)
                break

    tree.bind("<ButtonPress-1>", on_tree_press, add="+")
    tree.bind("<B1-Motion>", on_tree_motion, add="+")
    tree.bind("<ButtonRelease-1>", on_tree_release, add="+")

    # ---------------- SUMMARY ----------------
    summary = ttk.Frame(body)
    summary.pack(fill="x")

    lbl_count = ttk.Label(summary, text="Itens: 0")
    lbl_count.pack(side="left")

    lbl_total = ttk.Label(summary, text="Total: 0.00 m")
    lbl_total.pack(side="left", padx=16)

    lbl_time = ttk.Label(summary, text="Tempo total: 0 min")
    lbl_time.pack(side="left", padx=16)

    # ---------------- RESUMO POR ROLO (conferência) ----------------
    summary_box = ttk.LabelFrame(body, text="Resumo por rolo (conferência)")
    summary_box.pack(fill="both", expand=False, pady=(10, 0))

    summary_bar = ttk.Frame(summary_box)
    summary_bar.pack(fill="x", pady=(4, 0))
    ttk.Button(
        summary_bar, text="⤢ Abrir em janela", command=lambda: open_roll_summary_window()
    ).pack(side="right")

    cols_sum = ("roll", "fabric", "scrap", "blocks", "items", "total_m", "time")
    tree_summary = ttk.Treeview(summary_box, columns=cols_sum, show="headings", height=6)
    for col, txt, w, anchor in [
        ("roll", "Rolo", 50, "center"),
        ("fabric", "Tecido", 140, "w"),
        ("scrap", "Pedaço cortado usado", 220, "w"),
        ("blocks", "Blocos", 60, "e"),
        ("items", "Itens", 60, "e"),
        ("total_m", "Total (m)", 90, "e"),
        ("time", "Tempo", 90, "e"),
    ]:
        tree_summary.heading(col, text=txt)
        tree_summary.column(col, width=w, anchor=anchor)

    sb_sum = ttk.Scrollbar(summary_box, orient="vertical", command=tree_summary.yview)
    tree_summary.configure(yscrollcommand=sb_sum.set)
    tree_summary.pack(side="left", fill="both", expand=True, padx=(0, 0), pady=4)
    sb_sum.pack(side="right", fill="y", pady=4)

    # ---------------- PEDIDOS NA FILA ----------------
    pedidos_box = ttk.LabelFrame(body, text="Pedidos sendo impressos")
    pedidos_box.pack(fill="both", expand=False, pady=(10, 0))

    pedidos_bar = ttk.Frame(pedidos_box)
    pedidos_bar.pack(fill="x", pady=(4, 0))
    ttk.Button(
        pedidos_bar, text="⤢ Abrir em janela", command=lambda: open_pedidos_window()
    ).pack(side="right")

    cols_ped = ("pedido", "fabrics", "total_m", "pecas")
    tree_pedidos = ttk.Treeview(pedidos_box, columns=cols_ped, show="headings", height=6)
    for col, txt, w, anchor in [
        ("pedido", "Pedido", 260, "w"),
        ("fabrics", "Tecido(s)", 180, "w"),
        ("total_m", "Total (m)", 90, "e"),
        ("pecas", "Peças", 70, "e"),
    ]:
        tree_pedidos.heading(col, text=txt)
        tree_pedidos.column(col, width=w, anchor=anchor)

    sb_ped = ttk.Scrollbar(pedidos_box, orient="vertical", command=tree_pedidos.yview)
    tree_pedidos.configure(yscrollcommand=sb_ped.set)
    tree_pedidos.pack(side="left", fill="both", expand=True, padx=(0, 0), pady=4)
    sb_ped.pack(side="right", fill="y", pady=4)

    # ---------------- INTERNALS ----------------
    def get_config() -> Tuple[float, str, float, float]:
        dpi = safe_float(var_dpi.get(), 150.0)
        axis = (var_axis.get() or "altura").strip().lower()
        speed = safe_float(var_speed.get(), 1.5)
        setup = safe_float(var_setup.get(), 2.0)

        if dpi <= 0:
            raise ValueError("DPI inválido.")
        if speed <= 0:
            raise ValueError("Velocidade inválida.")
        if setup < 0:
            raise ValueError("Setup inválido.")
        if axis not in {"altura", "largura", "maior"}:
            axis = "altura"
        return dpi, axis, speed, setup

    def job_dpi(j: Job, dpi_global: float) -> float:
        return float(j.dpi_override) if (j.dpi_override and j.dpi_override > 0) else dpi_global

    def compute_length(w: int, h: int, dpi: float, axis: str) -> float:
        if axis == "largura":
            return px_to_m(w, dpi)
        if axis == "maior":
            return px_to_m(max(w, h), dpi)
        return px_to_m(h, dpi)

    def compute_time(length_m: float, speed_m_min: float, setup_min: float, is_gap: bool) -> float:
        if is_gap:
            return (length_m / speed_m_min) if speed_m_min > 0 else 0.0
        return setup_min + (length_m / speed_m_min)

    def recompute_job(j: Job):
        dpi_global, axis, speed, setup = get_config()
        dpi_use = job_dpi(j, dpi_global)
        j.length_m = float(compute_length(j.w_px, j.h_px, dpi_use, axis))
        j.time_min = float(compute_time(j.length_m, speed, setup, is_gap=j.is_gap))

    def build_queue_row(j: Job) -> tuple:
        roll_txt = f"{j.roll_no}" if j.roll_no > 0 else ""
        name = "— ESPAÇO —" if (j.is_gap and j.name.upper() == "ESPAÇO") else j.name
        dpi_txt = ""
        if not j.is_gap and j.dpi_override:
            dpi_txt = f"{j.dpi_override:.0f}"
        return (
            roll_txt, j.fabric, dpi_txt, name,
            j.w_px if j.w_px else "", j.h_px if j.h_px else "",
            fmt_m(j.length_m), fmt_min(j.time_min),
        )

    def refresh_table(rows: List[Job]):
        tree.delete(*tree.get_children())

        total_m = 0.0
        total_time = 0.0
        reorder_enabled = var_mode.get().strip().lower() == "original"

        for i, j in enumerate(rows):
            total_m += j.length_m
            total_time += j.time_min

            if j.hidden:
                continue

            drag_txt = "⋮⋮" if (reorder_enabled and not j.is_gap) else ""

            tree.insert(
                "", "end", iid=str(i),
                values=(drag_txt,) + build_queue_row(j),
            )

        lbl_count.config(text=f"Itens: {len(rows)}")
        lbl_total.config(text=f"Total: {fmt_m(total_m)}")
        lbl_time.config(text=f"Tempo total: {fmt_min(total_time)}")

    def build_roll_summary_rows(rows: List[Job]) -> List[tuple]:
        out: List[tuple] = []
        roll_order, by_roll = _group_by_roll(rows)
        for rn in roll_order:
            rr = by_roll[rn]
            jobs_only = [x for x in rr if not x.is_gap]
            roll_m = sum(x.length_m for x in rr)
            roll_t = sum(x.time_min for x in rr)
            blocks = _roll_blocks(rr)

            fab_count: Dict[str, int] = {}
            for x in jobs_only:
                fab_count[x.fabric] = fab_count.get(x.fabric, 0) + 1
            main_fab = max(fab_count.items(), key=lambda kv: kv[1])[0] if fab_count else "—"

            scrap_label = roll_scrap_labels.get(rn, "")

            out.append((rn, main_fab, scrap_label, len(blocks), len(jobs_only), fmt_m(roll_m), fmt_min(roll_t)))
        return out

    def refresh_roll_summary(rows: List[Job]):
        nonlocal last_roll_summary_rows
        last_roll_summary_rows = rows
        tree_summary.delete(*tree_summary.get_children())
        for values in build_roll_summary_rows(rows):
            tree_summary.insert("", "end", values=values)

    def build_pedido_groups(rows: List[Job]) -> Dict[str, Dict[str, object]]:
        groups: Dict[str, Dict[str, object]] = {}
        for j in rows:
            if j.is_gap:
                continue
            pedido = pedido_from_document(j.name)
            g = groups.setdefault(pedido, {"total_m": 0.0, "count": 0, "fabrics": set()})
            g["total_m"] = g["total_m"] + j.length_m
            g["count"] = g["count"] + 1
            g["fabrics"].add(j.fabric)
        return groups

    def build_pedido_rows(rows: List[Job], sort_mode: str = "total_m") -> List[tuple]:
        groups = build_pedido_groups(rows)
        items = list(groups.items())
        if sort_mode == "alpha":
            items.sort(key=lambda kv: kv[0].lower())
        else:
            items.sort(key=lambda kv: kv[1]["total_m"], reverse=True)
        return [
            (pedido, ", ".join(sorted(data["fabrics"])), fmt_m(data["total_m"]), data["count"])
            for pedido, data in items
        ]

    def refresh_pedidos_summary(rows: List[Job]):
        nonlocal last_pedidos_rows
        last_pedidos_rows = rows
        tree_pedidos.delete(*tree_pedidos.get_children())
        for values in build_pedido_rows(rows, "total_m"):
            tree_pedidos.insert("", "end", values=values)

    # ---------------- Abrir painéis em janela separada ----------------
    def _open_list_popup(title: str, columns: List[Tuple[str, str, int, str]]):
        dlg = tk.Toplevel(frame)
        dlg.title(title)
        dlg.geometry("1000x560")

        top_bar = ttk.Frame(dlg)
        top_bar.pack(fill="x", padx=10, pady=(10, 4))

        body = ttk.Frame(dlg)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        pop_tree = ttk.Treeview(body, columns=[c[0] for c in columns], show="headings")
        for col_id, txt, w, anchor in columns:
            pop_tree.heading(col_id, text=txt)
            pop_tree.column(col_id, width=w, anchor=anchor)

        sb = ttk.Scrollbar(body, orient="vertical", command=pop_tree.yview)
        pop_tree.configure(yscrollcommand=sb.set)
        pop_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        return dlg, top_bar, pop_tree

    def _fill_popup(pop_tree: ttk.Treeview, rows: List[tuple]):
        pop_tree.delete(*pop_tree.get_children())
        for values in rows:
            pop_tree.insert("", "end", values=values)

    def open_queue_window():
        _dlg, top_bar, pop_tree = _open_list_popup(
            "Fila (sequência)",
            [
                ("roll", "Rolo", 70, "center"),
                ("fabric", "Tecido", 120, "w"),
                ("dpi", "DPI(item)", 70, "e"),
                ("arquivo", "Arquivo", 420, "w"),
                ("w", "Largura px", 100, "e"),
                ("h", "Altura px", 100, "e"),
                ("metros", "Comprimento", 120, "e"),
                ("tempo", "Tempo", 120, "e"),
            ],
        )

        def refresh():
            _fill_popup(pop_tree, [build_queue_row(j) for j in view_rows if not j.hidden])

        ttk.Button(top_bar, text="🔄 Atualizar", command=refresh).pack(side="left")
        refresh()

    def open_roll_summary_window():
        _dlg, top_bar, pop_tree = _open_list_popup(
            "Resumo por rolo (conferência)",
            [
                ("roll", "Rolo", 60, "center"),
                ("fabric", "Tecido", 160, "w"),
                ("scrap", "Pedaço cortado usado", 260, "w"),
                ("blocks", "Blocos", 70, "e"),
                ("items", "Itens", 70, "e"),
                ("total_m", "Total (m)", 110, "e"),
                ("time", "Tempo", 110, "e"),
            ],
        )

        def refresh():
            _fill_popup(pop_tree, build_roll_summary_rows(last_roll_summary_rows))

        ttk.Button(top_bar, text="🔄 Atualizar", command=refresh).pack(side="left")
        refresh()

    def open_pedidos_window():
        _dlg, top_bar, pop_tree = _open_list_popup(
            "Pedidos sendo impressos",
            [
                ("pedido", "Pedido", 320, "w"),
                ("fabrics", "Tecido(s)", 220, "w"),
                ("total_m", "Total (m)", 110, "e"),
                ("pecas", "Peças", 90, "e"),
            ],
        )

        sort_mode = tk.StringVar(value="total_m")

        def refresh():
            _fill_popup(pop_tree, build_pedido_rows(last_pedidos_rows, sort_mode.get()))

        ttk.Label(top_bar, text="Ordenar por:").pack(side="left")
        ttk.Radiobutton(
            top_bar, text="Metragem", value="total_m", variable=sort_mode, command=refresh
        ).pack(side="left", padx=(4, 0))
        ttk.Radiobutton(
            top_bar, text="Alfabética (A-Z)", value="alpha", variable=sort_mode, command=refresh
        ).pack(side="left", padx=(8, 16))
        ttk.Button(top_bar, text="🔄 Atualizar", command=refresh).pack(side="left")

        refresh()

    def show_base():
        nonlocal view_rows, last_view
        view_rows = list(jobs)
        last_view = "base"
        refresh_table(view_rows)
        refresh_roll_summary([])
        refresh_pedidos_summary(jobs)

    def selected_rows() -> List[Job]:
        sel = tree.selection()
        if not sel:
            return []
        picked: List[Job] = []
        for iid in sel:
            try:
                idx = int(iid)
            except Exception:
                continue
            if 0 <= idx < len(view_rows):
                r = view_rows[idx]
                if not r.is_gap:
                    picked.append(r)
        return picked

    def selected_base_jobs() -> List[Job]:
        picked_view = selected_rows()
        if not picked_view:
            return []
        out: List[Job] = []
        for row in picked_view:
            for jb in jobs:
                if jb.path == row.path and jb.name == row.name:
                    out.append(jb)
                    break
        return out

    def selected_single_job_index() -> Optional[int]:
        """Índice em `jobs` (lista base/importação) do único item selecionado
        na tabela — funciona tanto na visão base quanto na fila gerada,
        casando por arquivo (path + nome)."""
        sel = tree.selection()
        if len(sel) != 1:
            return None
        try:
            idx = int(sel[0])
        except Exception:
            return None
        if not (0 <= idx < len(view_rows)):
            return None
        row = view_rows[idx]
        if row.is_gap:
            return None
        for i, jb in enumerate(jobs):
            if jb.path == row.path and jb.name == row.name:
                return i
        return None

    def _reorder_allowed() -> bool:
        """Reordenar manualmente só tem efeito no modo 'original' — no modo
        'tecido' a fila é sempre reagrupada por tecido (bin packing), então
        mover/arrastar um item não mudaria nada na fila gerada."""
        if var_mode.get().strip().lower() == "tecido":
            messagebox.showinfo(
                "Modo tecido",
                "No modo \"tecido\" a fila é sempre reagrupada automaticamente por tecido, "
                "então reordenar arquivos não tem efeito na fila gerada.\n\n"
                "Troque o Modo para \"original\" para reordenar manualmente."
            )
            return False
        return True

    def move_job(delta: int):
        if not _reorder_allowed():
            return
        idx = selected_single_job_index()
        if idx is None:
            messagebox.showinfo(
                "Selecione",
                "Selecione exatamente 1 arquivo (não selecione ESPAÇO) para mover."
            )
            return
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(jobs):
            return
        moved = jobs[idx]
        jobs[idx], jobs[new_idx] = jobs[new_idx], jobs[idx]
        if last_view == "queue":
            generate_queue()
        else:
            show_base()

        for i, row in enumerate(view_rows):
            if row.path == moved.path and row.name == moved.name:
                iid = str(i)
                tree.selection_set(iid)
                tree.see(iid)
                break

    def remove_selected_jobs():
        picked = selected_base_jobs()
        if not picked:
            messagebox.showinfo("Remover item", "Selecione 1 ou mais itens (não ESPAÇO) para remover.")
            return
        if not messagebox.askyesno("Remover item", f"Remover {len(picked)} item(ns) da fila?"):
            return
        picked_ids = {id(jb) for jb in picked}
        jobs[:] = [jb for jb in jobs if id(jb) not in picked_ids]
        generate_queue() if var_mode.get().strip().lower() == "tecido" else show_base()

    def show_context_menu(event):
        iid = tree.identify_row(event.y)
        if iid and iid not in tree.selection():
            tree.selection_set(iid)

        picked = selected_rows()
        has_selection = bool(picked)
        single = len(picked) == 1
        reorder_mode = var_mode.get().strip().lower() == "original"

        def edit_single():
            base = selected_base_jobs()
            if base:
                open_edit_dialog(base[0])

        menu = tk.Menu(frame, tearoff=0)
        menu.add_command(
            label="Editar item…", command=edit_single,
            state=("normal" if single else "disabled"),
        )
        menu.add_command(
            label="Definir tecido…", command=set_fabric_selected,
            state=("normal" if has_selection else "disabled"),
        )
        menu.add_separator()
        if reorder_mode:
            menu.add_command(
                label="Mover para cima", command=lambda: move_job(-1),
                state=("normal" if single else "disabled"),
            )
            menu.add_command(
                label="Mover para baixo", command=lambda: move_job(+1),
                state=("normal" if single else "disabled"),
            )
            menu.add_separator()
        menu.add_command(
            label="Remover item(s)", command=remove_selected_jobs,
            state=("normal" if has_selection else "disabled"),
        )
        menu.add_separator()
        menu.add_command(
            label="Atualizar",
            command=lambda: generate_queue() if var_mode.get().strip().lower() == "tecido" else show_base(),
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ---------------- Actions ----------------
    IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")

    def import_image_paths(paths):
        if not _HAS_PIL:
            messagebox.showerror("Erro", "Instale pillow: pip install pillow")
            return
        if not paths:
            return

        try:
            _ = get_config()
        except Exception as e:
            messagebox.showerror("Configuração inválida", str(e))
            return

        errors = []
        for p in paths:
            path = Path(p)
            try:
                w, h = safe_image_size(path)
                fabric = infer_fabric_from_filename(path.name, fabrics_map)

                j = Job(
                    name=path.name,
                    path=path,
                    fabric=fabric,
                    w_px=int(w),
                    h_px=int(h),
                    dpi_override=None,
                )
                recompute_job(j)
                jobs.append(j)

            except Exception as ex:
                errors.append(f"{path.name}: {ex}")

        # por padrão, já mostra a fila por tecido
        generate_queue()

        if errors:
            messagebox.showwarning(
                "Alguns arquivos falharam",
                "Falhas:\n\n" + "\n".join(errors[:12]) + ("\n..." if len(errors) > 12 else "")
            )

    def import_images():
        paths = filedialog.askopenfilenames(
            filetypes=[("Imagens", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff")]
        )
        import_image_paths(list(paths))

    def _split_dnd_files(data: str) -> List[str]:
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
        if buff:
            out.append(buff)
        return out

    def on_drop_files(event):
        raw = getattr(event, "data", "") or ""
        all_paths = _split_dnd_files(raw)
        imgs = [p for p in all_paths if p.lower().endswith(IMAGE_EXTS)]
        if not imgs:
            messagebox.showwarning("Sem imagens", "Solte apenas arquivos de imagem (jpg/png/bmp/tif).")
            return
        import_image_paths(imgs)

    def recalc_all():
        if not jobs:
            return
        try:
            _ = get_config()
        except Exception as e:
            messagebox.showerror("Configuração inválida", str(e))
            return

        for j in jobs:
            recompute_job(j)

        generate_queue() if var_mode.get().strip().lower() == "tecido" else show_base()

    def clear_all():
        jobs.clear()
        gap_overrides.clear()
        show_base()

    def export_csv():
        if not view_rows:
            return

        out = filedialog.asksaveasfilename(defaultextension=".csv")
        if not out:
            return

        try:
            with open(out, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["rolo", "tecido", "dpi_item", "arquivo", "largura_px", "altura_px", "comprimento_m", "tempo_min", "tipo"])
                for j in view_rows:
                    w.writerow([
                        j.roll_no if j.roll_no else "",
                        j.fabric,
                        f"{j.dpi_override:.0f}" if (j.dpi_override and not j.is_gap) else "",
                        j.name,
                        j.w_px if j.w_px else "",
                        j.h_px if j.h_px else "",
                        f"{j.length_m:.6f}",
                        f"{j.time_min:.6f}",
                        "ESPACO" if j.is_gap else "JOB"
                    ])
            messagebox.showinfo("Exportado", "CSV salvo com sucesso.")
        except Exception as e:
            messagebox.showerror("Erro ao exportar", str(e))

    # ---------------- Salvar / Importar lista de impressão ----------------
    def save_job_list(path: Path):
        payload = {
            "version": 1,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "config": {
                "dpi": var_dpi.get(),
                "axis": var_axis.get(),
                "speed": var_speed.get(),
                "setup": var_setup.get(),
                "printer": var_printer.get(),
                "mode": var_mode.get(),
                "gap_between": var_gap_between.get(),
                "gap_endroll": var_gap_endroll.get(),
                "gap_files": var_gap_files.get(),
                "roll_other": var_roll_other.get(),
                "batch_name": var_batch_name.get(),
                "report_mode": var_report_mode.get(),
                "jpg_mode": var_jpg_mode.get(),
                "jpg_custom": var_jpg_custom.get(),
                "auto_fabric_order": bool(var_auto_fabric_order.get()),
                "manual_fabric_order": list(manual_fabric_order),
                "use_scraps": bool(var_use_scraps.get()),
            },
            "jobs": [
                {
                    "name": j.name,
                    "path": str(j.path) if j.path else None,
                    "fabric": j.fabric,
                    "w_px": j.w_px,
                    "h_px": j.h_px,
                    "dpi_override": j.dpi_override,
                    "length_m": j.length_m,
                    "time_min": j.time_min,
                }
                for j in jobs
            ],
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_job_list(path: Path):
        nonlocal manual_fabric_order

        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("jobs"), list):
            raise ValueError("Arquivo de lista inválido.")

        cfg = raw.get("config") or {}

        if "dpi" in cfg:
            var_dpi.set(str(cfg["dpi"]))
        if "axis" in cfg:
            var_axis.set(str(cfg["axis"]))
        if "speed" in cfg:
            var_speed.set(str(cfg["speed"]))
        if "setup" in cfg:
            var_setup.set(str(cfg["setup"]))
        if cfg.get("printer") in _printer_options():
            var_printer.set(cfg["printer"])
        if "mode" in cfg:
            var_mode.set(str(cfg["mode"]))
        if "gap_between" in cfg:
            var_gap_between.set(str(cfg["gap_between"]))
        if "gap_endroll" in cfg:
            var_gap_endroll.set(str(cfg["gap_endroll"]))
        if "gap_files" in cfg:
            var_gap_files.set(str(cfg["gap_files"]))
        if "roll_other" in cfg:
            var_roll_other.set(str(cfg["roll_other"]))
        if "batch_name" in cfg:
            var_batch_name.set(str(cfg["batch_name"]))
        if "report_mode" in cfg:
            var_report_mode.set(str(cfg["report_mode"]))
        if "jpg_mode" in cfg:
            var_jpg_mode.set(str(cfg["jpg_mode"]))
        if "jpg_custom" in cfg:
            var_jpg_custom.set(str(cfg["jpg_custom"]))
        if "auto_fabric_order" in cfg:
            var_auto_fabric_order.set(bool(cfg["auto_fabric_order"]))
        if "manual_fabric_order" in cfg:
            manual_fabric_order = [str(x) for x in (cfg.get("manual_fabric_order") or [])]
        if "use_scraps" in cfg:
            var_use_scraps.set(bool(cfg["use_scraps"]))

        new_jobs: List[Job] = []
        for jd in raw["jobs"]:
            new_jobs.append(Job(
                name=str(jd.get("name", "")),
                path=Path(jd["path"]) if jd.get("path") else None,
                fabric=str(jd.get("fabric", "Outro")),
                w_px=int(jd.get("w_px", 0)),
                h_px=int(jd.get("h_px", 0)),
                dpi_override=(float(jd["dpi_override"]) if jd.get("dpi_override") else None),
                length_m=float(jd.get("length_m", 0.0)),
                time_min=float(jd.get("time_min", 0.0)),
            ))

        jobs.clear()
        jobs.extend(new_jobs)

    def on_save_list():
        if not jobs:
            messagebox.showinfo("Nada para salvar", "Importe imagens primeiro.")
            return

        out = filedialog.asksaveasfilename(
            title="Salvar lista de impressão",
            defaultextension=".json",
            filetypes=[("Lista de impressão (JSON)", "*.json")],
        )
        if not out:
            return

        try:
            save_job_list(Path(out))
            messagebox.showinfo("Lista salva", f"Lista de impressão salva em:\n{out}")
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))

    def on_import_list():
        path = filedialog.askopenfilename(
            title="Importar lista de impressão",
            filetypes=[("Lista de impressão (JSON)", "*.json")],
        )
        if not path:
            return

        try:
            load_job_list(Path(path))
        except Exception as e:
            messagebox.showerror("Erro ao importar", str(e))
            return

        generate_queue() if var_mode.get().strip().lower() == "tecido" else show_base()
        messagebox.showinfo("Lista importada", f"{len(jobs)} item(ns) carregado(s).")

    def set_fabric_selected():
        fab = var_fabric_pick.get().strip() or "Outro"
        picked = selected_base_jobs()
        if not picked:
            messagebox.showinfo("Seleção", "Selecione 1 ou mais itens (não selecione ESPAÇO).")
            return
        for j in picked:
            j.fabric = fab
        generate_queue() if var_mode.get().strip().lower() == "tecido" else show_base()

    # ---------------- Double click edit ----------------
    def on_double_click():
        sel = tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except Exception:
            return
        if not (0 <= idx < len(view_rows)):
            return
        row = view_rows[idx]
        if row.is_gap:
            if row.gap_index is not None:
                open_edit_gap_dialog(row.gap_index, row.length_m)
            return

        base: Optional[Job] = None
        for jb in jobs:
            if jb.path == row.path and jb.name == row.name:
                base = jb
                break
        if base is None:
            return

        open_edit_dialog(base)

    def open_edit_gap_dialog(gap_index: int, current_m: float):
        dlg = tk.Toplevel(frame)
        dlg.title("Editar espaço")
        dlg.transient(frame.winfo_toplevel())
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Tamanho do espaço (m):").grid(row=0, column=0, sticky="w")
        var_len = tk.StringVar(value=f"{current_m:.2f}")
        ttk.Entry(frm, textvariable=var_len, width=10).grid(row=0, column=1, sticky="w", padx=(6, 0))

        def on_save():
            v = safe_float(var_len.get(), -1.0)
            if v < 0:
                messagebox.showerror("Espaço inválido", "Informe um valor maior ou igual a 0.")
                return
            gap_overrides[gap_index] = v
            dlg.destroy()
            generate_queue()

        def on_reset():
            gap_overrides.pop(gap_index, None)
            dlg.destroy()
            generate_queue()

        btns = ttk.Frame(frm)
        btns.grid(row=1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Restaurar padrão", command=on_reset).pack(side="left")
        ttk.Button(btns, text="Cancelar", command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="Salvar", command=on_save).pack(side="right", padx=(0, 8))

    def open_edit_dialog(job: Job):
        dlg = tk.Toplevel(frame)
        dlg.title("Editar item")
        dlg.transient(frame.winfo_toplevel())
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Arquivo:").grid(row=0, column=0, sticky="w")
        ttk.Label(frm, text=job.name).grid(row=0, column=1, sticky="w")

        ttk.Label(frm, text="Tecido:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        var_fab = tk.StringVar(value=job.fabric)
        cb = ttk.Combobox(frm, values=sorted(set(list(fabrics_map.keys()) + ["Outro"])),
                          textvariable=var_fab, state="readonly", width=22)
        cb.grid(row=1, column=1, sticky="w", pady=(8, 0))

        def on_new_fabric():
            name = simpledialog.askstring(
                "Novo tecido", "Nome do tecido:", parent=dlg
            )
            if name is None:
                return
            try:
                canonical = register_new_fabric(name)
            except ValueError as e:
                messagebox.showerror("Erro", str(e))
                return

            cb.config(values=sorted(set(list(fabrics_map.keys()) + ["Outro"])))
            var_fab.set(canonical)

        ttk.Button(frm, text="Novo tecido…", command=on_new_fabric).grid(
            row=1, column=2, sticky="w", padx=(6, 0), pady=(8, 0)
        )

        ttk.Label(frm, text="DPI do item (vazio = DPI global):").grid(row=2, column=0, sticky="w", pady=(8, 0))
        var_dpi_item = tk.StringVar(value=(f"{job.dpi_override:.0f}" if job.dpi_override else ""))
        ttk.Entry(frm, textvariable=var_dpi_item, width=10).grid(row=2, column=1, sticky="w", pady=(8, 0))

        def on_save():
            job.fabric = var_fab.get().strip() or "Outro"
            dpi_txt = var_dpi_item.get().strip()
            if dpi_txt == "":
                job.dpi_override = None
            else:
                v = safe_float(dpi_txt, -1)
                if v <= 0:
                    messagebox.showerror("DPI inválido", "Informe um DPI > 0 ou deixe vazio.")
                    return
                job.dpi_override = float(v)

            try:
                recompute_job(job)
            except Exception as e:
                messagebox.showerror("Erro ao recalcular", str(e))
                return

            dlg.destroy()
            generate_queue() if var_mode.get().strip().lower() == "tecido" else show_base()

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Cancelar", command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="Salvar", command=on_save).pack(side="right", padx=(0, 8))

    # ---------------- Fabric manager dialog ----------------
    def open_fabrics_dialog():
        dlg = tk.Toplevel(frame)
        dlg.title("Cadastro de Tecidos e Variações")
        dlg.transient(frame.winfo_toplevel())
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Tecidos cadastrados (canonical -> aliases | metragem do rolo):").pack(anchor="w")

        lb = tk.Listbox(frm, height=12, width=84)
        lb.pack(fill="both", expand=True, pady=8)

        list_keys: List[str] = []

        def refresh_list():
            nonlocal list_keys
            lb.delete(0, tk.END)
            list_keys = sorted(fabrics_map.keys())
            for canonical in list_keys:
                entry = fabrics_map.get(canonical, {})
                aliases = fabric_aliases(entry)
                roll_m = fabric_roll_length(entry)
                alias_txt = ', '.join(aliases) if aliases else '(sem aliases)'
                lb.insert(tk.END, f"{canonical} -> {alias_txt} | Rolo: {roll_m:.0f} m")

        refresh_list()

        form = ttk.Frame(frm)
        form.pack(fill="x", pady=(8, 0))

        ttk.Label(form, text="Tecido (canonical):").grid(row=0, column=0, sticky="w")
        var_new_can = tk.StringVar()
        ttk.Entry(form, textvariable=var_new_can, width=24).grid(row=0, column=1, sticky="w", padx=6)

        ttk.Label(form, text="Variações (separadas por vírgula):").grid(row=1, column=0, sticky="w", pady=(6, 0))
        var_new_alias = tk.StringVar()
        ttk.Entry(form, textvariable=var_new_alias, width=52).grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))

        ttk.Label(form, text="Metragem do rolo (m):").grid(row=2, column=0, sticky="w", pady=(6, 0))
        var_new_roll = tk.StringVar(value=str(int(DEFAULT_ROLL_LENGTH_M)))
        ttk.Entry(form, textvariable=var_new_roll, width=10).grid(row=2, column=1, sticky="w", padx=6, pady=(6, 0))

        def on_pick(_evt=None):
            sel = lb.curselection()
            if not sel:
                return
            canonical = list_keys[sel[0]]
            entry = fabrics_map.get(canonical, {})
            var_new_can.set(canonical)
            var_new_alias.set(', '.join(fabric_aliases(entry)))
            var_new_roll.set(f"{fabric_roll_length(entry):.0f}")

        lb.bind("<<ListboxSelect>>", on_pick)

        def add_fabric():
            can = var_new_can.get().strip()
            if not can:
                messagebox.showerror("Erro", "Informe o nome do tecido (canonical).")
                return

            aliases_raw = var_new_alias.get().strip()
            aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()] if aliases_raw else []

            roll_m = safe_float(var_new_roll.get(), DEFAULT_ROLL_LENGTH_M)
            if roll_m <= 0:
                messagebox.showerror("Erro", "Metragem do rolo deve ser maior que zero.")
                return

            register_new_fabric(can, aliases, roll_length_m=roll_m)
            refresh_list()

            var_new_can.set("")
            var_new_alias.set("")
            var_new_roll.set(str(int(DEFAULT_ROLL_LENGTH_M)))

        ttk.Button(form, text="Adicionar / Atualizar", command=add_fabric).grid(row=3, column=1, sticky="w", pady=(10, 0))
        ttk.Button(frm, text="Fechar", command=dlg.destroy).pack(anchor="e", pady=(10, 0))

    # ---------------- Seleção de pedaços elegíveis para esta fila ----------------
    def open_scrap_selection_dialog():
        dlg = tk.Toplevel(frame)
        dlg.title("Selecionar pedaços a usar")
        dlg.transient(frame.winfo_toplevel())
        dlg.grab_set()
        dlg.geometry("480x570")

        ttk.Label(
            dlg,
            text=(
                "Marque quais pedaços cortados (não usados) podem ser usados ao\n"
                "gerar a fila — útil quando há pedaços do mesmo tecido vindos de\n"
                "fabricantes/lotes diferentes que não podem se misturar num rolo."
            ),
            justify="left",
        ).pack(padx=12, pady=(12, 6), anchor="w")

        bleed_box = ttk.LabelFrame(dlg, text="Metragem considerada de cada pedaço")
        bleed_box.pack(fill="x", padx=12, pady=(0, 6))

        ttk.Radiobutton(
            bleed_box, text="Tamanho exato do pedaço (cadastrado)",
            value=False, variable=var_scrap_bleed,
        ).pack(anchor="w", padx=8, pady=(6, 0))

        bleed_row = ttk.Frame(bleed_box)
        bleed_row.pack(anchor="w", padx=8, pady=(0, 6))
        ttk.Radiobutton(
            bleed_row, text="Sangria: contar", value=True, variable=var_scrap_bleed,
        ).pack(side="left")
        ttk.Entry(bleed_row, textvariable=var_scrap_bleed_cm, width=5).pack(side="left", padx=(4, 4))
        ttk.Label(bleed_row, text="cm a mais do que o cadastrado").pack(side="left")

        top_bar = ttk.Frame(dlg)
        top_bar.pack(fill="x", padx=12)

        list_frame = ttk.Frame(dlg)
        list_frame.pack(fill="both", expand=True, padx=12, pady=(6, 6))

        canvas = tk.Canvas(list_frame, highlightthickness=0)
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        inner = ttk.Frame(canvas)
        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(_evt=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(evt):
            canvas.itemconfig(inner_window, width=evt.width)

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        unused = sorted((s for s in scraps if not s.used), key=lambda s: (s.fabric, s.name))

        check_vars: Dict[str, tk.BooleanVar] = {}
        for sc in unused:
            default_checked = selected_scrap_keys is None or sc.key in selected_scrap_keys
            var = tk.BooleanVar(value=default_checked)
            check_vars[sc.key] = var
            ttk.Checkbutton(
                inner, variable=var,
                text=f"{sc.name} — {sc.fabric} — {fmt_m(sc.length_m)}",
            ).pack(anchor="w", pady=2)

        if not unused:
            ttk.Label(inner, text="Nenhum pedaço cortado disponível (não usado).").pack(
                anchor="w", pady=6
            )

        def select_all():
            for v in check_vars.values():
                v.set(True)

        def select_none():
            for v in check_vars.values():
                v.set(False)

        ttk.Button(top_bar, text="Marcar todos", command=select_all).pack(side="left")
        ttk.Button(top_bar, text="Desmarcar todos", command=select_none).pack(side="left", padx=(6, 0))

        def on_save():
            nonlocal selected_scrap_keys
            selected_scrap_keys = {key for key, v in check_vars.items() if v.get()}
            dlg.destroy()
            if var_mode.get().strip().lower() == "tecido":
                generate_queue()

        btn = ttk.Frame(dlg)
        btn.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btn, text="Salvar", command=on_save).pack(side="right", padx=4)
        ttk.Button(btn, text="Cancelar", command=dlg.destroy).pack(side="right", padx=4)

    # ---------------- Fabric scraps (pedaços cortados) dialog ----------------
    def open_scraps_dialog():
        dlg = tk.Toplevel(frame)
        dlg.title("Pedaços de tecido cortados")
        dlg.transient(frame.winfo_toplevel())
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)

        cols = ("name", "fabric", "length", "used")
        tree = ttk.Treeview(frm, columns=cols, show="headings", height=10)
        for col, txt, w in [
            ("name", "Nome", 200),
            ("fabric", "Tecido", 140),
            ("length", "Metragem (m)", 110),
            ("used", "Usado?", 70),
        ]:
            tree.heading(col, text=txt)
            tree.column(col, width=w, anchor="w")
        tree.pack(fill="both", expand=True, pady=(0, 10))

        selected_key: Dict[str, Optional[str]] = {"value": None}

        def refresh_tree(select_key: Optional[str] = None):
            tree.delete(*tree.get_children())
            for sc in scraps:
                tree.insert(
                    "", "end", iid=sc.key,
                    values=(sc.name, sc.fabric, f"{sc.length_m:.1f}", "Sim" if sc.used else "Não"),
                )
            if select_key:
                tree.selection_set(select_key)

        form = ttk.Frame(frm)
        form.pack(fill="x")

        ttk.Label(form, text="Nome:").grid(row=0, column=0, sticky="w")
        var_sc_name = tk.StringVar()
        ttk.Entry(form, textvariable=var_sc_name, width=26).grid(row=0, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(form, text="Tecido:").grid(row=0, column=2, sticky="w", padx=(12, 0))
        var_sc_fabric = tk.StringVar(value=fabric_options[0] if fabric_options else "")
        ttk.Combobox(
            form, width=18, values=sorted(fabrics_map.keys()),
            state="readonly", textvariable=var_sc_fabric,
        ).grid(row=0, column=3, sticky="w", padx=6, pady=2)

        ttk.Label(form, text="Metragem (m):").grid(row=1, column=0, sticky="w")
        var_sc_length = tk.StringVar()
        ttk.Entry(form, textvariable=var_sc_length, width=10).grid(row=1, column=1, sticky="w", padx=6, pady=2)

        def clear_form():
            selected_key["value"] = None
            var_sc_name.set("")
            var_sc_length.set("")
            tree.selection_remove(*tree.selection())

        def on_select(_evt=None):
            sel = tree.selection()
            if not sel:
                return
            key = sel[0]
            sc = next((s for s in scraps if s.key == key), None)
            if sc is None:
                return
            selected_key["value"] = sc.key
            var_sc_name.set(sc.name)
            var_sc_fabric.set(sc.fabric)
            var_sc_length.set(f"{sc.length_m:.1f}")

        tree.bind("<<TreeviewSelect>>", on_select)

        def on_save():
            nonlocal scraps
            length_m = safe_float(var_sc_length.get(), -1.0)
            try:
                scraps = add_or_update_scrap(
                    scraps,
                    key=selected_key["value"],
                    name=var_sc_name.get(),
                    fabric=var_sc_fabric.get(),
                    length_m=length_m,
                )
            except ValueError as e:
                messagebox.showerror("Pedaços de tecido", str(e))
                return

            save_scraps(scraps)
            new_key = selected_key["value"] or scraps[-1].key
            refresh_tree(select_key=new_key)
            selected_key["value"] = new_key

        def on_remove():
            nonlocal scraps
            key = selected_key["value"]
            if not key:
                messagebox.showwarning("Pedaços de tecido", "Selecione um pedaço na lista.")
                return
            sc = next((s for s in scraps if s.key == key), None)
            label = sc.name if sc else key
            if not messagebox.askyesno("Remover pedaço", f"Remover o pedaço '{label}'?"):
                return
            scraps = remove_scrap(scraps, key)
            save_scraps(scraps)
            clear_form()
            refresh_tree()

        def on_toggle_used(used: bool):
            nonlocal scraps
            key = selected_key["value"]
            if not key:
                messagebox.showwarning("Pedaços de tecido", "Selecione um pedaço na lista.")
                return
            scraps = set_scrap_used(scraps, key, used)
            save_scraps(scraps)
            refresh_tree(select_key=key)

        def on_close():
            dlg.destroy()
            if var_mode.get().strip().lower() == "tecido":
                generate_queue()

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Novo", command=clear_form).pack(side="left")
        ttk.Button(btns, text="Salvar", command=on_save).pack(side="left", padx=6)
        ttk.Button(btns, text="Remover", command=on_remove).pack(side="left", padx=6)
        ttk.Button(btns, text="Marcar como usado", command=lambda: on_toggle_used(True)).pack(side="left", padx=(16, 6))
        ttk.Button(btns, text="Desmarcar", command=lambda: on_toggle_used(False)).pack(side="left")
        ttk.Button(btns, text="Fechar", command=on_close).pack(side="right")

        refresh_tree()

    # ---------------- Fabric order dialog ----------------
    def open_fabric_order_dialog():
        fabrics = sorted({j.fabric for j in jobs if not j.is_gap})
        if not fabrics:
            messagebox.showinfo("Ordem dos tecidos", "Importe imagens primeiro.")
            return

        nonlocal manual_fabric_order
        if not manual_fabric_order:
            manual_fabric_order = list(fabrics)

        dlg = tk.Toplevel(frame)
        dlg.title("Ordem dos tecidos")
        dlg.transient(frame.winfo_toplevel())
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Cima imprime antes.").pack(anchor="w")

        lb = tk.Listbox(frm, height=10, width=28)
        lb.pack(fill="both", expand=True, pady=8)

        def reload_list():
            lb.delete(0, tk.END)
            for f in manual_fabric_order:
                lb.insert(tk.END, f)

        existing = set(fabrics)
        manual_fabric_order = [f for f in manual_fabric_order if f in existing]
        for f in fabrics:
            if f not in manual_fabric_order:
                manual_fabric_order.append(f)

        reload_list()

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=6)

        def move(delta: int):
            sel = lb.curselection()
            if not sel:
                return
            i = sel[0]
            j = i + delta
            if j < 0 or j >= len(manual_fabric_order):
                return
            manual_fabric_order[i], manual_fabric_order[j] = manual_fabric_order[j], manual_fabric_order[i]
            reload_list()
            lb.selection_set(j)

        ttk.Button(btns, text="Subir", command=lambda: move(-1)).pack(side="left")
        ttk.Button(btns, text="Descer", command=lambda: move(+1)).pack(side="left", padx=6)

        ttk.Checkbutton(
            frm,
            text="Usar ordem automática (menores no fim)",
            variable=var_auto_fabric_order
        ).pack(anchor="w", pady=(6, 0))

        def on_close():
            dlg.destroy()
            if var_mode.get().strip().lower() == "tecido":
                generate_queue()

        ttk.Button(frm, text="OK", command=on_close).pack(anchor="e", pady=(10, 0))

    # ---------------- Queue planner ----------------
    def roll_limit_for(fabric: str) -> float:
        entry = fabrics_map.get(fabric)
        if isinstance(entry, dict) and entry.get("roll_length_m"):
            return fabric_roll_length(entry)
        return safe_float(var_roll_other.get(), DEFAULT_ROLL_LENGTH_M)

    def eligible_scraps_for_fabric(fabric: str) -> List[FabricScrap]:
        """Pedaços não usados desse tecido que podem entrar no planejamento —
        todos, ou só os marcados em 'Selecionar pedaços a usar…' quando o
        usuário restringiu a seleção (ex.: tecido do mesmo nome vindo de
        fabricantes/lotes diferentes que não podem se misturar num rolo)."""
        items = unused_scraps_for_fabric(scraps, fabric)
        if selected_scrap_keys is not None:
            items = [s for s in items if s.key in selected_scrap_keys]
        return items

    def scrap_bleed_m() -> float:
        """Sangria: metragem extra (em m) considerada em cada pedaço cortado
        além da metragem cadastrada, quando 'Usar sangria' está ativo."""
        if not var_scrap_bleed.get():
            return 0.0
        return max(0.0, safe_float(var_scrap_bleed_cm.get(), 5.0)) / 100.0

    def scrap_effective_length(sc: FabricScrap) -> float:
        """Metragem considerada no planejamento para esse pedaço — a cadastrada,
        ou com a sangria somada quando 'Usar sangria' está ativo."""
        return sc.length_m + scrap_bleed_m()

    def limit_for_roll(fabric: str, roll_index: int) -> float:
        """roll_index começa em 0. Com 'priorizar pedaços', os primeiros rolos do
        tecido usam a metragem dos pedaços cortados (não usados e elegíveis,
        com sangria se ativa) antes de cair para a metragem padrão de rolo
        cheio do tecido."""
        if var_use_scraps.get():
            scrap_lens = [scrap_effective_length(s) for s in eligible_scraps_for_fabric(fabric)]
            if roll_index < len(scrap_lens):
                return scrap_lens[roll_index]
        return roll_limit_for(fabric) or DEFAULT_ROLL_LENGTH_M

    def scrap_match_for_roll(fabric: str, roll_index: int) -> Optional[FabricScrap]:
        """Pedaço cortado usado nesse rolo (None se o rolo for um rolo cheio normal)."""
        if not var_use_scraps.get():
            return None
        matching = eligible_scraps_for_fabric(fabric)
        if roll_index < len(matching):
            return matching[roll_index]
        return None

    def pack_fabric_items(
        fabric: str, items: List[Job], gap_endroll: float, gap_files: float = 0.0
    ) -> List[Tuple[int, List[Job]]]:
        """
        First-fit decreasing: maiores primeiro, mas cada item vai pro primeiro rolo
        (pedaço cortado ou rolo cheio) em que ele realmente CABE. Um item maior que
        um pedaço cortado não "ocupa" esse pedaço só por ser o primeiro da fila —
        ele passa para o próximo rolo, deixando o pedaço livre para um item menor
        que vier depois (mesmo que processado mais tarde nesta mesma função).

        gap_files é o espaço reservado ENTRE arquivos dentro do mesmo rolo (bloco
        do mesmo tecido) — conta na metragem do rolo, mas não é reservado antes do
        primeiro item nem depois do último item do bloco.

        Retorna [(índice_original_do_rolo, itens), ...] só com rolos não vazios —
        o índice original é preservado para identificar corretamente qual pedaço
        cortado (se algum) foi usado em cada rolo.
        """
        sorted_items = sorted(items, key=lambda j: j.length_m, reverse=True)
        bins: List[List[Job]] = []
        bin_used: List[float] = []
        bin_limit: List[float] = []

        def open_new_bin() -> int:
            idx = len(bins)
            bins.append([])
            bin_used.append(0.0)
            bin_limit.append(limit_for_roll(fabric, idx))
            return idx

        for item in sorted_items:
            # Primeiro rolo já aberto em que o item CABE (considerando o que já
            # está nele). Só abre um rolo novo se não couber em nenhum dos já
            # abertos — nunca empilha num rolo "de sobra" junto com itens que
            # não cabem juntos (isso misturava itens de rolos diferentes
            # quando nenhum item cabia no limite configurado, ex.: gap de fim
            # de rolo maior que a própria metragem do rolo).
            idx = None
            for i in range(len(bins)):
                extra_gap = gap_files if bins[i] else 0.0
                if (bin_used[i] + extra_gap + item.length_m + gap_endroll) <= bin_limit[i]:
                    idx = i
                    break

            if idx is None:
                idx = open_new_bin()

            extra_gap = gap_files if bins[idx] else 0.0
            bins[idx].append(item)
            bin_used[idx] += extra_gap + item.length_m

        # remove rolos reservados que nenhum item acabou ocupando, preservando o índice original
        return [(i, b) for i, b in enumerate(bins) if b]

    def add_gap(rows: List[Job], fabric: str, gap_m: float, speed: float, hidden: bool = False):
        nonlocal gap_seq

        gap_index: Optional[int] = None
        use_m = gap_m
        if not hidden:
            gap_index = gap_seq
            gap_seq += 1
            if gap_index in gap_overrides:
                use_m = gap_overrides[gap_index]

        if use_m <= 0:
            return

        g = Job(
            name="ESPAÇO",
            path=None,
            fabric=fabric,
            w_px=0,
            h_px=0,
            dpi_override=None,
            is_gap=True,
            roll_no=0,
            hidden=hidden,
            gap_index=gap_index,
        )
        g.length_m = float(use_m)
        g.time_min = float((g.length_m / speed) if speed > 0 else 0.0)  # gap não tem setup
        rows.append(g)

    def fabric_totals(base_list: List[Job]) -> Dict[str, float]:
        tot: Dict[str, float] = {}
        for j in base_list:
            if j.is_gap:
                continue
            tot[j.fabric] = tot.get(j.fabric, 0.0) + j.length_m
        return tot

    def ordered_fabrics(base_list: List[Job]) -> List[str]:
        fabrics = sorted({j.fabric for j in base_list if not j.is_gap})
        if not fabrics:
            return []

        if var_auto_fabric_order.get():
            totals = fabric_totals(base_list)
            return sorted(fabrics, key=lambda f: totals.get(f, 0.0), reverse=True)

        nonlocal manual_fabric_order
        if not manual_fabric_order:
            manual_fabric_order = list(fabrics)

        existing = set(fabrics)
        manual_fabric_order = [f for f in manual_fabric_order if f in existing]
        for f in fabrics:
            if f not in manual_fabric_order:
                manual_fabric_order.append(f)
        return list(manual_fabric_order)

    def generate_queue():
        nonlocal view_rows, last_view, gap_seq

        roll_scrap_labels.clear()
        roll_scrap_keys.clear()
        gap_seq = 0

        if not jobs:
            show_base()
            return

        if edit_roll_id is not None:
            # Editando um rolo já registrado: é um único rolo contínuo (igual
            # ao PXPrintLogs) — sem reagrupar/separar por tecido nem bin
            # packing. Os itens entram na ordem em que estão na lista, todos
            # no mesmo rolo; novos itens acrescentados só continuam o rolo.
            planned = [
                Job(
                    name=item.name, path=item.path, fabric=item.fabric,
                    w_px=item.w_px, h_px=item.h_px, dpi_override=item.dpi_override,
                    length_m=item.length_m, time_min=item.time_min,
                    is_gap=False, roll_no=1,
                )
                for item in jobs
            ]
            view_rows = planned
            last_view = "queue"
            refresh_table(view_rows)
            refresh_roll_summary(view_rows)
            refresh_pedidos_summary(view_rows)
            return

        try:
            _, _, speed, _ = get_config()
        except Exception as e:
            messagebox.showerror("Configuração inválida", str(e))
            return

        mode = var_mode.get().strip().lower()
        gap_between = safe_float(var_gap_between.get(), 1.0)
        gap_endroll = safe_float(var_gap_endroll.get(), 1.0)
        gap_files = safe_float(var_gap_files.get(), 0.0)

        base_list = list(jobs)
        planned: List[Job] = []
        global_roll_no = 0

        def emit(item: Job, roll_no: int):
            planned.append(Job(
                name=item.name,
                path=item.path,
                fabric=item.fabric,
                w_px=item.w_px,
                h_px=item.h_px,
                dpi_override=item.dpi_override,
                length_m=item.length_m,
                time_min=item.time_min,
                is_gap=False,
                roll_no=roll_no,
            ))

        if mode != "tecido":
            # Mantém a ordem de importação; só quebra rolo quando o tecido muda
            # ou quando o rolo atual enche (sem bin packing entre tecidos).
            current_fabric: Optional[str] = None
            fabric_roll_index = 0
            used_in_roll = 0.0

            for j in base_list:
                fabric = j.fabric or "Outro"

                if current_fabric is None:
                    current_fabric = fabric
                    global_roll_no = 1
                    fabric_roll_index = 0
                    used_in_roll = 0.0
                elif fabric != current_fabric:
                    add_gap(planned, current_fabric, gap_between, speed)
                    current_fabric = fabric
                    global_roll_no += 1
                    fabric_roll_index = 0
                    used_in_roll = 0.0

                limit = limit_for_roll(fabric, fabric_roll_index)
                guard = 0

                # nunca encostar no limite (reserva gap_endroll e, se já houver item
                # no bloco atual, gap_files). Só insere o espaço de fim de rolo se o
                # rolo atual já tiver algo nele — um rolo vazio (ex.: pedaço cortado
                # menor que o próprio item) é pulado sem gerar espaço extra.
                while True:
                    file_gap = gap_files if used_in_roll > 0 else 0.0
                    if (used_in_roll + file_gap + j.length_m + gap_endroll) <= limit or guard >= 50:
                        break
                    guard += 1
                    if used_in_roll > 0:
                        add_gap(planned, current_fabric, gap_endroll, speed)
                    global_roll_no += 1
                    fabric_roll_index += 1
                    used_in_roll = 0.0
                    limit = limit_for_roll(fabric, fabric_roll_index)

                if global_roll_no not in roll_scrap_labels:
                    sc_match = scrap_match_for_roll(fabric, fabric_roll_index)
                    if sc_match:
                        roll_scrap_labels[global_roll_no] = f"{sc_match.name} ({fmt_m(sc_match.length_m)})"
                        roll_scrap_keys[global_roll_no] = sc_match.key

                # gap entre arquivos: nunca antes do primeiro item do bloco.
                # Não aparece na lista — só soma na metragem do rolo/tecido.
                file_gap = gap_files if used_in_roll > 0 else 0.0
                if file_gap > 0:
                    add_gap(planned, current_fabric, file_gap, speed, hidden=True)

                emit(j, global_roll_no)
                used_in_roll += file_gap + j.length_m

            if current_fabric is not None and gap_endroll > 0:
                add_gap(planned, current_fabric, gap_endroll, speed)

        else:
            # Modo tecido: agrupa por tecido e faz bin packing (first-fit decreasing)
            # dentro de cada tecido, para que pedaços cortados pequenos sejam
            # preenchidos por itens menores em vez de pulados por serem menores
            # que o maior item da fila.
            fabrics = ordered_fabrics(base_list)

            by_fab: Dict[str, List[Job]] = {f: [] for f in fabrics}
            for j in base_list:
                if j.is_gap:
                    continue
                by_fab.setdefault(j.fabric, []).append(j)

            last_fabric_with_items: Optional[str] = None

            for f in fabrics:
                items = by_fab.get(f, [])
                if not items:
                    continue

                if last_fabric_with_items is not None:
                    add_gap(planned, last_fabric_with_items, gap_between, speed)

                bins = pack_fabric_items(f, items, gap_endroll, gap_files)

                for seq_pos, (bin_index, bin_items) in enumerate(bins):
                    global_roll_no += 1

                    sc_match = scrap_match_for_roll(f, bin_index)
                    if sc_match:
                        roll_scrap_labels[global_roll_no] = f"{sc_match.name} ({fmt_m(sc_match.length_m)})"
                        roll_scrap_keys[global_roll_no] = sc_match.key

                    # gap entre arquivos: nunca antes do primeiro nem depois do
                    # último item do bloco (rolo) — só entre itens consecutivos.
                    # Não aparece na lista — só soma na metragem do rolo/tecido.
                    for pos, item in enumerate(sorted(bin_items, key=lambda j: j.length_m, reverse=True)):
                        if pos > 0 and gap_files > 0:
                            add_gap(planned, f, gap_files, speed, hidden=True)
                        emit(item, global_roll_no)

                    if seq_pos < len(bins) - 1:
                        add_gap(planned, f, gap_endroll, speed)

                last_fabric_with_items = f

            if last_fabric_with_items is not None and gap_endroll > 0:
                add_gap(planned, last_fabric_with_items, gap_endroll, speed)

        view_rows = planned
        last_view = "queue"
        refresh_table(view_rows)
        refresh_roll_summary(view_rows)
        refresh_pedidos_summary(view_rows)

    # ---------------- Export (PDF Normal / JPG Espelhado / Ambos) ----------------
    def _ensure_queue_view() -> List[Job]:
        # Para exportar, sempre gera fila (tem roll_no, gaps e blocos)
        generate_queue()
        return list(view_rows)

    def _auto_batch_name() -> str:
        machine = var_printer.get() or "M?"
        now = datetime.now()
        # Número sequencial atômico (banco compartilhado) em vez do horário —
        # evita duplicar entre computadores diferentes. Se não conseguir
        # (ex.: pasta de rede fora do ar), propaga o erro — não cai de volta
        # pro horário, que reintroduziria o risco de duplicata.
        seq = next_roll_sequence()
        return f"{machine}_{now.strftime('%d-%m-%Y')}_{seq:04d}"

    def on_refresh_batch_name():
        try:
            var_batch_name.set(_auto_batch_name())
        except Exception as e:
            messagebox.showerror(
                "Número sequencial",
                f"Não foi possível gerar o nome do lote.\n\n{type(e).__name__}: {e}",
            )

    def _get_batch_name() -> str:
        name = var_batch_name.get().strip()
        if not name:
            name = _auto_batch_name()
            var_batch_name.set(name)
        return sanitize_filename(name)

    def _get_mirror_target_cm() -> float:
        mode = (var_jpg_mode.get() or "").strip()
        if mode in ("17", "21"):
            return float(mode)

        s = (var_jpg_custom.get() or "").replace(",", ".").strip()
        try:
            value = float(s)
        except Exception:
            raise ValueError("Largura personalizada inválida.")

        if value < 8 or value > 40:
            raise ValueError("Use entre 8 cm e 40 cm.")
        return value

    def on_set_default_mode():
        mcfg["report_mode_default"] = var_report_mode.get()
        write_module_cfg(MODULE_NAME, mcfg)
        messagebox.showinfo("Padrão salvo", "O modo de PDF foi definido como padrão.")

    def on_set_default_jpg():
        try:
            cm = _get_mirror_target_cm()
        except Exception as e:
            messagebox.showerror("JPG", str(e))
            return

        mcfg["mirror_jpg_width_mode"] = var_jpg_mode.get()
        mcfg["mirror_jpg_width_cm_custom"] = float(cm)
        write_module_cfg(MODULE_NAME, mcfg)
        messagebox.showinfo("JPG", f"Padrão salvo: {cm:.1f} cm")

    def _resolve_mirror_jpg_path(out_jpg_dir: Path, base_name: str, machine: str) -> Path:
        if var_use_printer_jpg_path.get():
            pr = find_printer_by_display_name(machine)
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

    def on_export(which: str):
        nonlocal scraps
        rows = _ensure_queue_view()
        if not rows:
            messagebox.showwarning("Nada para exportar", "Importe imagens e gere a fila primeiro.")
            return

        if edit_roll_id is not None:
            total_m_check = sum(x.length_m for x in rows if not x.is_gap)
            fabric_check = next((x.fabric for x in rows if not x.is_gap), "")
            limit_check = roll_limit_for(fabric_check) or DEFAULT_ROLL_LENGTH_M
            if total_m_check > limit_check:
                messagebox.showerror(
                    "Atualizar rolo",
                    "O conteúdo atualizado não cabe mais em um único rolo (excede a metragem "
                    f"de um rolo cheio de {fabric_check}: {fmt_m(limit_check)}). Reduza os itens "
                    "acrescentados ou lance o excedente como um novo rolo pelo fluxo normal de "
                    "exportação.",
                )
                return

        machine = var_printer.get() or "?"
        mode = var_report_mode.get()
        mode_tag = "FULL" if mode == "full" else "SUMMARY"
        try:
            batch = _get_batch_name()
        except Exception as e:
            messagebox.showerror(
                "Número sequencial",
                f"Não foi possível gerar o número sequencial do lote.\n\n{type(e).__name__}: {e}",
            )
            return
        title = f"Fila de Impressão - {batch}"

        dt = datetime.now()
        out_pdf_dir = pdf_dir(dt)
        out_jpg_dir = jpg_dir(dt)
        out_temp_dir = temp_dir()

        date_iso = dt.strftime("%Y-%m-%d")
        batch_safe = sanitize_filename(batch)
        base_name = f"{date_iso}_{machine}_{batch_safe}_{mode_tag}"

        normal_path = str(versioned_path(out_pdf_dir / f"{base_name}.pdf"))
        mirror_path = str(_resolve_mirror_jpg_path(out_jpg_dir, base_name, machine))
        tmp_mirror_pdf = str(out_temp_dir / f"{base_name}.tmp.pdf")
        tmp_normal_pdf = str(out_temp_dir / f"{base_name}.normal.tmp.pdf")

        try:
            target_cm = float(_get_mirror_target_cm())
        except Exception as e:
            messagebox.showerror("JPG", str(e))
            return

        dpi = int(mcfg.get("mirror_jpg_dpi", 300))

        scrap_labels_snapshot = dict(roll_scrap_labels)

        # Quando a pasta/arquivo da impressora está configurado, esse é o
        # único arquivo que ela recebe — por isso ele traz o espelhado
        # seguido do normal (não espelhado), em vez de só o espelhado.
        use_printer_folder = var_use_printer_jpg_path.get()

        try:
            if which == "normal":
                export_queue_pdf(
                    normal_path, rows, title, machine,
                    mode=mode, mirrored=False, scrap_labels=scrap_labels_snapshot,
                )

            elif which == "mirror":
                export_queue_pdf(
                    tmp_mirror_pdf, rows, title, machine,
                    mode=mode, mirrored=True, scrap_labels=scrap_labels_snapshot,
                )
                if use_printer_folder:
                    export_queue_pdf(
                        tmp_normal_pdf, rows, title, machine,
                        mode=mode, mirrored=False, scrap_labels=scrap_labels_snapshot,
                    )
                    mirror_and_normal_to_jpg_scaled(
                        tmp_normal_pdf, tmp_mirror_pdf, mirror_path,
                        target_width_cm=target_cm, dpi=dpi, quality=95,
                    )
                    Path(tmp_normal_pdf).unlink(missing_ok=True)
                else:
                    pdf_all_pages_to_jpg_scaled(
                        tmp_mirror_pdf, mirror_path,
                        target_width_cm=target_cm, dpi=dpi, quality=95,
                    )
                Path(tmp_mirror_pdf).unlink(missing_ok=True)

            elif which == "both":
                export_queue_pdf(
                    normal_path, rows, title, machine,
                    mode=mode, mirrored=False, scrap_labels=scrap_labels_snapshot,
                )

                export_queue_pdf(
                    tmp_mirror_pdf, rows, title, machine,
                    mode=mode, mirrored=True, scrap_labels=scrap_labels_snapshot,
                )
                if use_printer_folder:
                    mirror_and_normal_to_jpg_scaled(
                        normal_path, tmp_mirror_pdf, mirror_path,
                        target_width_cm=target_cm, dpi=dpi, quality=95,
                    )
                else:
                    pdf_all_pages_to_jpg_scaled(
                        tmp_mirror_pdf, mirror_path,
                        target_width_cm=target_cm, dpi=dpi, quality=95,
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

        db_status = ""
        try:
            export_time_iso = datetime.now().isoformat(timespec="seconds")
            roll_order, by_roll = _group_by_roll(rows)
            roll_ids: List[int] = []

            if edit_roll_id is not None:
                rn = 1
                rr = by_roll[rn]
                jobs_only = [x for x in rr if not x.is_gap]

                fab_count: Dict[str, int] = {}
                for x in jobs_only:
                    fab_count[x.fabric] = fab_count.get(x.fabric, 0) + 1
                main_fab = max(fab_count.items(), key=lambda kv: kv[1])[0]

                order_rows, total_m = _build_order_rows(rr, export_time_iso)

                old_scrap_key = get_roll_scrap_key(edit_roll_id)
                new_scrap_key = old_scrap_key
                scrap_reverted = False
                if old_scrap_key:
                    sc = next((s for s in scraps if s.key == old_scrap_key), None)
                    if sc and total_m > scrap_effective_length(sc):
                        scraps = set_scrap_used(scraps, old_scrap_key, False)
                        save_scraps(scraps)
                        new_scrap_key = ""
                        scrap_reverted = True

                roll_label = f"{batch} - Rolo {rn} - {main_fab}"
                payload = {
                    "which": which,
                    "pdf_dir": str(out_pdf_dir),
                    "jpg_dir": str(out_jpg_dir),
                    "normal_path": normal_path if which in ("normal", "both") else None,
                    "mirror_path": mirror_path if which in ("mirror", "both") else None,
                    "module": MODULE_NAME,
                    "roll_no": rn,
                    "scrap_key": new_scrap_key,
                    "scrap_label": scrap_labels_snapshot.get(rn, "") if new_scrap_key else "",
                    "scrap_reverted": scrap_reverted,
                }

                update_roll_orders(
                    edit_roll_id,
                    machine=machine,
                    roll_name=roll_label,
                    export_mode=mode,
                    app_version=APP_VERSION,
                    orders=order_rows,
                    event_type="UPDATE_ROLL",
                    event_payload=payload,
                )
                roll_ids.append(edit_roll_id)

                db_status = f"\n\nRolo atualizado no SearchOrders (id {edit_roll_id})."
                if scrap_reverted:
                    db_status += (
                        f"\n\nAviso: o pedaço cortado \"{old_scrap_key}\" foi marcado como "
                        "NÃO USADO novamente, pois o rolo atualizado excedeu a metragem dele."
                    )
            else:
                for rn in roll_order:
                    rr = by_roll[rn]
                    jobs_only = [x for x in rr if not x.is_gap]
                    if not jobs_only:
                        continue

                    fab_count: Dict[str, int] = {}
                    for x in jobs_only:
                        fab_count[x.fabric] = fab_count.get(x.fabric, 0) + 1
                    main_fab = max(fab_count.items(), key=lambda kv: kv[1])[0]

                    order_rows, _total_m = _build_order_rows(rr, export_time_iso)

                    scrap_key = roll_scrap_keys.get(rn, "")

                    roll_label = f"{batch} - Rolo {rn} - {main_fab}"
                    payload = {
                        "which": which,
                        "pdf_dir": str(out_pdf_dir),
                        "jpg_dir": str(out_jpg_dir),
                        "normal_path": normal_path if which in ("normal", "both") else None,
                        "mirror_path": mirror_path if which in ("mirror", "both") else None,
                        "module": MODULE_NAME,
                        "roll_no": rn,
                        "scrap_key": scrap_key,
                        "scrap_label": scrap_labels_snapshot.get(rn, ""),
                    }

                    roll_id, is_new = save_export_transactional(
                        machine=machine,
                        roll_name=roll_label,
                        export_mode=mode,
                        app_version=APP_VERSION,
                        orders=order_rows,
                        event_type="EXPORT_ROLL",
                        event_payload=payload,
                    )
                    roll_ids.append(roll_id)

                    if is_new and scrap_key:
                        scraps = set_scrap_used(scraps, scrap_key, True)
                        save_scraps(scraps)

                if roll_ids:
                    db_status = f"\n\nRegistrado no SearchOrders: {len(roll_ids)} rolo(s) (ids {roll_ids})."
                else:
                    db_status = (
                        "\n\nAviso: nenhum rolo foi registrado no SearchOrders "
                        "(a fila gerada não tinha nenhum item, só espaços)."
                    )
        except Exception as e:
            db_status = f"\n\nAviso: falha ao registrar no SearchOrders.\n\n{traceback.format_exc()}"

        if which == "both":
            messagebox.showinfo(
                "Exportado",
                f"PDF (comprovante):\n{out_pdf_dir}\n"
                f"JPG (operação):\n{out_jpg_dir}\n\n"
                f"{Path(normal_path).name}\n"
                f"{Path(mirror_path).name}"
                f"{db_status}",
            )
        elif which == "normal":
            messagebox.showinfo(
                "Exportado", f"PDF (comprovante):\n{out_pdf_dir}\n\n{Path(normal_path).name}{db_status}"
            )
        else:
            messagebox.showinfo(
                "Exportado", f"JPG (operação):\n{out_jpg_dir}\n\n{Path(mirror_path).name}{db_status}"
            )

    if preload:
        jobs.clear()
        for jd in preload.get("jobs", []):
            jobs.append(job_from_known_length(
                name=str(jd.get("name", "")),
                path=Path(jd["path"]) if jd.get("path") else None,
                fabric=str(jd.get("fabric", "Outro")),
                length_m=float(jd.get("length_m", 0.0) or 0.0),
            ))
        if preload.get("batch_name"):
            var_batch_name.set(str(preload["batch_name"]))

        var_edit_banner.set(
            f"✏ Editando rolo já registrado (ID {edit_roll_id}) — ao exportar, "
            "este rolo será ATUALIZADO (não cria um novo registro)."
        )
        btn_export_normal.configure(text="Atualizar PDF Normal")
        btn_export_mirror.configure(text="Atualizar JPG Espelhado")
        btn_export_both.configure(text="Atualizar Ambos")

    # init: já inicia em modo tecido com fila
    generate_queue()
    return frame