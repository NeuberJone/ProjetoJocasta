"""Testes de core.roll_naming.build_roll_name — o identificador do
computador (core.station) entra logo depois da máquina no nome do rolo,
não no fim (ex.: M3_N_05-11-2026_0083, não M3_05-11-2026_0083_N)."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from core.roll_naming import build_roll_name


class BuildRollNameTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp_dir.name)
        self._patcher = patch("core.config._config_path", return_value=self.tmp_path / "config.json")
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def test_without_station_id_has_no_extra_segment(self):
        name = build_roll_name("M3", 83, when=datetime(2026, 11, 5))
        self.assertEqual(name, "M3_05-11-2026_0083")

    def test_station_id_goes_right_after_machine(self):
        from core.station import save_station_id

        save_station_id("N")
        name = build_roll_name("M3", 83, when=datetime(2026, 11, 5))
        self.assertEqual(name, "M3_N_05-11-2026_0083")

    def test_missing_machine_falls_back_to_placeholder(self):
        name = build_roll_name("", 1, when=datetime(2026, 11, 5))
        self.assertEqual(name, "M?_05-11-2026_0001")


if __name__ == "__main__":
    unittest.main()
