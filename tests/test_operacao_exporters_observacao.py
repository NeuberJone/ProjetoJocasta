"""Confirma que o comprovante (PDF modo completo, de onde o JPG também é
renderizado — ver export_pdf_continuous) imprime a observação de cada item,
além do pedido por linha — pedido reportado pelo usuário: observação não
aparecia em lugar nenhum do comprovante."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import fitz

from modules.operacao.exporters import export_pdf
from modules.operacao.models import Block, Job


class ExportPdfObservacaoTests(unittest.TestCase):
    def test_observacao_and_pedido_appear_in_full_mode_pdf(self):
        job = Job(
            end_time=datetime(2026, 11, 6, 10, 0, 0),
            document="doc1.jpg",
            fabric="DRYFIT",
            pedido="Cliente A",
            height_mm=1000.0,
            vpos_mm=0.0,
            real_mm=1000.0,
            src_file="/x/doc1.jpg",
            tipo="Pedido",
            observacao="o papel manchou aqui",
        )
        block = Block(fabric="DRYFIT", machine="M1", Jobs=[job])

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "comprovante.pdf"
            export_pdf(out_path, [block], roll_name="M1-0001", machine="M1", mode="full")

            doc = fitz.open(str(out_path))
            try:
                text = "".join(page.get_text() for page in doc)
            finally:
                doc.close()

        self.assertIn("Cliente A", text)
        self.assertIn("o papel manchou aqui", text)

    def test_test_roll_name_shows_warning_banner_in_pdf(self):
        job = Job(
            end_time=datetime(2026, 11, 6, 10, 0, 0),
            document="doc1.jpg",
            fabric="DRYFIT",
            pedido="Cliente A",
            height_mm=1000.0,
            vpos_mm=0.0,
            real_mm=1000.0,
            src_file="/x/doc1.jpg",
            tipo="Pedido",
        )
        block = Block(fabric="DRYFIT", machine="M1", Jobs=[job])

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "comprovante.pdf"
            export_pdf(out_path, [block], roll_name="M1-0001_TESTE", machine="M1", mode="full")

            doc = fitz.open(str(out_path))
            try:
                text = "".join(page.get_text() for page in doc)
            finally:
                doc.close()

        self.assertIn("ROLO DE TESTE", text)

    def test_normal_roll_name_has_no_test_banner(self):
        job = Job(
            end_time=datetime(2026, 11, 6, 10, 0, 0),
            document="doc1.jpg",
            fabric="DRYFIT",
            pedido="Cliente A",
            height_mm=1000.0,
            vpos_mm=0.0,
            real_mm=1000.0,
            src_file="/x/doc1.jpg",
            tipo="Pedido",
        )
        block = Block(fabric="DRYFIT", machine="M1", Jobs=[job])

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "comprovante.pdf"
            export_pdf(out_path, [block], roll_name="M1-0001", machine="M1", mode="full")

            doc = fitz.open(str(out_path))
            try:
                text = "".join(page.get_text() for page in doc)
            finally:
                doc.close()

        self.assertNotIn("ROLO DE TESTE", text)


if __name__ == "__main__":
    unittest.main()
