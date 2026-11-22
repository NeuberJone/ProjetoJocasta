"""Testes do serviço de resolução automática/manual do vendedor de um
pedido (core/order_vendor_resolution.py) — Etapa C do recurso de
identificação de vendedor (ver [[core/order_files.py]] pra Etapa B e
[[core/vendedores.py]] pra Etapa A). Combina um banco SQLite temporário
(vínculos, mesmo padrão de tests/test_order_vendor_links.py) com pastas
temporárias reais indexadas (mesmo padrão de tests/test_order_files.py).
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.order_files import build_order_index
from core.order_vendor_resolution import (
    RESOLUTION_AMBIGUOUS,
    RESOLUTION_AUTO,
    RESOLUTION_MANUAL,
    RESOLUTION_NOT_FOUND,
    clear_order_vendor,
    confirm_order_vendor,
    guess_vendor_name_for_pedido,
    preview_order_vendor,
    resolve_order_vendor,
)
from core.printlogs_db import OrderRow, get_vendor_link_history, save_export_transactional, get_roll_orders
from core.vendedores import add_or_update_vendedor, add_vendedor_folder


def _order(document: str, pedido: str) -> OrderRow:
    return OrderRow(
        end_time="2026-11-10T10:00:00", document=document, fabric="DRYFIT", pedido=pedido,
        height_mm=1000.0, vpos_mm=0.0, real_m=1.0, source_path=f"/x/{document}", tipo="Pedido",
    )


class OrderVendorResolutionTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._db_patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._db_patcher.start()

        self._folders_dir = Path(self._tmp_dir.name) / "folders"
        self.evandro_root = self._folders_dir / "_Evandro"
        (self.evandro_root / "ESCOLINHA DOUGLAS AMÉRICA" / "ESCOLINHA DOUGLAS AMÉRICA").mkdir(parents=True)
        (self.evandro_root / "ESCOLINHA DOUGLAS AMÉRICA" / "ESCOLINHA DOUGLAS AMÉRICA 2").mkdir(parents=True)
        vendedores = add_or_update_vendedor([], name="Evandro")
        self.vendedores = add_vendedor_folder(vendedores, "evandro", str(self.evandro_root))
        self.index = build_order_index(self.vendedores)

    def tearDown(self):
        self._db_patcher.stop()
        self._tmp_dir.cleanup()

    def _make_order(self, suffix: str, pedido: str) -> int:
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name=f"M1-{suffix}", export_mode="normal", app_version="1.0.0",
            orders=[_order(f"doc{suffix}.jpeg", pedido)],
        )
        return int(get_roll_orders(roll_id)[0]["id"])

    def test_single_exact_match_auto_links_and_persists(self):
        order_id = self._make_order("0001", "ESCOLINHA DOUGLAS AMÉRICA")
        result = resolve_order_vendor(order_id, "ESCOLINHA DOUGLAS AMÉRICA", index=self.index, vendedores=self.vendedores)

        self.assertEqual(result.state, RESOLUTION_AUTO)
        self.assertEqual(result.vendor_key, "evandro")
        self.assertEqual(result.link["origin"], "auto")

        history = get_vendor_link_history(order_id)
        self.assertEqual(len(history), 1)

    def test_pedido_1_and_pedido_2_resolve_to_distinct_links(self):
        order1 = self._make_order("0001", "ESCOLINHA DOUGLAS AMÉRICA")
        order2 = self._make_order("0002", "ESCOLINHA DOUGLAS AMÉRICA 2")
        r1 = resolve_order_vendor(order1, "ESCOLINHA DOUGLAS AMÉRICA", index=self.index, vendedores=self.vendedores)
        r2 = resolve_order_vendor(order2, "ESCOLINHA DOUGLAS AMÉRICA 2", index=self.index, vendedores=self.vendedores)

        self.assertEqual(r1.state, RESOLUTION_AUTO)
        self.assertEqual(r2.state, RESOLUTION_AUTO)
        self.assertEqual(r1.vendor_key, "evandro")
        self.assertEqual(r2.vendor_key, "evandro")
        self.assertNotEqual(order1, order2)

        history1 = get_vendor_link_history(order1)
        history2 = get_vendor_link_history(order2)
        self.assertEqual(len(history1), 1)
        self.assertEqual(len(history2), 1)

    def test_rerunning_same_resolution_does_not_duplicate_history(self):
        order_id = self._make_order("0001", "ESCOLINHA DOUGLAS AMÉRICA")
        resolve_order_vendor(order_id, "ESCOLINHA DOUGLAS AMÉRICA", index=self.index, vendedores=self.vendedores)
        resolve_order_vendor(order_id, "ESCOLINHA DOUGLAS AMÉRICA", index=self.index, vendedores=self.vendedores)

        self.assertEqual(len(get_vendor_link_history(order_id)), 1)

    def test_ambiguous_exact_matches_do_not_write_a_link(self):
        other_root = self._folders_dir / "_OutroVendedor"
        (other_root / "ESCOLINHA DOUGLAS AMÉRICA" / "ESCOLINHA DOUGLAS AMÉRICA").mkdir(parents=True)
        vendedores = add_or_update_vendedor(self.vendedores, name="Outro Vendedor")
        vendedores = add_vendedor_folder(vendedores, "outro_vendedor", str(other_root))
        index = build_order_index(vendedores)

        order_id = self._make_order("0001", "ESCOLINHA DOUGLAS AMÉRICA")
        result = resolve_order_vendor(order_id, "ESCOLINHA DOUGLAS AMÉRICA", index=index, vendedores=vendedores)

        self.assertEqual(result.state, RESOLUTION_AMBIGUOUS)
        self.assertEqual(len(result.candidates), 2)
        self.assertIsNone(result.link)
        self.assertEqual(get_vendor_link_history(order_id), [])

    def test_no_match_returns_not_found_without_writing(self):
        order_id = self._make_order("0001", "PEDIDO TOTALMENTE DESCONHECIDO XYZ")
        result = resolve_order_vendor(order_id, "PEDIDO TOTALMENTE DESCONHECIDO XYZ", index=self.index, vendedores=self.vendedores)

        self.assertEqual(result.state, RESOLUTION_NOT_FOUND)
        self.assertIsNone(result.link)
        self.assertEqual(get_vendor_link_history(order_id), [])

    def test_manual_confirmation_takes_precedence_over_future_auto_resolution(self):
        order_id = self._make_order("0001", "ESCOLINHA DOUGLAS AMÉRICA")
        confirm_order_vendor(order_id, "evandro_manual_override", "Vendedor Escolhido Manualmente")

        result = resolve_order_vendor(order_id, "ESCOLINHA DOUGLAS AMÉRICA", index=self.index, vendedores=self.vendedores)

        self.assertEqual(result.state, RESOLUTION_MANUAL)
        self.assertEqual(result.vendor_key, "evandro_manual_override")
        # Nenhuma escrita nova disparada pela resolução automática (só a confirmação manual).
        self.assertEqual(len(get_vendor_link_history(order_id)), 1)

    def test_ambiguity_never_overwrites_a_previous_auto_link(self):
        order_id = self._make_order("0001", "ESCOLINHA DOUGLAS AMÉRICA")
        first = resolve_order_vendor(order_id, "ESCOLINHA DOUGLAS AMÉRICA", index=self.index, vendedores=self.vendedores)
        self.assertEqual(first.state, RESOLUTION_AUTO)

        other_root = self._folders_dir / "_OutroVendedor"
        (other_root / "ESCOLINHA DOUGLAS AMÉRICA" / "ESCOLINHA DOUGLAS AMÉRICA").mkdir(parents=True)
        vendedores = add_or_update_vendedor(self.vendedores, name="Outro Vendedor")
        vendedores = add_vendedor_folder(vendedores, "outro_vendedor", str(other_root))
        index = build_order_index(vendedores)

        second = resolve_order_vendor(order_id, "ESCOLINHA DOUGLAS AMÉRICA", index=index, vendedores=vendedores)
        self.assertEqual(second.state, RESOLUTION_AMBIGUOUS)
        self.assertIsNotNone(second.link)
        self.assertEqual(second.link["vendor_key"], "evandro")
        self.assertEqual(second.link["status"], "active")

    def test_clear_order_vendor_allows_fresh_resolution_afterwards(self):
        order_id = self._make_order("0001", "ESCOLINHA DOUGLAS AMÉRICA")
        confirm_order_vendor(order_id, "manual_key", "Manual")
        self.assertTrue(clear_order_vendor(order_id, note="corrigindo"))

        result = resolve_order_vendor(order_id, "ESCOLINHA DOUGLAS AMÉRICA", index=self.index, vendedores=self.vendedores)
        self.assertEqual(result.state, RESOLUTION_AUTO)
        self.assertEqual(result.vendor_key, "evandro")

    def test_source_unavailable_flagged_when_vendor_root_errors(self):
        order_id = self._make_order("0001", "ESCOLINHA DOUGLAS AMÉRICA")
        resolve_order_vendor(order_id, "ESCOLINHA DOUGLAS AMÉRICA", index=self.index, vendedores=self.vendedores)

        from core.order_files import VendorIndexState
        broken_index = VendorIndexState(generated_at="", folders=[], errors=[f"{self.evandro_root}: acesso negado"])

        result = resolve_order_vendor(order_id, "ESCOLINHA DOUGLAS AMÉRICA", index=broken_index, vendedores=self.vendedores)
        self.assertTrue(result.source_unavailable)
        self.assertEqual(result.state, RESOLUTION_NOT_FOUND)
        # O vínculo anterior (auto) é preservado, não apagado, mesmo com a raiz indisponível.
        self.assertIsNotNone(result.link)
        self.assertEqual(result.link["vendor_key"], "evandro")

    def test_source_unavailable_not_flagged_by_unrelated_vendor_with_prefix_path(self):
        """Achado de revisão: _vendor_root_unavailable não pode usar
        startswith() puro no caminho — a raiz de um vendedor pode ser
        prefixo de string da raiz de outro (ex.: ".../_Evandro" e
        ".../_EvandroNovo"), e um erro de acesso na segunda nunca deveria
        marcar a primeira como indisponível."""
        order_id = self._make_order("0001", "ESCOLINHA DOUGLAS AMÉRICA")
        resolve_order_vendor(order_id, "ESCOLINHA DOUGLAS AMÉRICA", index=self.index, vendedores=self.vendedores)

        outro_root = Path(f"{self.evandro_root}Novo")
        outro_root.mkdir(parents=True)

        from core.order_files import VendorIndexState
        broken_index = VendorIndexState(generated_at="", folders=[], errors=[f"{outro_root}: acesso negado"])

        result = resolve_order_vendor(order_id, "ESCOLINHA DOUGLAS AMÉRICA", index=broken_index, vendedores=self.vendedores)
        self.assertFalse(result.source_unavailable)

    def test_source_unavailable_flagged_regardless_of_path_casing(self):
        """Achado de revisão: caminho de pasta no Windows é
        case-insensitive — um erro reportado com uma caixa diferente da
        cadastrada (ex.: letra de unidade minúscula) ainda deve marcar o
        vendedor como indisponível."""
        order_id = self._make_order("0001", "ESCOLINHA DOUGLAS AMÉRICA")
        resolve_order_vendor(order_id, "ESCOLINHA DOUGLAS AMÉRICA", index=self.index, vendedores=self.vendedores)

        from core.order_files import VendorIndexState
        broken_index = VendorIndexState(
            generated_at="", folders=[], errors=[f"{str(self.evandro_root).upper()}: acesso negado"],
        )

        result = resolve_order_vendor(order_id, "ESCOLINHA DOUGLAS AMÉRICA", index=broken_index, vendedores=self.vendedores)
        self.assertTrue(result.source_unavailable)


class GuessVendorNameForPedidoTests(unittest.TestCase):
    """Pré-visualização somente leitura (sem order_id) usada no comprovante
    Prisma (ver modules/operacao/exporters.py:_build_prisma_report_data) —
    mesmo índice/pastas temporárias de OrderVendorResolutionTests.setUp,
    mas nunca lê nem grava vínculo nenhum."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._db_patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._db_patcher.start()

        self._folders_dir = Path(self._tmp_dir.name) / "folders"
        self.evandro_root = self._folders_dir / "_Evandro"
        (self.evandro_root / "ESCOLINHA DOUGLAS AMÉRICA" / "ESCOLINHA DOUGLAS AMÉRICA").mkdir(parents=True)
        vendedores = add_or_update_vendedor([], name="Evandro")
        self.vendedores = add_vendedor_folder(vendedores, "evandro", str(self.evandro_root))
        self.index = build_order_index(self.vendedores)

    def tearDown(self):
        self._db_patcher.stop()
        self._tmp_dir.cleanup()

    def _make_order(self, suffix: str, pedido: str) -> int:
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name=f"M1-{suffix}", export_mode="normal", app_version="1.0.0",
            orders=[_order(f"doc{suffix}.jpeg", pedido)],
        )
        return int(get_roll_orders(roll_id)[0]["id"])

    def test_single_exact_match_returns_vendor_name(self):
        name = guess_vendor_name_for_pedido("ESCOLINHA DOUGLAS AMÉRICA", index=self.index)
        self.assertEqual(name, "Evandro")

    def test_no_match_returns_empty_string(self):
        self.assertEqual(guess_vendor_name_for_pedido("Pedido Inexistente", index=self.index), "")

    def test_ambiguous_match_returns_empty_string(self):
        other_root = self._folders_dir / "_OutroVendedor"
        (other_root / "ESCOLINHA DOUGLAS AMÉRICA" / "ESCOLINHA DOUGLAS AMÉRICA").mkdir(parents=True)
        vendedores = add_or_update_vendedor(self.vendedores, name="Outro Vendedor")
        vendedores = add_vendedor_folder(vendedores, "outro_vendedor", str(other_root))
        index = build_order_index(vendedores)

        self.assertEqual(guess_vendor_name_for_pedido("ESCOLINHA DOUGLAS AMÉRICA", index=index), "")

    def test_never_reads_or_writes_any_link(self):
        order_id = self._make_order("0001", "ESCOLINHA DOUGLAS AMÉRICA")
        confirm_order_vendor(order_id, "manual_key", "Vendedor Manual")

        # A pré-visualização ignora completamente o order_id/vínculo — usa
        # só o índice de pastas, nunca lê core.printlogs_db.
        name = guess_vendor_name_for_pedido("ESCOLINHA DOUGLAS AMÉRICA", index=self.index)
        self.assertEqual(name, "Evandro")  # não "Vendedor Manual"

        history = get_vendor_link_history(order_id)
        self.assertEqual(len(history), 1)  # só a confirmação manual acima, nada criado pela pré-visualização


class PreviewOrderVendorTests(unittest.TestCase):
    """`preview_order_vendor` (Parte 1 — painel de Operação, antes do rolo
    ser salvo): mesma prioridade de resolve_order_vendor, mas sem
    order_id e sem nenhum efeito colateral no banco."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._folders_dir = Path(self._tmp_dir.name) / "folders"
        self.evandro_root = self._folders_dir / "_Evandro"
        (self.evandro_root / "ESCOLINHA DOUGLAS AMÉRICA" / "ESCOLINHA DOUGLAS AMÉRICA").mkdir(parents=True)
        vendedores = add_or_update_vendedor([], name="Evandro")
        self.vendedores = add_vendedor_folder(vendedores, "evandro", str(self.evandro_root))
        self.index = build_order_index(self.vendedores)

    def tearDown(self):
        self._tmp_dir.cleanup()

    def test_single_exact_match_is_auto(self):
        result = preview_order_vendor("ESCOLINHA DOUGLAS AMÉRICA", index=self.index)
        self.assertEqual(result.state, RESOLUTION_AUTO)
        self.assertEqual(result.vendor_key, "evandro")
        self.assertEqual(result.vendor_name, "Evandro")
        self.assertEqual(len(result.candidates), 1)

    def test_no_match_is_not_found(self):
        result = preview_order_vendor("Pedido Inexistente", index=self.index)
        self.assertEqual(result.state, RESOLUTION_NOT_FOUND)
        self.assertEqual(result.vendor_key, "")

    def test_ambiguous_match_lists_all_candidates(self):
        other_root = self._folders_dir / "_OutroVendedor"
        (other_root / "ESCOLINHA DOUGLAS AMÉRICA" / "ESCOLINHA DOUGLAS AMÉRICA").mkdir(parents=True)
        vendedores = add_or_update_vendedor(self.vendedores, name="Outro Vendedor")
        vendedores = add_vendedor_folder(vendedores, "outro_vendedor", str(other_root))
        index = build_order_index(vendedores)

        result = preview_order_vendor("ESCOLINHA DOUGLAS AMÉRICA", index=index)
        self.assertEqual(result.state, RESOLUTION_AMBIGUOUS)
        self.assertEqual(result.vendor_key, "")
        self.assertEqual(len(result.candidates), 2)

    def test_never_touches_the_database(self):
        # Nenhum patch de core.printlogs_db.get_db_path nesta classe —
        # se preview_order_vendor tentasse ler/gravar algo, o teste
        # quebraria tentando acessar o banco real da instalação.
        preview_order_vendor("ESCOLINHA DOUGLAS AMÉRICA", index=self.index)
        preview_order_vendor("Pedido Inexistente", index=self.index)


if __name__ == "__main__":
    unittest.main()
