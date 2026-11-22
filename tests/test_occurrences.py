"""Testes de core.printlogs_db para "Registrar ocorrências operacionais"
(roadmap Fase 3) — create_occurrence/add_occurrence_entry/
list_occurrences_for_roll/get_occurrence_history. Decisão confirmada com o
usuário: ocorrência é vinculada ao ROLO inteiro (não a um pedido/item
específico). Usa um banco SQLite temporário isolado (nunca o banco real do
usuário), mesmo padrão de test_reconcile_planned_vs_logged.py.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import (
    OCCURRENCE_STATUS_OPEN,
    OCCURRENCE_STATUS_RESOLVED,
    OrderRow,
    add_occurrence_entry,
    create_occurrence,
    get_occurrence_history,
    list_occurrences_for_roll,
    save_export_transactional,
)


def _order(document: str = "doc.jpg") -> OrderRow:
    return OrderRow(
        end_time="2026-11-19T10:00:00", document=document, fabric="DRYFIT", pedido="Cliente A",
        height_mm=1000.0, vpos_mm=0.0, real_m=1.0, source_path=f"/x/{document}", tipo="Pedido",
    )


class OccurrencesTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._patcher.start()

        self.roll_id, _ = save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order()],
        )

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def test_create_occurrence_appears_in_the_roll_list_with_its_first_entry(self):
        occurrence_id = create_occurrence(self.roll_id, "Máquina travou no meio do rolo")

        rows = list_occurrences_for_roll(self.roll_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["occurrence_id"], occurrence_id)
        self.assertEqual(rows[0]["description"], "Máquina travou no meio do rolo")
        self.assertEqual(rows[0]["status"], OCCURRENCE_STATUS_OPEN)

    def test_create_occurrence_rejects_empty_description(self):
        with self.assertRaises(ValueError):
            create_occurrence(self.roll_id, "   ")

    def test_create_occurrence_rejects_invalid_status(self):
        with self.assertRaises(ValueError):
            create_occurrence(self.roll_id, "Algo", status="Inventado")

    def test_add_entry_never_overwrites_the_previous_one(self):
        occurrence_id = create_occurrence(self.roll_id, "Tecido rasgado")
        add_occurrence_entry(occurrence_id, "Tecido rasgado - trocado o rolo", OCCURRENCE_STATUS_RESOLVED)

        history = get_occurrence_history(occurrence_id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["description"], "Tecido rasgado")
        self.assertEqual(history[0]["status"], OCCURRENCE_STATUS_OPEN)
        self.assertEqual(history[1]["description"], "Tecido rasgado - trocado o rolo")
        self.assertEqual(history[1]["status"], OCCURRENCE_STATUS_RESOLVED)

    def test_list_shows_the_most_recent_entry_as_current_state(self):
        occurrence_id = create_occurrence(self.roll_id, "Erro de impressão")
        add_occurrence_entry(occurrence_id, "Erro de impressão - resolvido reiniciando", OCCURRENCE_STATUS_RESOLVED)

        rows = list_occurrences_for_roll(self.roll_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "Erro de impressão - resolvido reiniciando")
        self.assertEqual(rows[0]["status"], OCCURRENCE_STATUS_RESOLVED)

    def test_add_entry_to_nonexistent_occurrence_raises(self):
        with self.assertRaises(ValueError):
            add_occurrence_entry(999, "Algo", OCCURRENCE_STATUS_OPEN)

    def test_multiple_occurrences_on_the_same_roll_are_independent(self):
        first = create_occurrence(self.roll_id, "Primeira ocorrência")
        second = create_occurrence(self.roll_id, "Segunda ocorrência")
        add_occurrence_entry(first, "Primeira ocorrência - resolvida", OCCURRENCE_STATUS_RESOLVED)

        rows = list_occurrences_for_roll(self.roll_id)
        by_id = {r["occurrence_id"]: r for r in rows}
        self.assertEqual(len(rows), 2)
        self.assertEqual(by_id[first]["status"], OCCURRENCE_STATUS_RESOLVED)
        self.assertEqual(by_id[second]["status"], OCCURRENCE_STATUS_OPEN)
        self.assertEqual(len(get_occurrence_history(second)), 1)

    def test_occurrences_from_a_different_roll_are_not_listed(self):
        other_roll_id, _ = save_export_transactional(
            machine="M1", roll_name="M1-0002", export_mode="normal", app_version="1.0.0",
            orders=[_order(document="doc2.jpg")],
        )
        create_occurrence(other_roll_id, "Ocorrência de outro rolo")

        self.assertEqual(list_occurrences_for_roll(self.roll_id), [])

    def test_list_orders_most_recently_created_occurrence_first(self):
        first = create_occurrence(self.roll_id, "Primeira")
        second = create_occurrence(self.roll_id, "Segunda")

        rows = list_occurrences_for_roll(self.roll_id)
        self.assertEqual([r["occurrence_id"] for r in rows], [second, first])


if __name__ == "__main__":
    unittest.main()
