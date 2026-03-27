from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

from core.format import fmt_m
from .models import Block

try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
except Exception:
    canvas = None
    A4 = None
    pdfmetrics = None

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


def _cm_to_px(cm: float, dpi: int) -> int:
    return max(1, int(round((float(cm) / 2.54) * int(dpi))))


def pdf_first_page_to_jpg_scaled(
    pdf_path: str | Path,
    jpg_path: str | Path,
    *,
    target_width_cm: float,
    dpi: int = 300,
    quality: int = 95,
) -> None:
    """
    Renderiza a 1ª página do PDF em JPG com largura física alvo (cm).

    - Gera pixels suficientes para bater a largura em cm no DPI informado
    - Salva o JPG com metadata dpi=(dpi, dpi) para impressão no tamanho correto
    """
    if not _HAS_PYMUPDF or fitz is None:
        raise RuntimeError("PyMuPDF não instalado. Instale: pip install pymupdf")

    if not _HAS_PIL or Image is None:
        raise RuntimeError("Pillow não instalado. Instale: pip install pillow")

    if target_width_cm <= 0:
        raise ValueError("target_width_cm deve ser > 0")

    if dpi <= 0:
        raise ValueError("dpi deve ser > 0")

    pdf_path = str(pdf_path)
    jpg_path = str(jpg_path)

    target_width_px = _cm_to_px(target_width_cm, dpi)

    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(0)
        page_width_pt = float(page.rect.width)
        if page_width_pt <= 0:
            raise RuntimeError("Página inválida para renderizar.")

        zoom = target_width_px / page_width_pt
        mat = fitz.Matrix(zoom, zoom)

        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        img.save(jpg_path, "JPEG", dpi=(dpi, dpi), quality=int(quality))
    finally:
        doc.close()


def pdf_first_page_to_jpg_sized(
    pdf_path: str | Path,
    jpg_path: str | Path,
    target_width_cm: float,
    dpi: int = 300,
) -> None:
    """
    Compat wrapper.

    Mantido para não quebrar chamadas antigas, mas delega para
    pdf_first_page_to_jpg_scaled para evitar duplicação de lógica.
    """
    pdf_first_page_to_jpg_scaled(
        pdf_path,
        jpg_path,
        target_width_cm=target_width_cm,
        dpi=dpi,
        quality=95,
    )


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
        (
            f"Máquina: {machine}    "
            f"Modo: {'Completo' if mode == 'full' else 'Resumido'}    "
            f"Gerado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        ),
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

        # quebra por caracteres se a palavra sozinha for maior que a coluna
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


def _draw_wrapped_cell(
    c,
    x: float,
    y_top: float,
    lines: List[str],
    font_name: str,
    font_size: int,
    line_h: float,
) -> None:
    c.setFont(font_name, font_size)
    yy = y_top
    for line in lines:
        c.drawString(x, yy, line)
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
    - Total (m) centralizado, usando fmt_m
    - Qtd Pedidos centralizado
    - Total geral no final
    """
    # área útil A4 com margem 40 => ~515
    w_num = 30
    w_fab = 180
    w_total = 90
    w_jobs = 70
    w_last = 145  # reservado para "Último fim"

    def _reprint_summary_header(y0: float) -> float:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y0, "Resumo (ordem do rolo)")
        y0 -= 16

        c.setFont("Helvetica", 10)
        c.line(40, y0, page_w - 40, y0)
        y0 -= 18

        c.setFont("Helvetica-Bold", 10)
        x = 40
        c.drawString(x, y0, "#")
        x += w_num
        c.drawString(x, y0, "Tecido")
        x += w_fab
        c.drawCentredString(x + (w_total / 2), y0, "Total (m)")
        x += w_total
        c.drawCentredString(x + (w_jobs / 2), y0, "Qtd Pedidos")
        x += w_jobs
        c.drawString(x, y0, "Último fim")
        y0 -= 14

        c.setFont("Helvetica", 10)
        return y0

    y = _reprint_summary_header(y)

    for index, block in enumerate(blocks, start=1):
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
        c.drawString(x, y, str(index))
        x += w_num

        c.drawString(x, y, block.fabric)
        x += w_fab

        c.drawCentredString(x + (w_total / 2), y, fmt_m(block.total_m))
        x += w_total

        c.drawCentredString(x + (w_jobs / 2), y, str(block.job_count))
        x += w_jobs

        c.drawString(x, y, block.newest_end.strftime("%d/%m/%Y %H:%M:%S"))
        y -= 14

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
    c.drawRightString(page_w - 40, y, fmt_m(total_roll))
    c.setFont("Helvetica", 10)
    y -= 18

    return y


def export_pdf(
    out_path: str | Path,
    blocks: List[Block],
    roll_name: str,
    machine: str,
    mode: str = "full",
    mirrored: bool = False,
) -> None:
    if canvas is None or A4 is None:
        raise RuntimeError("reportlab não está instalado. Instale: pip install reportlab")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    page_w, page_h = A4
    c = canvas.Canvas(str(out_path), pagesize=A4)

    def _begin_page() -> None:
        if mirrored:
            c.saveState()
            c.transform(-1, 0, 0, 1, page_w, 0)

    def _end_page() -> None:
        if mirrored:
            c.restoreState()
        c.showPage()

    y = page_h - 40
    _begin_page()
    y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)

    if mode == "summary":
        _pdf_draw_summary_table(c, blocks, y, page_w, page_h, roll_name, machine, mode, mirrored)
        _end_page()
        c.save()
        return

    # completo
    w_end = 120
    w_doc = 260
    w_fab = 95
    w_size = 40

    font = "Helvetica"
    font_bold = "Helvetica-Bold"
    fs_head = 10
    fs_row = 10
    line_h = 12

    def _reprint_jobs_header(y0: float) -> float:
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

    y = _reprint_jobs_header(y)

    for block_index, block in enumerate(blocks):
        if block_index > 0:
            if _pdf_need_new_page(y, min_y=95):
                _end_page()
                _begin_page()
                y = page_h - 40
                y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)
                y = _reprint_jobs_header(y)

            c.setLineWidth(1)
            c.line(40, y + 6, page_w - 40, y + 6)
            y -= 8

        for job in sorted(block.Jobs, key=lambda j: j.end_time, reverse=True):
            end_txt = job.end_time.strftime("%d/%m/%Y %H:%M:%S")
            doc_txt = job.document
            fab_txt = job.fabric
            size_txt = fmt_m(job.real_m, suffix=False)

            doc_lines = _wrap_text(doc_txt, w_doc - 6, font, fs_row)
            fab_lines = _wrap_text(fab_txt, w_fab - 6, font, fs_row)

            row_lines = max(len(doc_lines), len(fab_lines), 1)
            row_h = row_lines * line_h

            if _pdf_need_new_page(y - row_h, min_y=95):
                _end_page()
                _begin_page()
                y = page_h - 40
                y = _pdf_draw_header(c, roll_name, machine, mode, page_w, y)
                y = _reprint_jobs_header(y)

            x0 = 40
            c.setFont(font, fs_row)

            c.drawString(x0, y, end_txt)
            _draw_wrapped_cell(c, x0 + w_end, y, doc_lines, font, fs_row, line_h)
            _draw_wrapped_cell(c, x0 + w_end + w_doc, y, fab_lines, font, fs_row, line_h)
            c.drawRightString(
                x0 + w_end + w_doc + w_fab + w_size - 2,
                y,
                size_txt,
            )

            y -= row_h

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