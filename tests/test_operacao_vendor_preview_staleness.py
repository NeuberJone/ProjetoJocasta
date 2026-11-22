"""Achado de revisão de código: mudar o vendedor de um pedido no painel de
pré-visualização de Operação (`on_choose_vendor_preview`), ou o próprio
índice sugerir um vendedor diferente numa atualização (`_refresh_vendor_previews`),
não limpava um PDF já descoberto automaticamente na pasta do vendedor
ANTERIOR — o painel continuava mostrando esse PDF como se fosse da pasta
nova, e a guarda de `on_select_pedido_preview` (`if ... or preview.pdf_state:
return`) impedia uma nova descoberta automática.

Chama os métodos de `PXPrintLogsUI` diretamente (sem instanciar nenhum
widget Tkinter), mesmo padrão já usado em `tests/test_prisma_report.py`
(`_make_operacao_app`) — um `SimpleNamespace` com só os atributos/métodos
que cada função realmente lê."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules.operacao.ui import PXPrintLogsUI
from modules.operacao.vendor_pdf_apply import PedidoSessionDecision


class _Vendor(SimpleNamespace):
    pass


def _make_app(*, pedido_previews, pedidos):
    return SimpleNamespace(
        _pedido_previews=pedido_previews,
        pedidos=pedidos,
        _preview_vendedores=None,
        _preview_index=None,
        _selected_pedido_summary=lambda: pedidos[0] if pedidos else None,
        _refresh_vendor_previews=lambda: None,
        _update_pedido_row=lambda _name: None,
        _update_pedido_detail_panel=lambda: None,
    )


class OnChooseVendorPreviewClearsStalePdfTests(unittest.TestCase):
    def _preview_with_stale_pdf(self) -> PedidoSessionDecision:
        return PedidoSessionDecision(
            pedido="0001",
            vendor_state="auto_identified", vendor_key="vendor_a", vendor_name="Vendor A",
            folder=r"Z:\VendorA\0001",
            pdf_state="auto_identified", pdf_path=r"Z:\VendorA\0001\arte.pdf",
            pdf_confirmed=False,
        )

    def test_choosing_a_different_vendor_clears_stale_auto_discovered_pdf(self):
        pedido = SimpleNamespace(pedido="0001")
        preview = self._preview_with_stale_pdf()
        app = _make_app(pedido_previews={"0001": preview}, pedidos=[pedido])

        vendor_b = _Vendor(key="vendor_b", name="Vendor B", active=True)
        with patch("modules.operacao.ui.load_vendedores", return_value=[vendor_b]), \
             patch("modules.operacao.ui.ask_pick_from_list", return_value=vendor_b), \
             patch("modules.operacao.ui.folder_for_vendor", return_value=r"Z:\VendorB\0001"):
            PXPrintLogsUI.on_choose_vendor_preview(app)

        self.assertEqual(preview.vendor_key, "vendor_b")
        self.assertEqual(preview.folder, r"Z:\VendorB\0001")
        self.assertEqual(preview.pdf_state, "", "achado: PDF da pasta do vendedor anterior ficou preso no preview")
        self.assertEqual(preview.pdf_path, "")
        self.assertEqual(preview.candidates_pdf, [])

    def test_choosing_a_different_vendor_never_overwrites_a_manually_confirmed_pdf(self):
        """Precedência do operador: um PDF escolhido manualmente (ver
        `on_choose_pdf_preview`) nunca é limpo só porque o vendedor mudou —
        o módulo já documenta isso como independente do vendedor."""
        pedido = SimpleNamespace(pedido="0001")
        preview = self._preview_with_stale_pdf()
        preview.pdf_confirmed = True
        app = _make_app(pedido_previews={"0001": preview}, pedidos=[pedido])

        vendor_b = _Vendor(key="vendor_b", name="Vendor B", active=True)
        with patch("modules.operacao.ui.load_vendedores", return_value=[vendor_b]), \
             patch("modules.operacao.ui.ask_pick_from_list", return_value=vendor_b), \
             patch("modules.operacao.ui.folder_for_vendor", return_value=r"Z:\VendorB\0001"):
            PXPrintLogsUI.on_choose_vendor_preview(app)

        self.assertEqual(preview.pdf_path, r"Z:\VendorA\0001\arte.pdf")

    def test_choosing_a_vendor_marks_vendor_state_as_manual_not_auto(self):
        """Achado de revisão: `vendor_state` era gravado como AUTO pra uma
        escolha manual — hoje mascarado porque a exibição checa
        `vendor_confirmed` primeiro, mas um código futuro que olhasse só
        pro estado trataria a confirmação do operador como mero palpite."""
        pedido = SimpleNamespace(pedido="0001")
        preview = self._preview_with_stale_pdf()
        app = _make_app(pedido_previews={"0001": preview}, pedidos=[pedido])

        vendor_b = _Vendor(key="vendor_b", name="Vendor B", active=True)
        with patch("modules.operacao.ui.load_vendedores", return_value=[vendor_b]), \
             patch("modules.operacao.ui.ask_pick_from_list", return_value=vendor_b), \
             patch("modules.operacao.ui.folder_for_vendor", return_value=r"Z:\VendorB\0001"):
            PXPrintLogsUI.on_choose_vendor_preview(app)

        from core.order_vendor_resolution import RESOLUTION_MANUAL
        self.assertEqual(preview.vendor_state, RESOLUTION_MANUAL)

    def test_clearing_the_vendor_also_clears_the_stale_pdf(self):
        pedido = SimpleNamespace(pedido="0001")
        preview = self._preview_with_stale_pdf()
        app = _make_app(pedido_previews={"0001": preview}, pedidos=[pedido])

        clear_sentinel = object()

        def fake_ask_pick_from_list(_parent, _title, _prompt, items, _label_fn):
            # O "— Remover escolha..." é sempre o último item da lista.
            return items[-1]

        with patch("modules.operacao.ui.load_vendedores", return_value=[_Vendor(key="vendor_a", name="Vendor A", active=True)]), \
             patch("modules.operacao.ui.ask_pick_from_list", side_effect=fake_ask_pick_from_list):
            PXPrintLogsUI.on_choose_vendor_preview(app)

        self.assertEqual(preview.vendor_key, "")
        self.assertEqual(preview.folder, "")
        self.assertEqual(preview.pdf_state, "")
        self.assertEqual(preview.pdf_path, "")


class RefreshVendorPreviewsClearsStalePdfTests(unittest.TestCase):
    def test_vendor_suggestion_changing_between_refreshes_clears_stale_pdf(self):
        """Ex.: índice atualizado em Configurações enquanto o rolo ainda
        está sendo editado em Operação — a sugestão automática de
        vendedor passa a apontar pra outra pasta entre duas chamadas."""
        pedido = SimpleNamespace(pedido="0001")
        preview = PedidoSessionDecision(
            pedido="0001",
            vendor_state="auto_identified", vendor_key="vendor_a", vendor_name="Vendor A",
            folder=r"Z:\VendorA\0001",
            pdf_state="auto_identified", pdf_path=r"Z:\VendorA\0001\arte.pdf",
            pdf_confirmed=False,
        )
        app = SimpleNamespace(
            pedidos=[pedido],
            _pedido_previews={"0001": preview},
        )

        new_result = SimpleNamespace(state="auto_identified", vendor_key="vendor_b", vendor_name="Vendor B", candidates=[])
        with patch("modules.operacao.ui.load_vendedores", return_value=[]), \
             patch("modules.operacao.ui.load_order_index", return_value=object()), \
             patch("modules.operacao.ui.preview_order_vendor", return_value=new_result), \
             patch("modules.operacao.ui.folder_for_vendor", return_value=r"Z:\VendorB\0001"):
            PXPrintLogsUI._refresh_vendor_previews(app)

        self.assertEqual(preview.vendor_key, "vendor_b")
        self.assertEqual(preview.folder, r"Z:\VendorB\0001")
        self.assertEqual(preview.pdf_state, "")
        self.assertEqual(preview.pdf_path, "")

    def test_vendor_suggestion_unchanged_keeps_the_already_discovered_pdf(self):
        """Contraste com o teste acima: se a pasta resolvida não mudou,
        não há motivo pra descartar um PDF já descoberto — só limpa
        quando a pasta de fato muda."""
        pedido = SimpleNamespace(pedido="0001")
        preview = PedidoSessionDecision(
            pedido="0001",
            vendor_state="auto_identified", vendor_key="vendor_a", vendor_name="Vendor A",
            folder=r"Z:\VendorA\0001",
            pdf_state="auto_identified", pdf_path=r"Z:\VendorA\0001\arte.pdf",
            pdf_confirmed=False,
        )
        app = SimpleNamespace(
            pedidos=[pedido],
            _pedido_previews={"0001": preview},
        )

        same_result = SimpleNamespace(state="auto_identified", vendor_key="vendor_a", vendor_name="Vendor A", candidates=[])
        with patch("modules.operacao.ui.load_vendedores", return_value=[]), \
             patch("modules.operacao.ui.load_order_index", return_value=object()), \
             patch("modules.operacao.ui.preview_order_vendor", return_value=same_result), \
             patch("modules.operacao.ui.folder_for_vendor", return_value=r"Z:\VendorA\0001"):
            PXPrintLogsUI._refresh_vendor_previews(app)

        self.assertEqual(preview.pdf_path, r"Z:\VendorA\0001\arte.pdf")


if __name__ == "__main__":
    unittest.main()
