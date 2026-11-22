"""Testes do filtro por vendedor em core.printlogs_db.list_rolls (Etapa E
do recurso de identificação de vendedor, ver [[modules/registros/ui.py]] —
combobox "Vendedor" na tela de Registros). Mesmo padrão de banco SQLite
temporário de tests/test_order_vendor_links.py."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import (
    OrderRow,
    VENDOR_LINK_ORIGIN_MANUAL,
    clear_vendor_link,
    get_roll_orders,
    list_rolls,
    save_export_transactional,
    upsert_vendor_link,
)


def _order(document: str, *, tipo: str = "Pedido") -> OrderRow:
    return OrderRow(
        end_time="2026-11-11T10:00:00", document=document, fabric="DRYFIT", pedido="Cliente A",
        height_mm=1000.0, vpos_mm=0.0, real_m=1.0, source_path=f"/x/{document}", tipo=tipo,
    )


class ListRollsVendorFilterTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def _make_roll(self, suffix: str, *, tipo: str = "Pedido") -> tuple[int, int]:
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name=f"M1-{suffix}", export_mode="normal", app_version="1.0.0",
            orders=[_order(f"doc{suffix}.jpeg", tipo=tipo)],
        )
        order_id = int(get_roll_orders(roll_id)[0]["id"])
        return roll_id, order_id

    def test_vendor_key_filter_returns_only_rolls_with_active_link_to_that_vendor(self):
        roll_evandro, order_evandro = self._make_roll("0001")
        roll_maria, order_maria = self._make_roll("0002")
        upsert_vendor_link(order_evandro, vendor_key="evandro", vendor_name_snapshot="Evandro", origin=VENDOR_LINK_ORIGIN_MANUAL)
        upsert_vendor_link(order_maria, vendor_key="maria", vendor_name_snapshot="Maria", origin=VENDOR_LINK_ORIGIN_MANUAL)

        rows = list_rolls(limit=100, vendor_key="evandro")
        ids = {r["id"] for r in rows}
        self.assertIn(roll_evandro, ids)
        self.assertNotIn(roll_maria, ids)

    def test_vendor_unidentified_filter_excludes_rolls_with_an_active_link(self):
        roll_linked, order_linked = self._make_roll("0003")
        roll_unlinked, _ = self._make_roll("0004")
        upsert_vendor_link(order_linked, vendor_key="evandro", vendor_name_snapshot="Evandro", origin=VENDOR_LINK_ORIGIN_MANUAL)

        rows = list_rolls(limit=100, vendor_unidentified=True)
        ids = {r["id"] for r in rows}
        self.assertIn(roll_unlinked, ids)
        self.assertNotIn(roll_linked, ids)

    def test_gap_only_roll_never_counts_as_unidentified(self):
        """Avanço/espaço (tipo vazio) nunca tem vendedor — um rolo cujas
        orders são só espaço não deve aparecer em "sem vendedor
        identificado" (seria sempre verdadeiro e inútil como filtro)."""
        roll_id, _ = self._make_roll("0005", tipo="")
        rows = list_rolls(limit=100, vendor_unidentified=True)
        ids = {r["id"] for r in rows}
        self.assertNotIn(roll_id, ids)

    def test_cleared_link_counts_as_unidentified_again(self):
        roll_id, order_id = self._make_roll("0006")
        upsert_vendor_link(order_id, vendor_key="evandro", vendor_name_snapshot="Evandro", origin=VENDOR_LINK_ORIGIN_MANUAL)
        self.assertNotIn(roll_id, {r["id"] for r in list_rolls(limit=100, vendor_unidentified=True)})

        clear_vendor_link(order_id)
        self.assertIn(roll_id, {r["id"] for r in list_rolls(limit=100, vendor_unidentified=True)})
        self.assertNotIn(roll_id, {r["id"] for r in list_rolls(limit=100, vendor_key="evandro")})

    def test_no_vendor_filters_returns_everything_unchanged(self):
        roll_a, _ = self._make_roll("0007")
        roll_b, _ = self._make_roll("0008")
        ids = {r["id"] for r in list_rolls(limit=100)}
        self.assertIn(roll_a, ids)
        self.assertIn(roll_b, ids)


if __name__ == "__main__":
    unittest.main()
