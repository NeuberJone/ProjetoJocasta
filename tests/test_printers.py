import unittest

from core.printers import Printer, add_or_update_printer


class PrinterJpgRotationTests(unittest.TestCase):
    """Orientação do JPG de registro é por impressora (cadastro de
    Impressoras), não uma opção global — cada máquina pode precisar
    receber o arquivo girado de um jeito diferente."""

    def test_default_rotation_is_zero(self):
        self.assertEqual(Printer(key="m1", name="Máquina 1", display_name="M1").jpg_rotation, 0)

    def test_new_printer_keeps_chosen_rotation(self):
        out = add_or_update_printer(
            [], key=None, name="Máquina 1", display_name="M1", speed_m_min=1.5, jpg_rotation=90,
        )
        self.assertEqual(out[0].jpg_rotation, 90)

    def test_updating_printer_changes_rotation(self):
        printers = [Printer(key="m1", name="Máquina 1", display_name="M1", jpg_rotation=0)]
        out = add_or_update_printer(
            printers, key="m1", name="Máquina 1", display_name="M1", speed_m_min=1.5, jpg_rotation=270,
        )
        self.assertEqual(out[0].jpg_rotation, 270)

    def test_invalid_rotation_falls_back_to_zero(self):
        out = add_or_update_printer(
            [], key=None, name="Máquina 1", display_name="M1", speed_m_min=1.5, jpg_rotation=45,
        )
        self.assertEqual(out[0].jpg_rotation, 0)


class PrinterLogImportDirTests(unittest.TestCase):
    """Pasta dos logs desta impressora — a Operação abre o diálogo de
    'Importar logs' direto nela quando cadastrada."""

    def test_default_is_empty(self):
        self.assertEqual(Printer(key="m1", name="Máquina 1", display_name="M1").log_import_dir, "")

    def test_new_printer_keeps_log_import_dir(self):
        out = add_or_update_printer(
            [], key=None, name="Máquina 1", display_name="M1", speed_m_min=1.5,
            log_import_dir=r"C:\Logs\M1",
        )
        self.assertEqual(out[0].log_import_dir, r"C:\Logs\M1")

    def test_updating_printer_changes_log_import_dir(self):
        printers = [Printer(key="m1", name="Máquina 1", display_name="M1", log_import_dir=r"C:\Old")]
        out = add_or_update_printer(
            printers, key="m1", name="Máquina 1", display_name="M1", speed_m_min=1.5,
            log_import_dir=r"C:\New",
        )
        self.assertEqual(out[0].log_import_dir, r"C:\New")


if __name__ == "__main__":
    unittest.main()
