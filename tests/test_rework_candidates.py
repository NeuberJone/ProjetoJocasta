"""Testes de core.printlogs_db.list_rework_candidates — item de roadmap
(Fase 3) "acompanhar retrabalho de forma explícita, distinguindo-o da
impressão original nas consultas e métricas". Decisões confirmadas com o
usuário: critério é mesmo (pedido, tecido) em rolos DIFERENTES da Operação
(não o nome do arquivo); é só um relatório novo, nunca muda nenhuma
métrica existente. Usa um banco SQLite temporário isolado (nunca o banco
real do usuário), mesmo padrão de test_reconcile_planned_vs_logged.py.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import OrderRow, list_rework_candidates, save_export_transactional


def _order(
    pedido: str, fabric: str, real_m: float, end_time: str, document: str = "doc.jpg"
) -> OrderRow:
    return OrderRow(
        end_time=end_time, document=document, fabric=fabric, pedido=pedido,
        height_mm=real_m * 1000.0, vpos_mm=0.0, real_m=real_m, source_path=f"/x/{document}",
        tipo="Pedido",
    )


class RewordCandidatesTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def _save(self, module: str, roll_name: str, orders) -> int:
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name=roll_name, export_mode="normal", app_version="1.0.0",
            orders=orders, event_payload={"module": module},
        )
        return roll_id

    def test_same_pedido_fabric_in_two_operacao_rolls_is_a_rework_candidate(self):
        original_roll = self._save(
            "Operacao", "M1-0001", [_order("Cliente A", "DRYFIT", 5.0, "2026-11-01T10:00:00")]
        )
        rework_roll = self._save(
            "Operacao", "M1-0002", [_order("Cliente A", "DRYFIT", 4.8, "2026-11-05T10:00:00")]
        )

        candidates = list_rework_candidates()
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c["pedido"], "Cliente A")
        self.assertEqual(c["fabric"], "DRYFIT")
        self.assertEqual(c["original_roll_id"], original_roll)
        self.assertEqual(c["rework_roll_id"], rework_roll)
        self.assertAlmostEqual(c["original_real_m"], 5.0)
        self.assertAlmostEqual(c["rework_real_m"], 4.8)

    def test_same_pedido_fabric_in_a_single_roll_is_not_a_rework_candidate(self):
        self._save(
            "Operacao", "M1-0001",
            [
                _order("Cliente A", "DRYFIT", 5.0, "2026-11-01T10:00:00", document="a.jpg"),
                _order("Cliente A", "DRYFIT", 3.0, "2026-11-01T10:05:00", document="b.jpg"),
            ],
        )

        self.assertEqual(list_rework_candidates(), [])

    def test_earliest_end_time_is_always_the_original_regardless_of_roll_order(self):
        # Rolo com o end_time mais antigo salvo DEPOIS — original ainda é
        # identificado pelo horário, não pela ordem de inserção no banco.
        later_roll = self._save(
            "Operacao", "M1-0002", [_order("Cliente B", "RIBANA", 2.0, "2026-11-10T10:00:00")]
        )
        earlier_roll = self._save(
            "Operacao", "M1-0001", [_order("Cliente B", "RIBANA", 2.0, "2026-11-01T10:00:00")]
        )

        candidates = list_rework_candidates()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["original_roll_id"], earlier_roll)
        self.assertEqual(candidates[0]["rework_roll_id"], later_roll)

    def test_two_reworks_of_the_same_original_each_get_their_own_row(self):
        original_roll = self._save(
            "Operacao", "M1-0001", [_order("Cliente C", "OXFORD", 3.0, "2026-11-01T10:00:00")]
        )
        rework1 = self._save(
            "Operacao", "M1-0002", [_order("Cliente C", "OXFORD", 2.9, "2026-11-02T10:00:00")]
        )
        rework2 = self._save(
            "Operacao", "M1-0003", [_order("Cliente C", "OXFORD", 3.1, "2026-11-03T10:00:00")]
        )

        candidates = list_rework_candidates()
        self.assertEqual(len(candidates), 2)
        rework_ids = {c["rework_roll_id"] for c in candidates}
        self.assertEqual(rework_ids, {rework1, rework2})
        self.assertTrue(all(c["original_roll_id"] == original_roll for c in candidates))

    def test_planejador_rolls_are_never_counted_as_rework_or_original(self):
        self._save(
            "Planejador", "M1-Plan", [_order("Cliente D", "RIBANA", 5.0, "2026-11-01T10:00:00")]
        )
        self._save(
            "Planejador", "M1-Plan2", [_order("Cliente D", "RIBANA", 5.0, "2026-11-05T10:00:00")]
        )

        self.assertEqual(list_rework_candidates(), [])

    def test_legacy_pxprintlogs_module_name_still_counts(self):
        self._save(
            "PXPrintLogs", "M1-0001", [_order("Cliente E", "DRYFIT", 5.0, "2026-11-01T10:00:00")]
        )
        self._save(
            "PXPrintLogs", "M1-0002", [_order("Cliente E", "DRYFIT", 5.0, "2026-11-05T10:00:00")]
        )

        candidates = list_rework_candidates()
        self.assertEqual(len(candidates), 1)

    def test_different_pedido_or_fabric_never_matches_as_rework(self):
        self._save(
            "Operacao", "M1-0001", [_order("Cliente F", "DRYFIT", 5.0, "2026-11-01T10:00:00")]
        )
        self._save(
            "Operacao", "M1-0002", [_order("Cliente F", "RIBANA", 5.0, "2026-11-02T10:00:00")]
        )
        self._save(
            "Operacao", "M1-0003", [_order("Cliente G", "DRYFIT", 5.0, "2026-11-03T10:00:00")]
        )

        self.assertEqual(list_rework_candidates(), [])


if __name__ == "__main__":
    unittest.main()
