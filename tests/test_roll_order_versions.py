"""Testes do histórico de versões de um rolo editado pelos Registros
("Editar rolo" -> Operação/Planejador -> "Atualizar Rolo"): ver
core.printlogs_db.update_roll_orders, was_roll_edited,
get_roll_order_version_count, get_roll_order_version e a migração da
antiga tabela roll_original_orders (só guardava UMA cópia, "a original")
para roll_order_versions (uma cópia por edição: Original, Edição 1, Edição
2...). Usa um banco SQLite temporário isolado (nunca o banco real do
usuário).
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import (
    OrderRow,
    connect,
    ensure_schema,
    get_roll_order_version,
    get_roll_order_version_count,
    get_roll_orders,
    save_export_transactional,
    update_roll_orders,
    was_roll_edited,
)


def _order(document: str, fabric: str = "DRYFIT", pedido: str = "Cliente A") -> OrderRow:
    return _order_at(document, "2026-11-05T10:00:00", fabric=fabric, pedido=pedido)


def _order_at(document: str, end_time: str, fabric: str = "DRYFIT", pedido: str = "Cliente A") -> OrderRow:
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


class RollOrderVersionsTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def test_fresh_roll_was_not_edited_and_has_no_versions(self):
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpg")],
        )
        self.assertFalse(was_roll_edited(roll_id))
        self.assertEqual(get_roll_order_version_count(roll_id), 0)

    def test_first_update_creates_version_0_original(self):
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpg")],
        )
        update_roll_orders(
            roll_id, machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpg"), _order("doc2.jpg")],
        )

        self.assertTrue(was_roll_edited(roll_id))
        self.assertEqual(get_roll_order_version_count(roll_id), 1)

        original_docs = {o["document"] for o in get_roll_order_version(roll_id, 0)}
        self.assertEqual(original_docs, {"doc1.jpg"})

        current_docs = {o["document"] for o in get_roll_orders(roll_id)}
        self.assertEqual(current_docs, {"doc1.jpg", "doc2.jpg"})

    def test_each_update_adds_a_new_version_instead_of_overwriting(self):
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpg")],
        )
        update_roll_orders(
            roll_id, machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpg"), _order("doc2.jpg")],
        )
        update_roll_orders(
            roll_id, machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpg"), _order("doc2.jpg"), _order("doc3.jpg")],
        )

        self.assertEqual(get_roll_order_version_count(roll_id), 2)

        version_0 = {o["document"] for o in get_roll_order_version(roll_id, 0)}  # Original
        version_1 = {o["document"] for o in get_roll_order_version(roll_id, 1)}  # Edição 1
        current = {o["document"] for o in get_roll_orders(roll_id)}  # Edição 2 (atual)

        self.assertEqual(version_0, {"doc1.jpg"})
        self.assertEqual(version_1, {"doc1.jpg", "doc2.jpg"})
        self.assertEqual(current, {"doc1.jpg", "doc2.jpg", "doc3.jpg"})

    def test_saved_version_is_sorted_by_end_time_regardless_of_import_order(self):
        """Bug real: os itens entram em `orders` na ordem em que foram
        importados (não cronológica) — a cópia guardada em
        roll_order_versions precisa sair ordenada por end_time (mais
        recente primeiro, igual a get_roll_orders), senão o combobox de
        versão mostra a lista "embaralhada" mesmo sem o conteúdo ter
        mudado."""
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[
                _order_at("doc-10h.jpg", "2026-11-05T10:00:00"),
                _order_at("doc-08h.jpg", "2026-11-05T08:00:00"),
                _order_at("doc-09h.jpg", "2026-11-05T09:00:00"),
            ],
        )
        update_roll_orders(
            roll_id, machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc-extra.jpg")],
        )

        documents = [o["document"] for o in get_roll_order_version(roll_id, 0)]
        self.assertEqual(documents, ["doc-10h.jpg", "doc-09h.jpg", "doc-08h.jpg"])

    def test_migrates_old_roll_original_orders_table_as_version_0(self):
        """Bancos de versões anteriores do Nexor (1.6.32-1.6.36) guardavam
        só uma cópia em roll_original_orders — a migração de schema
        precisa trazer isso pra roll_order_versions como version_no=0, sem
        perder o que já estava preservado."""
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpg")],
        )
        update_roll_orders(
            roll_id, machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpg"), _order("doc2.jpg")],
        )

        # Simula um banco "antigo": recria a tabela legada com os mesmos
        # dados que já foram migrados, como se esta base tivesse sido
        # aberta antes da migração existir.
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        con.execute(
            "CREATE TABLE roll_original_orders (roll_id INTEGER PRIMARY KEY, "
            "orders_json TEXT NOT NULL, saved_at TEXT NOT NULL)"
        )
        con.execute(
            "INSERT INTO roll_original_orders(roll_id, orders_json, saved_at) "
            "SELECT roll_id, orders_json, saved_at FROM roll_order_versions WHERE version_no = 0"
        )
        con.commit()
        con.close()

        con = connect()
        try:
            ensure_schema(con)  # dispara a migração de novo
            tables = {
                row[0] for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            con.close()

        self.assertNotIn("roll_original_orders", tables)
        self.assertEqual(get_roll_order_version_count(roll_id), 1)
        self.assertEqual({o["document"] for o in get_roll_order_version(roll_id, 0)}, {"doc1.jpg"})


if __name__ == "__main__":
    unittest.main()
