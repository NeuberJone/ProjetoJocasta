"""Testes do índice de pastas dos vendedores e do motor de correspondência
pedido<->pasta (core/order_files.py) — Etapa B do recurso de identificação
de vendedor e rastreabilidade de arquivos originais (ver [[core/vendedores.py]]
pra Etapa A). Usa diretórios temporários (nunca a estrutura real de rede do
usuário) montados no mesmo formato descrito na especificação original:

    <raiz do vendedor>/<cliente ou projeto>/<pedido individual>/
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.order_files import (
    MATCH_EXACT,
    MATCH_FUZZY,
    build_order_index,
    find_order_candidates,
    folder_for_vendor,
    load_order_index,
    normalize_order_name,
    refresh_order_index,
    save_order_index,
)
from core.vendedores import add_or_update_vendedor, add_vendedor_folder


def _make_order_folder(root: Path, client: str, pedido: str) -> Path:
    p = root / client / pedido
    p.mkdir(parents=True, exist_ok=True)
    return p


class NormalizeOrderNameTests(unittest.TestCase):
    def test_strips_accents_and_lowercases(self):
        self.assertEqual(normalize_order_name("ESCOLINHA DOUGLAS AMÉRICA"), "escolinha douglas america")

    def test_pedido_1_and_pedido_2_are_not_equal(self):
        self.assertNotEqual(
            normalize_order_name("ESCOLINHA DOUGLAS AMÉRICA"),
            normalize_order_name("ESCOLINHA DOUGLAS AMÉRICA 2"),
        )

    def test_collapses_duplicated_spaces_and_punctuation(self):
        self.assertEqual(normalize_order_name("Cliente   X -- Pedido"), "cliente x pedido")

    def test_blank_name_normalizes_to_empty(self):
        self.assertEqual(normalize_order_name("   "), "")

    def test_preserves_distinguishing_numbers(self):
        self.assertEqual(normalize_order_name("Pedido 10"), "pedido 10")
        self.assertNotEqual(normalize_order_name("Pedido 10"), normalize_order_name("Pedido 1"))


class BuildOrderIndexTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp_dir.name) / "_Evandro"
        _make_order_folder(self.root, "ESCOLINHA DOUGLAS AMÉRICA", "ESCOLINHA DOUGLAS AMÉRICA")
        _make_order_folder(self.root, "ESCOLINHA DOUGLAS AMÉRICA", "ESCOLINHA DOUGLAS AMÉRICA 2")
        self.vendedores = add_or_update_vendedor([], name="Evandro")
        self.vendedores = add_vendedor_folder(self.vendedores, "evandro", str(self.root))

    def tearDown(self):
        self._tmp_dir.cleanup()

    def test_indexes_both_distinct_order_folders(self):
        index = build_order_index(self.vendedores)
        names = sorted(f.display_name for f in index.folders)
        self.assertEqual(names, ["ESCOLINHA DOUGLAS AMÉRICA", "ESCOLINHA DOUGLAS AMÉRICA 2"])

    def test_each_entry_carries_vendor_and_client_context(self):
        index = build_order_index(self.vendedores)
        f = next(f for f in index.folders if f.display_name == "ESCOLINHA DOUGLAS AMÉRICA 2")
        self.assertEqual(f.vendor_key, "evandro")
        self.assertEqual(f.vendor_name_snapshot, "Evandro")
        self.assertEqual(f.client_folder, "ESCOLINHA DOUGLAS AMÉRICA")
        self.assertEqual(f.normalized_name, normalize_order_name("ESCOLINHA DOUGLAS AMÉRICA 2"))

    def test_inactive_vendor_is_not_indexed(self):
        vendedores = add_or_update_vendedor(self.vendedores, key="evandro", name="Evandro", active=False)
        index = build_order_index(vendedores)
        self.assertEqual(index.folders, [])

    def test_vendor_with_no_folders_is_skipped_without_error(self):
        vendedores = add_or_update_vendedor([], name="SemPasta")
        index = build_order_index(vendedores)
        self.assertEqual(index.folders, [])
        self.assertEqual(index.errors, [])

    def test_missing_root_folder_is_recorded_as_error_not_raised(self):
        vendedores = add_or_update_vendedor([], name="Fantasma")
        vendedores = add_vendedor_folder(vendedores, "fantasma", r"Z:\caminho\inexistente\nexor_test")
        index = build_order_index(vendedores)
        self.assertEqual(index.folders, [])
        self.assertEqual(len(index.errors), 1)


class FindOrderCandidatesTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp_dir.name) / "_Evandro"
        _make_order_folder(self.root, "ESCOLINHA DOUGLAS AMÉRICA", "ESCOLINHA DOUGLAS AMÉRICA")
        _make_order_folder(self.root, "ESCOLINHA DOUGLAS AMÉRICA", "ESCOLINHA DOUGLAS AMÉRICA 2")
        vendedores = add_or_update_vendedor([], name="Evandro")
        vendedores = add_vendedor_folder(vendedores, "evandro", str(self.root))
        self.index = build_order_index(vendedores)

    def tearDown(self):
        self._tmp_dir.cleanup()

    def test_exact_match_for_pedido_1(self):
        candidates = find_order_candidates("ESCOLINHA DOUGLAS AMÉRICA", self.index)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].match_kind, MATCH_EXACT)
        self.assertEqual(candidates[0].display_name, "ESCOLINHA DOUGLAS AMÉRICA")

    def test_exact_match_for_pedido_2_is_not_confused_with_pedido_1(self):
        candidates = find_order_candidates("ESCOLINHA DOUGLAS AMÉRICA 2", self.index)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].display_name, "ESCOLINHA DOUGLAS AMÉRICA 2")

    def test_match_ignores_accents_and_case(self):
        candidates = find_order_candidates("escolinha douglas america", self.index)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].match_kind, MATCH_EXACT)

    def test_ambiguous_same_name_across_vendors_returns_all_candidates(self):
        other_root = Path(self._tmp_dir.name) / "_OutroVendedor"
        _make_order_folder(other_root, "ESCOLINHA DOUGLAS AMÉRICA", "ESCOLINHA DOUGLAS AMÉRICA 2")
        vendedores = add_or_update_vendedor([], name="Evandro")
        vendedores = add_vendedor_folder(vendedores, "evandro", str(self.root))
        vendedores = add_or_update_vendedor(vendedores, name="Outro Vendedor")
        vendedores = add_vendedor_folder(vendedores, "outro_vendedor", str(other_root))
        index = build_order_index(vendedores)

        candidates = find_order_candidates("ESCOLINHA DOUGLAS AMÉRICA 2", index)
        self.assertEqual(len(candidates), 2)
        self.assertEqual({c.vendor_key for c in candidates}, {"evandro", "outro_vendedor"})

    def test_unknown_order_with_no_exact_match_falls_back_to_fuzzy(self):
        candidates = find_order_candidates("ESCOLINHA DOUGLAS AMERICA", self.index)  # sem acento mas igual após normalizar
        self.assertTrue(any(c.match_kind == MATCH_EXACT for c in candidates))

    def test_no_candidates_when_nothing_similar_enough(self):
        candidates = find_order_candidates("PEDIDO TOTALMENTE DIFERENTE XYZ", self.index)
        self.assertEqual(candidates, [])

    def test_fuzzy_candidates_never_returned_when_exact_exists(self):
        candidates = find_order_candidates("ESCOLINHA DOUGLAS AMÉRICA", self.index)
        self.assertTrue(all(c.match_kind == MATCH_EXACT for c in candidates))

    def test_blank_pedido_name_returns_no_candidates(self):
        self.assertEqual(find_order_candidates("   ", self.index), [])


class FolderForVendorTests(unittest.TestCase):
    """folder_for_vendor — usado por Registros e pelo painel de Operação
    (Parte 1) pra achar a pasta do pedido dentro da raiz do vendedor já
    identificado, sem repetir a busca por conta própria."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.evandro_root = Path(self._tmp_dir.name) / "_Evandro"
        _make_order_folder(self.evandro_root, "ESCOLINHA DOUGLAS AMÉRICA", "ESCOLINHA DOUGLAS AMÉRICA")
        self.outro_root = Path(self._tmp_dir.name) / "_OutroVendedor"
        _make_order_folder(self.outro_root, "ESCOLINHA DOUGLAS AMÉRICA", "ESCOLINHA DOUGLAS AMÉRICA")
        vendedores = add_or_update_vendedor([], name="Evandro")
        vendedores = add_vendedor_folder(vendedores, "evandro", str(self.evandro_root))
        vendedores = add_or_update_vendedor(vendedores, name="Outro Vendedor")
        vendedores = add_vendedor_folder(vendedores, "outro_vendedor", str(self.outro_root))
        self.index = build_order_index(vendedores)

    def tearDown(self):
        self._tmp_dir.cleanup()

    def test_returns_path_for_matching_vendor(self):
        path = folder_for_vendor("ESCOLINHA DOUGLAS AMÉRICA", self.index, "evandro")
        self.assertEqual(path, str(self.evandro_root / "ESCOLINHA DOUGLAS AMÉRICA" / "ESCOLINHA DOUGLAS AMÉRICA"))

    def test_returns_different_path_for_the_other_vendor_with_same_pedido_name(self):
        path = folder_for_vendor("ESCOLINHA DOUGLAS AMÉRICA", self.index, "outro_vendedor")
        self.assertEqual(path, str(self.outro_root / "ESCOLINHA DOUGLAS AMÉRICA" / "ESCOLINHA DOUGLAS AMÉRICA"))

    def test_returns_none_when_vendor_key_has_no_match(self):
        self.assertIsNone(folder_for_vendor("ESCOLINHA DOUGLAS AMÉRICA", self.index, "vendedor_inexistente"))


class RefreshOrderIndexPreservesUnavailableRootsTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp_dir.name) / "_Evandro"
        _make_order_folder(self.root, "CLIENTE", "PEDIDO X")
        self.vendedores = add_or_update_vendedor([], name="Evandro")
        self.vendedores = add_vendedor_folder(self.vendedores, "evandro", str(self.root))

    def tearDown(self):
        self._tmp_dir.cleanup()

    def test_previously_known_folder_survives_a_round_where_root_is_unavailable(self):
        import shutil

        first = build_order_index(self.vendedores)
        self.assertEqual(len(first.folders), 1)

        # Simula a pasta de rede saindo do ar: MESMO caminho cadastrado,
        # mas agora inacessível (ver docstring de refresh_order_index — a
        # preservação é por pasta raiz cadastrada, não por vendedor).
        shutil.rmtree(self.root)

        refreshed = refresh_order_index(self.vendedores, previous=first)
        self.assertEqual(len(refreshed.folders), 1)
        self.assertEqual(refreshed.folders[0].display_name, "PEDIDO X")
        self.assertTrue(refreshed.errors)

    def test_refresh_replaces_entries_once_root_is_available_again(self):
        first = build_order_index(self.vendedores)
        _make_order_folder(self.root, "CLIENTE", "PEDIDO NOVO")

        refreshed = refresh_order_index(self.vendedores, previous=first)
        names = sorted(f.display_name for f in refreshed.folders)
        self.assertEqual(names, ["PEDIDO NOVO", "PEDIDO X"])

    def test_partial_client_folder_failure_keeps_fresh_data_from_healthy_siblings(self):
        """Achado de revisão de código: antes, uma falha numa ÚNICA pasta de
        cliente (não a raiz em si) descartava TODAS as pastas de cliente
        que responderam normalmente na mesma rodada, caindo pro snapshot
        da raiz inteira — pedidos novos descobertos nas pastas saudáveis
        ficavam invisíveis até a pasta com problema voltar a responder."""
        _make_order_folder(self.root, "CLIENTE2", "PEDIDO Y")
        first = build_order_index(self.vendedores)
        self.assertEqual(sorted(f.display_name for f in first.folders), ["PEDIDO X", "PEDIDO Y"])

        # Pedido novo surge em "CLIENTE" (saudável) nesta rodada, enquanto
        # "CLIENTE2" fica inacessível (simulado) — nunca a raiz inteira.
        _make_order_folder(self.root, "CLIENTE", "PEDIDO NOVO")

        real_iterdir = Path.iterdir

        def flaky_iterdir(self_path):
            if self_path.name == "CLIENTE2":
                raise OSError("acesso negado (simulado)")
            return real_iterdir(self_path)

        with patch.object(Path, "iterdir", flaky_iterdir):
            refreshed = refresh_order_index(self.vendedores, previous=first)

        names = sorted(f.display_name for f in refreshed.folders)
        # "PEDIDO NOVO" (de CLIENTE, saudável) precisa aparecer — não pode
        # ser descartado só porque CLIENTE2 falhou. "PEDIDO Y" (de
        # CLIENTE2, agora inacessível) precisa ser preservado do snapshot
        # anterior, não some.
        self.assertEqual(names, ["PEDIDO NOVO", "PEDIDO X", "PEDIDO Y"])
        self.assertTrue(refreshed.errors)


class OrderIndexPersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.store_path = Path(self._tmp_dir.name) / "order_index.json"
        self._patcher = patch("core.order_files._index_store_path", return_value=self.store_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def test_fresh_store_loads_empty_index(self):
        index = load_order_index()
        self.assertEqual(index.folders, [])
        self.assertEqual(index.generated_at, "")

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as data_dir:
            root = Path(data_dir) / "_Evandro"
            _make_order_folder(root, "CLIENTE", "PEDIDO X")
            vendedores = add_or_update_vendedor([], name="Evandro")
            vendedores = add_vendedor_folder(vendedores, "evandro", str(root))
            built = build_order_index(vendedores)
            save_order_index(built)

            reloaded = load_order_index()
            self.assertEqual(len(reloaded.folders), 1)
            self.assertEqual(reloaded.folders[0].display_name, "PEDIDO X")
            self.assertEqual(reloaded.generated_at, built.generated_at)


if __name__ == "__main__":
    unittest.main()
