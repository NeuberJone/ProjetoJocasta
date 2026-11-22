"""Testes da verificação de impressão incompleta (modules/operacao/print_check.py)."""
import unittest

from modules.operacao.print_check import (
    STATUS_INCOMPLETE,
    STATUS_NOT_AVAILABLE,
    STATUS_OK,
    check_completeness,
    observacao_with_warning,
)


class PrintCheckTests(unittest.TestCase):
    def test_matching_height_is_ok(self):
        result = check_completeness(height_mm=3908.2, vpos_mm=0.0, print_height_mm=3908.2, file_count=1)
        self.assertEqual(result.status, STATUS_OK)
        self.assertEqual(result.detail, "")

    def test_rounding_noise_within_tolerance_is_ok(self):
        # Visto nos 277 logs reais conferidos: diferença máxima de 0,1mm
        # numa impressão completa de verdade.
        result = check_completeness(height_mm=94361.0, vpos_mm=130.7, print_height_mm=94491.7, file_count=1)
        self.assertEqual(result.status, STATUS_OK)

    def test_gap_before_image_is_included_in_expected_total(self):
        # "24-11 - RIBANA - ADEGA BRADOCK (2)" real: HeightMM=476.5,
        # VPositionMM=986.4, PrintHeightMM=1463.0 (476.5+986.4=1462.9).
        result = check_completeness(height_mm=476.5, vpos_mm=986.4, print_height_mm=1463.0, file_count=1)
        self.assertEqual(result.status, STATUS_OK)

    def test_real_interrupted_case_is_flagged(self):
        # "24-11 - DRYFIT - ADEGA BRADOCK (3)" real: pedia 7975,9mm, só
        # saiu 5171,9mm — a reimpressão (outro arquivo de log) depois
        # bateu certinho.
        result = check_completeness(height_mm=7975.9, vpos_mm=0.0, print_height_mm=5171.9, file_count=1)
        self.assertEqual(result.status, STATUS_INCOMPLETE)
        self.assertIn("2.80 m", result.detail)
        self.assertAlmostEqual(result.shortfall_mm, 2804.0, places=1)

    def test_reprint_of_interrupted_job_matches_exactly(self):
        result = check_completeness(height_mm=4996.1, vpos_mm=0.0, print_height_mm=4996.1, file_count=1)
        self.assertEqual(result.status, STATUS_OK)

    def test_almost_nothing_printed_is_flagged(self):
        # "26-11 - DRYFIT - RESENHA FUTEBOL" real: pedia 3908,2mm, só
        # saiu 138,8mm.
        result = check_completeness(height_mm=3908.2, vpos_mm=0.0, print_height_mm=138.8, file_count=1)
        self.assertEqual(result.status, STATUS_INCOMPLETE)

    def test_missing_cost_field_is_not_available(self):
        result = check_completeness(height_mm=1000.0, vpos_mm=0.0, print_height_mm=None, file_count=1)
        self.assertEqual(result.status, STATUS_NOT_AVAILABLE)
        self.assertEqual(result.detail, "")

    def test_multi_file_job_is_not_available(self):
        # Nunca visto FileCount != 1 nos logs reais — sem caso pra validar
        # a soma por item, então não arrisca um resultado.
        result = check_completeness(height_mm=1000.0, vpos_mm=0.0, print_height_mm=500.0, file_count=2)
        self.assertEqual(result.status, STATUS_NOT_AVAILABLE)

    def test_shortfall_exactly_at_tolerance_boundary_is_ok(self):
        result = check_completeness(height_mm=1000.0, vpos_mm=0.0, print_height_mm=990.0, file_count=1)
        self.assertEqual(result.status, STATUS_OK)

    def test_shortfall_just_above_tolerance_is_incomplete(self):
        result = check_completeness(height_mm=1000.0, vpos_mm=0.0, print_height_mm=989.0, file_count=1)
        self.assertEqual(result.status, STATUS_INCOMPLETE)

    def test_observacao_with_warning_prefixes_without_losing_manual_note(self):
        text = observacao_with_warning("manchou no final", STATUS_INCOMPLETE, "Impresso 5.17 m de 7.98 m esperados (faltaram 2.80 m).")
        self.assertTrue(text.startswith("ATENÇÃO — IMPRESSÃO INCOMPLETA: Impresso 5.17 m de 7.98 m esperados"))
        self.assertIn("manchou no final", text)

    def test_observacao_with_warning_untouched_when_ok(self):
        self.assertEqual(observacao_with_warning("manchou no final", STATUS_OK, ""), "manchou no final")

    def test_observacao_with_warning_without_manual_note(self):
        text = observacao_with_warning("", STATUS_INCOMPLETE, "faltaram 2.80 m")
        self.assertEqual(text, "ATENÇÃO — IMPRESSÃO INCOMPLETA: faltaram 2.80 m")

    def test_observacao_with_warning_never_uses_unicode_symbol(self):
        """Confirmado em reportlab (fontes base Helvetica/WinAnsiEncoding):
        '⚠' não existe nessas fontes e sai como um caractere errado no PDF
        — o aviso no comprovante não pode depender desse símbolo."""
        text = observacao_with_warning("", STATUS_INCOMPLETE, "faltaram 2.80 m")
        self.assertNotIn("⚠", text)


if __name__ == "__main__":
    unittest.main()
