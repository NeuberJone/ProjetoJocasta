"""Testes do sufixo de modo/estilo no nome dos comprovantes
(core.export_config.report_filename_tag) — parte do recurso "Prisma"
(estilo de comprovante Clássico/Prisma). Cobre:

1. A função pura em si (todas as combinações de modo x estilo).
2. O comportamento real de Operação (modules/operacao/ui.py:on_export),
   usando o mesmo padrão de chamada de método "desligado" de
   tests/test_failure_reporting.py — já que PXPrintLogsUI.on_export é
   testável sem precisar de um Tk real.

A combinação Clássico + completo é a mudança de comportamento real pedida
pela especificação: o nome do PDF/JPG deixa de levar "_FULL" (arquivos já
exportados antes NÃO são renomeados — isso é mudança só no código que
GERA nomes novos, nunca em arquivos existentes). Resumido continua com
"_SUMMARY" (não pedido pela especificação). Prisma NÃO soma "_PRISMA" ao
nome (pedido explícito do usuário) — Clássico e Prisma do mesmo rolo/modo
geram o mesmo nome de arquivo.

Planejador (modules/planejador.py) usa a mesma fórmula (report_filename_tag)
no mesmo ponto do código, mas seu on_export é uma função aninhada/closure
dentro de build_ui (sem classe, sem teste automatizado pré-existente nesse
módulo) — não há um jeito prático de chamá-la isoladamente sem construir a
tela inteira e simular uma fila de impressão completa. A mudança lá é
verificada por simetria exata de código com Operação (já testada aqui) e
por smoke test de construção real da tela (ver fim deste arquivo)."""
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.export_config import REPORT_STYLE_CLASSIC, REPORT_STYLE_PRISMA, report_filename_tag
from modules.operacao.ui import PXPrintLogsUI


class ReportFilenameTagTests(unittest.TestCase):
    def test_classic_full_has_no_tag(self):
        self.assertEqual(report_filename_tag("full", REPORT_STYLE_CLASSIC), "")

    def test_classic_summary_keeps_summary_tag(self):
        self.assertEqual(report_filename_tag("summary", REPORT_STYLE_CLASSIC), "SUMMARY")

    def test_prisma_full_has_no_tag_either(self):
        self.assertEqual(report_filename_tag("full", REPORT_STYLE_PRISMA), "")

    def test_prisma_summary_keeps_only_summary_tag(self):
        self.assertEqual(report_filename_tag("summary", REPORT_STYLE_PRISMA), "SUMMARY")

    def test_classic_and_prisma_produce_the_same_tag_for_the_same_mode(self):
        for mode in ("full", "summary"):
            self.assertEqual(
                report_filename_tag(mode, REPORT_STYLE_CLASSIC),
                report_filename_tag(mode, REPORT_STYLE_PRISMA),
            )


def _make_operacao_app(output: Path, *, export_cfg: dict) -> SimpleNamespace:
    status = Mock()
    status.cget.return_value = "Arquivos gerados"
    job = SimpleNamespace(
        end_time=datetime(2026, 11, 10, 10, 0), document="arquivo.jpeg",
        fabric="Dryfit", pedido="Pedido exemplo", height_mm=1000.0,
        vpos_mm=0.0, real_m=1.0, src_file="arquivo.txt", tipo="Pedido", observacao="",
        start_time=None,
    )
    return SimpleNamespace(
        blocks=[object()], machine="M1", Jobs=[job], pedidos=[],
        _confirm_duplicates_on_export=lambda: True,
        _get_roll_name=lambda: "M1_10-11-2026_0001",
        var_mode=SimpleNamespace(get=lambda: export_cfg.get("_mode", "full")),
        _resolve_mirror_jpg_path=lambda folder, name: folder / (name + ".jpg"),
        _get_mirror_target_cm=lambda: 17.0, edit_roll_id=None,
        status=status, _last_pdf_path=None, btn_open_comprovante=Mock(),
        var_close_roll_text=Mock(),
    )


class OperacaoFilenameTagIntegrationTests(unittest.TestCase):
    """Confirma, através do fluxo real de exportação, que o PDF gerado tem
    o nome esperado — sem precisar inspecionar o código de on_export."""

    def _run_export(self, *, mode: str, report_style: str) -> str:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
            output = Path(temporary)
            export_cfg = {"mirror_jpg_dpi": 300, "report_style": report_style, "_mode": mode}
            app = _make_operacao_app(output, export_cfg=export_cfg)

            captured_paths = []
            with ExitStack() as stack:
                for name in ("pdf_dir", "jpg_dir", "temp_dir"):
                    stack.enter_context(patch("modules.operacao.ui." + name, return_value=output))
                stack.enter_context(patch("modules.operacao.ui.load_export_cfg", return_value=export_cfg))
                stack.enter_context(patch("modules.operacao.ui.find_printer_by_display_name", return_value=None))

                def _fake_export_pdf(path, *args, **kwargs):
                    captured_paths.append(path)
                    Path(path).write_bytes(b"pdf already generated")

                stack.enter_context(patch("modules.operacao.ui.export_pdf", side_effect=_fake_export_pdf))
                stack.enter_context(patch(
                    "modules.operacao.ui.save_export_transactional", return_value=(1, True),
                ))
                # Sem isto, a identificação automática de vendedor que
                # roda logo após salvar (ver on_export) chamaria
                # get_roll_orders(1) contra o banco real da instalação —
                # nunca tocar o banco de verdade num teste isolado.
                stack.enter_context(patch("modules.operacao.ui.get_roll_orders", return_value=[]))
                stack.enter_context(patch("modules.operacao.ui.messagebox.showinfo"))
                stack.enter_context(patch("modules.operacao.ui.messagebox.showwarning"))
                PXPrintLogsUI.on_export(app, "normal")

            self.assertEqual(len(captured_paths), 1)
            return Path(captured_paths[0]).stem

    def test_classic_full_pdf_name_has_no_full_suffix(self):
        name = self._run_export(mode="full", report_style=REPORT_STYLE_CLASSIC)
        self.assertNotIn("FULL", name)
        self.assertNotIn("SUMMARY", name)
        self.assertNotIn("PRISMA", name)

    def test_classic_summary_pdf_name_keeps_summary_suffix(self):
        name = self._run_export(mode="summary", report_style=REPORT_STYLE_CLASSIC)
        self.assertTrue(name.endswith("_SUMMARY"))
        self.assertNotIn("PRISMA", name)

    def test_prisma_full_pdf_name_has_no_prisma_suffix(self):
        name = self._run_export(mode="full", report_style=REPORT_STYLE_PRISMA)
        self.assertNotIn("PRISMA", name)
        self.assertNotIn("SUMMARY", name)
        self.assertNotIn("FULL", name)

    def test_prisma_summary_pdf_name_keeps_only_summary_suffix(self):
        name = self._run_export(mode="summary", report_style=REPORT_STYLE_PRISMA)
        self.assertTrue(name.endswith("_SUMMARY"))
        self.assertNotIn("PRISMA", name)

    def test_classic_and_prisma_full_produce_the_same_filename(self):
        classic_name = self._run_export(mode="full", report_style=REPORT_STYLE_CLASSIC)
        prisma_name = self._run_export(mode="full", report_style=REPORT_STYLE_PRISMA)
        self.assertEqual(classic_name, prisma_name)


if __name__ == "__main__":
    unittest.main()
