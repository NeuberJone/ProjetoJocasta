import unittest

from core.print_pattern import (
    KIND_DATE,
    KIND_FABRIC,
    KIND_FIXED,
    KIND_LETTERS_NUMBER,
    KIND_SEPARATOR,
    KIND_VARIABLE,
    MATCH_MODE_EXACT,
    MATCH_MODE_START,
    build_pattern,
)
from core.print_pattern_analyzer import analyze_examples

FAB = {
    "Dryfit": ["Dryfit", "dryfit"],
    "Aeroready": ["Aeroready", "aeroready"],
    "Tactel": ["Tactel", "tactel"],
    "Poliamida": ["Poliamida", "poliamida"],
}


def kinds(result):
    return [b.kind for b in result.blocks]


class AnalyzeExamplesTests(unittest.TestCase):
    def test_pedido_two_examples_suggests_date_fabric_variable(self):
        r = analyze_examples(
            ["26-10 - Dryfit - Nome do Pedido", "2/9 - Aeroready - Cliente"],
            fabric_names=FAB,
        )
        self.assertEqual(kinds(r), [KIND_DATE, KIND_FABRIC, KIND_VARIABLE])
        self.assertTrue(r.consistent)
        self.assertEqual(r.blocks[0].confidence, "alta")
        self.assertEqual(r.blocks[1].confidence, "alta")

    def test_reposicao_suggests_letters_number_then_fabric(self):
        r = analyze_examples(["N1 - Dryfit", "NJ15 - Tactel"], fabric_names=FAB)
        self.assertEqual(kinds(r), [KIND_LETTERS_NUMBER, KIND_FABRIC])

    def test_teste_single_fixed_block_suggests_exact_mode(self):
        r = analyze_examples(["Teste de cor"], fabric_names=FAB)
        self.assertEqual(kinds(r), [KIND_FIXED])
        self.assertEqual(r.blocks[0].value, "Teste de cor")
        self.assertEqual(r.suggested_match_mode, MATCH_MODE_EXACT)

    def test_cliente_terceirizado_three_examples_variable_then_fabric(self):
        r = analyze_examples(
            [
                "Cliente João - Dryfit",
                "Empresa ABC - Aeroready",
                "Futebol Clube - Tactel",
            ],
            fabric_names=FAB,
        )
        self.assertEqual(kinds(r), [KIND_VARIABLE, KIND_FABRIC])
        self.assertEqual(r.blocks[0].confidence, "media")
        self.assertEqual(r.blocks[1].confidence, "alta")

    def test_amostra_single_example_low_confidence_blocks_need_confirmation(self):
        r = analyze_examples(["Amostra - Pedido ABC - Poliamida"], fabric_names=FAB)
        self.assertEqual(kinds(r), [KIND_FIXED, KIND_VARIABLE, KIND_FABRIC])
        self.assertEqual(r.blocks[0].value, "Amostra")
        self.assertEqual(r.blocks[0].confidence, "baixa")
        self.assertIsNotNone(r.blocks[0].note)
        self.assertEqual(r.blocks[1].confidence, "baixa")
        # tecido tem evidência real do cadastro, mesmo com um único exemplo.
        self.assertEqual(r.blocks[2].confidence, "alta")

    def test_literal_word_tecido_is_not_forced_into_fabric_kind(self):
        """'Tecido' não está cadastrado como tecido nenhum — não deve ser
        forçado para o tipo Tecido só porque parece um nome genérico."""
        r = analyze_examples(["Nome do Cliente - Tecido"], fabric_names=FAB)
        self.assertEqual(kinds(r), [KIND_VARIABLE, KIND_FIXED])

    def test_separator_slash_is_detected(self):
        r = analyze_examples(["N1/Dryfit"], fabric_names=FAB)
        seps = [c.value for c in r.components if c.kind == KIND_SEPARATOR]
        self.assertEqual(seps, ["/"])

    def test_extra_spacing_around_separator_is_tolerated(self):
        a = analyze_examples(["N1 - Dryfit"], fabric_names=FAB)
        b = analyze_examples(["N1   -   Dryfit"], fabric_names=FAB)
        self.assertEqual(kinds(a), kinds(b))

    def test_file_extension_is_stripped_before_analysis(self):
        r = analyze_examples(["N1 - Dryfit.jpeg"], fabric_names=FAB)
        self.assertEqual(r.blocks[-1].sample_text, "Dryfit")

    def test_inconsistent_example_structure_is_flagged_not_silently_merged(self):
        r = analyze_examples(
            ["N1 - Dryfit", "Cliente João - Dryfit - Extra - Campo"],
            fabric_names=FAB,
        )
        self.assertFalse(r.consistent)
        self.assertEqual(len(r.warnings), 1)
        # a estrutura sugerida ainda é utilizável (baseada no formato majoritário/primeiro)
        self.assertTrue(r.components)

    def test_empty_examples_returns_warning_and_no_components(self):
        r = analyze_examples([""])
        self.assertEqual(r.components, [])
        self.assertTrue(r.warnings)

    def test_generated_pattern_matches_all_source_examples(self):
        examples = ["26-10 - Dryfit - Nome do Pedido", "2/9 - Aeroready - Cliente"]
        r = analyze_examples(examples, fabric_names=FAB)
        pattern = build_pattern(r.components, r.suggested_match_mode, fabric_names=FAB)
        import re

        for ex in examples:
            self.assertTrue(re.match(pattern, ex), ex)


if __name__ == "__main__":
    unittest.main()
