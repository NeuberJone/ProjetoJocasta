import unittest

from core.fabric_scraps import FabricScrap, set_scrap_used
from core.print_types import (
    DEFAULT_RULES,
    FALLBACK_TYPE,
    classify_document,
    normalize_rules,
    pedido_override_for_type,
    warn_duplicate_for_type,
)


class PrintTypeRulesTests(unittest.TestCase):
    def test_pedido_uses_day_month_without_year(self):
        for doc in (
            "16-10 - Dryfit - Primos e Amigos 3 (1).jpeg",
            "9/10 - Aeroready - Cliente",
            "05.10 - Crepe - Pedido",
        ):
            self.assertEqual(classify_document(doc, DEFAULT_RULES), "Pedido", doc)

    def test_reposicao_is_operator_initial_plus_number(self):
        for doc in ("N2 - Aeroready", "NB12 - Dryfit", "n 3 - Crepe"):
            self.assertEqual(classify_document(doc, DEFAULT_RULES), "Reposição", doc)

    def test_other_names_fall_back(self):
        for doc in ("Jusc.jpg", "Teste cor.png", "orion city fc 7"):
            self.assertEqual(classify_document(doc, DEFAULT_RULES), FALLBACK_TYPE, doc)

    def test_saved_legacy_default_patterns_are_upgraded(self):
        legacy = [
            {"name": "Pedido", "pattern": r"^\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s*-"},
            {"name": "Reposição", "pattern": r"^\s*[A-Za-z]{1,3}\d+\s*-"},
        ]
        normalized = normalize_rules(legacy)
        # O padrão (regex) é atualizado para o de fábrica atual; o restante
        # dos campos (id, estrutura, exemplos...) é preenchido pela migração
        # para o modelo novo — ver core/print_pattern.migrate_rule_dict.
        self.assertEqual([r["name"] for r in normalized], [r["name"] for r in DEFAULT_RULES])
        self.assertEqual([r["pattern"] for r in normalized], [r["pattern"] for r in DEFAULT_RULES])
        for rule in normalized:
            self.assertTrue(rule["custom_regex"], rule)
            self.assertIsNone(rule["components"])
        # Config antiga (sem o campo "warn_duplicate", que não existia
        # ainda): Reposição vem desligada por padrão (nomes de arquivo quase
        # sempre repetidos entre reposições), Pedido continua avisando.
        by_name = {r["name"]: r for r in normalized}
        self.assertFalse(by_name["Reposição"]["warn_duplicate"])
        self.assertTrue(by_name["Pedido"]["warn_duplicate"])

    def test_warn_duplicate_default_rules(self):
        self.assertTrue(warn_duplicate_for_type("Pedido", DEFAULT_RULES))
        self.assertFalse(warn_duplicate_for_type("Reposição", DEFAULT_RULES))
        # Tipo sem regra correspondente (Fora do padrão, subtipo manual): avisa.
        self.assertTrue(warn_duplicate_for_type(FALLBACK_TYPE, DEFAULT_RULES))

    def test_warn_duplicate_is_configurable_per_rule(self):
        rules = [{"name": "Pedido", "pattern": r"^\d", "warn_duplicate": False}]
        self.assertFalse(warn_duplicate_for_type("Pedido", rules))

    def test_pedido_override_default_rules_use_filename(self):
        self.assertIsNone(pedido_override_for_type("Pedido", DEFAULT_RULES))
        self.assertIsNone(pedido_override_for_type("Reposição", DEFAULT_RULES))
        self.assertIsNone(pedido_override_for_type(FALLBACK_TYPE, DEFAULT_RULES))

    def test_pedido_override_fixed_name(self):
        rules = [
            {"name": "Reposição", "pattern": r"^[A-Za-z]+\d", "pedido_mode": "fixed", "pedido_fixed": "Variados"},
        ]
        self.assertEqual(pedido_override_for_type("Reposição", rules), "Variados")

    def test_pedido_override_fixed_mode_without_name_falls_back_to_filename(self):
        rules = [
            {"name": "Reposição", "pattern": r"^[A-Za-z]+\d", "pedido_mode": "fixed", "pedido_fixed": "   "},
        ]
        self.assertIsNone(pedido_override_for_type("Reposição", rules))


class FabricScrapTests(unittest.TestCase):
    def test_toggling_used_keeps_tipo_and_observacao(self):
        sc = FabricScrap(key="a", name="A", fabric="Dryfit", length_m=3.0, used=False,
                         tipo="Novo", observacao="lote 4")
        (out,) = set_scrap_used([sc], "a", True)
        self.assertTrue(out.used)
        self.assertEqual((out.tipo, out.observacao), ("Novo", "lote 4"))


if __name__ == "__main__":
    unittest.main()
