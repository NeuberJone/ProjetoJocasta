"""Testes de modules/operacao/vendor_pdf_apply.py (Parte 1 da conclusão do
recurso de identificação de vendedor/PDF original) — aplica as decisões do
painel de pré-visualização de Operação depois que o rolo já foi salvo
(order_id real). Mesmo padrão de fixture de tests/test_order_vendor_resolution.py
(banco SQLite temporário + pastas de vendedor temporárias reais indexadas).
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from core.order_files import build_order_index
from core.order_pdfs import get_pdf_link
from core.printlogs_db import (
    OrderRow,
    get_vendor_link,
    get_roll_orders,
    save_export_transactional,
)
from core.vendedores import add_or_update_vendedor, add_vendedor_folder
from modules.operacao.vendor_pdf_apply import PedidoSessionDecision, apply_session_decisions


def _order(document: str, pedido: str) -> OrderRow:
    return OrderRow(
        end_time="2026-11-12T10:00:00", document=document, fabric="DRYFIT", pedido=pedido,
        height_mm=1000.0, vpos_mm=0.0, real_m=1.0, source_path=f"/x/{document}", tipo="Pedido",
    )


def _space_order(document: str) -> OrderRow:
    return OrderRow(
        end_time="2026-11-12T10:00:01", document=document, fabric="DRYFIT", pedido="",
        height_mm=100.0, vpos_mm=0.0, real_m=0.1, source_path=f"/x/{document}", tipo="",
    )


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    try:
        doc.new_page(width=600, height=800)
        doc.save(str(path))
    finally:
        doc.close()


class ApplySessionDecisionsTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._db_patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._db_patcher.start()

        self._folders_dir = Path(self._tmp_dir.name) / "folders"
        self.evandro_root = self._folders_dir / "_Evandro"
        self.order_folder = self.evandro_root / "ESCOLINHA DOUGLAS AMÉRICA" / "ESCOLINHA DOUGLAS AMÉRICA"
        self.order_folder.mkdir(parents=True)
        vendedores = add_or_update_vendedor([], name="Evandro")
        self.vendedores = add_vendedor_folder(vendedores, "evandro", str(self.evandro_root))
        self.index = build_order_index(self.vendedores)

    def tearDown(self):
        self._db_patcher.stop()
        self._tmp_dir.cleanup()

    def _save_roll(self, *orders: OrderRow) -> int:
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name="M1-0001", export_mode="normal", app_version="1.0.0",
            orders=list(orders),
        )
        return roll_id

    def test_no_decision_falls_back_to_automatic_resolution(self):
        roll_id = self._save_roll(_order("doc1.jpeg", "ESCOLINHA DOUGLAS AMÉRICA"))
        apply_session_decisions(roll_id, {}, index=self.index, vendedores=self.vendedores)

        order_id = int(get_roll_orders(roll_id)[0]["id"])
        link = get_vendor_link(order_id)
        self.assertEqual(link["vendor_key"], "evandro")
        self.assertEqual(link["origin"], "auto")

    def test_confirmed_session_decision_takes_precedence_over_automatic(self):
        # Pedido ambíguo de propósito: dois vendedores com a mesma pasta,
        # a resolução automática nunca escolheria sozinha.
        outro_root = self._folders_dir / "_OutroVendedor"
        (outro_root / "ESCOLINHA DOUGLAS AMÉRICA" / "ESCOLINHA DOUGLAS AMÉRICA").mkdir(parents=True)
        vendedores = add_or_update_vendedor(self.vendedores, name="Outro Vendedor")
        vendedores = add_vendedor_folder(vendedores, "outro_vendedor", str(outro_root))
        index = build_order_index(vendedores)

        roll_id = self._save_roll(_order("doc1.jpeg", "ESCOLINHA DOUGLAS AMÉRICA"))
        decisions = {
            "ESCOLINHA DOUGLAS AMÉRICA": PedidoSessionDecision(
                pedido="ESCOLINHA DOUGLAS AMÉRICA",
                vendor_key="evandro", vendor_name="Evandro", vendor_confirmed=True,
            ),
        }
        apply_session_decisions(roll_id, decisions, index=index, vendedores=vendedores)

        order_id = int(get_roll_orders(roll_id)[0]["id"])
        link = get_vendor_link(order_id)
        self.assertEqual(link["vendor_key"], "evandro")
        self.assertEqual(link["origin"], "manual")

    def test_pdf_auto_linked_when_vendor_resolved_and_single_pdf_in_folder(self):
        _make_pdf(self.order_folder / "arte.pdf")
        roll_id = self._save_roll(_order("doc1.jpeg", "ESCOLINHA DOUGLAS AMÉRICA"))
        apply_session_decisions(roll_id, {}, index=self.index, vendedores=self.vendedores)

        order_id = int(get_roll_orders(roll_id)[0]["id"])
        pdf_link = get_pdf_link(order_id)
        self.assertIsNotNone(pdf_link)
        self.assertEqual(pdf_link["pdf_path"], str(self.order_folder / "arte.pdf"))
        self.assertEqual(pdf_link["origin"], "auto")

    def test_confirmed_pdf_decision_takes_precedence(self):
        _make_pdf(self.order_folder / "arte.pdf")
        chosen = self.order_folder / "arte_escolhida.pdf"
        _make_pdf(chosen)

        roll_id = self._save_roll(_order("doc1.jpeg", "ESCOLINHA DOUGLAS AMÉRICA"))
        decisions = {
            "ESCOLINHA DOUGLAS AMÉRICA": PedidoSessionDecision(
                pedido="ESCOLINHA DOUGLAS AMÉRICA", pdf_path=str(chosen), pdf_confirmed=True,
            ),
        }
        apply_session_decisions(roll_id, decisions, index=self.index, vendedores=self.vendedores)

        order_id = int(get_roll_orders(roll_id)[0]["id"])
        pdf_link = get_pdf_link(order_id)
        self.assertEqual(pdf_link["pdf_path"], str(chosen))
        self.assertEqual(pdf_link["origin"], "manual")

    def test_space_rows_are_never_touched(self):
        roll_id = self._save_roll(_space_order("doc_gap.jpeg"))
        apply_session_decisions(roll_id, {}, index=self.index, vendedores=self.vendedores)

        order_id = int(get_roll_orders(roll_id)[0]["id"])
        self.assertIsNone(get_vendor_link(order_id))
        self.assertIsNone(get_pdf_link(order_id))

    def test_empty_index_does_not_raise_and_leaves_order_unidentified(self):
        from core.order_files import VendorIndexState

        roll_id = self._save_roll(_order("doc1.jpeg", "PEDIDO DESCONHECIDO"))
        apply_session_decisions(roll_id, {}, index=VendorIndexState(), vendedores=[])

        order_id = int(get_roll_orders(roll_id)[0]["id"])
        self.assertIsNone(get_vendor_link(order_id))
        self.assertIsNone(get_pdf_link(order_id))


if __name__ == "__main__":
    unittest.main()
