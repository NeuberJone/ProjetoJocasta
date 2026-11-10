import unittest

from core.printlogs_db import TEST_ROLL_SUFFIX, is_test_roll_name


class IsTestRollNameTests(unittest.TestCase):
    def test_suffix_is_recognized(self):
        self.assertTrue(is_test_roll_name(f"M1-0001{TEST_ROLL_SUFFIX}"))

    def test_case_insensitive(self):
        self.assertTrue(is_test_roll_name("m1-0001_teste"))

    def test_normal_roll_is_not_a_test_roll(self):
        self.assertFalse(is_test_roll_name("M1-0001"))

    def test_empty_or_none_is_not_a_test_roll(self):
        self.assertFalse(is_test_roll_name(""))
        self.assertFalse(is_test_roll_name(None))


if __name__ == "__main__":
    unittest.main()
