"""Testes de core/pdf_text.py — achado de revisão de código: a quebra de
texto por largura real de fonte (reportlab) estava copiada byte a byte em
modules/planejador.py (`_pdf_wrap_text`), modules/operacao/exporters.py e
core/prisma_report.py (ambos `_wrap_text`). Consolidada aqui; os três
módulos agora só importam `wrap_pdf_text` com um alias local. Este teste
cobre o algoritmo uma vez só e confirma que os três pontos de chamada
continuam apontando pro mesmo objeto de função (nunca uma cópia que possa
divergir de novo sem ser notada)."""
import unittest

from core.pdf_text import wrap_pdf_text


class WrapPdfTextTests(unittest.TestCase):
    def test_empty_text_returns_single_empty_line(self):
        self.assertEqual(wrap_pdf_text("   ", 1000.0, "Helvetica", 10), [""])

    def test_short_text_fits_on_one_line(self):
        lines = wrap_pdf_text("ABC", 1000.0, "Helvetica", 10)
        self.assertEqual(lines, ["ABC"])

    def test_long_text_wraps_at_word_boundaries(self):
        # Largura mínima o bastante pra caber só 1-2 palavras curtas por linha.
        lines = wrap_pdf_text("aaa bbb ccc", 25.0, "Helvetica", 10)
        self.assertGreater(len(lines), 1)
        self.assertEqual(" ".join(lines).replace("  ", " "), "aaa bbb ccc")

    def test_single_word_longer_than_width_breaks_by_character(self):
        lines = wrap_pdf_text("aaaaaaaaaaaaaaaaaaaaaaaaaa", 15.0, "Helvetica", 10)
        self.assertGreater(len(lines), 1)
        self.assertEqual("".join(lines), "aaaaaaaaaaaaaaaaaaaaaaaaaa")


class SharedAcrossCallSitesTests(unittest.TestCase):
    """Garante que os três lugares que antes tinham sua própria cópia do
    algoritmo agora delegam pro mesmo objeto de função — não uma cópia
    equivalente, mas literalmente o mesmo `wrap_pdf_text`."""

    def test_planejador_uses_shared_function(self):
        from modules.planejador import _pdf_wrap_text
        self.assertIs(_pdf_wrap_text, wrap_pdf_text)

    def test_operacao_exporters_uses_shared_function(self):
        from modules.operacao.exporters import _wrap_text
        self.assertIs(_wrap_text, wrap_pdf_text)

    def test_prisma_report_uses_shared_function(self):
        from core.prisma_report import _wrap_text
        self.assertIs(_wrap_text, wrap_pdf_text)


if __name__ == "__main__":
    unittest.main()
