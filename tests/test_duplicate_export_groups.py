"""Testes de core.printlogs_db.list_duplicate_export_groups — achado real
durante a investigação do item de roadmap de retrabalho: reexportação
duplicada do mesmo lote (mesmo roll_name, mesmo conteúdo — mesmo conjunto
de job_hash — salvo como rolos DIFERENTES no banco). Decisões confirmadas
com o usuário: é só um relatório novo (mesmo estilo de
list_rework_candidates), nunca muda nenhuma métrica existente. Usa um
banco SQLite temporário isolado (nunca o banco real do usuário), mesmo
padrão de test_rework_candidates.py.

Achado ao escrever estes testes: save_export_transactional já tem o
próprio anti-duplicata (`source_hash`, que soma end_time/document/fabric/
height_mm/real_m/nome do arquivo de origem) — chamá-lo duas vezes com
orders IDÊNTICAS não cria um rolo novo, só registra outro evento no MESMO
rolo (`is_new=False`). Os pares reais encontrados no banco de produção
tinham job_hash idêntico (mesma máquina/hora/documento/altura) mas
source_hash DIFERENTE — ou seja, `real_m` variou minimamente entre as duas
exportações (ex.: arredondamento diferente de um cálculo repetido) sem
`height_mm` variar. Os testes abaixo reproduzem exatamente essa forma:
`height_mm` fixo entre as duas orders (job_hash igual) e `real_m` com uma
diferença mínima (source_hash diferente, dispara um rolo novo de
verdade) — não só "chamar duas vezes com os mesmos dados".
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import OrderRow, list_duplicate_export_groups, save_export_transactional


def _order(
    document: str, pedido: str, fabric: str, real_m: float, end_time: str, *, height_mm: float = None
) -> OrderRow:
    if height_mm is None:
        height_mm = real_m * 1000.0
    return OrderRow(
        end_time=end_time, document=document, fabric=fabric, pedido=pedido,
        height_mm=height_mm, vpos_mm=0.0, real_m=real_m, source_path=f"/x/{document}",
        tipo="Pedido",
    )


class DuplicateExportGroupsTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"
        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def _save(self, module: str, machine: str, roll_name: str, orders) -> int:
        roll_id, _ = save_export_transactional(
            machine=machine, roll_name=roll_name, export_mode="normal", app_version="1.0.0",
            orders=orders, event_payload={"module": module},
        )
        return roll_id

    def test_same_roll_name_with_identical_job_hash_is_a_duplicate_group(self):
        # height_mm fixo (job_hash igual nas duas); real_m varia por uma
        # fração mínima (source_hash diferente -> save_export_transactional
        # cria um rolo novo de verdade, em vez de só marcar reexport no
        # mesmo rolo) — reproduz o par real encontrado no banco de produção.
        orders_a = [_order("a.jpg", "Cliente A", "DRYFIT", 5.0, "2026-11-01T10:00:00", height_mm=5000.0)]
        orders_b = [_order("a.jpg", "Cliente A", "DRYFIT", 5.0000001, "2026-11-01T10:00:00", height_mm=5000.0)]
        self._save("Operacao", "M1", "M1-0001", orders_a)
        self._save("Operacao", "M1", "M1-0001", orders_b)

        groups = list_duplicate_export_groups()
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(g["roll_name"], "M1-0001")
        self.assertEqual(g["module"], "Operacao")
        self.assertEqual(g["order_count"], 1)
        self.assertAlmostEqual(g["real_m_per_copy"], 5.0, places=4)
        self.assertEqual(len(g["copies"]), 2)
        self.assertEqual([c["roll_id"] for c in g["copies"]], sorted(c["roll_id"] for c in g["copies"]))

    def test_same_roll_name_with_different_content_is_not_a_duplicate_group(self):
        first = [_order("a.jpg", "Cliente A", "DRYFIT", 5.0, "2026-11-01T10:00:00")]
        grown = [
            _order("a.jpg", "Cliente A", "DRYFIT", 5.0, "2026-11-01T10:00:00"),
            _order("b.jpg", "Cliente B", "DRYFIT", 3.0, "2026-11-01T11:00:00"),
        ]
        self._save("Operacao", "M1", "M1-0002", first)
        self._save("Operacao", "M1", "M1-0002", grown)

        self.assertEqual(list_duplicate_export_groups(), [])

    def test_unique_roll_names_are_never_grouped(self):
        self._save("Operacao", "M1", "M1-0003", [_order("a.jpg", "X", "DRYFIT", 5.0, "2026-11-01T10:00:00")])
        self._save("Operacao", "M1", "M1-0004", [_order("b.jpg", "Y", "DRYFIT", 5.0, "2026-11-02T10:00:00")])

        self.assertEqual(list_duplicate_export_groups(), [])

    def test_three_identical_copies_are_one_group_with_three_copies(self):
        orders = lambda eps: [
            _order("a.jpg", "Cliente A", "RIBANA", 2.0 + eps, "2026-11-01T10:00:00", height_mm=2000.0)
        ]
        self._save("Planejador", "M1", "M1-0005", orders(0.0))
        self._save("Planejador", "M1", "M1-0005", orders(0.0000001))
        self._save("Planejador", "M1", "M1-0005", orders(0.0000002))

        groups = list_duplicate_export_groups()
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["copies"]), 3)

    def test_oldest_copy_is_first_in_the_list(self):
        orders = lambda eps: [
            _order("a.jpg", "Cliente A", "RIBANA", 2.0 + eps, "2026-11-01T10:00:00", height_mm=2000.0)
        ]
        first_id = self._save("Planejador", "M1", "M1-0006", orders(0.0))
        second_id = self._save("Planejador", "M1", "M1-0006", orders(0.0000001))

        copies = list_duplicate_export_groups()[0]["copies"]
        self.assertEqual(copies[0]["roll_id"], first_id)
        self.assertEqual(copies[1]["roll_id"], second_id)

    def test_duplicates_across_operacao_and_planejador_are_both_detected_independently(self):
        op_orders = lambda eps: [
            _order("op.jpg", "Cliente Op", "DRYFIT", 4.0 + eps, "2026-11-01T10:00:00", height_mm=4000.0)
        ]
        plan_orders = lambda eps: [
            _order("plan.jpg", "Cliente Plan", "RIBANA", 6.0 + eps, "2026-11-02T10:00:00", height_mm=6000.0)
        ]
        self._save("Operacao", "M1", "M1-DUP-OP", op_orders(0.0))
        self._save("Operacao", "M1", "M1-DUP-OP", op_orders(0.0000001))
        self._save("Planejador", "M2", "M2-DUP-PLAN", plan_orders(0.0))
        self._save("Planejador", "M2", "M2-DUP-PLAN", plan_orders(0.0000001))

        groups = list_duplicate_export_groups()
        names = {g["roll_name"] for g in groups}
        self.assertEqual(names, {"M1-DUP-OP", "M2-DUP-PLAN"})
        modules = {g["roll_name"]: g["module"] for g in groups}
        self.assertEqual(modules, {"M1-DUP-OP": "Operacao", "M2-DUP-PLAN": "Planejador"})

    def test_planejador_duplicate_is_detected_even_though_end_time_always_differs(self):
        # Achado real: no Planejador, end_time é só a hora da própria
        # exportação (nunca um horário físico de impressão) — igual pra
        # todas as orders de UM rolo, mas SEMPRE diferente entre duas
        # exportações da mesma fila, mesmo minutos depois. job_hash (que
        # usa end_time) nunca bateria aqui; a comparação pra Planejador
        # ignora end_time de propósito.
        orders_a = [_order("fila.jpg", "Cliente A", "RIBANA", 2.0, "2026-11-01T10:00:00", height_mm=2000.0)]
        orders_b = [_order("fila.jpg", "Cliente A", "RIBANA", 2.0, "2026-11-01T10:18:00", height_mm=2000.0)]
        self._save("Planejador", "M1", "M1-PLAN-DUP", orders_a)
        self._save("Planejador", "M1", "M1-PLAN-DUP", orders_b)

        groups = list_duplicate_export_groups()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["roll_name"], "M1-PLAN-DUP")
        self.assertEqual(groups[0]["module"], "Planejador")

    def test_operacao_same_roll_name_with_different_end_times_is_not_a_duplicate(self):
        # Mesmo cenário, módulo Operação: aqui end_time É real, então
        # horários diferentes significam jobs físicos diferentes — não
        # deve ser tratado como duplicata (ao contrário do caso Planejador
        # acima, onde ignorar end_time é o comportamento certo).
        orders_a = [_order("a.jpg", "Cliente A", "RIBANA", 2.0, "2026-11-01T10:00:00", height_mm=2000.0)]
        orders_b = [_order("a.jpg", "Cliente A", "RIBANA", 2.0, "2026-11-01T10:18:00", height_mm=2000.0)]
        self._save("Operacao", "M1", "M1-OP-NOT-DUP", orders_a)
        self._save("Operacao", "M1", "M1-OP-NOT-DUP", orders_b)

        self.assertEqual(list_duplicate_export_groups(), [])

    def test_a_single_export_of_a_roll_name_is_never_a_group(self):
        self._save("Operacao", "M1", "M1-0007", [_order("a.jpg", "X", "DRYFIT", 5.0, "2026-11-01T10:00:00")])
        self.assertEqual(list_duplicate_export_groups(), [])


if __name__ == "__main__":
    unittest.main()
