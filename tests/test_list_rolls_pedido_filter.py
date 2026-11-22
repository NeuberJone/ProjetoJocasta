"""Testes do filtro `pedido_like` em core.printlogs_db.list_rolls — item de
roadmap (Fase 3) "unificar busca... mantendo claro o significado de cada
identificador". Achado real: a busca "Pedido contém" da tela de Registros
na verdade filtrava pelo NOME DO ARQUIVO (`order_like`/`o.document`), não
pelo pedido já normalizado (`o.pedido`) — então buscar pelo pedido fixo de
um tipo com override (ex.: Reposição -> "Variados") não encontrava nada,
mesmo com itens reais daquele pedido salvos. `pedido_like` é o filtro novo,
genuinamente sobre `o.pedido`; `order_like` continua intocado, sobre
`o.document`. Mesmo padrão de banco SQLite temporário de
tests/test_list_rolls_vendor_filter.py.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import OrderRow, list_rolls, save_export_transactional


def _order(document: str, pedido: str, *, tipo: str = "Pedido") -> OrderRow:
    return OrderRow(
        end_time="2026-11-18T10:00:00", document=document, fabric="DRYFIT", pedido=pedido,
        height_mm=1000.0, vpos_mm=0.0, real_m=1.0, source_path=f"/x/{document}", tipo=tipo,
    )


class ListRollsPedidoFilterTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def _save(self, suffix: str, document: str, pedido: str, *, tipo: str = "Pedido") -> int:
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name=f"M1-{suffix}", export_mode="normal", app_version="1.0.0",
            orders=[_order(document, pedido, tipo=tipo)],
        )
        return roll_id

    def test_pedido_like_finds_a_fixed_override_pedido_even_when_the_filename_differs(self):
        # Mesmo cenário real de Reposição: o pedido salvo é o nome fixo
        # configurado ("Variados"), nunca o nome real do arquivo reposto.
        roll_id = self._save("0001", "16-10 - algo estranho reposto.jpeg", "Variados", tipo="Reposição")

        rows = list_rolls(limit=100, pedido_like="Variados")
        self.assertEqual({r["id"] for r in rows}, {roll_id})

    def test_order_like_never_matches_the_pedido_when_only_the_filename_contains_it(self):
        # order_like busca o ARQUIVO — buscar "Variados" ali não deve achar
        # nada, mesmo que exista um pedido "Variados" de verdade (esse é
        # exatamente o campo errado pra essa busca).
        self._save("0002", "16-10 - algo estranho reposto.jpeg", "Variados", tipo="Reposição")

        rows = list_rolls(limit=100, order_like="Variados")
        self.assertEqual(rows, [])

    def test_order_like_still_matches_by_filename_as_before(self):
        roll_id = self._save("0003", "16-10 - algo estranho reposto.jpeg", "Variados", tipo="Reposição")

        rows = list_rolls(limit=100, order_like="estranho")
        self.assertEqual({r["id"] for r in rows}, {roll_id})

    def test_pedido_like_never_matches_by_filename_when_the_pedido_itself_differs(self):
        self._save("0004", "16-10 - estranho.jpeg", "Cliente A")

        rows = list_rolls(limit=100, pedido_like="estranho")
        self.assertEqual(rows, [])

    def test_pedido_like_is_case_insensitive_substring(self):
        roll_id = self._save("0005", "doc.jpeg", "Cliente A Grande")

        rows = list_rolls(limit=100, pedido_like="cliente a")
        self.assertEqual({r["id"] for r in rows}, {roll_id})

    def test_pedido_like_and_order_like_combine_with_and_when_both_given(self):
        roll_match = self._save("0006", "arquivo-certo.jpeg", "Cliente A")
        self._save("0007", "arquivo-errado.jpeg", "Cliente A")
        self._save("0008", "arquivo-certo.jpeg", "Cliente B")

        rows = list_rolls(limit=100, pedido_like="Cliente A", order_like="certo")
        self.assertEqual({r["id"] for r in rows}, {roll_match})


if __name__ == "__main__":
    unittest.main()
