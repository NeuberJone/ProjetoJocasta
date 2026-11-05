import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core.print_types import DEFAULT_RULES
from modules.operacao.models import Job
from modules.operacao.parser import (
    build_auto_gap_job,
    fabric_from_document,
    operator_code_from_document,
    parse_log_txt,
    pedido_from_document,
)


class FabricFromDocumentTests(unittest.TestCase):
    def test_reposicao_strips_extension_and_duplicate_marker(self):
        self.assertEqual(fabric_from_document("N1 - Dryfit (2).jpeg"), "DRYFIT")

    def test_reposicao_strips_plain_extension(self):
        self.assertEqual(fabric_from_document("N1 - Dryfit.jpeg"), "DRYFIT")

    def test_reposicao_strips_textual_observation(self):
        self.assertEqual(fabric_from_document("N1 - Dryfit (reimpressão).jpeg"), "DRYFIT")

    def test_pedido_with_name_unaffected(self):
        self.assertEqual(fabric_from_document("16-10 - Dryfit - Primos e Amigos 3 (1).jpeg"), "DRYFIT")

    def test_no_fabric_segment_is_unknown(self):
        self.assertEqual(fabric_from_document("Jusc.jpg"), "DESCONHECIDO")


class FabricFromDocumentCanonicalizationTests(unittest.TestCase):
    """Com o cadastro de tecidos (fabrics_map), aliases do mesmo tecido devem
    ser agrupados sob o nome canônico — ex.: "Dry Fit" e "Dryfit" não podem
    aparecer como tecidos diferentes na Operação."""

    def setUp(self):
        self.fabrics_map = {
            "Dryfit": {"aliases": ["dryfit", "dry fit", "dry-fit", "drifit"], "roll_length_m": 90.0},
        }

    def test_alias_is_mapped_to_canonical_name(self):
        self.assertEqual(
            fabric_from_document("N1 - Dry Fit.jpeg", self.fabrics_map), "DRYFIT"
        )

    def test_canonical_and_alias_produce_same_result(self):
        canonical = fabric_from_document("N1 - Dryfit.jpeg", self.fabrics_map)
        alias = fabric_from_document("N2 - Dry Fit.jpeg", self.fabrics_map)
        self.assertEqual(canonical, alias)

    def test_unregistered_fabric_falls_back_to_raw_text(self):
        self.assertEqual(
            fabric_from_document("N1 - Tecido Novo.jpeg", self.fabrics_map), "TECIDO NOVO"
        )

    def test_no_fabrics_map_keeps_old_behavior(self):
        self.assertEqual(fabric_from_document("N1 - Dry Fit.jpeg"), "DRY FIT")


class OperatorCodeFromDocumentTests(unittest.TestCase):
    def test_single_letter_operator_code(self):
        self.assertEqual(operator_code_from_document("N1 - Dryfit"), "N")

    def test_multi_letter_operator_code(self):
        self.assertEqual(operator_code_from_document("NJ15 - Tactel"), "NJ")

    def test_space_between_letters_and_number_is_tolerated(self):
        self.assertEqual(operator_code_from_document("N 2 - Aeroready"), "N")

    def test_extension_on_single_segment_is_stripped(self):
        self.assertEqual(operator_code_from_document("N1.jpeg"), "N")

    def test_pedido_style_document_has_no_operator_code(self):
        self.assertEqual(operator_code_from_document("16-10 - Dryfit - Nome do Pedido"), "")

    def test_empty_document_has_no_operator_code(self):
        self.assertEqual(operator_code_from_document(""), "")


class PedidoFromDocumentTests(unittest.TestCase):
    def test_trailing_paren_is_noise_not_identity(self):
        self.assertEqual(pedido_from_document("16-10 - Dryfit - Salum 12 (Argentina).jpg"), "Salum 12")
        self.assertEqual(pedido_from_document("16-10 - Dryfit - Salum 12 (Brasil).jpg"), "Salum 12")

    def test_loose_trailing_number_without_paren_is_part_of_the_pedido_name(self):
        """Só número entre parênteses é ignorado — um número solto no fim,
        sem parênteses, é parte do nome do pedido (não um contador), senão
        o mesmo pedido (ex.: "Haras DRB 4") vira dois nomes diferentes
        dependendo de qual arquivo (com ou sem parênteses) é analisado."""
        self.assertEqual(pedido_from_document("16-10 - Dryfit - Escolinha Reis 21"), "Escolinha Reis 21")

    def test_same_pedido_with_and_without_parens_normalize_to_the_same_name(self):
        self.assertEqual(pedido_from_document("09-11 - Ribana - Haras DRB 4.JPEG"), "Haras DRB 4")
        self.assertEqual(pedido_from_document("09-11 - dryfit - Haras DRB 4 (2).jpeg"), "Haras DRB 4")


class ParseLogTxtPedidoModeTests(unittest.TestCase):
    """O pedido de um tipo pode ser detectado pelo nome do arquivo (padrão)
    ou usar um nome fixo configurado na regra do tipo (ex.: Reposição ->
    "Variados") — ver core.print_types.pedido_override_for_type."""

    def _write_log(self, document: str) -> str:
        tmp_dir = Path(tempfile.mkdtemp())
        path = tmp_dir / "log.txt"
        path.write_text(
            "[General]\n"
            "EndTime=21/10/2026 10:00:00\n"
            f"Document={document}\n"
            "[1]\n"
            f"Name={document}\n"
            "HeightMM=1000\n"
            "WidthMM=500\n"
            "VPositionMM=0\n",
            encoding="utf-8",
        )
        return str(path)

    def test_default_rules_still_detect_pedido_from_filename(self):
        path = self._write_log("N1 - Dryfit")
        job = parse_log_txt(path, type_rules=DEFAULT_RULES)
        self.assertEqual(job.tipo, "Reposição")
        self.assertEqual(job.pedido, "DESCONHECIDO")

    def test_fixed_pedido_mode_overrides_filename_detection(self):
        rules = [
            {"name": "Reposição", "pattern": r"^\s*[A-Za-z]{1,3}\s*\d+\s*-",
             "pedido_mode": "fixed", "pedido_fixed": "Variados"},
        ]
        path = self._write_log("N1 - Dryfit")
        job = parse_log_txt(path, type_rules=rules)
        self.assertEqual(job.tipo, "Reposição")
        self.assertEqual(job.pedido, "Variados")

    def test_auto_pedido_mode_is_unaffected_by_other_types_fixed_mode(self):
        rules = [
            {"name": "Reposição", "pattern": r"^\s*[A-Za-z]{1,3}\s*\d+\s*-",
             "pedido_mode": "fixed", "pedido_fixed": "Variados"},
            {"name": "Pedido", "pattern": r"^\s*\d{1,2}[-/.]\d{1,2}\s*-"},
        ]
        path = self._write_log("16-10 - Dryfit - Cliente A")
        job = parse_log_txt(path, type_rules=rules)
        self.assertEqual(job.tipo, "Pedido")
        self.assertEqual(job.pedido, "Cliente A")


class BuildAutoGapJobTests(unittest.TestCase):
    """Impressoras sem arquivo de espaço dedicado registram o avanço em
    branco direto no log do arquivo real (VPositionMM) — esse avanço tem
    que virar um item de ESPAÇO próprio na listagem."""

    def _job(self, *, vpos_mm: float, is_gap: bool = False, start_time=None) -> Job:
        return Job(
            end_time=datetime(2026, 10, 30, 10, 0, 0),
            document="16-10 - Dryfit - Cliente A.jpeg",
            fabric="DRYFIT",
            pedido="Cliente A",
            height_mm=1000.0,
            vpos_mm=vpos_mm,
            real_mm=1000.0,
            src_file="C:/logs/16-10 - Dryfit - Cliente A.jpeg.txt",
            is_gap=is_gap,
            start_time=start_time,
        )

    def test_no_gap_when_vpos_is_zero(self):
        self.assertIsNone(build_auto_gap_job(self._job(vpos_mm=0.0)))

    def test_no_gap_for_an_already_gap_job(self):
        self.assertIsNone(build_auto_gap_job(self._job(vpos_mm=500.0, is_gap=True)))

    def test_gap_job_uses_vpos_as_length_and_marks_as_espaco(self):
        job = self._job(vpos_mm=1097.7, start_time=datetime(2026, 10, 30, 9, 58, 0))
        gap = build_auto_gap_job(job)
        self.assertIsNotNone(gap)
        self.assertTrue(gap.is_gap)
        self.assertEqual(gap.fabric, "ESPAÇO")
        self.assertEqual(gap.real_mm, 1097.7)
        self.assertEqual(gap.height_mm, 1097.7)
        self.assertEqual(gap.end_time, datetime(2026, 10, 30, 9, 58, 0))
        self.assertNotEqual(gap.src_file, job.src_file)

    def test_gap_job_falls_back_to_end_time_without_start_time(self):
        job = self._job(vpos_mm=200.0, start_time=None)
        gap = build_auto_gap_job(job)
        self.assertLess(gap.end_time, job.end_time)


if __name__ == "__main__":
    unittest.main()
