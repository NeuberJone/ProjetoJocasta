"""Testes do vínculo pedido<->PDF original (core/printlogs_db.py:
order_pdf_links/order_pdf_history) — Etapa D do recurso de identificação de
vendedor/rastreabilidade de arquivos (ver [[tests/test_order_vendor_links.py]]
pro equivalente da Etapa A, mesmo padrão de banco SQLite temporário).

Inclui o mesmo teste de regressão crítico de test_order_vendor_links.py:
"Atualizar Rolo" nunca deve levantar nem apagar o histórico de um vínculo de
PDF já existente, pela mesma razão (order_id sem FOREIGN KEY — ver
comentário em core/printlogs_db.py, init_schema).
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import (
    OrderRow,
    PDF_LINK_ORIGIN_MANUAL,
    PDF_LINK_STATUS_CLEARED,
    clear_pdf_link,
    get_pdf_link,
    get_pdf_link_history,
    get_roll_orders,
    save_export_transactional,
    update_roll_orders,
    upsert_pdf_link,
)


def _order(document: str, end_time: str = "2026-11-10T10:00:00") -> OrderRow:
    return OrderRow(
        end_time=end_time,
        document=document,
        fabric="DRYFIT",
        pedido="Cliente A",
        height_mm=1000.0,
        vpos_mm=0.0,
        real_m=1.0,
        source_path=f"/x/{document}",
        tipo="Pedido",
    )


class OrderPdfLinksTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def _make_order(self, suffix: str = "") -> int:
        roll_name = f"M1-{suffix or '0001'}"
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name=roll_name, export_mode="normal", app_version="1.0.0",
            orders=[_order(f"doc{suffix or '1'}.jpeg")],
        )
        orders = get_roll_orders(roll_id)
        return int(orders[0]["id"])

    def test_get_pdf_link_absent_returns_none(self):
        order_id = self._make_order()
        self.assertIsNone(get_pdf_link(order_id))

    def test_upsert_then_second_call_replaces_current_and_keeps_history(self):
        order_id = self._make_order()
        upsert_pdf_link(order_id, pdf_path=r"Z:\_Evandro\A\A\pedido.pdf", origin=PDF_LINK_ORIGIN_MANUAL)
        upsert_pdf_link(order_id, pdf_path=r"Z:\_Evandro\A\A\pedido_v2.pdf", origin=PDF_LINK_ORIGIN_MANUAL)

        current = get_pdf_link(order_id)
        self.assertEqual(current["pdf_path"], r"Z:\_Evandro\A\A\pedido_v2.pdf")

        history = get_pdf_link_history(order_id)
        self.assertEqual(len(history), 2)
        self.assertTrue(history[0]["pdf_path"].endswith("pedido.pdf"))
        self.assertTrue(history[1]["pdf_path"].endswith("pedido_v2.pdf"))

    def test_clear_pdf_link_marks_cleared_never_deletes(self):
        order_id = self._make_order()
        upsert_pdf_link(order_id, pdf_path=r"Z:\_Evandro\A\A\pedido.pdf", origin=PDF_LINK_ORIGIN_MANUAL)
        cleared = clear_pdf_link(order_id, note="arquivo errado")
        self.assertTrue(cleared)

        current = get_pdf_link(order_id)
        self.assertEqual(current["status"], PDF_LINK_STATUS_CLEARED)
        self.assertTrue(current["pdf_path"].endswith("pedido.pdf"))

        history = get_pdf_link_history(order_id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]["status"], PDF_LINK_STATUS_CLEARED)

    def test_clear_pdf_link_noop_when_no_link(self):
        order_id = self._make_order()
        self.assertFalse(clear_pdf_link(order_id))

    def test_invalid_origin_raises_and_writes_nothing(self):
        order_id = self._make_order()
        with self.assertRaises(ValueError):
            upsert_pdf_link(order_id, pdf_path=r"Z:\x.pdf", origin="robo")
        self.assertIsNone(get_pdf_link(order_id))
        self.assertEqual(get_pdf_link_history(order_id), [])

    def test_blank_pdf_path_raises_and_writes_nothing(self):
        order_id = self._make_order()
        with self.assertRaises(ValueError):
            upsert_pdf_link(order_id, pdf_path="   ", origin=PDF_LINK_ORIGIN_MANUAL)
        self.assertIsNone(get_pdf_link(order_id))

    def test_update_roll_orders_never_raises_or_cascades_against_linked_orders(self):
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name="M1-0002", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpeg")],
        )
        old_order_id = int(get_roll_orders(roll_id)[0]["id"])
        upsert_pdf_link(old_order_id, pdf_path=r"Z:\_Evandro\A\A\pedido.pdf", origin=PDF_LINK_ORIGIN_MANUAL)

        try:
            update_roll_orders(
                roll_id, machine="M1", roll_name="M1-0002", export_mode="normal", app_version="1.0.0",
                orders=[_order("doc1.jpeg"), _order("doc2.jpeg", end_time="2026-11-10T11:00:00")],
            )
        except Exception as exc:  # noqa: BLE001
            self.fail(f"update_roll_orders levantou exceção por causa do vínculo de PDF: {exc}")

        new_order_ids = {int(o["id"]) for o in get_roll_orders(roll_id)}
        self.assertNotIn(old_order_id, new_order_ids)

        history = get_pdf_link_history(old_order_id)
        self.assertEqual(len(history), 1)
        self.assertTrue(history[0]["pdf_path"].endswith("pedido.pdf"))


if __name__ == "__main__":
    unittest.main()
