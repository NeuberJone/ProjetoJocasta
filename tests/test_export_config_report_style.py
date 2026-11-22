"""Testes de persistência do campo `report_style` (Clássico/Prisma) em
core/export_config.py — ver [[tests/test_report_filename_tag.py]] pro
sufixo de nome de arquivo que consome esse valor. Usa o mesmo padrão de
isolamento de tests/test_config_hardening.py (patch de
core.config._config_path), já que módulos usam
core.config.module_config_path (derivado dali) pra gravar."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import config
from core.export_config import (
    REPORT_STYLE_CLASSIC,
    REPORT_STYLE_PRISMA,
    VALID_REPORT_STYLES,
    load_export_cfg,
    save_export_cfg,
)


class IsolatedExportConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.json"
        self.patcher = patch("core.config._config_path", return_value=self.path)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        dirs = patch("core.config._ensure_dirs")
        dirs.start()
        self.addCleanup(dirs.stop)

    def _module_path(self) -> Path:
        return config.module_config_path("Exportacao")


class ReportStyleDefaultsTests(IsolatedExportConfigTest):
    def test_fresh_install_defaults_to_classic(self):
        cfg = load_export_cfg()
        self.assertEqual(cfg["report_style"], REPORT_STYLE_CLASSIC)

    def test_old_config_without_report_style_key_still_resolves_to_classic(self):
        """Simula uma instalação existente, que salvou Exportacao.json
        antes do campo report_style existir."""
        module_path = self._module_path()
        module_path.write_text(
            json.dumps({"report_mode_default": "summary", "mirror_jpg_width_mode": "21"}),
            encoding="utf-8",
        )
        cfg = load_export_cfg()
        self.assertEqual(cfg["report_style"], REPORT_STYLE_CLASSIC)
        # Campos antigos continuam intactos — adicionar o default novo não
        # pisou em nada que já existia.
        self.assertEqual(cfg["report_mode_default"], "summary")
        self.assertEqual(cfg["mirror_jpg_width_mode"], "21")

    def test_explicit_prisma_choice_persists_across_reload(self):
        cfg = load_export_cfg()
        cfg["report_style"] = REPORT_STYLE_PRISMA
        save_export_cfg(cfg)

        reloaded = load_export_cfg()
        self.assertEqual(reloaded["report_style"], REPORT_STYLE_PRISMA)

    def test_saving_other_fields_does_not_reset_report_style_back_to_classic(self):
        cfg = load_export_cfg()
        cfg["report_style"] = REPORT_STYLE_PRISMA
        save_export_cfg(cfg)

        cfg2 = load_export_cfg()
        cfg2["mirror_jpg_width_mode"] = "21"
        save_export_cfg(cfg2)

        self.assertEqual(load_export_cfg()["report_style"], REPORT_STYLE_PRISMA)

    def test_valid_report_styles_are_exactly_classic_and_prisma(self):
        self.assertEqual(VALID_REPORT_STYLES, {REPORT_STYLE_CLASSIC, REPORT_STYLE_PRISMA})


if __name__ == "__main__":
    unittest.main()
