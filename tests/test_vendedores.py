"""Testes do cadastro de vendedores (core/vendedores.py) — etapa A do recurso
de identificação de vendedor e rastreabilidade de arquivos originais. Cobre
só o modelo de dados (cadastro + pastas); nenhuma busca automática de
arquivo/pedido existe ainda nesta etapa.

Nomes de teste usam "Joao" (sem acento) de propósito: _slugify (idêntico ao
de core/printers.py) só preserva a-z0-9, então um nome acentuado não geraria
a key previsível que os testes usam para chamar as outras funções.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.vendedores as vendedores_mod
from core.vendedores import (
    Vendedor,
    VendorFolder,
    add_or_update_vendedor,
    add_vendedor_folder,
    find_vendedor_by_key,
    load_vendedores,
    remove_vendedor,
    remove_vendedor_folder,
    save_vendedores,
    set_vendedor_folder_access_result,
)


class VendedorDataclassDefaultsTests(unittest.TestCase):
    def test_vendedor_defaults(self):
        v = Vendedor(key="joao", name="Joao")
        self.assertTrue(v.active)
        self.assertEqual(v.priority, 100)
        self.assertEqual(v.notes, "")
        self.assertEqual(v.folders, [])

    def test_vendor_folder_defaults(self):
        f = VendorFolder(path=r"Z:\joao")
        self.assertEqual(f.last_checked_at, "")
        self.assertIsNone(f.last_check_ok)
        self.assertEqual(f.last_check_detail, "")


class AddOrUpdateVendedorTests(unittest.TestCase):
    def setUp(self):
        self.vendedores = []

    def test_adds_new_vendedor(self):
        out = add_or_update_vendedor(self.vendedores, name="Joao")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].name, "Joao")
        self.assertEqual(out[0].key, "joao")

    def test_update_preserves_folders(self):
        out = add_or_update_vendedor(self.vendedores, name="Joao")
        out = add_vendedor_folder(out, "joao", r"Z:\joao")
        out = add_or_update_vendedor(out, key="joao", name="Joao Silva", priority=50)
        self.assertEqual(out[0].name, "Joao Silva")
        self.assertEqual(out[0].priority, 50)
        self.assertEqual(len(out[0].folders), 1)
        self.assertEqual(out[0].folders[0].path, r"Z:\joao")

    def test_duplicate_name_rejected(self):
        out = add_or_update_vendedor(self.vendedores, name="Joao")
        with self.assertRaises(ValueError):
            add_or_update_vendedor(out, name="joao")

    def test_duplicate_name_rejected_even_against_inactive_vendor(self):
        out = add_or_update_vendedor(self.vendedores, name="Joao", active=False)
        with self.assertRaises(ValueError):
            add_or_update_vendedor(out, name="Joao")

    def test_update_against_own_key_is_not_a_duplicate(self):
        out = add_or_update_vendedor(self.vendedores, name="Joao")
        out = add_or_update_vendedor(out, key="joao", name="Joao", priority=10)
        self.assertEqual(len(out), 1)

    def test_blank_name_raises(self):
        with self.assertRaises(ValueError):
            add_or_update_vendedor(self.vendedores, name="   ")

    def test_update_unknown_key_raises(self):
        with self.assertRaises(ValueError):
            add_or_update_vendedor(self.vendedores, key="inexistente", name="X")

    def test_remove_vendedor(self):
        out = add_or_update_vendedor(self.vendedores, name="Joao")
        out = remove_vendedor(out, "joao")
        self.assertEqual(out, [])

    def test_find_vendedor_by_key(self):
        out = add_or_update_vendedor(self.vendedores, name="Joao")
        self.assertIsNotNone(find_vendedor_by_key("joao", out))
        self.assertIsNone(find_vendedor_by_key("ninguem", out))


class VendedorFolderTests(unittest.TestCase):
    def setUp(self):
        self.vendedores = add_or_update_vendedor([], name="Joao")

    def test_add_folder(self):
        out = add_vendedor_folder(self.vendedores, "joao", r"Z:\_Evandro\joao")
        self.assertEqual(len(out[0].folders), 1)

    def test_duplicate_folder_same_vendor_rejected(self):
        out = add_vendedor_folder(self.vendedores, "joao", r"Z:\_Evandro\joao")
        with self.assertRaises(ValueError):
            add_vendedor_folder(out, "joao", r"Z:\_Evandro\joao")

    def test_same_path_different_vendor_allowed(self):
        vendedores = add_or_update_vendedor(self.vendedores, name="Maria")
        out = add_vendedor_folder(vendedores, "joao", r"Z:\compartilhada")
        out = add_vendedor_folder(out, "maria", r"Z:\compartilhada")
        joao = find_vendedor_by_key("joao", out)
        maria = find_vendedor_by_key("maria", out)
        self.assertEqual(len(joao.folders), 1)
        self.assertEqual(len(maria.folders), 1)

    def test_remove_folder(self):
        out = add_vendedor_folder(self.vendedores, "joao", r"Z:\_Evandro\joao")
        out = remove_vendedor_folder(out, "joao", r"Z:\_Evandro\joao")
        self.assertEqual(out[0].folders, [])

    def test_remove_folder_ignores_case_and_surrounding_whitespace(self):
        """Achado de revisão: add_vendedor_folder já normaliza (.strip().lower())
        pra checar duplicata, mas remove_vendedor_folder comparava com `!=`
        puro — uma chamada com a mesma pasta em caixa diferente não
        removia nada, silenciosamente."""
        out = add_vendedor_folder(self.vendedores, "joao", r"Z:\_Evandro\joao")
        out = remove_vendedor_folder(out, "joao", r" z:\_evandro\JOAO ")
        self.assertEqual(out[0].folders, [])

    def test_set_folder_access_result_ignores_case_and_whitespace(self):
        out = add_vendedor_folder(self.vendedores, "joao", r"Z:\_Evandro\joao")
        out = set_vendedor_folder_access_result(
            out, "joao", r" z:\_evandro\JOAO ", ok=True, detail="Acesso confirmado.", checked_at="10/11/2026 09:00",
        )
        f = out[0].folders[0]
        self.assertTrue(f.last_check_ok)
        self.assertEqual(f.last_check_detail, "Acesso confirmado.")

    def test_add_folder_blank_path_raises(self):
        with self.assertRaises(ValueError):
            add_vendedor_folder(self.vendedores, "joao", "   ")

    def test_add_folder_unknown_vendedor_raises(self):
        with self.assertRaises(ValueError):
            add_vendedor_folder(self.vendedores, "ninguem", r"Z:\x")

    def test_set_folder_access_result(self):
        out = add_vendedor_folder(self.vendedores, "joao", r"Z:\_Evandro\joao")
        out = set_vendedor_folder_access_result(
            out, "joao", r"Z:\_Evandro\joao", ok=True, detail="Acesso confirmado.", checked_at="10/11/2026 09:00",
        )
        f = out[0].folders[0]
        self.assertTrue(f.last_check_ok)
        self.assertEqual(f.last_check_detail, "Acesso confirmado.")
        self.assertEqual(f.last_checked_at, "10/11/2026 09:00")


class FolderAccessCheckTests(unittest.TestCase):
    """core.vendedores.test_folder_access — nome mantido fora de um `from
    import` direto (chamado via `vendedores_mod.`) pra pytest não tentar
    coletá-la como teste só por começar com "test_"."""

    def test_real_directory_is_accessible(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, detail = vendedores_mod.test_folder_access(tmp)
            self.assertTrue(ok)
            self.assertTrue(detail)

    def test_nonexistent_path_is_not_accessible(self):
        ok, detail = vendedores_mod.test_folder_access(r"Z:\caminho\que\nao\existe\nexor_test")
        self.assertFalse(ok)
        self.assertTrue(detail)

    def test_file_path_is_not_a_directory(self):
        with tempfile.NamedTemporaryFile() as tmp:
            ok, detail = vendedores_mod.test_folder_access(tmp.name)
            self.assertFalse(ok)

    def test_blank_path_is_not_accessible(self):
        ok, detail = vendedores_mod.test_folder_access("")
        self.assertFalse(ok)

    def test_never_raises_on_bad_input(self):
        try:
            ok, detail = vendedores_mod.test_folder_access(None)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            self.fail(f"test_folder_access levantou exceção: {exc}")
        self.assertFalse(ok)


class LoadSaveVendedoresRoundTripTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.store_path = Path(self._tmp_dir.name) / "vendedores.json"
        self._patcher = patch("core.vendedores._store_path", return_value=self.store_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def test_fresh_store_is_empty(self):
        self.assertEqual(load_vendedores(), [])

    def test_round_trip(self):
        vendedores = add_or_update_vendedor([], name="Joao", priority=10, notes="obs")
        vendedores = add_vendedor_folder(vendedores, "joao", r"Z:\joao")
        save_vendedores(vendedores)

        reloaded = load_vendedores()
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0].name, "Joao")
        self.assertEqual(reloaded[0].priority, 10)
        self.assertEqual(len(reloaded[0].folders), 1)
        self.assertEqual(reloaded[0].folders[0].path, r"Z:\joao")

    def test_unknown_field_survives_rewrite(self):
        vendedores = add_or_update_vendedor([], name="Joao")
        save_vendedores(vendedores)

        raw = self.store_path.read_text(encoding="utf-8")
        import json

        data = json.loads(raw)
        data[0]["future_field"] = "mantido"
        self.store_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        vendedores = load_vendedores()
        vendedores = add_or_update_vendedor(vendedores, key="joao", name="Joao", priority=5)
        save_vendedores(vendedores)

        raw_after = json.loads(self.store_path.read_text(encoding="utf-8"))
        self.assertEqual(raw_after[0].get("future_field"), "mantido")


if __name__ == "__main__":
    unittest.main()
