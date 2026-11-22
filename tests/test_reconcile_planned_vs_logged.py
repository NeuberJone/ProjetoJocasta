"""Testes de core.printlogs_db.reconcile_planned_vs_logged — primeiro passo
do item de roadmap (Fase 2) "reconciliar o que foi planejado, registrado nos
logs e confirmado na operação". Usa um banco SQLite temporário isolado
(nunca o banco real do usuário), mesmo padrão de
test_find_pedido_fabric_rolls.py.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import OrderRow, reconcile_planned_vs_logged, save_export_transactional


def _order(pedido: str, fabric: str, real_m: float, document: str = "doc.jpg") -> OrderRow:
    return OrderRow(
        end_time="2026-11-05T10:00:00",
        document=document,
        fabric=fabric,
        pedido=pedido,
        height_mm=real_m * 1000.0,
        vpos_mm=0.0,
        real_m=real_m,
        source_path=f"/x/{document}",
        tipo="Pedido",
    )


class ReconcilePlannedVsLoggedTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def _save(self, module: str, pedido: str, fabric: str, real_m: float, machine: str = "M1", roll_name: str = None):
        roll_name = roll_name or f"{machine}-{module}"
        return save_export_transactional(
            machine=machine,
            roll_name=roll_name,
            export_mode="normal",
            app_version="1.0.0",
            orders=[_order(pedido, fabric, real_m)],
            event_payload={"module": module},
        )

    def test_matching_pair_reports_both_sides_and_the_delta(self):
        self._save("Planejador", "Cliente A", "DRYFIT", 10.0)
        self._save("Operacao", "Cliente A", "DRYFIT", 9.5)

        result = reconcile_planned_vs_logged([("Cliente A", "DRYFIT")])
        entry = result[("Cliente A", "DRYFIT")]
        self.assertAlmostEqual(entry["planned_m"], 10.0)
        self.assertAlmostEqual(entry["logged_m"], 9.5)
        self.assertAlmostEqual(entry["delta_m"], -0.5)
        self.assertEqual(len(entry["planned_rolls"]), 1)
        self.assertEqual(len(entry["logged_rolls"]), 1)

    def test_planned_only_has_zero_logged_and_empty_logged_rolls(self):
        self._save("Planejador", "Cliente A", "DRYFIT", 10.0)

        result = reconcile_planned_vs_logged([("Cliente A", "DRYFIT")])
        entry = result[("Cliente A", "DRYFIT")]
        self.assertAlmostEqual(entry["planned_m"], 10.0)
        self.assertAlmostEqual(entry["logged_m"], 0.0)
        self.assertEqual(entry["logged_rolls"], [])

    def test_logged_only_has_zero_planned_and_empty_planned_rolls(self):
        self._save("Operacao", "Cliente A", "DRYFIT", 9.5)

        result = reconcile_planned_vs_logged([("Cliente A", "DRYFIT")])
        entry = result[("Cliente A", "DRYFIT")]
        self.assertAlmostEqual(entry["logged_m"], 9.5)
        self.assertAlmostEqual(entry["planned_m"], 0.0)
        self.assertEqual(entry["planned_rolls"], [])

    def test_roll_with_no_module_in_payload_counts_on_neither_side(self):
        save_export_transactional(
            machine="M1", roll_name="M1-sem-modulo", export_mode="normal", app_version="1.0.0",
            orders=[_order("Cliente A", "DRYFIT", 10.0)],
            event_payload={},  # sem "module" — versão anterior a esse campo existir
        )

        result = reconcile_planned_vs_logged([("Cliente A", "DRYFIT")])
        self.assertEqual(result, {})

    def test_pair_with_no_production_anywhere_is_absent_from_result(self):
        result = reconcile_planned_vs_logged([("Ninguem", "NADA")])
        self.assertEqual(result, {})

    def test_pairs_none_discovers_every_pair_with_production(self):
        self._save("Planejador", "Cliente A", "DRYFIT", 10.0)
        self._save("Operacao", "Cliente B", "RIBANA", 5.0)

        result = reconcile_planned_vs_logged()
        self.assertEqual(set(result.keys()), {("Cliente A", "DRYFIT"), ("Cliente B", "RIBANA")})

    def test_explicit_pairs_restrict_to_requested_subset(self):
        self._save("Planejador", "Cliente A", "DRYFIT", 10.0)
        self._save("Operacao", "Cliente B", "RIBANA", 5.0)

        result = reconcile_planned_vs_logged([("Cliente A", "DRYFIT")])
        self.assertEqual(set(result.keys()), {("Cliente A", "DRYFIT")})

    def test_legacy_pre_rebrand_module_names_count_on_the_right_side(self):
        """Achado real no banco de produção: rolo exportado antes do
        rebrand pra Nexor grava payload["module"] = "PXPrintCalc"
        (Planejador) ou "PXPrintLogs" (Operação), não o nome novo — sem
        reconhecer isso, esses rolos sumiam dos dois lados da reconciliação
        (27 "PXPrintCalc" e 16 "PXPrintLogs" no banco real conferido)."""
        self._save("PXPrintCalc", "Cliente A", "DRYFIT", 10.0)
        self._save("PXPrintLogs", "Cliente A", "DRYFIT", 9.5)

        result = reconcile_planned_vs_logged([("Cliente A", "DRYFIT")])
        entry = result[("Cliente A", "DRYFIT")]
        self.assertAlmostEqual(entry["planned_m"], 10.0)
        self.assertAlmostEqual(entry["logged_m"], 9.5)
        self.assertEqual(len(entry["planned_rolls"]), 1)
        self.assertEqual(len(entry["logged_rolls"]), 1)

    def test_multiple_rolls_on_the_same_side_are_summed(self):
        self._save("Planejador", "Cliente A", "DRYFIT", 10.0, roll_name="M1-0001")
        self._save("Planejador", "Cliente A", "DRYFIT", 3.0, roll_name="M1-0002")

        result = reconcile_planned_vs_logged([("Cliente A", "DRYFIT")])
        entry = result[("Cliente A", "DRYFIT")]
        self.assertAlmostEqual(entry["planned_m"], 13.0)
        self.assertEqual(len(entry["planned_rolls"]), 2)


if __name__ == "__main__":
    unittest.main()
