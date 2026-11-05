"""Testes de core.paths.reveal_file_in_explorer — "Mostrar arquivo na pasta" usado na
confirmação pós-exportação do contexto de produção (ver modules/registros/ui.py,
_show_export_confirmation). Nunca chama o Explorer de verdade aqui: subprocess.Popen é sempre
mockado, nunca abre uma janela real durante os testes.
"""
import unittest
from pathlib import Path
from unittest.mock import patch

from core.paths import reveal_file_in_explorer


class RevealFileInExplorerTests(unittest.TestCase):
    def test_calls_explorer_with_argument_list_not_shell_string(self):
        """Nunca shell=True, nunca uma string concatenada — sempre uma lista de argumentos
        (ver AGENTS.md/pedido da tarefa: "não monte comandos de shell concatenando caminhos")."""
        with patch("core.paths.subprocess.Popen") as mock_popen:
            reveal_file_in_explorer(Path(r"C:\temp\arquivo.json"))

        args, kwargs = mock_popen.call_args
        self.assertIsInstance(args[0], list)
        self.assertEqual(args[0][0], "explorer")
        self.assertNotIn("shell", kwargs)

    def test_path_with_spaces_and_accents_passed_as_single_unmodified_argument(self):
        tricky_path = Path(r"C:\temp\pasta com espaço e acentuação\joão-contexto-produção.json")
        with patch("core.paths.subprocess.Popen") as mock_popen:
            reveal_file_in_explorer(tricky_path)

        args, _ = mock_popen.call_args
        argv = args[0]
        # O caminho inteiro precisa chegar como UM único elemento da lista — nunca dividido ou
        # re-escapado por concatenação manual (o próprio Popen cuida de passar cada elemento
        # como um argumento distinto ao processo, sem interpretação de shell).
        self.assertTrue(any(str(tricky_path.resolve()) == arg for arg in argv))

    def test_select_flag_is_its_own_argument(self):
        with patch("core.paths.subprocess.Popen") as mock_popen:
            reveal_file_in_explorer(Path(r"C:\temp\arquivo.json"))

        args, _ = mock_popen.call_args
        self.assertIn("/select,", args[0])


if __name__ == "__main__":
    unittest.main()
