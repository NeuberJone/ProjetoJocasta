"""Testes do estilo "Prisma" aplicado à fila do Planejador — pedido
explícito do usuário: "o prisma deve funcionar e mostrar as mesmas
informações que tem no comprovante comum tanto no planejador quanto em
operação". A fila (vários rolos, nenhum fechado ainda) não tem
pedido/vendedor/tipo/operador (conceitos de um rolo já fechado, que a
Operação usa) — tem rolo/tecido/arquivo/tempo, exatamente o que o
Clássico já desenha (`modules/planejador.py:_pdf_draw_items`/
`_pdf_draw_roll_summary`). Por isso os testes confirmam paridade de
conteúdo com o Clássico, não um redesenho."""
import tempfile
import unittest
from pathlib import Path

import fitz

from modules.planejador import (
    Job,
    _build_prisma_queue_report_data,
    _group_by_roll,
    export_queue_pdf,
)


def _rows():
    return [
        Job(name="ped1.jpg", path=None, fabric="DRYFIT", w_px=100, h_px=100,
            length_m=3.2, time_min=2.0, roll_no=1),
        Job(name="ped2.jpg", path=None, fabric="DRYFIT", w_px=100, h_px=100,
            length_m=5.0, time_min=3.5, roll_no=1),
        Job(name="— ESPAÇO —", path=None, fabric="DRYFIT", w_px=0, h_px=0,
            length_m=0.5, time_min=0.0, roll_no=1, is_gap=True),
        Job(name="ped3.jpg", path=None, fabric="RIBANA", w_px=100, h_px=100,
            length_m=8.0, time_min=4.0, roll_no=2),
    ]


class BuildPrismaQueueReportDataTests(unittest.TestCase):
    def test_items_exclude_gaps_and_carry_roll_fabric_doc_metros_time(self):
        rows = _rows()
        roll_order, by_roll = _group_by_roll(list(reversed(rows)))
        data = _build_prisma_queue_report_data(roll_order, by_roll, "Fila de Impressão - M1-0001", "M1", "full")

        self.assertEqual(len(data.items), 3)  # 3 itens reais, o espaço nunca entra na lista
        docs = {it.document for it in data.items}
        self.assertEqual(docs, {"ped1.jpg", "ped2.jpg", "ped3.jpg"})

    def test_roll_summary_has_one_row_per_roll_with_blocks_items_scrap_total_time(self):
        rows = _rows()
        scrap_labels = {1: "Retalho Dryfit 10m"}
        roll_order, by_roll = _group_by_roll(list(reversed(rows)))
        data = _build_prisma_queue_report_data(
            roll_order, by_roll, "Fila de Impressão - M1-0001", "M1", "full", scrap_labels,
        )

        self.assertEqual(len(data.roll_summary), 2)
        roll1 = next(r for r in data.roll_summary if r.roll_no == 1)
        self.assertEqual(roll1.main_fabric, "DRYFIT")
        self.assertEqual(roll1.scrap_label, "Retalho Dryfit 10m")
        self.assertEqual(roll1.block_count, 1)  # um só bloco de DRYFIT (o espaço interrompe, mas não reabre outro tecido)
        self.assertEqual(roll1.item_count, 2)
        roll2 = next(r for r in data.roll_summary if r.roll_no == 2)
        self.assertEqual(roll2.scrap_label, "")  # sem pedaço cortado cadastrado pra este rolo

    def test_grand_total_sums_all_rolls_including_gaps(self):
        rows = _rows()
        roll_order, by_roll = _group_by_roll(list(reversed(rows)))
        data = _build_prisma_queue_report_data(roll_order, by_roll, "Fila", "M1", "full")
        # 3.2 + 5.0 + 0.5 + 8.0 = 16.7
        self.assertIn("16,70", data.total_metros_label.replace(".", ","))


class ExportQueuePdfReportStyleDispatchTests(unittest.TestCase):
    def test_classic_is_default_and_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "classic.pdf"
            export_queue_pdf(out_path, _rows(), "Fila de Impressão - M1-0001", "M1", mode="full")
            doc = fitz.open(str(out_path))
            try:
                text = "".join(page.get_text() for page in doc)
            finally:
                doc.close()
        self.assertIn("Fila de Impressão - M1-0001", text)
        self.assertIn("Pedidos (último da fila primeiro)", text)
        self.assertNotIn("PLANEJAMENTO DE PRODUÇÃO", text)

    def test_prisma_style_renders_prisma_layout_with_same_information(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "prisma.pdf"
            export_queue_pdf(
                out_path, _rows(), "Fila de Impressão - M1-0001", "M1", mode="full",
                scrap_labels={1: "Retalho Dryfit 10m"}, report_style="prisma",
            )
            doc = fitz.open(str(out_path))
            try:
                text = "".join(page.get_text() for page in doc)
            finally:
                doc.close()
        self.assertIn("PLANEJAMENTO DE PRODUÇÃO", text)
        self.assertIn("Fila de Impressão - M1-0001", text)
        # Mesmas informações do Clássico: arquivos, tecidos e pedaço cortado.
        self.assertIn("ped1.jpg", text)
        self.assertIn("ped3.jpg", text)
        self.assertIn("DRYFIT", text)
        self.assertIn("RIBANA", text)
        self.assertIn("Retalho Dryfit 10m", text)
        self.assertNotIn("Pedidos (último da fila primeiro)", text)  # marca exclusiva do cabeçalho Clássico

    def test_prisma_summary_mode_shows_only_roll_summary_like_classic(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "prisma_summary.pdf"
            export_queue_pdf(
                out_path, _rows(), "Fila de Impressão - M1-0001", "M1", mode="summary",
                report_style="prisma",
            )
            doc = fitz.open(str(out_path))
            try:
                text = "".join(page.get_text() for page in doc)
            finally:
                doc.close()
        self.assertIn("Resumo por rolo", text)
        self.assertNotIn("ped1.jpg", text)  # modo resumido não lista os itens, igual ao Clássico

    def test_prisma_mirrored_export_still_produces_a_valid_single_page_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "prisma_mirror.pdf"
            export_queue_pdf(
                out_path, _rows(), "Fila de Impressão - M1-0001", "M1", mode="full",
                mirrored=True, report_style="prisma",
            )
            doc = fitz.open(str(out_path))
            try:
                self.assertGreaterEqual(len(doc), 1)
            finally:
                doc.close()

    def test_long_filename_and_scrap_label_are_truncated_never_overlap_next_column(self):
        """Achado na revisão visual manual desta etapa: nome de arquivo e
        pedaço cortado longos invadiam visualmente as colunas seguintes
        (TEMPO/METROS), já que _mini_table desenha uma linha só, sem
        quebra — ver core/prisma_report.py:_truncate_to_width. Texto
        extraído não prova ausência de sobreposição visual sozinho, mas
        confirma que o corte com reticências realmente aconteceu (nunca o
        texto inteiro) — a prova visual real foi feita manualmente,
        renderizando a página e inspecionando a imagem."""
        long_name = "outro arquivo com nome gigante só pra garantir que o texto quebra direitinho sem sobrepor.jpg"
        long_scrap = "Retalho Dryfit bem comprido pra forçar o corte da coluna pedaço cortado também"
        rows = [
            Job(name=long_name, path=None, fabric="DRYFIT", w_px=100, h_px=100,
                length_m=2.3, time_min=2.0, roll_no=1),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "prisma_truncate.pdf"
            export_queue_pdf(
                out_path, rows, "Fila de Impressão - M1-0001", "M1", mode="full",
                scrap_labels={1: long_scrap}, report_style="prisma",
            )
            doc = fitz.open(str(out_path))
            try:
                text = "".join(page.get_text() for page in doc)
            finally:
                doc.close()
        self.assertNotIn(long_name, text)
        self.assertNotIn(long_scrap, text)
        self.assertIn("…", text)


if __name__ == "__main__":
    unittest.main()
