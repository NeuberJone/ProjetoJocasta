import unittest

from core.fabrics import canonical_fabric_name


class CanonicalFabricNameTests(unittest.TestCase):
    def setUp(self):
        self.fabrics_map = {
            "Dryfit": {"aliases": ["dryfit", "dry fit", "dry-fit", "drifit"], "roll_length_m": 90.0},
            "Jaquard Corinthians": {"aliases": ["CORINTHIANS"], "roll_length_m": 60.0},
        }

    def test_matches_canonical_name_case_insensitive(self):
        self.assertEqual(canonical_fabric_name("dryfit", self.fabrics_map), "Dryfit")

    def test_matches_alias_with_different_spacing(self):
        self.assertEqual(canonical_fabric_name("Dry Fit", self.fabrics_map), "Dryfit")
        self.assertEqual(canonical_fabric_name("DRY-FIT", self.fabrics_map), "Dryfit")

    def test_matches_alias_regardless_of_case(self):
        self.assertEqual(canonical_fabric_name("corinthians", self.fabrics_map), "Jaquard Corinthians")

    def test_unregistered_name_returns_empty(self):
        self.assertEqual(canonical_fabric_name("Tecido Novo", self.fabrics_map), "")

    def test_substring_does_not_match(self):
        # "Dry" sozinho não deve casar com "Dryfit" (evita falsos positivos).
        self.assertEqual(canonical_fabric_name("Dry", self.fabrics_map), "")

    def test_empty_input_returns_empty(self):
        self.assertEqual(canonical_fabric_name("", self.fabrics_map), "")


if __name__ == "__main__":
    unittest.main()
