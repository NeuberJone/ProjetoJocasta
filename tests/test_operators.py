import unittest

from core.operators import normalize_operators, operator_name_for_code


class NormalizeOperatorsTests(unittest.TestCase):
    def test_keeps_valid_entries_and_uppercases_identifier(self):
        raw = [{"identifier": "n", "name": "Neuber"}, {"identifier": "NJ", "name": "Nicole"}]
        out = normalize_operators(raw)
        self.assertEqual(out, [{"identifier": "N", "name": "Neuber"}, {"identifier": "NJ", "name": "Nicole"}])

    def test_drops_entries_missing_identifier_or_name(self):
        raw = [{"identifier": "", "name": "Neuber"}, {"identifier": "N", "name": ""}, {}]
        self.assertEqual(normalize_operators(raw), [])

    def test_drops_identifier_with_digits_or_symbols(self):
        raw = [{"identifier": "N1", "name": "Neuber"}, {"identifier": "N-2", "name": "X"}]
        self.assertEqual(normalize_operators(raw), [])

    def test_duplicate_identifier_last_one_wins(self):
        raw = [{"identifier": "N", "name": "Antigo"}, {"identifier": "n", "name": "Novo"}]
        out = normalize_operators(raw)
        self.assertEqual(out, [{"identifier": "N", "name": "Novo"}])

    def test_ignores_non_dict_items(self):
        self.assertEqual(normalize_operators(["N", None, 123]), [])

    def test_none_input_returns_empty(self):
        self.assertEqual(normalize_operators(None), [])


class OperatorNameForCodeTests(unittest.TestCase):
    def setUp(self):
        self.operators = [{"identifier": "N", "name": "Neuber"}, {"identifier": "NJ", "name": "Nicole"}]

    def test_finds_name_case_insensitively(self):
        self.assertEqual(operator_name_for_code("n", self.operators), "Neuber")
        self.assertEqual(operator_name_for_code("N", self.operators), "Neuber")

    def test_longer_identifier_is_distinct_from_shorter_one(self):
        self.assertEqual(operator_name_for_code("NJ", self.operators), "Nicole")

    def test_unregistered_code_returns_empty_string(self):
        self.assertEqual(operator_name_for_code("AB", self.operators), "")

    def test_empty_code_returns_empty_string(self):
        self.assertEqual(operator_name_for_code("", self.operators), "")
        self.assertEqual(operator_name_for_code(None, self.operators), "")


if __name__ == "__main__":
    unittest.main()
