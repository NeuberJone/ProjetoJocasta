"""Testes de core.printlogs_db.compute_machine_metrics — item de roadmap
(Fase 2) "definir métricas verificáveis de metragem, duração, espaços e
produção por máquina, com rastreabilidade até os registros de origem". Usa
um banco SQLite temporário isolado (nunca o banco real do usuário), mesmo
padrão de test_find_pedido_fabric_rolls.py.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import OrderRow, compute_machine_metrics, save_export_transactional


def _order(
    document: str = "doc.jpg",
    real_m: float = 10.0,
    tipo: str = "Pedido",
    start_time: str = "",
    end_time: str = "2026-11-05T10:00:00",
) -> OrderRow:
    return OrderRow(
        end_time=end_time,
        document=document,
        fabric="DRYFIT",
        pedido="Cliente A",
        height_mm=real_m * 1000.0,
        vpos_mm=0.0,
        real_m=real_m,
        source_path=f"/x/{document}",
        tipo=tipo,
        start_time=start_time,
    )


class ComputeMachineMetricsTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def _save(self, module: str, machine: str, orders, roll_name: str = None):
        roll_name = roll_name or f"{machine}-{module}"
        return save_export_transactional(
            machine=machine, roll_name=roll_name, export_mode="normal", app_version="1.0.0",
            orders=orders, event_payload={"module": module},
        )

    def _set_created_at(self, roll_id: int, created_at: str) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("UPDATE rolls SET created_at = ? WHERE id = ?", (created_at, roll_id))
            con.commit()
        finally:
            con.close()

    def test_empty_database_returns_empty_dict(self):
        self.assertEqual(compute_machine_metrics(), {})

    def test_real_item_counts_as_produced_m_and_order(self):
        self._save("Operacao", "M1", [_order(real_m=10.0)])
        metrics = compute_machine_metrics()["M1"]
        self.assertAlmostEqual(metrics["produced_m"], 10.0)
        self.assertEqual(metrics["order_count"], 1)
        self.assertAlmostEqual(metrics["gap_m"], 0.0)
        self.assertEqual(metrics["gap_count"], 0)

    def test_item_with_empty_tipo_counts_as_gap_not_production(self):
        self._save("Operacao", "M1", [_order(document="espaco.jpg", real_m=2.0, tipo="")])
        metrics = compute_machine_metrics()["M1"]
        self.assertAlmostEqual(metrics["gap_m"], 2.0)
        self.assertEqual(metrics["gap_count"], 1)
        self.assertAlmostEqual(metrics["produced_m"], 0.0)
        self.assertEqual(metrics["order_count"], 0)

    def test_duration_minutes_summed_only_for_rows_with_start_time(self):
        self._save("Operacao", "M1", [
            _order(document="a.jpg", start_time="2026-11-05T10:00:00", end_time="2026-11-05T10:05:00"),
            _order(document="b.jpg", start_time="", end_time="2026-11-05T11:00:00"),
        ])
        metrics = compute_machine_metrics()["M1"]
        self.assertAlmostEqual(metrics["duration_minutes"], 5.0)
        self.assertEqual(metrics["timed_order_count"], 1)
        # A segunda order (sem start_time) ainda conta como produção — só
        # não entra na duração.
        self.assertEqual(metrics["order_count"], 2)

    def test_negative_or_zero_duration_is_never_counted(self):
        self._save("Operacao", "M1", [
            _order(document="a.jpg", start_time="2026-11-05T10:10:00", end_time="2026-11-05T10:00:00"),
        ])
        metrics = compute_machine_metrics()["M1"]
        self.assertAlmostEqual(metrics["duration_minutes"], 0.0)
        self.assertEqual(metrics["timed_order_count"], 0)

    def test_planejador_rolls_are_excluded_entirely(self):
        self._save("Planejador", "M1", [_order(real_m=99.0)])
        self.assertEqual(compute_machine_metrics(), {})

    def test_legacy_pre_rebrand_pxprintlogs_rolls_count_as_operacao(self):
        """Achado real no banco de produção: rolo exportado antes do
        rebrand pra Nexor grava payload["module"] = "PXPrintLogs", não
        "Operacao" — sem reconhecer isso, 16 rolos reais sumiam das
        métricas por máquina."""
        self._save("PXPrintLogs", "M1", [_order(real_m=10.0)])
        metrics = compute_machine_metrics()["M1"]
        self.assertAlmostEqual(metrics["produced_m"], 10.0)

    def test_legacy_pre_rebrand_pxprintcalc_rolls_are_excluded_entirely(self):
        self._save("PXPrintCalc", "M1", [_order(real_m=99.0)])
        self.assertEqual(compute_machine_metrics(), {})

    def test_different_machines_are_kept_separate(self):
        self._save("Operacao", "M1", [_order(real_m=10.0)])
        self._save("Operacao", "M2", [_order(real_m=20.0)])
        metrics = compute_machine_metrics()
        self.assertAlmostEqual(metrics["M1"]["produced_m"], 10.0)
        self.assertAlmostEqual(metrics["M2"]["produced_m"], 20.0)

    def test_roll_count_counts_distinct_rolls_contributing(self):
        self._save("Operacao", "M1", [_order(document="a.jpg")], roll_name="M1-0001")
        self._save("Operacao", "M1", [_order(document="b.jpg")], roll_name="M1-0002")
        metrics = compute_machine_metrics()["M1"]
        self.assertEqual(metrics["roll_count"], 2)

    def test_date_range_filters_by_created_at(self):
        roll_old, _ = self._save("Operacao", "M1", [_order(document="old.jpg", real_m=5.0)])
        roll_new, _ = self._save("Operacao", "M1", [_order(document="new.jpg", real_m=7.0)])
        self._set_created_at(roll_old, "2026-01-01T00:00:00")
        self._set_created_at(roll_new, "2026-11-05T00:00:00")

        metrics = compute_machine_metrics(date_from="2026-11-01")["M1"]
        self.assertAlmostEqual(metrics["produced_m"], 7.0)

        metrics = compute_machine_metrics(date_to="2026-01-31")["M1"]
        self.assertAlmostEqual(metrics["produced_m"], 5.0)

    def test_date_to_without_time_still_includes_the_whole_end_date(self):
        """Achado de revisão de código: `date_to` é documentado como
        inclusivo, mas a comparação de string pura ("<= date_to") excluía o
        dia inteiro quando passado sem hora — created_at sempre tem hora
        (ex.: "2026-11-22T14:03:05"), e essa string é MAIOR que a data
        sozinha ("2026-11-22") na ordem lexicográfica, então nada daquele
        dia batia com "<=" apesar do docstring prometer inclusão."""
        roll_id, _ = self._save("Operacao", "M1", [_order(real_m=9.0)])
        self._set_created_at(roll_id, "2026-11-22T14:03:05")

        metrics = compute_machine_metrics(date_to="2026-11-22")["M1"]
        self.assertAlmostEqual(metrics["produced_m"], 9.0)


if __name__ == "__main__":
    unittest.main()
