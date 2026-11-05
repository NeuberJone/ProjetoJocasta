"""Testes de core/config.get_installation_id — id curto e opaco por instalação, usado na
exportação do contexto de produção pro PX Tool Box (ver modules/registros/px_export.py).
Usa um caminho de config TEMPORÁRIO isolado (patch de core.config._config_path) — nunca o
config.json real do usuário (%APPDATA%\\PXCore\\config.json).
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.config import get_installation_id


class InstallationIdTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self._tmp_dir.name) / "config.json"
        self._patcher = patch("core.config._config_path", return_value=self.config_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def test_generates_and_persists_id_on_first_call(self):
        self.assertFalse(self.config_path.exists())  # load_config() ainda não rodou

        first = get_installation_id()

        self.assertTrue(first)
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["installation_id"], first)

    def test_second_call_never_regenerates_the_id(self):
        first = get_installation_id()
        second = get_installation_id()

        self.assertEqual(first, second)

    def test_id_survives_a_config_reload_from_disk(self):
        first = get_installation_id()

        # Simula o processo reabrindo (load_config() lendo o arquivo de novo, não reusando
        # nenhum estado em memória) — o id precisa ser o mesmo, nunca regenerado.
        from core.config import load_config
        reloaded_cfg = load_config()

        self.assertEqual(reloaded_cfg.installation_id, first)

    def test_existing_config_without_installation_id_gets_one_added(self):
        # Simula uma instalação já existente, com config.json de antes deste campo existir.
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps({"base_dir": r"C:\PXCore", "theme_name": "dark"}), encoding="utf-8"
        )

        generated = get_installation_id()

        self.assertTrue(generated)
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["installation_id"], generated)
        # Campos já existentes nunca são perdidos ao adicionar o novo.
        self.assertEqual(saved["theme_name"], "dark")


if __name__ == "__main__":
    unittest.main()
