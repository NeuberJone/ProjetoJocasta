"""Testes de ponta a ponta do fluxo novo: exemplos -> estrutura sugerida ->
regex -> classificação, cobrindo os casos obrigatórios do pedido de
melhoria da tela "Tipos de impressão"."""
import unittest

from core.print_pattern import build_pattern, components_to_list
from core.print_pattern_analyzer import analyze_examples
from core.print_types import (
    DEFAULT_RULES,
    FALLBACK_TYPE,
    classify_document,
    classify_with_detail,
    detect_conflicts,
    matching_rules,
    normalize_rules,
)

FAB = {
    "Dryfit": ["Dryfit", "dryfit"],
    "Aeroready": ["Aeroready", "aeroready"],
    "Tactel": ["Tactel", "tactel"],
    "Poliamida": ["Poliamida", "poliamida"],
}


def build_rule(rule_id, name, examples, match_mode=None, active=True):
    analysis = analyze_examples(examples, fabric_names=FAB)
    mode = match_mode or analysis.suggested_match_mode
    pattern = build_pattern(analysis.components, mode, fabric_names=FAB)
    return {
        "id": rule_id,
        "name": name,
        "pattern": pattern,
        "match_mode": mode,
        "components": components_to_list(analysis.components),
        "examples": examples,
        "custom_regex": False,
        "active": active,
    }


# Ordem de prioridade deliberada: "Amostra" (mais específica, começa com
# texto fixo) precisa vir antes de "Cliente Terceirizado" (genérica,
# [variável] - [tecido]), senão a genérica rouba a classificação — ver
# RuleConflictTests abaixo, que cobre exatamente esse cenário.
RULES = [
    build_rule("pedido", "Pedido", ["26-10 - Dryfit - Nome do Pedido", "2/9 - Aeroready - Cliente"]),
    build_rule("reposicao", "Reposição", ["N1 - Dryfit", "NJ15 - Tactel"]),
    build_rule("teste", "Teste", ["Teste de cor"]),
    build_rule("amostra", "Amostra", ["Amostra - Pedido ABC - Poliamida"]),
    build_rule(
        "terceirizado",
        "Cliente Terceirizado",
        ["Cliente João - Dryfit", "Empresa ABC - Aeroready", "Futebol Clube - Tactel"],
    ),
]


class RequiredExamplesClassificationTests(unittest.TestCase):
    def test_pedido_examples(self):
        self.assertEqual(classify_document("26-10 - Dryfit - Nome do Pedido", RULES, fabric_names=FAB), "Pedido")
        self.assertEqual(classify_document("2/9 - Aeroready - Cliente", RULES, fabric_names=FAB), "Pedido")

    def test_reposicao_examples(self):
        self.assertEqual(classify_document("N1 - Dryfit", RULES, fabric_names=FAB), "Reposição")
        self.assertEqual(classify_document("NJ15 - Tactel", RULES, fabric_names=FAB), "Reposição")

    def test_teste_example(self):
        self.assertEqual(classify_document("Teste de cor", RULES, fabric_names=FAB), "Teste")

    def test_cliente_terceirizado_example(self):
        self.assertEqual(classify_document("Cliente João - Dryfit", RULES, fabric_names=FAB), "Cliente Terceirizado")

    def test_amostra_example(self):
        self.assertEqual(
            classify_document("Amostra - Pedido ABC - Poliamida", RULES, fabric_names=FAB), "Amostra"
        )


class FileExtensionTests(unittest.TestCase):
    def test_classification_ignores_extension(self):
        for ext in (".jpg", ".jpeg", ".png", ".tif", ".TIFF"):
            with self.subTest(ext=ext):
                self.assertEqual(
                    classify_document(f"N1 - Dryfit{ext}", RULES, fabric_names=FAB), "Reposição"
                )


class ExtraSpacingTests(unittest.TestCase):
    def test_extra_spaces_around_separators_still_classify(self):
        self.assertEqual(classify_document("N1   -   Dryfit", RULES, fabric_names=FAB), "Reposição")
        self.assertEqual(
            classify_document("26-10   -   Dryfit   -   Nome do Pedido", RULES, fabric_names=FAB), "Pedido"
        )


class FabricAliasTests(unittest.TestCase):
    def test_alias_variants_are_recognized(self):
        fab = {"Dryfit": ["Dryfit", "dry fit", "drifit"]}
        rule = build_rule("reposicao", "Reposição", ["N1 - Dryfit"])
        # recompila contra um cadastro com variações diferentes do mesmo tecido
        self.assertEqual(classify_document("N1 - dry fit", [rule], fabric_names=fab), "Reposição")
        self.assertEqual(classify_document("N1 - DRIFIT", [rule], fabric_names=fab), "Reposição")

    def test_unregistered_fabric_does_not_match_fabric_component(self):
        rule = build_rule("reposicao", "Reposição", ["N1 - Dryfit"])
        self.assertEqual(
            classify_document("N1 - TecidoNuncaRegistrado", [rule], fabric_names=FAB), FALLBACK_TYPE
        )


class PriorityTests(unittest.TestCase):
    def test_first_matching_rule_in_order_wins(self):
        hits = matching_rules("N1 - Dryfit", RULES, fabric_names=FAB)
        self.assertEqual([r["name"] for r in hits][0], "Reposição")

    def test_classify_with_detail_reports_winner_and_also_matches(self):
        detail = classify_with_detail("N1 - Dryfit", RULES, fabric_names=FAB)
        self.assertEqual(detail["type"], "Reposição")
        self.assertEqual(detail["winner"]["name"], "Reposição")


class RuleConflictTests(unittest.TestCase):
    def test_generic_rule_below_specific_rule_does_not_steal_classification(self):
        # "Amostra" está acima de "Cliente Terceirizado" em RULES -> vence.
        self.assertEqual(
            classify_document("Amostra - Pedido ABC - Poliamida", RULES, fabric_names=FAB), "Amostra"
        )

    def test_reordering_changes_the_winner_first_match_wins(self):
        reordered = [RULES[4], RULES[3]] + RULES[:3]  # Cliente Terceirizado antes de Amostra
        self.assertEqual(
            classify_document("Amostra - Pedido ABC - Poliamida", reordered, fabric_names=FAB),
            "Cliente Terceirizado",
        )

    def test_detect_conflicts_flags_overlap_between_generic_and_specific_rules(self):
        others = [r for r in RULES if r["id"] != "amostra"]
        conflicts = detect_conflicts(["Amostra - Pedido ABC - Poliamida"], others, fabric_names=FAB)
        self.assertIn("Amostra - Pedido ABC - Poliamida", conflicts)
        self.assertIn("Cliente Terceirizado", conflicts["Amostra - Pedido ABC - Poliamida"])

    def test_detect_conflicts_is_empty_when_no_other_rule_matches(self):
        others = [r for r in RULES if r["id"] != "teste"]
        conflicts = detect_conflicts(["Teste de cor"], others, fabric_names=FAB)
        self.assertEqual(conflicts, {})


class CustomRegexTests(unittest.TestCase):
    def test_custom_regex_rule_is_not_regenerated_from_components(self):
        rule = {
            "id": "x",
            "name": "ManualRule",
            "pattern": r"^ESPECIAL\d+$",
            "match_mode": "start",
            "components": [{"kind": "texto_fixo", "value": "outra coisa"}],
            "custom_regex": True,
            "active": True,
        }
        # Mesmo com uma estrutura visual presente, custom_regex=True preserva
        # o padrão digitado manualmente — não é sobrescrito silenciosamente.
        self.assertEqual(classify_document("ESPECIAL123", [rule]), "ManualRule")
        self.assertEqual(classify_document("outra coisa", [rule]), FALLBACK_TYPE)


class MigrationOfLegacyRulesTests(unittest.TestCase):
    def test_default_rules_still_classify_as_before(self):
        normalized = normalize_rules(DEFAULT_RULES)
        self.assertEqual(classify_document("16-10 - Dryfit - Cliente", normalized), "Pedido")
        self.assertEqual(classify_document("N2 - Aeroready", normalized), "Reposição")

    def test_legacy_rules_are_marked_custom_without_inventing_structure(self):
        for rule in normalize_rules(DEFAULT_RULES):
            self.assertTrue(rule["custom_regex"])
            self.assertIsNone(rule["components"])

    def test_legacy_rule_ids_are_stable_across_loads(self):
        a = normalize_rules(DEFAULT_RULES)
        b = normalize_rules(DEFAULT_RULES)
        self.assertEqual([r["id"] for r in a], [r["id"] for r in b])


class InvalidExamplesTests(unittest.TestCase):
    def test_blank_examples_are_ignored_by_the_analyzer(self):
        r = analyze_examples(["", "   "], fabric_names=FAB)
        self.assertEqual(r.components, [])
        self.assertTrue(r.warnings)

    def test_rule_with_broken_regex_is_skipped_not_fatal(self):
        broken = {
            "id": "broken",
            "name": "Quebrada",
            "pattern": "(",
            "custom_regex": True,
            "active": True,
        }
        ok = {"id": "ok", "name": "Pedido", "pattern": r"^\d", "custom_regex": True, "active": True}
        self.assertEqual(classify_document("123 - teste", [broken, ok]), "Pedido")


class NoMatchTests(unittest.TestCase):
    def test_name_matching_nothing_falls_back(self):
        self.assertEqual(classify_document("isso nao bate com nada aqui", RULES, fabric_names=FAB), FALLBACK_TYPE)

    def test_inactive_rule_is_skipped(self):
        rule = build_rule("teste", "Teste", ["Teste de cor"])
        rule["active"] = False
        self.assertEqual(classify_document("Teste de cor", [rule], fabric_names=FAB), FALLBACK_TYPE)


if __name__ == "__main__":
    unittest.main()
