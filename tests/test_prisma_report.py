"""Testes do recurso "Prisma" (ver especificação `fix/prisma-pdf-rendering`
— corrigir a renderização, que até aqui ignorava `report_style` e sempre
desenhava o layout Clássico, só com o nome de arquivo diferente).

Cobre:
1. `core.prisma_report.render_prisma_report_body` — desenho puro, dado um
   `PrismaReportData` já pronto (sem depender do modelo de dados da
   Operação).
2. `modules.operacao.exporters._build_prisma_report_data` — o adaptador
   que converte Block/Job/PedidoSummary da Operação para esse contrato.
3. `modules.operacao.exporters.export_pdf`/`export_pdf_continuous` — que
   `report_style="prisma"` realmente produz um PDF visualmente diferente
   do Clássico (não só o nome do arquivo), e que o padrão
   (`report_style="classic"`, parâmetro novo) preserva o comportamento
   anterior.
4. `modules.operacao.ui.PXPrintLogsUI.on_export` — que o estilo
   configurado em Configurações chega de fato até `export_pdf` (a causa
   raiz do bug: antes só alimentava o sufixo do nome do arquivo).
5. Regressão da sobreposição Fim/Arquivo no Clássico (achada ao investigar
   a mesma queixa relatada para o Prisma — já existia antes, pois o PDF
   "Prisma" de teste enviado pelo usuário era, na prática, o Clássico)."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import fitz
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from core.prisma_report import (
    PrismaFabricRow,
    PrismaFileRow,
    PrismaPedidoRow,
    PrismaReportData,
    render_prisma_report_body,
)
from modules.operacao.exporters import _build_prisma_report_data, export_pdf, export_pdf_continuous
from modules.operacao.models import Block, Job, PedidoSummary
from modules.operacao.ui import PXPrintLogsUI


def _sample_data(mode: str = "full") -> PrismaReportData:
    return PrismaReportData(
        roll_id="M1_N_11-11-2026_0106_TESTE",
        is_test_roll=True,
        printer_full_name="Mimaki TS55-1800 · M1",
        machine_code="M1",
        operator="Neuber",
        generated_at_label="11/11/2026 10:00:00",
        mode=mode,
        prints_count=2,
        pedidos_count=2,
        fabrics_count=2,
        normal_pedidos_count=1,
        reposicao_files_count=1,
        reposicao_operator_label="Neuber",
        fabric_cards=[
            PrismaFabricRow(fabric="DRYFIT", file_count=1, metros_label="5.00 m"),
            PrismaFabricRow(fabric="RIBANA", file_count=1, metros_label="2.00 m"),
        ],
        rows=[
            PrismaFileRow(
                end_time_label="10/11 10:00:00", pedido="Cliente X", document="a.jpeg",
                fabric="DRYFIT", is_space=False, tipo_label="Pedido", vendor="Evandro",
                metros_label="5.00 m",
            ),
            PrismaFileRow(
                end_time_label="10/11 09:59:00", pedido="ESPAÇO", document="espaço.jpeg",
                fabric="ESPAÇO", is_space=True, tipo_label="", metros_label="1.00 m",
            ),
            PrismaFileRow(
                end_time_label="10/11 09:58:00", pedido="N2 - Cliente Y", document="n2.jpeg",
                fabric="RIBANA", is_space=False, tipo_label="Reposição", operador="Neuber",
                metros_label="2.00 m",
            ),
        ],
        pedidos_summary=[
            PrismaPedidoRow(pedido="Cliente X", file_count=1, metros_label="5.00 m"),
            PrismaPedidoRow(pedido="N2 - Cliente Y", file_count=1, metros_label="2.00 m"),
        ],
        fabrics_summary=[
            PrismaFabricRow(fabric="ESPAÇO", file_count=1, metros_label="1.00 m", is_space=True,
                             last_end_label="10/11/2026 09:59:00"),
            PrismaFabricRow(fabric="DRYFIT", file_count=1, metros_label="5.00 m",
                             last_end_label="10/11/2026 10:00:00"),
            PrismaFabricRow(fabric="RIBANA", file_count=1, metros_label="2.00 m",
                             last_end_label="10/11/2026 09:58:00"),
        ],
    )


def _render_to_text(data: PrismaReportData, *, mirrored: bool = False, continuous: bool = False) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "out.pdf"
        page_w, page_h = A4
        c = canvas.Canvas(str(out_path), pagesize=A4)
        render_prisma_report_body(c, page_w, page_h, data, mirrored, continuous)
        c.save()
        doc = fitz.open(str(out_path))
        try:
            return "".join(page.get_text() for page in doc), len(doc)
        finally:
            doc.close()


class RenderPrismaReportBodyTests(unittest.TestCase):
    def test_full_mode_contains_all_sections_and_data(self):
        text, _ = _render_to_text(_sample_data("full"))
        self.assertIn("Ordem do rolo", text)
        self.assertIn("M1_N_11-11-2026_0106_TESTE", text)
        self.assertIn("ROLO DE TESTE", text)
        self.assertIn("Mimaki TS55-1800", text)
        self.assertIn("Metragem por tecido", text)
        self.assertIn("Sequência do rolo", text)
        self.assertIn("Pedidos no rolo", text)
        self.assertIn("Resumo de tecidos e espaços", text)
        self.assertIn("ÚLTIMO FIM", text)
        self.assertIn("10/11/2026 10:00:00", text)
        self.assertIn("Cliente X", text)
        self.assertIn("N2 - Cliente Y", text)
        self.assertIn("Reposição", text)
        self.assertIn("Neuber", text)
        self.assertIn("Vendedor: Evandro", text)
        self.assertIn("ESPAÇO", text)

    def test_vendor_is_not_shown_for_space_rows(self):
        data = _sample_data("full")
        data.rows[1].vendor = "Não deveria aparecer"  # linha de espaço
        text, _ = _render_to_text(data)
        self.assertNotIn("Não deveria aparecer", text)

    def test_summary_mode_skips_detail_and_pedidos_sections(self):
        text, _ = _render_to_text(_sample_data("summary"))
        self.assertIn("Resumo de tecidos e espaços", text)
        self.assertIn("Metragem por tecido", text)
        self.assertNotIn("Sequência do rolo", text)
        self.assertNotIn("Pedidos no rolo", text)

    def test_non_test_roll_has_no_test_banner(self):
        data = _sample_data("full")
        data.is_test_roll = False
        text, _ = _render_to_text(data)
        self.assertNotIn("ROLO DE TESTE", text)
        self.assertIn("ROLO FECHADO", text)

    def test_continuous_mode_never_breaks_page(self):
        data = _sample_data("full")
        data.rows = data.rows * 30  # bastante conteúdo para forçar quebra em modo normal
        _, continuous_pages = _render_to_text(data, continuous=True)
        _, paged_pages = _render_to_text(data, continuous=False)
        self.assertEqual(continuous_pages, 1)
        self.assertGreater(paged_pages, 1)

    def test_pagination_repeats_continuation_header(self):
        data = _sample_data("full")
        data.rows = data.rows * 30
        text, pages = _render_to_text(data, continuous=False)
        self.assertGreater(pages, 1)
        self.assertIn("(continuação)", text)

    def test_long_pedido_and_fabric_names_are_truncated_in_03_and_04_tables(self):
        """Mesmo achado da revisão visual do Prisma do Planejador (1.6.63):
        "03 · Pedidos no rolo" e "04 · Resumo de tecidos e espaços" usam
        _mini_table_pair/_draw_table_in_column, que desenham linha única
        sem quebra — um pedido ou tecido com nome muito longo invadia
        visualmente a coluna de IMPRESSÕES/METROS ao lado. Ver
        core/prisma_report.py:_truncate_to_width/_ped_fit/_fab_fit."""
        data = _sample_data("full")
        long_pedido = "Cliente com nome gigante só pra garantir que o texto trunca e não sobrepõe a coluna de impressões"
        long_fabric = "Tecido com nome extremamente longo pra forçar o corte também na tabela de resumo"
        data.pedidos_summary[0].pedido = long_pedido
        data.fabrics_summary[1].fabric = long_fabric
        text, _ = _render_to_text(data)
        self.assertNotIn(long_pedido, text)
        self.assertNotIn(long_fabric, text)
        self.assertIn("…", text)

    def test_long_fabric_name_is_truncated_in_summary_mode_02_table(self):
        data = _sample_data("summary")
        long_fabric = "Tecido com nome extremamente longo pra forçar o corte também no modo resumido"
        data.fabrics_summary[1].fabric = long_fabric
        text, _ = _render_to_text(data)
        self.assertNotIn(long_fabric, text)
        self.assertIn("…", text)


class BuildPrismaReportDataTests(unittest.TestCase):
    """Testa o adaptador Operação -> PrismaReportData isoladamente (sem
    gerar PDF nenhum) — contagens, agregação por tecido e detecção de
    espaço/reposição."""

    def _jobs(self):
        t0 = datetime(2026, 11, 11, 10, 0, 0)
        return [
            Job(end_time=t0, document="a.jpeg", fabric="DRYFIT", pedido="Cliente A",
                height_mm=5000, vpos_mm=0, real_mm=5000, src_file="a.jpeg", tipo="Pedido"),
            Job(end_time=t0.replace(minute=1), document="espaço.jpeg", fabric="ESPAÇO", pedido="ESPAÇO",
                height_mm=1000, vpos_mm=0, real_mm=1000, src_file="espaço.jpeg", is_gap=True, tipo=""),
            Job(end_time=t0.replace(minute=2), document="n1.jpeg", fabric="DRYFIT", pedido="N1 - Cliente A",
                height_mm=2000, vpos_mm=0, real_mm=2000, src_file="n1.jpeg", tipo="Reposição", operador="Neuber"),
            Job(end_time=t0.replace(minute=3), document="b.jpeg", fabric="RIBANA", pedido="Cliente B",
                height_mm=3000, vpos_mm=0, real_mm=3000, src_file="b.jpeg", tipo="Pedido"),
        ]

    def test_counts_exclude_gaps(self):
        jobs = self._jobs()
        blocks = [Block(fabric=j.fabric, machine="M1", Jobs=[j]) for j in jobs]
        pedidos = [
            PedidoSummary(pedido="Cliente A", total_m=5.0, job_count=1, newest_end=jobs[0].end_time, tipo="Pedido"),
            PedidoSummary(pedido="N1 - Cliente A", total_m=2.0, job_count=1, newest_end=jobs[2].end_time, tipo="Reposição"),
            PedidoSummary(pedido="Cliente B", total_m=3.0, job_count=1, newest_end=jobs[3].end_time, tipo="Pedido"),
        ]
        data = _build_prisma_report_data("M1-0001", "M1", "full", blocks, pedidos, "Mimaki TS55-1800")

        self.assertEqual(data.prints_count, 3)  # exclui o espaço
        self.assertEqual(data.pedidos_count, 3)
        self.assertEqual(data.fabrics_count, 2)  # DRYFIT + RIBANA, sem ESPAÇO
        self.assertEqual(data.normal_pedidos_count, 2)
        self.assertEqual(data.reposicao_files_count, 1)
        self.assertEqual(data.reposicao_operator_label, "Neuber")

    def test_fabric_cards_aggregate_across_non_contiguous_blocks(self):
        """DRYFIT aparece em dois blocos não contíguos (separados por um
        espaço) — o cartão de metragem deve somar os dois, não duplicar."""
        jobs = self._jobs()
        blocks = [
            Block(fabric="DRYFIT", machine="M1", Jobs=[jobs[0]]),
            Block(fabric="ESPAÇO", machine="M1", Jobs=[jobs[1]]),
            Block(fabric="DRYFIT", machine="M1", Jobs=[jobs[2]]),
            Block(fabric="RIBANA", machine="M1", Jobs=[jobs[3]]),
        ]
        data = _build_prisma_report_data("M1-0001", "M1", "full", blocks, [], "")

        dryfit_card = next(c for c in data.fabric_cards if c.fabric == "DRYFIT")
        self.assertEqual(dryfit_card.file_count, 2)
        self.assertEqual(dryfit_card.metros_label, "7.00 m")
        self.assertEqual(len(data.fabric_cards), 2)  # DRYFIT, RIBANA — sem ESPAÇO

    def test_fabrics_summary_includes_space(self):
        jobs = self._jobs()
        blocks = [Block(fabric=j.fabric, machine="M1", Jobs=[j]) for j in jobs]
        data = _build_prisma_report_data("M1-0001", "M1", "full", blocks, [], "")

        space_row = next(f for f in data.fabrics_summary if f.fabric == "ESPAÇO")
        self.assertTrue(space_row.is_space)
        self.assertEqual(space_row.file_count, 1)
        self.assertEqual(space_row.metros_label, "1.00 m")
        self.assertEqual(space_row.last_end_label, jobs[1].end_time.strftime("%d/%m/%Y %H:%M:%S"))

    def test_fabrics_summary_is_one_row_per_block_never_merged_across_gaps(self):
        """Ao contrário dos cartões de metragem (acima), o "Resumo de
        tecidos e espaços" tem que bater exatamente com a tabela "Resumo
        (ordem do rolo)" do Clássico: uma linha por bloco/corrida, na
        ordem cronológica dada em `blocks`, mesmo quando o mesmo tecido
        aparece em corridas não contíguas (pedido explícito do usuário)."""
        jobs = self._jobs()
        blocks = [
            Block(fabric="DRYFIT", machine="M1", Jobs=[jobs[0]]),
            Block(fabric="ESPAÇO", machine="M1", Jobs=[jobs[1]]),
            Block(fabric="DRYFIT", machine="M1", Jobs=[jobs[2]]),
            Block(fabric="RIBANA", machine="M1", Jobs=[jobs[3]]),
        ]
        data = _build_prisma_report_data("M1-0001", "M1", "full", blocks, [], "")

        self.assertEqual(len(data.fabrics_summary), 4)  # nenhuma linha mesclada
        self.assertEqual([f.fabric for f in data.fabrics_summary], ["DRYFIT", "ESPAÇO", "DRYFIT", "RIBANA"])
        dryfit_rows = [f for f in data.fabrics_summary if f.fabric == "DRYFIT"]
        self.assertEqual([f.metros_label for f in dryfit_rows], ["5.00 m", "2.00 m"])
        space_row = data.fabrics_summary[1]
        self.assertTrue(space_row.is_space)
        self.assertEqual(space_row.last_end_label, jobs[1].end_time.strftime("%d/%m/%Y %H:%M:%S"))

    def test_single_reposicao_operator_shown_multiple_operators_hidden(self):
        t0 = datetime(2026, 11, 11, 10, 0, 0)
        jobs = [
            Job(end_time=t0, document="n1.jpeg", fabric="DRYFIT", pedido="N1", height_mm=1000,
                vpos_mm=0, real_mm=1000, src_file="n1.jpeg", tipo="Reposição", operador="Neuber"),
            Job(end_time=t0.replace(minute=1), document="n2.jpeg", fabric="DRYFIT", pedido="N2", height_mm=1000,
                vpos_mm=0, real_mm=1000, src_file="n2.jpeg", tipo="Reposição", operador="Gabriel"),
        ]
        blocks = [Block(fabric="DRYFIT", machine="M1", Jobs=jobs)]
        data = _build_prisma_report_data("M1-0001", "M1", "full", blocks, [], "")
        self.assertEqual(data.reposicao_files_count, 2)
        self.assertEqual(data.reposicao_operator_label, "")  # mais de um operador — não escolhe um

    def test_printer_name_combines_with_machine_code(self):
        data = _build_prisma_report_data("M1-0001", "M1", "full", [], [], "Mimaki TS55-1800")
        self.assertEqual(data.printer_full_name, "Mimaki TS55-1800 · M1")

        data_sem_impressora = _build_prisma_report_data("M1-0001", "M1", "full", [], [], "")
        self.assertEqual(data_sem_impressora.printer_full_name, "M1")


class BuildPrismaReportDataPrintCompletenessTests(unittest.TestCase):
    """Aviso de impressão incompleta (ver modules/operacao/print_check.py)
    tem que chegar na observação exibida no comprovante Prisma, igual ao
    Clássico — pedido do usuário: "isso deve ser sinalizado na tela do
    programa e no comprovante"."""

    def test_incomplete_print_prefixes_observacao(self):
        t0 = datetime(2026, 11, 11, 10, 0, 0)
        job = Job(
            end_time=t0, document="a.jpeg", fabric="DRYFIT", pedido="Cliente A",
            height_mm=7975.9, vpos_mm=0, real_mm=7975.9, src_file="a.jpeg", tipo="Pedido",
            print_status="incompleta",
            print_status_detail="Impresso 5.17 m de 7.98 m esperados (faltaram 2.80 m).",
        )
        blocks = [Block(fabric="DRYFIT", machine="M1", Jobs=[job])]
        data = _build_prisma_report_data("M1-0001", "M1", "full", blocks, [], "")

        self.assertEqual(len(data.rows), 1)
        self.assertTrue(data.rows[0].observacao.startswith("ATENÇÃO — IMPRESSÃO INCOMPLETA: Impresso 5.17 m"))

    def test_complete_print_never_prefixes_observacao(self):
        t0 = datetime(2026, 11, 11, 10, 0, 0)
        job = Job(
            end_time=t0, document="a.jpeg", fabric="DRYFIT", pedido="Cliente A",
            height_mm=5000, vpos_mm=0, real_mm=5000, src_file="a.jpeg", tipo="Pedido",
            observacao="manchou", print_status="completa",
        )
        blocks = [Block(fabric="DRYFIT", machine="M1", Jobs=[job])]
        data = _build_prisma_report_data("M1-0001", "M1", "full", blocks, [], "")

        self.assertEqual(data.rows[0].observacao, "manchou")


class BuildPrismaReportDataVendorPreviewTests(unittest.TestCase):
    """`_build_prisma_report_data` mostra o vendedor (quando identificado)
    na coluna "Tipo / responsável" do Prisma — Etapa F do recurso de
    vendedores, usando a pré-visualização somente leitura
    `core.order_vendor_resolution.guess_vendor_name_for_pedido` (o pedido
    ainda não tem `order_id` neste ponto, exportar acontece antes de
    salvar — ver core/prisma_report.py)."""

    def _blocks_with_pedidos(self, pedidos: list[str]):
        t0 = datetime(2026, 11, 11, 10, 0, 0)
        jobs = [
            Job(end_time=t0.replace(minute=i), document=f"{i}.jpeg", fabric="DRYFIT", pedido=p,
                height_mm=1000, vpos_mm=0, real_mm=1000, src_file=f"{i}.jpeg", tipo="Pedido")
            for i, p in enumerate(pedidos)
        ]
        return [Block(fabric="DRYFIT", machine="M1", Jobs=jobs)]

    def test_vendor_field_populated_from_guess(self):
        blocks = self._blocks_with_pedidos(["Cliente A"])
        with patch("modules.operacao.exporters.guess_vendor_name_for_pedido", return_value="Evandro") as guess:
            data = _build_prisma_report_data("M1-0001", "M1", "full", blocks, [], "")
        guess.assert_called_once_with("Cliente A")
        self.assertEqual(data.rows[0].vendor, "Evandro")

    def test_vendor_empty_when_guess_returns_empty(self):
        blocks = self._blocks_with_pedidos(["Cliente A"])
        with patch("modules.operacao.exporters.guess_vendor_name_for_pedido", return_value=""):
            data = _build_prisma_report_data("M1-0001", "M1", "full", blocks, [], "")
        self.assertEqual(data.rows[0].vendor, "")

    def test_space_rows_never_guess_vendor(self):
        t0 = datetime(2026, 11, 11, 10, 0, 0)
        gap = Job(end_time=t0, document="espaço.jpeg", fabric="ESPAÇO", pedido="ESPAÇO",
                  height_mm=1000, vpos_mm=0, real_mm=1000, src_file="espaço.jpeg", is_gap=True, tipo="")
        blocks = [Block(fabric="ESPAÇO", machine="M1", Jobs=[gap])]
        with patch("modules.operacao.exporters.guess_vendor_name_for_pedido") as guess:
            data = _build_prisma_report_data("M1-0001", "M1", "full", blocks, [], "")
        guess.assert_not_called()
        self.assertEqual(data.rows[0].vendor, "")

    def test_same_pedido_only_guessed_once(self):
        """Vários itens do mesmo pedido não repetem a busca no índice."""
        blocks = self._blocks_with_pedidos(["Cliente A", "Cliente A", "Cliente B"])
        with patch("modules.operacao.exporters.guess_vendor_name_for_pedido", return_value="Evandro") as guess:
            _build_prisma_report_data("M1-0001", "M1", "full", blocks, [], "")
        self.assertEqual(guess.call_count, 2)  # Cliente A (1x) + Cliente B (1x)

    def test_different_vendors_in_the_same_roll_each_show_their_own_name(self):
        """Etapa G6: a exibição de vendedor não pode depender de haver só
        um vendedor por rolo — cada pedido resolve pro seu próprio
        vendedor, independente dos outros pedidos do mesmo rolo."""
        blocks = self._blocks_with_pedidos(["Cliente A", "Cliente B"])
        by_pedido = {"Cliente A": "Evandro", "Cliente B": "Outro Vendedor"}
        with patch("modules.operacao.exporters.guess_vendor_name_for_pedido", side_effect=lambda p, **kw: by_pedido[p]):
            data = _build_prisma_report_data("M1-0001", "M1", "full", blocks, [], "")
        vendor_by_pedido = {row.pedido: row.vendor for row in data.rows}
        self.assertEqual(vendor_by_pedido["Cliente A"], "Evandro")
        self.assertEqual(vendor_by_pedido["Cliente B"], "Outro Vendedor")


class ExportPdfReportStyleDispatchTests(unittest.TestCase):
    """`export_pdf`/`export_pdf_continuous` precisam de fato desenhar algo
    diferente quando report_style="prisma" — a causa raiz do bug relatado
    era `report_style` nunca chegar até aqui (só alimentava o nome do
    arquivo, nunca o desenho)."""

    def _job_and_block(self):
        job = Job(
            end_time=datetime(2026, 11, 11, 10, 0, 0), document="a.jpeg", fabric="DRYFIT",
            pedido="Cliente A", height_mm=1000.0, vpos_mm=0.0, real_mm=1000.0,
            src_file="a.jpeg", tipo="Pedido",
        )
        return [Block(fabric="DRYFIT", machine="M1", Jobs=[job])]

    def test_classic_is_default_and_unchanged(self):
        blocks = self._job_and_block()
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "classic.pdf"
            export_pdf(out_path, blocks, roll_name="M1-0001", machine="M1", mode="full")
            doc = fitz.open(str(out_path))
            try:
                text = "".join(page.get_text() for page in doc)
            finally:
                doc.close()
        self.assertIn("Ordem do Rolo - M1-0001", text)
        self.assertIn("EndTime", text)
        self.assertNotIn("COMPROVANTE DE PRODUÇÃO", text)

    def test_prisma_style_renders_prisma_layout(self):
        blocks = self._job_and_block()
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "prisma.pdf"
            export_pdf(
                out_path, blocks, roll_name="M1-0001", machine="M1", mode="full",
                report_style="prisma", printer_name="Mimaki TS55-1800",
            )
            doc = fitz.open(str(out_path))
            try:
                text = "".join(page.get_text() for page in doc)
            finally:
                doc.close()
        self.assertIn("COMPROVANTE DE PRODUÇÃO", text)
        self.assertIn("Ordem do rolo", text)
        self.assertIn("Mimaki TS55-1800", text)
        self.assertNotIn("EndTime", text)  # marca exclusiva do cabeçalho de tabela Clássico

    def test_prisma_style_also_applies_to_continuous_export(self):
        blocks = self._job_and_block()
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "prisma_continuous.pdf"
            export_pdf_continuous(
                out_path, blocks, roll_name="M1-0001", machine="M1", mode="full",
                mirrored=False, report_style="prisma",
            )
            doc = fitz.open(str(out_path))
            try:
                text = "".join(page.get_text() for page in doc)
                self.assertEqual(len(doc), 1)
            finally:
                doc.close()
        self.assertIn("COMPROVANTE DE PRODUÇÃO", text)

    def test_incomplete_print_warning_appears_in_classic_pdf(self):
        job = Job(
            end_time=datetime(2026, 11, 11, 10, 0, 0), document="a.jpeg", fabric="DRYFIT",
            pedido="Cliente A", height_mm=7975.9, vpos_mm=0.0, real_mm=7975.9,
            src_file="a.jpeg", tipo="Pedido",
            print_status="incompleta",
            print_status_detail="Impresso 5.17 m de 7.98 m esperados (faltaram 2.80 m).",
        )
        blocks = [Block(fabric="DRYFIT", machine="M1", Jobs=[job])]
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "classic.pdf"
            export_pdf(out_path, blocks, roll_name="M1-0001", machine="M1", mode="full")
            doc = fitz.open(str(out_path))
            try:
                text = "".join(page.get_text() for page in doc)
            finally:
                doc.close()
        self.assertIn("Impresso 5.17 m de 7.98 m esperados", text)

    def test_incomplete_print_warning_appears_in_prisma_pdf(self):
        job = Job(
            end_time=datetime(2026, 11, 11, 10, 0, 0), document="a.jpeg", fabric="DRYFIT",
            pedido="Cliente A", height_mm=7975.9, vpos_mm=0.0, real_mm=7975.9,
            src_file="a.jpeg", tipo="Pedido",
            print_status="incompleta",
            print_status_detail="Impresso 5.17 m de 7.98 m esperados (faltaram 2.80 m).",
        )
        blocks = [Block(fabric="DRYFIT", machine="M1", Jobs=[job])]
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "prisma.pdf"
            export_pdf(
                out_path, blocks, roll_name="M1-0001", machine="M1", mode="full",
                report_style="prisma", printer_name="Mimaki TS55-1800",
            )
            doc = fitz.open(str(out_path))
            try:
                text = "".join(page.get_text() for page in doc)
            finally:
                doc.close()
        self.assertIn("Impresso 5.17 m de 7.98 m esperados", text)

    def test_classic_endtime_column_no_longer_overlaps_arquivo_column(self):
        """Regressão: a sobreposição Fim/Arquivo relatada (reproduzida pelo
        usuário num PDF rotulado "Prisma", mas na verdade desenhado pelo
        Clássico, já que o estilo nunca chegava ao renderizador) vinha da
        coluna EndTime ser estreita demais para a data completa. Confirma
        que a largura reservada comporta o texto mais longo realista."""
        from modules.operacao import exporters
        full_width = pdfmetrics.stringWidth("11/11/2026 09:59:00", "Helvetica", 10)
        self.assertLess(full_width, 100 - 4)
        # a soma das colunas continua cabendo na página A4 útil (515pt).
        import re
        src = Path(exporters.__file__).read_text(encoding="utf-8")
        widths = {
            name: int(value) for name, value in re.findall(
                r"(w_end|w_doc|w_fab|w_ped|w_tipo|w_op|w_size) = (\d+)", src
            )
        }
        self.assertEqual(len(widths), 7)
        self.assertLessEqual(sum(widths.values()), 515)


class RollNameFooterTests(unittest.TestCase):
    """Pedido do usuário: "Repete o nome do rolo no final dos
    comprovantes" — além do cabeçalho, a última página/folha do
    comprovante (Clássico e Prisma, Completo e Resumido) também mostra o
    nome do rolo numa linha de rodapé isolada, depois do resumo final."""

    def _job_and_block(self):
        job = Job(
            end_time=datetime(2026, 11, 11, 10, 0, 0), document="a.jpeg", fabric="DRYFIT",
            pedido="Cliente A", height_mm=1000.0, vpos_mm=0.0, real_mm=1000.0,
            src_file="a.jpeg", tipo="Pedido",
        )
        return [Block(fabric="DRYFIT", machine="M1", Jobs=[job])]

    def _render_classic(self, mode: str) -> tuple[str, int]:
        blocks = self._job_and_block()
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "classic.pdf"
            export_pdf(out_path, blocks, roll_name="M1-0001", machine="M1", mode=mode)
            doc = fitz.open(str(out_path))
            try:
                return "".join(page.get_text() for page in doc), len(doc)
            finally:
                doc.close()

    def test_classic_full_repeats_roll_name_once_at_end(self):
        text, _ = self._render_classic("full")
        self.assertEqual(text.count("Rolo: M1-0001"), 1)

    def test_classic_summary_repeats_roll_name_once_at_end(self):
        text, _ = self._render_classic("summary")
        self.assertEqual(text.count("Rolo: M1-0001"), 1)

    def test_prisma_full_repeats_roll_name_once_at_end(self):
        data = _sample_data("full")
        text, _ = _render_to_text(data)
        self.assertEqual(text.count(f"Rolo: {data.roll_id}"), 1)

    def test_prisma_summary_repeats_roll_name_once_at_end(self):
        """Também cobre a correção do `y` descartado por `_mini_table` no
        modo Resumido (ver CHANGELOG 1.6.66) — sem capturar o retorno, o
        rodapé desenharia por cima da última linha da tabela em vez de
        depois dela."""
        data = _sample_data("summary")
        text, _ = _render_to_text(data)
        self.assertEqual(text.count(f"Rolo: {data.roll_id}"), 1)

    def test_footer_appears_once_on_last_page_when_classic_breaks_pages(self):
        jobs = [
            Job(
                end_time=datetime(2026, 11, 11, 10, 0, 0), document=f"a{i}.jpeg", fabric="DRYFIT",
                pedido=f"Pedido {i}", height_mm=1000.0, vpos_mm=0.0, real_mm=1000.0,
                src_file=f"a{i}.jpeg", tipo="Pedido",
            )
            for i in range(60)
        ]
        blocks = [Block(fabric="DRYFIT", machine="M1", Jobs=jobs)]
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "classic.pdf"
            export_pdf(out_path, blocks, roll_name="M1-MULTI", machine="M1", mode="full")
            doc = fitz.open(str(out_path))
            try:
                full_text = "".join(page.get_text() for page in doc)
                pages = len(doc)
                last_text = doc[-1].get_text()
            finally:
                doc.close()
        self.assertGreater(pages, 1)
        self.assertEqual(full_text.count("Rolo: M1-MULTI"), 1)
        self.assertIn("Rolo: M1-MULTI", last_text)

    def test_footer_appears_once_on_last_page_when_prisma_breaks_pages(self):
        data = _sample_data("full")
        data.rows = data.rows * 30
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "prisma.pdf"
            page_w, page_h = A4
            c = canvas.Canvas(str(out_path), pagesize=A4)
            render_prisma_report_body(c, page_w, page_h, data, mirrored=False, continuous=False)
            c.save()
            doc = fitz.open(str(out_path))
            try:
                full_text = "".join(page.get_text() for page in doc)
                pages = len(doc)
                last_text = doc[-1].get_text()
            finally:
                doc.close()
        self.assertGreater(pages, 1)
        self.assertEqual(full_text.count(f"Rolo: {data.roll_id}"), 1)
        self.assertIn(f"Rolo: {data.roll_id}", last_text)


def _make_operacao_app(*, export_cfg: dict, printer=None) -> SimpleNamespace:
    status = Mock()
    status.cget.return_value = "Arquivos gerados"
    job = SimpleNamespace(
        end_time=datetime(2026, 11, 11, 10, 0), document="arquivo.jpeg",
        fabric="Dryfit", pedido="Pedido exemplo", height_mm=1000.0,
        vpos_mm=0.0, real_m=1.0, src_file="arquivo.txt", tipo="Pedido", observacao="",
        start_time=None,
    )
    return SimpleNamespace(
        blocks=[object()], machine="M1", Jobs=[job], pedidos=[],
        _confirm_duplicates_on_export=lambda: True,
        _get_roll_name=lambda: "M1_11-11-2026_0001",
        var_mode=SimpleNamespace(get=lambda: "full"),
        _resolve_mirror_jpg_path=lambda folder, name: folder / (name + ".jpg"),
        _get_mirror_target_cm=lambda: 17.0, edit_roll_id=None,
        status=status, _last_pdf_path=None, btn_open_comprovante=Mock(),
        var_close_roll_text=Mock(),
        _pedido_previews={}, _preview_index=None, _preview_vendedores=None,
    )


class OnExportForwardsReportStyleTests(unittest.TestCase):
    """A causa raiz do bug: `on_export` já lia `report_style` de
    Configurações, mas só usava pra montar o sufixo do nome do arquivo —
    nunca repassava pro renderizador. Confirma, no fluxo real de
    `on_export`, que `export_pdf` agora recebe `report_style` e
    `printer_name`."""

    def test_on_export_passes_report_style_and_printer_name_to_export_pdf(self):
        printer = SimpleNamespace(
            name="Mimaki TS55-1800", display_name="M1", jpg_output_dir="",
            jpg_rotation=0,
        )
        app = _make_operacao_app(export_cfg={"report_style": "prisma"})

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
            output = Path(temporary)
            export_cfg = {"mirror_jpg_dpi": 300, "report_style": "prisma"}
            captured = {}

            def _fake_export_pdf(path, *args, **kwargs):
                captured["kwargs"] = kwargs
                Path(path).write_bytes(b"pdf")

            from contextlib import ExitStack
            with ExitStack() as stack:
                for name in ("pdf_dir", "jpg_dir", "temp_dir"):
                    stack.enter_context(patch("modules.operacao.ui." + name, return_value=output))
                stack.enter_context(patch("modules.operacao.ui.load_export_cfg", return_value=export_cfg))
                stack.enter_context(patch("modules.operacao.ui.find_printer_by_display_name", return_value=printer))
                stack.enter_context(patch("modules.operacao.ui.export_pdf", side_effect=_fake_export_pdf))
                stack.enter_context(patch("modules.operacao.ui.save_export_transactional", return_value=(1, True)))
                # Sem isto, a identificação automática de vendedor que roda
                # logo após salvar (ver on_export) chamaria get_roll_orders(1)
                # contra o banco real da instalação — nunca tocar o banco de
                # verdade num teste isolado.
                stack.enter_context(patch("modules.operacao.ui.get_roll_orders", return_value=[]))
                stack.enter_context(patch("modules.operacao.ui.messagebox.showinfo"))
                stack.enter_context(patch("modules.operacao.ui.messagebox.showwarning"))
                PXPrintLogsUI.on_export(app, "normal")

        self.assertEqual(captured["kwargs"].get("report_style"), "prisma")
        self.assertEqual(captured["kwargs"].get("printer_name"), "Mimaki TS55-1800")


class OnExportAutoResolvesVendorTests(unittest.TestCase):
    """Etapa F + Parte 1 da conclusão do recurso: depois que o rolo é
    salvo, `on_export` repassa as decisões de sessão do painel de
    pré-visualização (`self._pedido_previews`) para
    `modules.operacao.vendor_pdf_apply.apply_session_decisions`, que por
    sua vez decide vendedor/PDF por `order_id` real (nunca por
    espaço/avanço) — ver tests/test_operacao_vendor_pdf_apply.py para o
    comportamento desta função em si (precedência de decisão confirmada,
    etc.); aqui só confirma que `on_export` chama ela com os argumentos
    certos."""

    def test_apply_session_decisions_called_with_roll_id_and_session_previews(self):
        printer = SimpleNamespace(name="", display_name="M1", jpg_output_dir="", jpg_rotation=0)
        app = _make_operacao_app(export_cfg={"report_style": "classic"})
        app._pedido_previews = {"Cliente X": object()}
        app._preview_index = "INDEX"
        app._preview_vendedores = "VENDEDORES"

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
            output = Path(temporary)
            export_cfg = {"mirror_jpg_dpi": 300, "report_style": "classic"}

            def _fake_export_pdf(path, *args, **kwargs):
                Path(path).write_bytes(b"pdf")

            from contextlib import ExitStack
            with ExitStack() as stack:
                for name in ("pdf_dir", "jpg_dir", "temp_dir"):
                    stack.enter_context(patch("modules.operacao.ui." + name, return_value=output))
                stack.enter_context(patch("modules.operacao.ui.load_export_cfg", return_value=export_cfg))
                stack.enter_context(patch("modules.operacao.ui.find_printer_by_display_name", return_value=printer))
                stack.enter_context(patch("modules.operacao.ui.export_pdf", side_effect=_fake_export_pdf))
                stack.enter_context(patch("modules.operacao.ui.save_export_transactional", return_value=(42, True)))
                apply_mock = stack.enter_context(patch("modules.operacao.ui.apply_session_decisions"))
                stack.enter_context(patch("modules.operacao.ui.messagebox.showinfo"))
                stack.enter_context(patch("modules.operacao.ui.messagebox.showwarning"))
                PXPrintLogsUI.on_export(app, "normal")

        apply_mock.assert_called_once_with(42, app._pedido_previews, index="INDEX", vendedores="VENDEDORES")

    def test_failure_in_vendor_pdf_resolution_never_reports_export_as_failed(self):
        """Uma falha na identificação de vendedor/PDF (ex.: índice
        indisponível) não pode aparecer como se o fechamento do rolo
        tivesse falhado — o rolo já foi salvo com sucesso antes dessa
        etapa rodar."""
        printer = SimpleNamespace(name="", display_name="M1", jpg_output_dir="", jpg_rotation=0)
        app = _make_operacao_app(export_cfg={"report_style": "classic"})

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
            output = Path(temporary)
            export_cfg = {"mirror_jpg_dpi": 300, "report_style": "classic"}

            def _fake_export_pdf(path, *args, **kwargs):
                Path(path).write_bytes(b"pdf")

            from contextlib import ExitStack
            with ExitStack() as stack:
                for name in ("pdf_dir", "jpg_dir", "temp_dir"):
                    stack.enter_context(patch("modules.operacao.ui." + name, return_value=output))
                stack.enter_context(patch("modules.operacao.ui.load_export_cfg", return_value=export_cfg))
                stack.enter_context(patch("modules.operacao.ui.find_printer_by_display_name", return_value=printer))
                stack.enter_context(patch("modules.operacao.ui.export_pdf", side_effect=_fake_export_pdf))
                stack.enter_context(patch("modules.operacao.ui.save_export_transactional", return_value=(42, True)))
                stack.enter_context(
                    patch("modules.operacao.ui.apply_session_decisions", side_effect=RuntimeError("índice indisponível"))
                )
                stack.enter_context(patch("modules.operacao.ui.messagebox.showinfo"))
                warn = stack.enter_context(patch("modules.operacao.ui.messagebox.showwarning"))
                PXPrintLogsUI.on_export(app, "normal")

        warn.assert_not_called()
        self.assertIn("DB ok (roll_id=42)", app.status.configure.call_args.kwargs.get("text", ""))


if __name__ == "__main__":
    unittest.main()
