"""Testes de modules.planejador_queue — item de roadmap (Fase 3) "Extrair
cálculo/organização de fila do Planejador... para serviços menores, com
regressão dos resultados conhecidos". Cada caso fixa um comportamento já
documentado nos docstrings originais (agora extraídos de
modules/planejador.py:build_ui, onde eram closures) antes da extração, para
que a lógica de empacotamento/ordenação de fila nunca mude silenciosamente.

Usa modules.planejador.Job diretamente como item de fila — o módulo
extraído não importa Job (evita import circular), mas aceita qualquer
objeto com os atributos name/fabric/length_m/is_gap, e Job é exatamente o
que a tela real usa.
"""
import unittest

from core.fabric_scraps import FabricScrap
from modules.planejador import Job
from modules.planejador_queue import (
    RollLimitConfig,
    eligible_scraps_for_fabric,
    fabric_block_sort_key,
    fabric_totals,
    generate_queue_rows,
    limit_for_roll,
    ordered_fabrics,
    pack_fabric_items,
    roll_limit_for,
    scrap_effective_length,
    scrap_match_for_roll,
)


def _job(name: str, fabric: str, length_m: float) -> Job:
    return Job(name=name, path=None, fabric=fabric, w_px=0, h_px=0, length_m=length_m)


def _cfg(
    *,
    fabrics_map=None,
    roll_other_m: float = 50.0,
    use_scraps: bool = False,
    scraps=None,
    selected_scrap_keys=None,
    bleed_m: float = 0.0,
) -> RollLimitConfig:
    return RollLimitConfig(
        fabrics_map=fabrics_map or {},
        roll_other_m=roll_other_m,
        use_scraps=use_scraps,
        scraps=scraps or [],
        selected_scrap_keys=selected_scrap_keys,
        bleed_m=bleed_m,
    )


class RollLimitForTests(unittest.TestCase):
    def test_uses_fabric_roll_length_when_registered(self):
        cfg = _cfg(fabrics_map={"DRYFIT": {"roll_length_m": 30.0}}, roll_other_m=50.0)
        self.assertEqual(roll_limit_for("DRYFIT", cfg), 30.0)

    def test_falls_back_to_roll_other_m_when_fabric_not_registered(self):
        cfg = _cfg(fabrics_map={}, roll_other_m=42.0)
        self.assertEqual(roll_limit_for("OXFORD", cfg), 42.0)

    def test_falls_back_to_roll_other_m_when_fabric_has_no_roll_length(self):
        cfg = _cfg(fabrics_map={"OXFORD": {}}, roll_other_m=42.0)
        self.assertEqual(roll_limit_for("OXFORD", cfg), 42.0)


class EligibleScrapsForFabricTests(unittest.TestCase):
    def test_returns_unused_scraps_sorted_by_length_desc(self):
        scraps = [
            FabricScrap(key="a", name="A", fabric="RIBANA", length_m=3.0),
            FabricScrap(key="b", name="B", fabric="RIBANA", length_m=8.0),
        ]
        cfg = _cfg(scraps=scraps)
        result = eligible_scraps_for_fabric("RIBANA", cfg)
        self.assertEqual([s.key for s in result], ["b", "a"])

    def test_excludes_used_scraps_and_other_fabrics(self):
        scraps = [
            FabricScrap(key="used", name="U", fabric="RIBANA", length_m=5.0, used=True),
            FabricScrap(key="other", name="O", fabric="OXFORD", length_m=5.0),
        ]
        cfg = _cfg(scraps=scraps)
        self.assertEqual(eligible_scraps_for_fabric("RIBANA", cfg), [])

    def test_selected_scrap_keys_restricts_to_marked_subset(self):
        scraps = [
            FabricScrap(key="a", name="A", fabric="RIBANA", length_m=5.0),
            FabricScrap(key="b", name="B", fabric="RIBANA", length_m=4.0),
        ]
        cfg = _cfg(scraps=scraps, selected_scrap_keys={"b"})
        result = eligible_scraps_for_fabric("RIBANA", cfg)
        self.assertEqual([s.key for s in result], ["b"])


class ScrapEffectiveLengthTests(unittest.TestCase):
    def test_adds_configured_bleed_to_registered_length(self):
        sc = FabricScrap(key="a", name="A", fabric="RIBANA", length_m=5.0)
        cfg = _cfg(bleed_m=0.05)
        self.assertAlmostEqual(scrap_effective_length(sc, cfg), 5.05)

    def test_no_bleed_returns_exact_registered_length(self):
        sc = FabricScrap(key="a", name="A", fabric="RIBANA", length_m=5.0)
        cfg = _cfg(bleed_m=0.0)
        self.assertEqual(scrap_effective_length(sc, cfg), 5.0)


class LimitForRollTests(unittest.TestCase):
    def test_without_scraps_always_uses_full_roll_length(self):
        cfg = _cfg(use_scraps=False, roll_other_m=20.0)
        self.assertEqual(limit_for_roll("RIBANA", 0, cfg), 20.0)
        self.assertEqual(limit_for_roll("RIBANA", 3, cfg), 20.0)

    def test_with_scraps_uses_scrap_length_for_early_rolls_then_falls_back(self):
        scraps = [
            FabricScrap(key="a", name="A", fabric="RIBANA", length_m=8.0),
            FabricScrap(key="b", name="B", fabric="RIBANA", length_m=3.0),
        ]
        cfg = _cfg(use_scraps=True, scraps=scraps, roll_other_m=20.0)
        self.assertEqual(limit_for_roll("RIBANA", 0, cfg), 8.0)
        self.assertEqual(limit_for_roll("RIBANA", 1, cfg), 3.0)
        self.assertEqual(limit_for_roll("RIBANA", 2, cfg), 20.0)

    def test_falls_back_to_default_roll_length_when_roll_other_m_is_zero(self):
        cfg = _cfg(use_scraps=False, roll_other_m=0.0)
        from core.fabrics import DEFAULT_ROLL_LENGTH_M
        self.assertEqual(limit_for_roll("RIBANA", 0, cfg), DEFAULT_ROLL_LENGTH_M)


class ScrapMatchForRollTests(unittest.TestCase):
    def test_returns_none_when_scraps_disabled(self):
        cfg = _cfg(use_scraps=False)
        self.assertIsNone(scrap_match_for_roll("RIBANA", 0, cfg))

    def test_returns_matching_scrap_by_roll_index(self):
        scraps = [FabricScrap(key="a", name="A", fabric="RIBANA", length_m=8.0)]
        cfg = _cfg(use_scraps=True, scraps=scraps)
        self.assertEqual(scrap_match_for_roll("RIBANA", 0, cfg).key, "a")
        self.assertIsNone(scrap_match_for_roll("RIBANA", 1, cfg))


class FabricBlockSortKeyTests(unittest.TestCase):
    def test_without_group_by_pedido_sorts_only_by_length_desc(self):
        big = _job("Cliente A - foo.jpg", "RIBANA", 5.0)
        small = _job("Cliente B - bar.jpg", "RIBANA", 2.0)
        ordered = sorted([small, big], key=lambda j: fabric_block_sort_key(j, group_by_pedido=False))
        self.assertEqual([j.name for j in ordered], [big.name, small.name])

    def test_with_group_by_pedido_groups_by_pedido_then_by_length_desc(self):
        # pedido_from_document só reconhece o formato "data - tecido - pedido"
        # (pelo menos 3 segmentos separados por " - "); com menos que isso
        # devolve "DESCONHECIDO" para todos, por isso os nomes de teste usam
        # esse formato completo em vez de um nome qualquer.
        a_small = _job("01-01 - RIBANA - Cliente A.jpg", "RIBANA", 1.0)
        a_big = _job("01-01 - RIBANA - Cliente A (2).jpg", "RIBANA", 4.0)
        b_item = _job("01-01 - RIBANA - Cliente B.jpg", "RIBANA", 9.0)
        ordered = sorted(
            [b_item, a_small, a_big], key=lambda j: fabric_block_sort_key(j, group_by_pedido=True)
        )
        self.assertEqual([j.name for j in ordered], [a_big.name, a_small.name, b_item.name])


class PackFabricItemsTests(unittest.TestCase):
    def test_single_roll_when_everything_fits(self):
        items = [_job("a.jpg", "RIBANA", 3.0), _job("b.jpg", "RIBANA", 2.0)]
        cfg = _cfg(roll_other_m=10.0)
        bins = pack_fabric_items("RIBANA", items, gap_endroll=0.5, gap_files=0.0, cfg=cfg, group_by_pedido=False)
        self.assertEqual(len(bins), 1)
        idx, bin_items = bins[0]
        self.assertEqual(idx, 0)
        self.assertEqual([j.name for j in bin_items], ["a.jpg", "b.jpg"])

    def test_splits_into_multiple_rolls_when_exceeding_limit(self):
        items = [_job("a.jpg", "RIBANA", 6.0), _job("b.jpg", "RIBANA", 6.0)]
        cfg = _cfg(roll_other_m=10.0)
        bins = pack_fabric_items("RIBANA", items, gap_endroll=0.0, gap_files=0.0, cfg=cfg, group_by_pedido=False)
        self.assertEqual(len(bins), 2)
        self.assertEqual([j.name for bi, items_ in bins for j in items_], ["a.jpg", "b.jpg"])

    def test_item_too_big_for_the_full_bin_overflows_into_the_next_smaller_scrap(self):
        # eligible_scraps_for_fabric sempre devolve os pedaços do maior pro
        # menor, então o pedaço 8.0 é sempre o rolo 0 e o 2.0 o rolo 1 — a
        # ordem dos pedaços na lista de entrada não importa. O item grande
        # (processado primeiro, first-fit decreasing) ocupa o pedaço 0; não
        # cabe mais nada depois dele ali (7.0 + 1.5 > 8.0), então o item
        # pequeno vai pro pedaço 1 — nunca o oposto, mesmo o pedaço 1 sendo
        # pequeno demais pro item grande (que por isso nem tenta ir lá).
        scraps = [
            FabricScrap(key="small", name="Pequeno", fabric="RIBANA", length_m=2.0),
            FabricScrap(key="big", name="Grande", fabric="RIBANA", length_m=8.0),
        ]
        cfg = _cfg(use_scraps=True, scraps=scraps)
        items = [_job("grande.jpg", "RIBANA", 7.0), _job("pequeno.jpg", "RIBANA", 1.5)]
        bins = pack_fabric_items("RIBANA", items, gap_endroll=0.0, gap_files=0.0, cfg=cfg, group_by_pedido=False)
        self.assertEqual(len(bins), 2)
        by_idx = {idx: [j.name for j in its] for idx, its in bins}
        self.assertEqual(by_idx[0], ["grande.jpg"])
        self.assertEqual(by_idx[1], ["pequeno.jpg"])

    def test_small_item_fills_remaining_room_in_an_already_open_bin(self):
        # Rolo aberto pelo item maior ainda tem espaço; um item pequeno
        # processado depois cabe nesse espaço em vez de abrir um rolo novo.
        scraps = [
            FabricScrap(key="a", name="A", fabric="RIBANA", length_m=8.0),
            FabricScrap(key="b", name="B", fabric="RIBANA", length_m=5.0),
        ]
        cfg = _cfg(use_scraps=True, scraps=scraps)
        items = [
            _job("grande.jpg", "RIBANA", 6.0),
            _job("medio.jpg", "RIBANA", 4.5),
            _job("pequeno.jpg", "RIBANA", 1.5),
        ]
        bins = pack_fabric_items("RIBANA", items, gap_endroll=0.0, gap_files=0.0, cfg=cfg, group_by_pedido=False)
        by_idx = {idx: [j.name for j in its] for idx, its in bins}
        self.assertEqual(by_idx[0], ["grande.jpg", "pequeno.jpg"])
        self.assertEqual(by_idx[1], ["medio.jpg"])

    def test_gap_files_counts_between_items_in_the_same_roll(self):
        items = [_job("a.jpg", "RIBANA", 4.0), _job("b.jpg", "RIBANA", 4.0)]
        cfg = _cfg(roll_other_m=8.5)
        # 4 + 4 + gap_files(0.5) = 8.5 cabe exatamente no rolo (sem gap_endroll)
        bins = pack_fabric_items("RIBANA", items, gap_endroll=0.0, gap_files=0.5, cfg=cfg, group_by_pedido=False)
        self.assertEqual(len(bins), 1)
        # Sem o gap_files a conta não fecha e sobra pouco demais pro segundo item
        bins2 = pack_fabric_items("RIBANA", items, gap_endroll=0.0, gap_files=0.6, cfg=cfg, group_by_pedido=False)
        self.assertEqual(len(bins2), 2)

    def test_empty_bins_are_never_returned(self):
        items = [_job("a.jpg", "RIBANA", 1.0)]
        cfg = _cfg(roll_other_m=10.0)
        bins = pack_fabric_items("RIBANA", items, gap_endroll=0.0, gap_files=0.0, cfg=cfg, group_by_pedido=False)
        self.assertEqual(len(bins), 1)
        self.assertTrue(all(items for _, items in bins))


class FabricTotalsTests(unittest.TestCase):
    def test_sums_length_by_fabric_ignoring_gaps(self):
        gap = _job("ESPAÇO", "RIBANA", 1.0)
        gap.is_gap = True
        items = [_job("a.jpg", "RIBANA", 3.0), _job("b.jpg", "OXFORD", 5.0), gap]
        totals = fabric_totals(items)
        self.assertEqual(totals, {"RIBANA": 3.0, "OXFORD": 5.0})


class OrderedFabricsTests(unittest.TestCase):
    def test_auto_order_sorts_by_total_length_desc(self):
        items = [_job("a.jpg", "RIBANA", 2.0), _job("b.jpg", "OXFORD", 9.0)]
        order, manual = ordered_fabrics(items, auto_order=True, manual_order=[])
        self.assertEqual(order, ["OXFORD", "RIBANA"])
        self.assertEqual(manual, [])  # ordem manual não é tocada no modo automático

    def test_manual_order_is_preserved_and_extended_with_new_fabrics(self):
        items = [_job("a.jpg", "RIBANA", 2.0), _job("b.jpg", "OXFORD", 9.0)]
        order, manual = ordered_fabrics(items, auto_order=False, manual_order=["RIBANA"])
        self.assertEqual(order, ["RIBANA", "OXFORD"])
        self.assertEqual(manual, ["RIBANA", "OXFORD"])

    def test_manual_order_drops_fabrics_no_longer_present(self):
        items = [_job("a.jpg", "RIBANA", 2.0)]
        order, manual = ordered_fabrics(items, auto_order=False, manual_order=["OXFORD", "RIBANA"])
        self.assertEqual(order, ["RIBANA"])
        self.assertEqual(manual, ["RIBANA"])

    def test_empty_queue_returns_empty_order_and_untouched_manual_order(self):
        order, manual = ordered_fabrics([], auto_order=False, manual_order=["RIBANA"])
        self.assertEqual(order, [])
        self.assertEqual(manual, ["RIBANA"])


class GenerateQueueRowsTests(unittest.TestCase):
    """generate_queue_rows é a orquestração completa que antes só existia
    como modules.planejador.py:build_ui.generate_queue (closures sobre
    variáveis Tk) — estes casos não são só regressão das peças menores
    (já cobertas acima), são a prova de que a montagem da fila inteira
    (gaps entre tecidos/fim de rolo/entre arquivos, numeração de rolo,
    pedaço usado por rolo) continua igual depois de virar uma função pura
    com estado explícito (gap_seq/gap_overrides) em vez de nonlocal."""

    def test_single_roll_mode_ignores_gaps_and_keeps_everything_in_roll_one(self):
        items = [_job("a.jpg", "RIBANA", 3.0), _job("b.jpg", "OXFORD", 5.0)]
        result = generate_queue_rows(
            items, job_cls=Job, single_roll=True, mode="",
            gap_between=1.0, gap_endroll=1.0, gap_files=1.0, speed=1.0,
            cfg=_cfg(), group_by_pedido=False, gap_overrides={},
        )
        self.assertEqual([j.name for j in result.planned], ["a.jpg", "b.jpg"])
        self.assertTrue(all(j.roll_no == 1 and not j.is_gap for j in result.planned))
        self.assertEqual(result.roll_scrap_matches, {})

    def test_import_order_mode_inserts_gap_between_fabric_change(self):
        # gap_endroll=0.0 de propósito: sem ele, não há gap de "fim de fila"
        # depois do último tecido — só o gap_between no meio, da troca de
        # tecido, que é o que este caso quer isolar.
        items = [_job("a.jpg", "RIBANA", 3.0), _job("b.jpg", "OXFORD", 2.0)]
        cfg = _cfg(roll_other_m=10.0)
        result = generate_queue_rows(
            items, job_cls=Job, single_roll=False, mode="arquivo",
            gap_between=1.0, gap_endroll=0.0, gap_files=0.0, speed=2.0,
            cfg=cfg, group_by_pedido=False, gap_overrides={},
        )
        kinds = [(j.name, j.is_gap, j.roll_no) for j in result.planned]
        self.assertEqual(
            kinds,
            [("a.jpg", False, 1), ("ESPAÇO", True, 0), ("b.jpg", False, 2)],
        )
        gap = result.planned[1]
        self.assertEqual(gap.length_m, 1.0)  # gap_between, trocou de RIBANA pra OXFORD
        self.assertEqual(gap.gap_index, 0)
        self.assertEqual(gap.fabric, "RIBANA")  # o gap pertence ao bloco que terminou
        self.assertEqual(gap.time_min, 0.5)  # 1.0 m / speed(2.0)

    def test_import_order_mode_overflows_into_a_new_roll_using_the_next_scrap(self):
        # Mesmo cenário documentado em limit_for_roll: dois pedaços cortados
        # (8.0 e 2.0, sempre nessa ordem — do maior pro menor) e dois itens
        # que juntos não cabem no pedaço de 8.0; o segundo item nem cabe no
        # pedaço de 2.0, então acaba num terceiro rolo (rolo cheio padrão).
        scraps = [
            FabricScrap(key="small", name="Pequeno", fabric="RIBANA", length_m=2.0),
            FabricScrap(key="big", name="Grande", fabric="RIBANA", length_m=8.0),
        ]
        cfg = _cfg(use_scraps=True, scraps=scraps, roll_other_m=20.0)
        items = [_job("x.jpg", "RIBANA", 7.0), _job("y.jpg", "RIBANA", 3.0)]
        result = generate_queue_rows(
            items, job_cls=Job, single_roll=False, mode="arquivo",
            gap_between=1.0, gap_endroll=0.5, gap_files=0.0, speed=1.0,
            cfg=cfg, group_by_pedido=False, gap_overrides={},
        )
        rows = [(j.name, j.is_gap, j.roll_no, round(j.length_m, 2), j.gap_index) for j in result.planned]
        self.assertEqual(
            rows,
            [
                ("x.jpg", False, 1, 7.0, None),
                ("ESPAÇO", True, 0, 0.5, 0),
                ("y.jpg", False, 3, 3.0, None),
                ("ESPAÇO", True, 0, 0.5, 1),
            ],
        )
        # Rolo 1 usou o pedaço grande; rolo 3 não usou pedaço nenhum (o
        # pequeno não cabia 3.0, caiu pro rolo cheio padrão de 20.0) — e o
        # rolo 2 nunca chegou a existir (nenhum item coube nele).
        self.assertEqual(set(result.roll_scrap_matches.keys()), {1})
        self.assertEqual(result.roll_scrap_matches[1].key, "big")

    def test_gap_overrides_replaces_the_computed_length_of_a_specific_gap(self):
        items = [_job("a.jpg", "RIBANA", 3.0), _job("b.jpg", "OXFORD", 2.0)]
        cfg = _cfg(roll_other_m=10.0)
        result = generate_queue_rows(
            items, job_cls=Job, single_roll=False, mode="arquivo",
            gap_between=1.0, gap_endroll=0.0, gap_files=0.0, speed=2.0,
            cfg=cfg, group_by_pedido=False, gap_overrides={0: 0.25},
        )
        gaps = [j for j in result.planned if j.is_gap]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].gap_index, 0)
        self.assertEqual(gaps[0].length_m, 0.25)

    def test_fabric_mode_bin_packs_per_fabric_with_gaps_between_blocks_and_rolls(self):
        oxford = _job("o1.jpg", "OXFORD", 4.0)
        ribana1 = _job("r1.jpg", "RIBANA", 6.0)
        ribana2 = _job("r2.jpg", "RIBANA", 6.0)
        cfg = _cfg(roll_other_m=10.0)
        result = generate_queue_rows(
            [oxford, ribana1, ribana2], job_cls=Job, single_roll=False, mode="tecido",
            gap_between=1.0, gap_endroll=0.5, gap_files=0.0, speed=1.0,
            cfg=cfg, group_by_pedido=False, gap_overrides={},
            fabrics_order=["OXFORD", "RIBANA"],
        )
        rows = [(j.name, j.is_gap, j.roll_no) for j in result.planned]
        self.assertEqual(
            rows,
            [
                ("o1.jpg", False, 1),
                ("ESPAÇO", True, 0),   # gap_between: fim do bloco OXFORD
                ("r1.jpg", False, 2),
                ("ESPAÇO", True, 0),   # gap_endroll: entre os 2 rolos de RIBANA
                ("r2.jpg", False, 3),
                ("ESPAÇO", True, 0),   # gap_endroll: fim do último tecido
            ],
        )
        self.assertEqual([round(j.length_m, 2) for j in result.planned if j.is_gap], [1.0, 0.5, 0.5])

    def test_fabric_mode_with_no_items_returns_nothing(self):
        result = generate_queue_rows(
            [], job_cls=Job, single_roll=False, mode="tecido",
            gap_between=1.0, gap_endroll=1.0, gap_files=1.0, speed=1.0,
            cfg=_cfg(), group_by_pedido=False, gap_overrides={}, fabrics_order=[],
        )
        self.assertEqual(result.planned, [])
        self.assertEqual(result.roll_scrap_matches, {})


if __name__ == "__main__":
    unittest.main()
