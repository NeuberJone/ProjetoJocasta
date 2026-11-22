"""Testes de core.printlogs_db.find_orders_by_source_path — base para a
importação incremental/idempotente (mesmo arquivo físico reimportado em uma
sessão/rolo diferente). Usa um banco SQLite temporário isolado (nunca o
banco real do usuário), mesmo padrão de test_find_pedido_fabric_rolls.py.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import OrderRow, find_orders_by_source_path, save_export_transactional


def _order(document: str, source_path: str, end_time: str = "2026-11-05T10:00:00", height_mm: float = 1000.0) -> OrderRow:
    return OrderRow(
        end_time=end_time,
        document=document,
        fabric="DRYFIT",
        pedido="Cliente A",
        height_mm=height_mm,
        vpos_mm=0.0,
        real_m=1.0,
        source_path=source_path,
        tipo="Pedido",
    )


class FindOrdersBySourcePathTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def test_empty_paths_returns_empty_without_touching_the_database(self):
        self.assertEqual(find_orders_by_source_path([]), {})

    def test_unknown_path_is_absent_from_result(self):
        self.assertEqual(find_orders_by_source_path(["/x/never-imported.txt"]), {})

    def test_known_path_returns_roll_and_job_hash(self):
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpg", "/x/doc1.jpg.txt")],
        )
        result = find_orders_by_source_path(["/x/doc1.jpg.txt"])
        self.assertIn("/x/doc1.jpg.txt", result)
        self.assertEqual(result["/x/doc1.jpg.txt"]["roll_id"], roll_id)
        self.assertEqual(result["/x/doc1.jpg.txt"]["roll_name"], "M1-0001")

    def test_only_requested_paths_among_many_saved_orders_are_returned(self):
        save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpg", "/x/doc1.jpg.txt"), _order("doc2.jpg", "/x/doc2.jpg.txt")],
        )
        result = find_orders_by_source_path(["/x/doc1.jpg.txt"])
        self.assertEqual(set(result.keys()), {"/x/doc1.jpg.txt"})

    def test_most_recent_roll_wins_when_the_same_path_was_saved_more_than_once(self):
        save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpg", "/x/doc1.jpg.txt", end_time="2026-11-05T10:00:00")],
        )
        roll_b, _ = save_export_transactional(
            machine="M1", roll_name="M1-0002", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpg", "/x/doc1.jpg.txt", end_time="2026-11-06T10:00:00")],
        )
        result = find_orders_by_source_path(["/x/doc1.jpg.txt"])
        self.assertEqual(result["/x/doc1.jpg.txt"]["roll_id"], roll_b)

    def test_test_roll_is_never_returned_as_history(self):
        save_export_transactional(
            machine="M1", roll_name="M1-0001_TESTE", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpg", "/x/doc1.jpg.txt")],
        )
        self.assertEqual(find_orders_by_source_path(["/x/doc1.jpg.txt"]), {})

    def test_batches_larger_than_sqlite_limit_are_still_all_checked(self):
        many_paths = [f"/x/doc{i}.jpg.txt" for i in range(900)]
        orders = [_order(f"doc{i}.jpg", path) for i, path in enumerate(many_paths)]
        save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=orders,
        )
        result = find_orders_by_source_path(many_paths)
        self.assertEqual(len(result), len(many_paths))


if __name__ == "__main__":
    unittest.main()
