"""Testes do vínculo pedido<->vendedor (core/printlogs_db.py:
order_vendor_links/order_vendor_history) — etapa A do recurso de
identificação de vendedor. Usa um banco SQLite temporário isolado (nunca o
banco real do usuário), seguindo o mesmo padrão de
tests/test_roll_order_versions.py.

O teste mais importante deste arquivo é
test_update_roll_orders_never_raises_or_cascades_against_linked_orders: ele
prova que a decisão de NÃO colocar FOREIGN KEY em order_vendor_links.order_id
(ver comentário em core/printlogs_db.py, init_schema) está correta —
"Atualizar Rolo" (que apaga e reinsere as orders do rolo) nunca levanta
exceção por causa de um vínculo existente, e o histórico desse vínculo nunca
é apagado, mesmo que o order_id original tenha deixado de existir.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import (
    OrderRow,
    VENDOR_LINK_ORIGIN_MANUAL,
    VENDOR_LINK_STATUS_ACTIVE,
    VENDOR_LINK_STATUS_CLEARED,
    clear_vendor_link,
    get_roll_orders,
    get_vendor_link,
    get_vendor_link_history,
    list_vendor_links,
    save_export_transactional,
    update_roll_orders,
    upsert_vendor_link,
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


class OrderVendorLinksTests(unittest.TestCase):
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

    def test_get_vendor_link_absent_returns_none(self):
        order_id = self._make_order()
        self.assertIsNone(get_vendor_link(order_id))

    def test_upsert_then_second_call_replaces_current_and_keeps_history(self):
        order_id = self._make_order()
        upsert_vendor_link(
            order_id, vendor_key="joao", vendor_name_snapshot="João",
            origin=VENDOR_LINK_ORIGIN_MANUAL, status=VENDOR_LINK_STATUS_ACTIVE,
        )
        upsert_vendor_link(
            order_id, vendor_key="maria", vendor_name_snapshot="Maria",
            origin=VENDOR_LINK_ORIGIN_MANUAL, status=VENDOR_LINK_STATUS_ACTIVE,
        )

        current = get_vendor_link(order_id)
        self.assertEqual(current["vendor_key"], "maria")

        history = get_vendor_link_history(order_id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["vendor_key"], "joao")
        self.assertEqual(history[1]["vendor_key"], "maria")

    def test_clear_vendor_link_marks_cleared_never_deletes(self):
        order_id = self._make_order()
        upsert_vendor_link(
            order_id, vendor_key="joao", vendor_name_snapshot="João",
            origin=VENDOR_LINK_ORIGIN_MANUAL,
        )
        cleared = clear_vendor_link(order_id, note="trocou de vendedor")
        self.assertTrue(cleared)

        current = get_vendor_link(order_id)
        self.assertEqual(current["status"], VENDOR_LINK_STATUS_CLEARED)
        self.assertEqual(current["vendor_key"], "joao")

        history = get_vendor_link_history(order_id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]["status"], VENDOR_LINK_STATUS_CLEARED)

    def test_clear_vendor_link_noop_when_no_link(self):
        order_id = self._make_order()
        self.assertFalse(clear_vendor_link(order_id))

    def test_list_vendor_links_with_filters(self):
        order_id1 = self._make_order("0001")
        order_id2 = self._make_order("0002")
        upsert_vendor_link(order_id1, vendor_key="joao", vendor_name_snapshot="Joao", origin=VENDOR_LINK_ORIGIN_MANUAL)
        upsert_vendor_link(order_id2, vendor_key="maria", vendor_name_snapshot="Maria", origin=VENDOR_LINK_ORIGIN_MANUAL)

        only_joao = list_vendor_links(vendor_key="joao")
        self.assertEqual(len(only_joao), 1)
        self.assertEqual(only_joao[0]["order_id"], order_id1)

        all_active = list_vendor_links(status=VENDOR_LINK_STATUS_ACTIVE)
        self.assertEqual(len(all_active), 2)

    def test_invalid_origin_raises_and_writes_nothing(self):
        order_id = self._make_order()
        with self.assertRaises(ValueError):
            upsert_vendor_link(order_id, vendor_key="joao", vendor_name_snapshot="João", origin="robo")
        self.assertIsNone(get_vendor_link(order_id))
        self.assertEqual(get_vendor_link_history(order_id), [])

    def test_invalid_status_raises_and_writes_nothing(self):
        order_id = self._make_order()
        with self.assertRaises(ValueError):
            upsert_vendor_link(
                order_id, vendor_key="joao", vendor_name_snapshot="João",
                origin=VENDOR_LINK_ORIGIN_MANUAL, status="pendente",
            )
        self.assertIsNone(get_vendor_link(order_id))

    def test_update_roll_orders_never_raises_or_cascades_against_linked_orders(self):
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name="M1-0002", export_mode="normal", app_version="1.0.0",
            orders=[_order("doc1.jpeg")],
        )
        old_order_id = int(get_roll_orders(roll_id)[0]["id"])
        upsert_vendor_link(
            old_order_id, vendor_key="joao", vendor_name_snapshot="João",
            origin=VENDOR_LINK_ORIGIN_MANUAL,
        )

        # update_roll_orders apaga e reinsere as orders do rolo — orders.id
        # não é estável entre edições (ver comentário na definição da
        # tabela order_vendor_links). Isto não deve levantar exceção.
        try:
            update_roll_orders(
                roll_id, machine="M1", roll_name="M1-0002", export_mode="normal", app_version="1.0.0",
                orders=[_order("doc1.jpeg"), _order("doc2.jpeg", end_time="2026-11-10T11:00:00")],
            )
        except Exception as exc:  # noqa: BLE001
            self.fail(f"update_roll_orders levantou exceção por causa do vínculo de vendedor: {exc}")

        new_order_ids = {int(o["id"]) for o in get_roll_orders(roll_id)}
        self.assertNotIn(old_order_id, new_order_ids)

        # Histórico do vínculo antigo continua intacto (sem CASCADE apagando-o).
        history = get_vendor_link_history(old_order_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["vendor_key"], "joao")


if __name__ == "__main__":
    unittest.main()
