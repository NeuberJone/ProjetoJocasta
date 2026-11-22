"""Quebra de texto por largura real de fonte (reportlab), compartilhada
pelos três geradores de PDF do Nexor (Planejador clássico — `_pdf_wrap_text`,
Operação e o comprovante Prisma — ambos `_wrap_text`) — achado de revisão de
código: os três tinham exatamente o mesmo algoritmo copiado byte a byte.
Puro, sem Tkinter, pra ficar junto do resto de core/.

Só a quebra em várias linhas foi consolidada aqui. O corte com reticências
de uma linha só (`_pdf_truncate` em modules/planejador.py,
`_truncate_to_width` em core/prisma_report.py) tem uma diferença real de
comportamento entre as duas versões (uma faz rstrip antes da reticência, a
outra não) — não é o mesmo algoritmo com formatação diferente, então
permanece separado até alguém decidir qual comportamento é o certo pros
dois lugares.
"""
from __future__ import annotations

from typing import List

try:
    from reportlab.pdfbase import pdfmetrics
except Exception:
    pdfmetrics = None


def wrap_pdf_text(text: str, max_width: float, font_name: str, font_size: int) -> List[str]:
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
