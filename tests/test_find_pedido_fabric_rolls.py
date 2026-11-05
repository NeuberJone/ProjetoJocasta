"""Testes de core.printlogs_db.find_pedido_fabric_rolls — detecção de
duplicidade de pedido+tecido ENTRE rolos diferentes. Usa um banco SQLite
temporário isolado (nunca o banco real do usuário).

Cenário real que motivou o parâmetro exclude_roll_id: ao fechar um rolo
pela segunda vez na mesma sessão (depois de importar mais logs), ou ao
reabrir um rolo já salvo ("Atualizar Rolo"), o rolo sendo salvo contém os
MESMOS itens que já estão gravados nele mesmo no banco — sem excluir o
próprio roll_id, isso aparecia como "duplicidade entre rolos" contra ele
mesmo, quando na verdade é o mesmo rolo.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import OrderRow, find_pedido_fabric_rolls, save_export_transactional


def _order(pedido: str, fabric: str, end_time: str, document: str) -> OrderRow:
    return OrderRow(
        end_time=end_time,
        document=document,
        fabric=fabric,
        pedido=pedido,
        height_mm=1000.0,
        vpos_mm=0.0,
        real_m=1.0,
        source_path=f"/x/{document}",
        tipo="Pedido",
    )


class FindPedidoFabricRollsTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def test_same_pedido_fabric_in_two_different_rolls_is_a_real_duplicate(self):
        roll_a, _ = save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("Cliente A", "DRYFIT", "2026-11-05T10:00:00", "doc1.jpg")],
        )
        roll_b, _ = save_export_transactional(
            machine="M1", roll_name="M1-0002", export_mode="normal", app_version="1.0.0",
            orders=[_order("Cliente A", "DRYFIT", "2026-11-05T11:00:00", "doc2.jpg")],
        )

        matches = find_pedido_fabric_rolls([("Cliente A", "DRYFIT")])
        self.assertIn(("Cliente A", "DRYFIT"), matches)
        found_roll_ids = {r["roll_id"] for r in matches[("Cliente A", "DRYFIT")]}
        self.assertEqual(found_roll_ids, {roll_a, roll_b})

    def test_exclude_roll_id_removes_self_match_when_closing_the_same_roll_again(self):
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("Cliente A", "DRYFIT", "2026-11-05T10:00:00", "doc1.jpg")],
        )

        # Fechar de novo o MESMO rolo (mais itens importados) reenvia o
        # mesmo par pedido+tecido — sem exclude_roll_id, bateria contra ele
        # mesmo.
        matches_without_exclude = find_pedido_fabric_rolls([("Cliente A", "DRYFIT")])
        self.assertIn(("Cliente A", "DRYFIT"), matches_without_exclude)

        matches_with_exclude = find_pedido_fabric_rolls(
            [("Cliente A", "DRYFIT")], exclude_roll_id=roll_id
        )
        self.assertEqual(matches_with_exclude, {})

    def test_exclude_roll_id_keeps_real_duplicates_from_other_rolls(self):
        roll_a, _ = save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("Cliente A", "DRYFIT", "2026-11-05T10:00:00", "doc1.jpg")],
        )
        roll_b, _ = save_export_transactional(
            machine="M1", roll_name="M1-0002", export_mode="normal", app_version="1.0.0",
            orders=[_order("Cliente A", "DRYFIT", "2026-11-05T11:00:00", "doc2.jpg")],
        )

        matches = find_pedido_fabric_rolls([("Cliente A", "DRYFIT")], exclude_roll_id=roll_a)
        found_roll_ids = {r["roll_id"] for r in matches[("Cliente A", "DRYFIT")]}
        self.assertEqual(found_roll_ids, {roll_b})


if __name__ == "__main__":
    unittest.main()
