"""Renderizador visual do comprovante "Prisma" (ver especificação
`fix/prisma-pdf-rendering`), compartilhado entre Operação e Planejador —
mesmo princípio arquitetural do Clássico (cada módulo mantém seu próprio
adaptador de dados, mas os dois chamam este único módulo de desenho),
sem fundir com nenhum dos dois renderizadores Clássico existentes
(`modules/operacao/exporters.py:_render_report_body` e as funções
`_pdf_draw_*` de `modules/planejador.py`), que continuam intocados.

Referência visual: `Referencia/nexor-comprovante-prototipo-v7.html` (lido
integralmente, HTML/CSS reais — ver seção 1 da especificação). Este
módulo não tenta reproduzir o HTML pixel a pixel (reportlab desenha em
canvas de baixo nível, não renderiza HTML/CSS), mas reproduz sua
hierarquia visual: cabeçalho com selo do rolo, grade de indicadores,
cartões compactos de metragem por tecido, tabela de sequência detalhada
e as duas tabelas de resumo finais — com paleta de cor e tipografia
próprias, propositalmente diferentes do Clássico.

Os dados de exemplo do protótipo (rolos 0101/0103/0104) NUNCA entram
aqui — este módulo só desenha o que `PrismaReportData` already carrega,
sempre vindo de dados reais do rolo."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

try:
    from reportlab.pdfbase import pdfmetrics
except Exception:
    pdfmetrics = None

from core.pdf_text import wrap_pdf_text as _wrap_text

PAGE_MARGIN = 40

# Paleta aproximada do protótipo V7 (ver <style> do HTML de referência).
_INK = (0.09, 0.14, 0.21)
_MUTED = (0.42, 0.47, 0.53)
_LINE = (0.89, 0.92, 0.94)
_TEAL = (0.03, 0.50, 0.48)
_TEAL_LIGHT_BG = (0.91, 0.96, 0.96)
_TEAL_LIGHT_BORDER = (0.80, 0.91, 0.90)
_CARD_BG = (0.96, 0.97, 0.98)
_CARD_BORDER = (0.88, 0.91, 0.93)
_SPACE_BG = (1.0, 0.96, 0.90)
_SPACE_BORDER = (0.95, 0.88, 0.76)
_SPACE_TEXT = (0.59, 0.40, 0.04)
_REPLACEMENT_TEXT = (0.03, 0.48, 0.41)
_TABLE_HEAD_BG = (0.95, 0.96, 0.97)
_ROW_ALT_BG = (0.98, 0.99, 1.0)
_TAG_BG = (0.941, 0.957, 0.969)
_TAG_TEXT = (0.314, 0.388, 0.475)


@dataclass
class PrismaFileRow:
    end_time_label: str
    pedido: str
    document: str
    fabric: str
    is_space: bool
    tipo_label: str
    operador: str = ""
    vendor: str = ""
    observacao: str = ""
    metros_label: str = ""


@dataclass
class PrismaFabricRow:
    fabric: str
    file_count: int
    metros_label: str
    is_space: bool = False
    last_end_label: str = ""


@dataclass
class PrismaPedidoRow:
    pedido: str
    file_count: int
    metros_label: str


@dataclass
class PrismaReportData:
    roll_id: str
    is_test_roll: bool
    printer_full_name: str
    machine_code: str
    operator: str
    generated_at_label: str
    mode: str
    prints_count: int
    pedidos_count: int
    fabrics_count: int
    normal_pedidos_count: int = 0
    reposicao_files_count: int = 0
    reposicao_operator_label: str = ""
    fabric_cards: List[PrismaFabricRow] = field(default_factory=list)
    rows: List[PrismaFileRow] = field(default_factory=list)
    pedidos_summary: List[PrismaPedidoRow] = field(default_factory=list)
    fabrics_summary: List[PrismaFabricRow] = field(default_factory=list)


def _truncate_to_width(text: str, max_width: float, font_name: str, font_size: int) -> str:
    """Corta com reticências (nunca quebra em várias linhas) — usado pelas
    células de uma linha só de `_mini_table`/`_draw_table_in_column`
    (ex.: nome de arquivo na fila do Planejador, pedaço cortado), que não
    têm como crescer em altura sem desalinhar as outras colunas da
    mesma linha. Mesmo princípio de `_pdf_truncate` do Clássico
    (modules/planejador.py), mas achando o maior prefixo que cabe em vez
    de um corte fixo de caracteres."""
    text = (text or "").strip()
    if not text or pdfmetrics is None:
        return text
    if pdfmetrics.stringWidth(text, font_name, font_size) <= max_width:
        return text
    ellipsis = "…"
    for i in range(len(text), 0, -1):
        candidate = text[:i].rstrip() + ellipsis
        if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
            return candidate
    return ellipsis


def _draw_wrapped(c, x: float, y_top: float, lines: List[str], font: str, size: int, line_h: float) -> float:
    c.setFont(font, size)
    yy = y_top
    for line in lines:
        c.drawString(x, yy, line)
        yy -= line_h
    return yy


def _need_new_page(y: float, min_y: float, continuous: bool) -> bool:
    if continuous:
        return False
    return y < min_y


def _begin_page(c, page_w: float, mirrored: bool) -> None:
    if mirrored:
        c.saveState()
        c.transform(-1, 0, 0, 1, page_w, 0)


def _end_page(c, mirrored: bool) -> None:
    if mirrored:
        c.restoreState()
    c.showPage()


def _draw_continuation_header(c, page_w: float, top_y: float, data: PrismaReportData) -> float:
    """Cabeçalho leve, repetido só nas páginas de continuação (a primeira
    página já tem o cabeçalho completo — ver _draw_main_header)."""
    c.setFillColorRGB(*_INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(PAGE_MARGIN, top_y, f"Ordem do rolo — {data.roll_id} (continuação)")
    c.setStrokeColorRGB(*_INK)
    c.setLineWidth(1)
    c.line(PAGE_MARGIN, top_y - 10, page_w - PAGE_MARGIN, top_y - 10)
    return top_y - 26


def _draw_roll_name_footer(
    c, page_w: float, page_h: float, y: float, data: PrismaReportData, mirrored: bool, continuous: bool
) -> float:
    """Repete o nome do rolo no final do comprovante (pedido do usuário) —
    além do cabeçalho, quem só olhar a última página/folha solta do
    comprovante (ex.: depois de separar as páginas) também consegue
    identificar de qual rolo ela é. Mesmo recurso do Clássico (ver
    modules/operacao/exporters.py:_draw_roll_name_footer)."""
    if _need_new_page(y, 40, continuous):
        _end_page(c, mirrored)
        _begin_page(c, page_w, mirrored)
        y = page_h - 40
        y = _draw_continuation_header(c, page_w, y, data)
    y -= 4
    c.setStrokeColorRGB(*_INK)
    c.setLineWidth(1)
    c.line(PAGE_MARGIN, y, page_w - PAGE_MARGIN, y)
    y -= 16
    c.setFillColorRGB(*_INK)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(page_w / 2, y, f"Rolo: {data.roll_id}")
    c.setFont("Helvetica", 10)
    return y - 14


def _draw_main_header(c, page_w: float, top_y: float, data: PrismaReportData) -> float:
    usable_w = page_w - 2 * PAGE_MARGIN
    y = top_y

    c.setFillColorRGB(*_TEAL)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(PAGE_MARGIN, y, "COMPROVANTE DE PRODUÇÃO")
    y -= 15

    c.setFillColorRGB(*_INK)
    c.setFont("Helvetica-Bold", 19)
    c.drawString(PAGE_MARGIN, y, "Ordem do rolo")

    # Selo (id completo do rolo) alinhado à direita, com quebra se o nome
    # for muito longo para a largura disponível.
    serial_max_w = 230
    serial_lines = _wrap_text(data.roll_id, serial_max_w, "Helvetica-Bold", 14)[:2]
    serial_y = y
    for line in serial_lines:
        c.setFont("Helvetica-Bold", 14)
        c.drawRightString(page_w - PAGE_MARGIN, serial_y, line)
        serial_y -= 16

    c.setFillColorRGB(*_MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(PAGE_MARGIN, y - 14, "Relatório de impressão")
    y -= 14

    pill_label = "ROLO DE TESTE" if data.is_test_roll else "ROLO FECHADO"
    pill_w = pdfmetrics.stringWidth(pill_label, "Helvetica-Bold", 8) + 16 if pdfmetrics else 90
    pill_y = serial_y - 4
    if data.is_test_roll:
        c.setFillColorRGB(0.75, 0, 0)
    else:
        c.setFillColorRGB(*_TEAL_LIGHT_BG)
    c.roundRect(page_w - PAGE_MARGIN - pill_w, pill_y - 10, pill_w, 16, 7, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1) if data.is_test_roll else c.setFillColorRGB(*_TEAL)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(page_w - PAGE_MARGIN - pill_w / 2, pill_y - 5, pill_label)

    y -= 18
    c.setStrokeColorRGB(*_INK)
    c.setLineWidth(1.3)
    c.line(PAGE_MARGIN, y, page_w - PAGE_MARGIN, y)
    y -= 20

    # Grade de metadados: IMPRESSORA / Identificador técnico / Fechado por / Gerado em.
    meta_cols = [
        ("IMPRESSORA", data.printer_full_name or data.machine_code),
        ("IDENTIFICADOR TÉCNICO", data.machine_code),
        ("FECHADO POR", data.operator or "—"),
        ("GERADO EM", data.generated_at_label),
    ]
    col_w = usable_w / 4
    for i, (label, value) in enumerate(meta_cols):
        cx = PAGE_MARGIN + i * col_w
        c.setFillColorRGB(*_MUTED)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(cx, y, label)
        c.setFillColorRGB(*_INK)
        c.setFont("Helvetica-Bold", 9)
        value_lines = _wrap_text(value, col_w - 8, "Helvetica-Bold", 9)[:2]
        _draw_wrapped(c, cx, y - 13, value_lines, "Helvetica-Bold", 9, 11)
    y -= 46

    # Cartões de indicadores (impressões / pedidos / tecidos).
    stat_w = (usable_w - 16) / 3
    stats = [
        ("IMPRESSÕES REGISTRADAS", str(data.prints_count), "Pedidos + reposições", True),
        ("PEDIDOS DISTINTOS", str(data.pedidos_count), "Sem contar espaços", False),
        ("TECIDOS IMPRESSOS", str(data.fabrics_count), "Tipos de tecido no rolo", False),
    ]
    for i, (label, number, sub, primary) in enumerate(stats):
        cx = PAGE_MARGIN + i * (stat_w + 8)
        box_h = 42
        if primary:
            c.setFillColorRGB(*_TEAL_LIGHT_BG)
            c.setStrokeColorRGB(*_TEAL_LIGHT_BORDER)
        else:
            c.setFillColorRGB(1, 1, 1)
            c.setStrokeColorRGB(*_CARD_BORDER)
        c.setLineWidth(0.8)
        c.roundRect(cx, y - box_h, stat_w, box_h, 5, stroke=1, fill=1)

        c.setFillColorRGB(*_MUTED)
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(cx + 8, y - 12, label)

        c.setFillColorRGB(*_INK)
        c.setFont("Helvetica-Bold", 17)
        c.drawString(cx + 8, y - 29, number)

        c.setFillColorRGB(*_MUTED)
        c.setFont("Helvetica", 6.5)
        c.drawString(cx + 8, y - 38, sub)
    y -= box_h + 12

    if data.normal_pedidos_count or data.reposicao_files_count:
        chip_y = y
        chip_h = 16
        cx = PAGE_MARGIN
        if data.normal_pedidos_count:
            label = f"{data.normal_pedidos_count} pedido normal" if data.normal_pedidos_count == 1 else f"{data.normal_pedidos_count} pedidos normais"
            w = pdfmetrics.stringWidth(label, "Helvetica", 8) + 14 if pdfmetrics else 100
            c.setFillColorRGB(0.97, 0.98, 0.98)
            c.setStrokeColorRGB(*_CARD_BORDER)
            c.roundRect(cx, chip_y - chip_h, w, chip_h, 6, stroke=1, fill=1)
            c.setFillColorRGB(*_INK)
            c.setFont("Helvetica", 8)
            c.drawString(cx + 7, chip_y - chip_h + 5, label)
            cx += w + 8
        if data.reposicao_files_count:
            label = f"{data.reposicao_files_count} reposição" if data.reposicao_files_count == 1 else f"{data.reposicao_files_count} reposições"
            if data.reposicao_operator_label:
                label += f" · {data.reposicao_operator_label}"
            w = pdfmetrics.stringWidth(label, "Helvetica", 8) + 14 if pdfmetrics else 140
            c.setFillColorRGB(*_TEAL_LIGHT_BG)
            c.setStrokeColorRGB(*_TEAL_LIGHT_BORDER)
            c.roundRect(cx, chip_y - chip_h, w, chip_h, 6, stroke=1, fill=1)
            c.setFillColorRGB(*_REPLACEMENT_TEXT)
            c.setFont("Helvetica", 8)
            c.drawString(cx + 7, chip_y - chip_h + 5, label)
        y -= chip_h + 10

    c.setFillColorRGB(*_INK)
    c.setStrokeColorRGB(0, 0, 0)
    return y


def _draw_fabric_cards(c, page_w: float, y: float, data: PrismaReportData) -> float:
    if not data.fabric_cards:
        return y
    usable_w = page_w - 2 * PAGE_MARGIN

    c.setFillColorRGB(*_INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(PAGE_MARGIN, y, "01 · Metragem por tecido")
    c.setFillColorRGB(*_MUTED)
    c.setFont("Helvetica", 8)
    c.drawRightString(page_w - PAGE_MARGIN, y, "Somente tecidos · compacto")
    y -= 16

    card_w, card_h, gap = 118, 26, 6
    per_row = max(1, int((usable_w + gap) // (card_w + gap)))
    cx, cy = PAGE_MARGIN, y
    for i, card in enumerate(data.fabric_cards):
        col = i % per_row
        if col == 0 and i > 0:
            cy -= card_h + gap
        cx = PAGE_MARGIN + col * (card_w + gap)

        c.setFillColorRGB(*_CARD_BG)
        c.setStrokeColorRGB(*_CARD_BORDER)
        c.setLineWidth(0.7)
        c.roundRect(cx, cy - card_h, card_w, card_h, 4, stroke=1, fill=1)

        c.setFillColorRGB(*_MUTED)
        c.setFont("Helvetica-Bold", 6.5)
        name = card.fabric if len(card.fabric) <= 18 else card.fabric[:17] + "…"
        c.drawString(cx + 7, cy - 10, name)

        c.setFillColorRGB(*_INK)
        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(cx + card_w - 7, cy - 20, card.metros_label)
    y = cy - card_h - 14
    return y


# Proporções 12% / 38% / 16% / 23% / 11% do protótipo HTML (colgroup da
# tabela "02 · Sequência do rolo"), aplicadas à largura útil da A4 (~515pt).
_COL_END = 62
_COL_PED = 196
_COL_FAB = 82
_COL_TIPO = 119
_COL_METROS = 57
_LEFT = PAGE_MARGIN


def _detail_table_header(c, page_w: float, y: float) -> float:
    c.setFillColorRGB(*_INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(PAGE_MARGIN, y, "02 · Sequência do rolo")
    c.setFillColorRGB(*_MUTED)
    c.setFont("Helvetica", 8)
    c.drawRightString(page_w - PAGE_MARGIN, y, "Último impresso primeiro")
    y -= 13

    c.setFont("Helvetica", 7)
    c.drawString(
        PAGE_MARGIN, y,
        "O tipo de impressão, o operador de reposição e o vendedor aparecem junto ao registro correspondente.",
    )
    y -= 12

    head_h = 15
    c.setFillColorRGB(*_TABLE_HEAD_BG)
    c.rect(_LEFT, y - head_h + 3, page_w - 2 * PAGE_MARGIN, head_h, stroke=0, fill=1)

    c.setFillColorRGB(0.36, 0.43, 0.50)
    c.setFont("Helvetica-Bold", 7)
    x = _LEFT + 4
    c.drawString(x, y - 7, "FIM")
    x += _COL_END
    c.drawString(x, y - 7, "PEDIDO E ARQUIVO")
    x += _COL_PED
    c.drawString(x, y - 7, "TECIDO")
    x += _COL_FAB
    c.drawString(x, y - 7, "TIPO / RESPONSÁVEL")
    x += _COL_TIPO
    c.drawRightString(x + _COL_METROS - 4, y - 7, "METROS")
    y -= head_h + 6
    c.setFillColorRGB(*_INK)
    return y


def _draw_detail_rows(c, page_w: float, page_h: float, y: float, data: PrismaReportData, mirrored: bool, continuous: bool) -> float:
    font, font_bold, font_italic = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"
    fs, fs_small = 8.5, 7.5
    line_h, line_h_small = 10, 9

    def new_page(y0: float) -> float:
        _end_page(c, mirrored)
        _begin_page(c, page_w, mirrored)
        y0 = page_h - 40
        y0 = _draw_continuation_header(c, page_w, y0, data)
        return _detail_table_header(c, page_w, y0)

    row_index = 0
    for row in data.rows:
        ped_lines = _wrap_text(row.pedido, _COL_PED - 8, font_bold, fs)
        doc_lines = _wrap_text(row.document, _COL_PED - 8, font, fs_small)
        # Vendedor fica na coluna de pedido/arquivo (igual ao protótipo
        # HTML — meta-line dentro da mesma célula), não na de tipo.
        vendor_lines = _wrap_text(f"Vendedor: {row.vendor}", _COL_PED - 8, font, fs_small) if (row.vendor and not row.is_space) else []
        fab_lines = _wrap_text(row.fabric, _COL_FAB - 6, font, fs)
        tipo_label = row.tipo_label or ("Espaço" if row.is_space else "")
        tipo_lines = _wrap_text(tipo_label, _COL_TIPO - 6, font_bold, fs)
        extra_lines: List[str] = []
        if row.operador:
            extra_lines.append(f"Operador: {row.operador}")
        extra_wrapped: List[str] = []
        for extra in extra_lines:
            extra_wrapped.extend(_wrap_text(extra, _COL_TIPO - 6, font, fs_small))
        obs_lines = _wrap_text(f"Obs: {row.observacao}", _COL_PED - 8, font_italic, fs_small) if row.observacao else []
        end_lines = _wrap_text(row.end_time_label, _COL_END - 6, font, fs_small)

        left_h = (
            len(ped_lines) * line_h
            + len(doc_lines) * line_h_small
            + len(vendor_lines) * line_h_small
            + len(obs_lines) * line_h_small
        )
        right_h = len(tipo_lines) * line_h + len(extra_wrapped) * line_h_small
        fab_h = len(fab_lines) * line_h
        end_h = len(end_lines) * line_h_small
        row_h = max(left_h, right_h, fab_h, end_h, line_h) + 4

        if _need_new_page(y - row_h, 90, continuous):
            y = new_page(y)

        if row.is_space:
            c.setFillColorRGB(*_SPACE_BG)
            c.rect(_LEFT, y - row_h + 2, page_w - 2 * PAGE_MARGIN, row_h - 2, stroke=0, fill=1)
        elif row_index % 2 == 1:
            c.setFillColorRGB(*_ROW_ALT_BG)
            c.rect(_LEFT, y - row_h + 2, page_w - 2 * PAGE_MARGIN, row_h - 2, stroke=0, fill=1)
        row_index += 1

        x = _LEFT + 4
        c.setFillColorRGB(*_MUTED if row.is_space else _INK)
        _draw_wrapped(c, x, y - 9, end_lines, font, fs_small, line_h_small)

        x = _LEFT + 4 + _COL_END
        yy = y - 9
        c.setFillColorRGB(*_INK)
        yy = _draw_wrapped(c, x, yy, ped_lines, font_bold, fs, line_h)
        c.setFillColorRGB(*_MUTED)
        yy = _draw_wrapped(c, x, yy - 1, doc_lines, font, fs_small, line_h_small)
        if vendor_lines:
            c.setFillColorRGB(*_MUTED)
            yy = _draw_wrapped(c, x, yy - 1, vendor_lines, font, fs_small, line_h_small)
        if obs_lines:
            c.setFillColorRGB(0.49, 0.37, 0.13)
            yy = _draw_wrapped(c, x, yy - 1, obs_lines, font_italic, fs_small, line_h_small)

        # Tecido desenhado como "tag" (pílula com fundo), igual ao
        # protótipo HTML — só quando cabe numa linha só (quase sempre,
        # nomes de tecido são curtos); nomes longos caem no texto simples.
        x = _LEFT + 4 + _COL_END + _COL_PED
        if pdfmetrics is not None and len(fab_lines) == 1 and fab_lines[0]:
            label = fab_lines[0]
            tag_font, tag_size = "Helvetica-Bold", 7.3
            pad_x, tag_h = 5, 10.5
            tag_w = pdfmetrics.stringWidth(label, tag_font, tag_size) + pad_x * 2
            tag_w = min(tag_w, _COL_FAB - 6)
            baseline = y - 9
            bg, text_color = (_SPACE_BG, _SPACE_TEXT) if row.is_space else (_TAG_BG, _TAG_TEXT)
            c.setFillColorRGB(*bg)
            c.roundRect(x, baseline - 2.3, tag_w, tag_h, 3, stroke=0, fill=1)
            c.setFillColorRGB(*text_color)
            c.setFont(tag_font, tag_size)
            c.drawString(x + pad_x, baseline, label)
        else:
            c.setFillColorRGB(*_SPACE_TEXT if row.is_space else _INK)
            _draw_wrapped(c, x, y - 9, fab_lines, font, fs, line_h)

        x = _LEFT + 4 + _COL_END + _COL_PED + _COL_FAB
        tipo_color = _REPLACEMENT_TEXT if tipo_label.startswith("Reposição") else (_MUTED if row.is_space else _INK)
        c.setFillColorRGB(*tipo_color)
        yy2 = _draw_wrapped(c, x, y - 9, tipo_lines, font_bold, fs, line_h)
        c.setFillColorRGB(*_MUTED)
        _draw_wrapped(c, x, yy2 - 1, extra_wrapped, font, fs_small, line_h_small)

        c.setFillColorRGB(*_INK)
        c.setFont(font_bold, fs)
        c.drawRightString(page_w - PAGE_MARGIN - 4, y - 9, row.metros_label)

        y -= row_h

    return y


def _mini_table(c, page_w: float, page_h: float, y: float, title: str, subtitle: str, headers: List[str], col_widths: List[float], rows: List[List[str]], highlight_space, mirrored: bool, continuous: bool, continuation_header, col_align: List[bool] | None = None) -> float:
    # col_align: True = alinhado à direita (padrão pras colunas numéricas
    # já existentes); passar explicitamente só quando alguma coluna além
    # da primeira precisa ficar alinhada à esquerda (ex.: data/hora).
    # continuation_header: callable(y0) -> y0, desenha o cabeçalho leve
    # repetido numa página de continuação — recebe só `y0` (não mais o
    # dataclass inteiro) pra este desenho genérico servir tanto o
    # comprovante de um rolo (PrismaReportData) quanto o da fila do
    # Planejador (PrismaQueueReportData), que não têm o mesmo formato.
    if col_align is None:
        col_align = [False] + [True] * (len(col_widths) - 1)
    def new_page(y0: float) -> float:
        _end_page(c, mirrored)
        _begin_page(c, page_w, mirrored)
        y0 = page_h - 40
        return continuation_header(y0)

    c.setFillColorRGB(*_INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(PAGE_MARGIN, y, title)
    c.setFillColorRGB(*_MUTED)
    c.setFont("Helvetica", 8)
    c.drawRightString(page_w - PAGE_MARGIN, y, subtitle)
    y -= 15

    total_w = sum(col_widths)
    head_h = 14
    c.setFillColorRGB(*_TABLE_HEAD_BG)
    c.rect(PAGE_MARGIN, y - head_h + 3, total_w, head_h, stroke=0, fill=1)
    c.setFillColorRGB(0.36, 0.43, 0.50)
    c.setFont("Helvetica-Bold", 7)
    x = PAGE_MARGIN + 4
    for header, w in zip(headers, col_widths):
        c.drawString(x, y - 6, header)
        x += w
    y -= head_h + 4
    c.setFillColorRGB(*_INK)

    for i, row_values in enumerate(rows):
        if _need_new_page(y - 13, 70, continuous):
            y = new_page(y)
        is_space = highlight_space(row_values) if highlight_space else False
        if is_space:
            c.setFillColorRGB(*_SPACE_BG)
            c.rect(PAGE_MARGIN, y - 9, total_w, 13, stroke=0, fill=1)
        elif i % 2 == 1:
            c.setFillColorRGB(*_ROW_ALT_BG)
            c.rect(PAGE_MARGIN, y - 9, total_w, 13, stroke=0, fill=1)

        c.setFillColorRGB(*_SPACE_TEXT if is_space else _INK)
        c.setFont("Helvetica", 8.5)
        x = PAGE_MARGIN + 4
        for col_index, (value, w) in enumerate(zip(row_values, col_widths)):
            if col_align[col_index]:
                c.drawRightString(x + w - 6, y - 4, value)
            else:
                c.drawString(x, y - 4, value)
            x += w
        y -= 13
    return y - 8


def _draw_table_in_column(
    c, x: float, width: float, y: float, title: str, subtitle: str,
    headers: List[str], col_widths: List[float], rows: List[List[str]],
    highlight_space, col_align: List[bool] | None = None,
) -> float:
    """Desenha uma mini-tabela dentro de uma coluna de largura fixa, sem
    paginação própria — usada só por `_mini_table_pair`, que já decidiu
    (uma única vez, pro par inteiro) se cabe na página atual."""
    if col_align is None:
        col_align = [False] + [True] * (len(col_widths) - 1)

    c.setFillColorRGB(*_INK)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(x, y, title)
    y -= 11
    c.setFillColorRGB(*_MUTED)
    c.setFont("Helvetica", 7)
    c.drawString(x, y, subtitle)
    y -= 13

    total_w = sum(col_widths)
    head_h = 13
    c.setFillColorRGB(*_TABLE_HEAD_BG)
    c.rect(x, y - head_h + 3, total_w, head_h, stroke=0, fill=1)
    c.setFillColorRGB(0.36, 0.43, 0.50)
    c.setFont("Helvetica-Bold", 6.5)
    xx = x + 4
    for header, w in zip(headers, col_widths):
        c.drawString(xx, y - 6, header)
        xx += w
    y -= head_h + 4
    c.setFillColorRGB(*_INK)

    for i, row_values in enumerate(rows):
        is_space = highlight_space(row_values) if highlight_space else False
        if is_space:
            c.setFillColorRGB(*_SPACE_BG)
            c.rect(x, y - 8, total_w, 12, stroke=0, fill=1)
        elif i % 2 == 1:
            c.setFillColorRGB(*_ROW_ALT_BG)
            c.rect(x, y - 8, total_w, 12, stroke=0, fill=1)

        c.setFillColorRGB(*_SPACE_TEXT if is_space else _INK)
        c.setFont("Helvetica", 7.8)
        xx = x + 4
        for col_index, (value, w) in enumerate(zip(row_values, col_widths)):
            if col_align[col_index]:
                c.drawRightString(xx + w - 5, y - 4, value)
            else:
                c.drawString(xx, y - 4, value)
            xx += w
        y -= 12
    return y


def _mini_table_pair(
    c, page_w: float, page_h: float, y: float,
    left_spec: dict, right_spec: dict,
    mirrored: bool, continuous: bool, data: PrismaReportData,
) -> float:
    """"03 · Pedidos no rolo" e "04 · Resumo de tecidos e espaços" lado a
    lado, em duas colunas — igual ao `.summary-grid` (grid de 2 colunas)
    do protótipo HTML, em vez de empilhadas em largura cheia. Decide
    quebra de página uma única vez pro par inteiro (estimativa de altura
    pela tabela mais alta); não pagina uma tabela no meio — os dados reais
    (pedidos/tecidos distintos de um rolo) nunca chegam perto do tamanho
    de uma página A4."""
    usable_w = page_w - 2 * PAGE_MARGIN
    gap = 18
    col_w = (usable_w - gap) / 2

    max_rows = max(len(left_spec["rows"]), len(right_spec["rows"]))
    estimated_h = 24 + 17 + max_rows * 12 + 10
    if _need_new_page(y - estimated_h, 70, continuous):
        _end_page(c, mirrored)
        _begin_page(c, page_w, mirrored)
        y = page_h - 40
        y = _draw_continuation_header(c, page_w, y, data)

    # `col_widths` de cada spec já vem dimensionado pra largura de meia
    # página (ver chamada em `render_prisma_report_body`) — nunca
    # reescalado a partir dos valores de largura cheia: um cabeçalho como
    # "IMPRESSÕES" não encolhe com a coluna, então escalar proporcional-
    # mente a largura original (pensada pra tabela de página inteira)
    # fazia o texto do cabeçalho invadir a coluna vizinha.
    y_left = _draw_table_in_column(
        c, PAGE_MARGIN, col_w, y,
        left_spec["title"], left_spec["subtitle"], left_spec["headers"],
        left_spec["col_widths"], left_spec["rows"],
        left_spec.get("highlight_space"), left_spec.get("col_align"),
    )
    y_right = _draw_table_in_column(
        c, PAGE_MARGIN + col_w + gap, col_w, y,
        right_spec["title"], right_spec["subtitle"], right_spec["headers"],
        right_spec["col_widths"], right_spec["rows"],
        right_spec.get("highlight_space"), right_spec.get("col_align"),
    )
    return min(y_left, y_right) - 8


def render_prisma_report_body(
    c,
    page_w: float,
    page_h: float,
    data: PrismaReportData,
    mirrored: bool,
    continuous: bool,
) -> float:
    """Desenha o comprovante Prisma completo no canvas `c` já aberto —
    mesmo contrato de `_render_report_body` do Clássico (não chama
    `c.save()`; quem chama decide isso). Modo resumido desenha só
    cabeçalho + cartões + resumo de tecidos (equivalente ao que o
    Clássico faz em `_pdf_draw_summary_table`); modo completo desenha
    também a sequência detalhada e o resumo de pedidos."""
    y = page_h - 40
    _begin_page(c, page_w, mirrored)
    y = _draw_main_header(c, page_w, y, data)
    y = _draw_fabric_cards(c, page_w, y, data)

    # Nome de tecido é texto livre (cadastro do usuário), pode ser mais
    # longo do que as larguras pensadas pra siglas curtas — truncado com
    # reticências pelo mesmo motivo de _truncate_to_width na fila do
    # Planejador (achado na revisão visual de 1.6.63): _mini_table/
    # _draw_table_in_column desenham linha única, sem quebra.
    # Achado de revisão de código: a largura usada pra truncar o texto e a
    # largura da coluna na tabela eram dois literais "195" repetidos — se
    # um mudasse sem o outro, o truncamento passaria a cortar no lugar
    # errado (texto sobrando ou sobrepondo a coluna seguinte). Uma só
    # variável alimenta os dois agora; valor igual ao de antes.
    _TECIDO_SUMMARY_COL_W = 195
    _w195_fit = lambda text: _truncate_to_width(text, _TECIDO_SUMMARY_COL_W - 8, "Helvetica", 8.5)

    if data.mode == "summary":
        fabric_by_truncated_name = {_w195_fit(f.fabric): f.is_space for f in data.fabrics_summary}
        y = _mini_table(
            c, page_w, page_h, y,
            "02 · Resumo de tecidos e espaços", "Consumo físico · inclui espaços",
            ["TECIDO", "ARQUIVOS", "METROS", "ÚLTIMO FIM"], [_TECIDO_SUMMARY_COL_W, 65, 70, 145],
            [[_w195_fit(f.fabric), str(f.file_count), f.metros_label, f.last_end_label] for f in data.fabrics_summary],
            lambda row: fabric_by_truncated_name.get(row[0], False), mirrored, continuous,
            lambda y0: _draw_continuation_header(c, page_w, y0, data),
            col_align=[False, True, True, False],
        )
        y = _draw_roll_name_footer(c, page_w, page_h, y, data, mirrored, continuous)
        _end_page(c, mirrored)
        return y

    if _need_new_page(y, 150, continuous):
        _end_page(c, mirrored)
        _begin_page(c, page_w, mirrored)
        y = page_h - 40
        y = _draw_continuation_header(c, page_w, y, data)

    y = _detail_table_header(c, page_w, y)
    y = _draw_detail_rows(c, page_w, page_h, y, data, mirrored, continuous)

    y -= 14
    if _need_new_page(y, 120, continuous):
        _end_page(c, mirrored)
        _begin_page(c, page_w, mirrored)
        y = page_h - 40
        y = _draw_continuation_header(c, page_w, y, data)

    # Nome de pedido e de tecido são texto livre, podem ser mais longos do
    # que a largura de meia página reservada pra eles aqui — truncados com
    # reticências pelo mesmo motivo de _w195_fit acima: _draw_table_in_column
    # também desenha linha única, sem quebra (fonte real: "Helvetica", 7.8).
    # Mesmo motivo do `_TECIDO_SUMMARY_COL_W` acima: largura de truncamento
    # e largura de coluna vêm da mesma variável, nunca dois literais soltos.
    _PED_COL_W = 148
    _FAB_COL_W = 78
    _ped_fit = lambda text: _truncate_to_width(text, _PED_COL_W - 8, "Helvetica", 7.8)
    _fab_fit = lambda text: _truncate_to_width(text, _FAB_COL_W - 8, "Helvetica", 7.8)
    fabric_by_truncated_name = {_fab_fit(f.fabric): f.is_space for f in data.fabrics_summary}

    # "03" e "04" lado a lado, igual ao `.summary-grid` (grid de 2
    # colunas) do protótipo HTML — não empilhados em largura cheia.
    y = _mini_table_pair(
        c, page_w, page_h, y,
        {
            "title": "03 · Pedidos no rolo", "subtitle": "Espaços excluídos",
            "headers": ["PEDIDO", "IMPRESSÕES", "METROS"], "col_widths": [_PED_COL_W, 50, 50],
            "rows": [[_ped_fit(p.pedido), str(p.file_count), p.metros_label] for p in data.pedidos_summary],
            "highlight_space": None,
        },
        {
            "title": "04 · Resumo de tecidos e espaços", "subtitle": "Consumo físico · inclui espaços",
            "headers": ["TECIDO", "ARQUIVOS", "METROS", "ÚLTIMO FIM"], "col_widths": [_FAB_COL_W, 40, 50, 80],
            "rows": [[_fab_fit(f.fabric), str(f.file_count), f.metros_label, f.last_end_label] for f in data.fabrics_summary],
            "highlight_space": lambda row: fabric_by_truncated_name.get(row[0], False),
            "col_align": [False, True, True, False],
        },
        mirrored, continuous, data,
    )
    y = _draw_roll_name_footer(c, page_w, page_h, y, data, mirrored, continuous)

    _end_page(c, mirrored)
    return y


# ---------------------------------------------------------------------------
# Fila do Planejador (vários rolos, nenhum fechado ainda) — pedido explícito
# do usuário: "o prisma deve funcionar e mostrar as mesmas informações que
# tem no comprovante comum tanto no planejador quanto em operação". A fila
# não tem pedido/vendedor/tipo/operador (conceitos de um rolo já fechado,
# ver PrismaReportData acima) — tem rolo/tecido/arquivo/tempo, igual ao
# relatório Clássico da fila (`modules/planejador.py:_pdf_draw_items`/
# `_pdf_draw_roll_summary`). Por isso usa suas próprias dataclasses, nunca
# forçadas dentro de PrismaReportData, mas reaproveita os mesmos desenhos
# de base (cores, tabela genérica `_mini_table`) pra ficar visualmente
# consistente com o resto do Prisma.
@dataclass
class PrismaQueueItemRow:
    roll_no: int
    fabric: str
    document: str
    metros_label: str
    time_label: str


@dataclass
class PrismaQueueRollRow:
    roll_no: int
    main_fabric: str
    scrap_label: str
    block_count: int
    item_count: int
    metros_label: str
    time_label: str


@dataclass
class PrismaQueueReportData:
    title: str
    machine: str
    mode: str
    generated_at_label: str
    items: List[PrismaQueueItemRow] = field(default_factory=list)
    roll_summary: List[PrismaQueueRollRow] = field(default_factory=list)
    total_metros_label: str = ""
    total_time_label: str = ""


def _draw_queue_header(c, page_w: float, top_y: float, data: PrismaQueueReportData) -> float:
    usable_w = page_w - 2 * PAGE_MARGIN
    y = top_y

    c.setFillColorRGB(*_TEAL)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(PAGE_MARGIN, y, "PLANEJAMENTO DE PRODUÇÃO")
    y -= 15

    c.setFillColorRGB(*_INK)
    c.setFont("Helvetica-Bold", 19)
    title_lines = _wrap_text(data.title, usable_w, "Helvetica-Bold", 19)[:2]
    y = _draw_wrapped(c, PAGE_MARGIN, y, title_lines, "Helvetica-Bold", 19, 20)

    c.setFillColorRGB(*_MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(PAGE_MARGIN, y - 2, "Fila ainda não impressa — sujeita a alteração até o fechamento de cada rolo.")
    y -= 16

    c.setStrokeColorRGB(*_INK)
    c.setLineWidth(1.3)
    c.line(PAGE_MARGIN, y, page_w - PAGE_MARGIN, y)
    y -= 20

    meta_cols = [
        ("MÁQUINA", data.machine or "—"),
        ("MODO", "Completo" if data.mode == "full" else "Resumido"),
        ("GERADO EM", data.generated_at_label),
    ]
    col_w = usable_w / 3
    for i, (label, value) in enumerate(meta_cols):
        cx = PAGE_MARGIN + i * col_w
        c.setFillColorRGB(*_MUTED)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(cx, y, label)
        c.setFillColorRGB(*_INK)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(cx, y - 13, value)
    y -= 36

    c.setFillColorRGB(*_INK)
    c.setStrokeColorRGB(0, 0, 0)
    return y


def _draw_queue_continuation_header(c, page_w: float, top_y: float, data: PrismaQueueReportData) -> float:
    c.setFillColorRGB(*_INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(PAGE_MARGIN, top_y, f"{data.title} (continuação)")
    c.setStrokeColorRGB(*_INK)
    c.setLineWidth(1)
    c.line(PAGE_MARGIN, top_y - 10, page_w - PAGE_MARGIN, top_y - 10)
    return top_y - 26


def _draw_queue_total(c, page_w: float, y: float, data: PrismaQueueReportData) -> float:
    y -= 6
    c.setStrokeColorRGB(*_INK)
    c.setLineWidth(1)
    c.line(PAGE_MARGIN, y, page_w - PAGE_MARGIN, y)
    y -= 18
    c.setFillColorRGB(*_INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(PAGE_MARGIN, y, "Total geral:")
    c.drawRightString(page_w - PAGE_MARGIN, y, f"{data.total_metros_label}   |   {data.total_time_label}")
    c.setFont("Helvetica", 10)
    y -= 18
    return y


def render_prisma_queue_report_body(
    c,
    page_w: float,
    page_h: float,
    data: PrismaQueueReportData,
    mirrored: bool,
    continuous: bool,
) -> float:
    """Mesmo contrato de render_prisma_report_body (não chama c.save()) —
    desenha a fila inteira do Planejador (vários rolos). Mostra exatamente
    as mesmas informações do relatório Clássico da fila: tabela de pedidos
    (rolo/tecido/arquivo/tempo/metros, último da fila primeiro) e resumo
    por rolo (tecido principal/pedaço cortado/blocos/itens/total/tempo),
    com o mesmo total geral no fim. Modo resumido mostra só o resumo por
    rolo, igual ao Clássico (`_pdf_draw_roll_summary` sozinho)."""
    y = page_h - 40
    _begin_page(c, page_w, mirrored)
    y = _draw_queue_header(c, page_w, y, data)

    continuation = lambda y0: _draw_queue_continuation_header(c, page_w, y0, data)

    # Células de uma linha só (sem quebra) — nome de arquivo e pedaço
    # cortado são texto livre do operador/nome de imagem, podem ser bem
    # mais longos do que tecido/rolo; truncadas com reticências (nunca
    # quebradas em várias linhas, que desalinharia as outras colunas da
    # mesma linha — ver _truncate_to_width). Fonte/tamanho iguais aos
    # usados de verdade pelo desenho da linha em _mini_table/
    # _draw_table_in_column ("Helvetica", 8.5).
    _ROW_FONT, _ROW_SIZE = "Helvetica", 8.5

    def _fit(text: str, col_w: float) -> str:
        return _truncate_to_width(text, col_w - 8, _ROW_FONT, _ROW_SIZE)

    if data.mode == "summary":
        w_roll, w_fab, w_scrap, w_blocks, w_items, w_total, w_time = 40, 95, 115, 50, 45, 65, 55
        y = _mini_table(
            c, page_w, page_h, y,
            "01 · Resumo por rolo", "Tecido principal, pedaço cortado, blocos, itens, total e tempo",
            ["ROLO", "TECIDO (ROLO)", "PEDAÇO CORTADO", "BLOCOS", "ITENS", "TOTAL (M)", "TEMPO"],
            [w_roll, w_fab, w_scrap, w_blocks, w_items, w_total, w_time],
            [
                [str(r.roll_no), _fit(r.main_fabric, w_fab), _fit(r.scrap_label, w_scrap) or "—", str(r.block_count), str(r.item_count), r.metros_label, r.time_label]
                for r in data.roll_summary
            ],
            None, mirrored, continuous, continuation,
            col_align=[False, False, False, True, True, True, True],
        )
        y = _draw_queue_total(c, page_w, y, data)
        _end_page(c, mirrored)
        return y

    w_roll, w_fab, w_doc, w_time, w_metros = 40, 90, 230, 60, 70
    y = _mini_table(
        c, page_w, page_h, y,
        "01 · Pedidos da fila", "Último da fila primeiro",
        ["ROLO", "TECIDO", "ARQUIVO", "TEMPO", "METROS"],
        [w_roll, w_fab, w_doc, w_time, w_metros],
        [
            [str(it.roll_no), _fit(it.fabric, w_fab), _fit(it.document, w_doc), it.time_label, it.metros_label]
            for it in data.items
        ],
        None, mirrored, continuous, continuation,
        col_align=[False, False, False, True, True],
    )

    y -= 10
    if _need_new_page(y, 110, continuous):
        _end_page(c, mirrored)
        _begin_page(c, page_w, mirrored)
        y = page_h - 40
        y = continuation(y)

    w_roll2, w_fab2, w_scrap2, w_blocks2, w_items2, w_total2, w_time2 = 40, 95, 115, 50, 45, 65, 55
    y = _mini_table(
        c, page_w, page_h, y,
        "02 · Resumo por rolo", "Tecido principal, pedaço cortado, blocos, itens, total e tempo",
        ["ROLO", "TECIDO (ROLO)", "PEDAÇO CORTADO", "BLOCOS", "ITENS", "TOTAL (M)", "TEMPO"],
        [w_roll2, w_fab2, w_scrap2, w_blocks2, w_items2, w_total2, w_time2],
        [
            [str(r.roll_no), _fit(r.main_fabric, w_fab2), _fit(r.scrap_label, w_scrap2) or "—", str(r.block_count), str(r.item_count), r.metros_label, r.time_label]
            for r in data.roll_summary
        ],
        None, mirrored, continuous, continuation,
        col_align=[False, False, False, True, True, True, True],
    )

    y = _draw_queue_total(c, page_w, y, data)
    _end_page(c, mirrored)
    return y
