"""Testes de core.station — identificador do computador e nome do
operador de fechamento (impresso no comprovante). Usa um config.json
temporário isolado (nunca o config real do usuário)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.station import (
    load_station_id,
    load_station_operator,
    save_station_id,
    save_station_operator,
)


class StationConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp_dir.name)
        self._patcher = patch("core.config._config_path", return_value=self.tmp_path / "config.json")
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def test_defaults_are_empty(self):
        self.assertEqual(load_station_id(), "")
        self.assertEqual(load_station_operator(), "")

    def test_saving_station_id_does_not_wipe_operator_name(self):
        """write_module_cfg substitui o arquivo inteiro — salvar um campo
        precisa preservar o outro já salvo (bug real: salvar o
        identificador sem ler o config atual apagava o operador salvo
        antes, e vice-versa)."""
        save_station_operator("Neuber")
        save_station_id("PC1")
        self.assertEqual(load_station_id(), "PC1")
        self.assertEqual(load_station_operator(), "Neuber")

    def test_saving_operator_name_does_not_wipe_station_id(self):
        save_station_id("PC1")
        save_station_operator("Neuber")
        self.assertEqual(load_station_id(), "PC1")
        self.assertEqual(load_station_operator(), "Neuber")

    def test_station_id_is_sanitized_and_truncated(self):
        save_station_id("PC 1 !! ")
        self.assertEqual(load_station_id(), "PC1")

    def test_operator_name_allows_spaces(self):
        save_station_operator("  Neuber Queiroz  ")
        self.assertEqual(load_station_operator(), "Neuber Queiroz")


if __name__ == "__main__":
    unittest.main()
