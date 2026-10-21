import unittest

from core.print_pattern import (
    Component,
    KIND_DATE,
    KIND_FABRIC,
    KIND_FIXED,
    KIND_LETTERS,
    KIND_LETTERS_NUMBER,
    KIND_NUMBER,
    KIND_NUMBER_LETTERS,
    KIND_OPTIONAL,
    KIND_SEPARATOR,
    KIND_VARIABLE,
    MATCH_MODE_CONTAINS,
    MATCH_MODE_EXACT,
    MATCH_MODE_START,
    build_pattern,
    compile_component,
    migrate_rule_dict,
    new_rule_id,
    resolve_pattern,
    strip_extension,
)

import re


FAB = {"Dryfit": ["Dryfit", "dryfit", "dry fit"], "Aeroready": ["Aeroready", "aeroready"]}


class StripExtensionTests(unittest.TestCase):
    def test_removes_common_extensions(self):
        for name, expected in (
            ("N1 - Dryfit (2).jpeg", "N1 - Dryfit (2)"),
            ("N1 - Dryfit.jpg", "N1 - Dryfit"),
            ("arquivo.png", "arquivo"),
            ("arquivo.TIF", "arquivo"),
            ("sem extensao", "sem extensao"),
        ):
            self.assertEqual(strip_extension(name), expected, name)


class CompileComponentTests(unittest.TestCase):
    def test_fixed_text_is_escaped_literal(self):
        frag = compile_component(Component(kind=KIND_FIXED, value="Amostra (1)"))
        self.assertTrue(re.match(frag, "Amostra (1)"))

    def test_variable_is_dot_plus(self):
        self.assertEqual(compile_component(Component(kind=KIND_VARIABLE)), r".+")

    def test_date_component(self):
        frag = compile_component(Component(kind=KIND_DATE))
        for text in ("26-10", "2/9", "05.10"):
            self.assertTrue(re.fullmatch(frag, text), text)
        self.assertFalse(re.fullmatch(frag, "abc"))

    def test_number_component(self):
        frag = compile_component(Component(kind=KIND_NUMBER))
        self.assertTrue(re.fullmatch(frag, "12345"))
        self.assertFalse(re.fullmatch(frag, "12a"))

    def test_letters_component(self):
        frag = compile_component(Component(kind=KIND_LETTERS))
        self.assertTrue(re.fullmatch(frag, "ABC"))
        self.assertFalse(re.fullmatch(frag, "AB1"))

    def test_letters_number_component_allows_short_or_long_prefix(self):
        frag = compile_component(Component(kind=KIND_LETTERS_NUMBER))
        for text in ("N1", "NJ2", "AB15"):
            self.assertTrue(re.fullmatch(frag, text), text)

    def test_number_letters_component(self):
        frag = compile_component(Component(kind=KIND_NUMBER_LETTERS))
        self.assertTrue(re.fullmatch(frag, "15AB"))

    def test_separator_variants_accept_flexible_spacing(self):
        for char, samples in (
            ("-", ["-", " - ", "  -  "]),
            ("/", ["/", " / "]),
            ("_", ["_", " _ "]),
            (" ", [" ", "   "]),
        ):
            frag = compile_component(Component(kind=KIND_SEPARATOR, value=char))
            for s in samples:
                self.assertTrue(re.fullmatch(frag, s), (char, s))

    def test_fabric_component_uses_registry_aliases(self):
        frag = compile_component(Component(kind=KIND_FABRIC), fabric_names=FAB)
        self.assertTrue(re.fullmatch(frag, "Dryfit", re.IGNORECASE))
        self.assertTrue(re.fullmatch(frag, "dry fit", re.IGNORECASE))
        self.assertFalse(re.fullmatch(frag, "Oxford", re.IGNORECASE))

    def test_fabric_component_without_registry_falls_back_to_variable(self):
        frag = compile_component(Component(kind=KIND_FABRIC), fabric_names={})
        self.assertEqual(frag, r".+")

    def test_optional_component_wraps_inner(self):
        inner = Component(kind=KIND_FIXED, value="X")
        frag = compile_component(Component(kind=KIND_OPTIONAL, inner=inner))
        self.assertTrue(re.fullmatch(frag, ""))
        self.assertTrue(re.fullmatch(frag, "X"))


class BuildPatternMatchModeTests(unittest.TestCase):
    def setUp(self):
        self.components = [Component(kind=KIND_FIXED, value="Teste de cor")]

    def test_exact_mode_requires_full_match(self):
        pattern = build_pattern(self.components, MATCH_MODE_EXACT)
        self.assertTrue(re.match(pattern, "Teste de cor"))
        self.assertFalse(re.match(pattern, "Teste de cor extra"))

    def test_start_mode_allows_trailing_content(self):
        pattern = build_pattern(self.components, MATCH_MODE_START)
        self.assertTrue(re.match(pattern, "Teste de cor extra"))

    def test_contains_mode_matches_anywhere(self):
        pattern = build_pattern(self.components, MATCH_MODE_CONTAINS)
        self.assertTrue(re.search(pattern, "prefixo Teste de cor sufixo"))
        self.assertFalse(re.match(pattern, "prefixo Teste de cor sufixo"))


class MigrateRuleDictTests(unittest.TestCase):
    def test_legacy_rule_becomes_custom_regex_without_components(self):
        legacy = {"name": "Pedido", "pattern": r"^\s*\d{1,2}[-/.]\d{1,2}\s*-"}
        migrated = migrate_rule_dict(legacy)
        self.assertTrue(migrated["custom_regex"])
        self.assertIsNone(migrated["components"])
        self.assertEqual(migrated["pattern"], legacy["pattern"])
        self.assertTrue(migrated["active"])

    def test_legacy_id_is_deterministic_across_calls(self):
        legacy = {"name": "Reposição", "pattern": r"^\s*[A-Za-z]{1,3}\s*\d+\s*-"}
        id1 = migrate_rule_dict(legacy)["id"]
        id2 = migrate_rule_dict(legacy)["id"]
        self.assertEqual(id1, id2)

    def test_structured_rule_keeps_its_id_and_components(self):
        raw = {
            "id": "abc123",
            "name": "Amostra",
            "pattern": "Amostra",
            "components": [{"kind": KIND_FIXED, "value": "Amostra"}],
            "custom_regex": False,
        }
        migrated = migrate_rule_dict(raw)
        self.assertEqual(migrated["id"], "abc123")
        self.assertFalse(migrated["custom_regex"])
        self.assertEqual(migrated["components"], raw["components"])

    def test_new_rule_id_generates_distinct_values(self):
        self.assertNotEqual(new_rule_id(), new_rule_id())

    def test_pedido_mode_defaults_to_auto_with_empty_fixed_name(self):
        migrated = migrate_rule_dict({"name": "Pedido", "pattern": r"^\d"})
        self.assertEqual(migrated["pedido_mode"], "auto")
        self.assertEqual(migrated["pedido_fixed"], "")

    def test_pedido_mode_fixed_is_preserved(self):
        raw = {"name": "Reposição", "pattern": r"^[A-Za-z]", "pedido_mode": "fixed", "pedido_fixed": "Variados"}
        migrated = migrate_rule_dict(raw)
        self.assertEqual(migrated["pedido_mode"], "fixed")
        self.assertEqual(migrated["pedido_fixed"], "Variados")

    def test_invalid_pedido_mode_falls_back_to_auto(self):
        migrated = migrate_rule_dict({"name": "Pedido", "pattern": r"^\d", "pedido_mode": "bogus"})
        self.assertEqual(migrated["pedido_mode"], "auto")


class ResolvePatternTests(unittest.TestCase):
    def test_structured_rule_regenerates_pattern_from_live_fabric_registry(self):
        rule = {
            "name": "Reposição",
            "pattern": "stale",
            "match_mode": MATCH_MODE_START,
            "components": [
                {"kind": KIND_LETTERS_NUMBER},
                {"kind": KIND_SEPARATOR, "value": "-"},
                {"kind": KIND_FABRIC},
            ],
            "custom_regex": False,
        }
        pattern_v1 = resolve_pattern(rule, fabric_names={"Dryfit": ["Dryfit"]})
        self.assertTrue(re.match(pattern_v1, "N1 - Dryfit"))
        self.assertFalse(re.match(pattern_v1, "N1 - Oxford"))

        # Tecido novo cadastrado depois -> a mesma regra estruturada passa a
        # reconhecer, sem precisar editar a regra (não fica "congelada").
        pattern_v2 = resolve_pattern(rule, fabric_names={"Oxford": ["Oxford"]})
        self.assertTrue(re.match(pattern_v2, "N1 - Oxford"))

    def test_custom_regex_rule_ignores_components(self):
        rule = {
            "name": "Pedido",
            "pattern": r"^\s*\d{1,2}[-/.]\d{1,2}\s*-",
            "components": None,
            "custom_regex": True,
        }
        self.assertEqual(resolve_pattern(rule), rule["pattern"])


if __name__ == "__main__":
    unittest.main()
