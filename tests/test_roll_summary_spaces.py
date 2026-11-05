"""Teste de core.printlogs_db.get_roll_summary para orders de ESPAÇO
(tipo="") de rolos da Operação — confirma que, uma vez que um avanço
chega a virar order (ver modules/operacao/ui.py on_export, que antes
excluía is_gap da lista salva), ele aparece na lista "spaces" do resumo,
separado do agrupamento por tecido, exatamente como o comentário real de
get_roll_summary já descrevia. Usa um banco SQLite temporário isolado
(nunca o banco real do usuário).
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import OrderRow, get_roll_summary, save_export_transactional


def _job_order(document: str, fabric: str, end_time: str) -> OrderRow:
    return OrderRow(
        end_time=end_time, document=document, fabric=fabric, pedido="Cliente A",
        height_mm=1000.0, vpos_mm=0.0, real_m=1.0, source_path=f"/x/{document}",
        tipo="Pedido",
    )


def _gap_order(document: str, end_time: str, real_m: float = 0.5) -> OrderRow:
    return OrderRow(
        end_time=end_time, document=document, fabric="ESPAÇO", pedido="ESPAÇO",
        height_mm=real_m * 1000.0, vpos_mm=0.0, real_m=real_m, source_path=f"/x/{document}",
        tipo="",
    )


class RollSummarySpacesTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def test_gap_orders_show_up_as_spaces_separate_from_fabric_grouping(self):
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[
                _job_order("doc1.jpg", "DRYFIT", "2026-11-05T10:00:00"),
                _gap_order("doc1.jpg (avanço)", "2026-11-05T09:59:00"),
                _job_order("doc2.jpg", "DRYFIT", "2026-11-05T09:58:00"),
            ],
            event_payload={"module": "Operacao"},
        )

        summary = get_roll_summary(roll_id)

        fabrics = {f["fabric"] for f in summary["fabrics"]}
        self.assertEqual(fabrics, {"DRYFIT"})
        self.assertEqual(summary["orders_count"], 3)

        spaces = summary["spaces"]
        self.assertEqual(len(spaces), 1)
        self.assertEqual(spaces[0]["fabric"], "ESPAÇO")
        self.assertAlmostEqual(spaces[0]["real_m"], 0.5)


if __name__ == "__main__":
    unittest.main()
