from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from Nexor import Nexor
from modules.operacao.ui import PXPrintLogsUI


class FailureReportingTests(unittest.TestCase):
    def test_theme_save_failure_preserves_current_theme_and_config(self):
        cfg = SimpleNamespace(theme_name="dark")
        app = SimpleNamespace(px_cfg=cfg, _mark_active_theme=Mock())
        with patch("Nexor.save_pxcore_config", side_effect=OSError("write denied")), \
                patch("Nexor.theme.apply_theme") as apply_theme:
            with self.assertRaises(OSError):
                Nexor._select_theme(app, "light")
        self.assertEqual(cfg.theme_name, "dark")
        apply_theme.assert_not_called()

    def test_database_failure_after_pdf_does_not_announce_completed_export(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
            output = Path(temporary)
            status = Mock()
            status.cget.return_value = "Arquivos gerados"
            job = SimpleNamespace(
                end_time=datetime(2026, 11, 5, 10, 0), document="arquivo.jpeg",
                fabric="Dryfit", pedido="Pedido exemplo", height_mm=1000.0,
                vpos_mm=0.0, real_m=1.0, src_file="arquivo.txt", tipo="Pedido", observacao="",
            )
            app = SimpleNamespace(
                blocks=[object()], machine="M1", Jobs=[job], pedidos=[],
                _confirm_duplicates_on_export=lambda: True,
                _get_roll_name=lambda: "M1_05-11-2026_0001",
                var_mode=SimpleNamespace(get=lambda: "full"),
                _resolve_mirror_jpg_path=lambda folder, name: folder / (name + ".jpg"),
                _get_mirror_target_cm=lambda: 17.0, edit_roll_id=None,
                status=status, _last_pdf_path=None, btn_open_comprovante=Mock(),
                var_close_roll_text=Mock(),
            )
            with ExitStack() as stack:
                for name in ("pdf_dir", "jpg_dir", "temp_dir"):
                    stack.enter_context(patch("modules.operacao.ui." + name, return_value=output))
                stack.enter_context(patch("modules.operacao.ui.load_export_cfg", return_value={}))
                stack.enter_context(patch("modules.operacao.ui.find_printer_by_display_name", return_value=None))
                stack.enter_context(patch("modules.operacao.ui.export_pdf", side_effect=
                    lambda path, *args, **kwargs: Path(path).write_bytes(b"pdf already generated")))
                stack.enter_context(patch("modules.operacao.ui.save_export_transactional", side_effect=OSError("database unavailable")))
                success = stack.enter_context(patch("modules.operacao.ui.messagebox.showinfo"))
                warning = stack.enter_context(patch("modules.operacao.ui.messagebox.showwarning"))
                PXPrintLogsUI.on_export(app, "normal")
                success.assert_not_called()
                self.assertIn("banco", warning.call_args.args[1])
                self.assertTrue(Path(app._last_pdf_path).exists())
                self.assertIsNone(app.edit_roll_id)


if __name__ == "__main__":
    unittest.main()
