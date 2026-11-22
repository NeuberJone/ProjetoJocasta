"""Testes de modules.planejador_export — segunda parte do item de roadmap
(Fase 3) "extrair cálculo/organização de fila do Planejador e coordenação
dos relatórios para serviços menores" (a primeira parte, bin
packing/montagem da fila, já está em tests/test_planejador_queue.py).

Cobre só as DECISÕES de modules/planejador.py:build_ui.on_export que são
seguras de isolar sem gravar nada em disco/banco: quais arquivos gerar pra
cada combinação de `which`/pasta de impressora, qual tecido é o
predominante de um rolo, e se um pedaço cortado deixou de caber depois de
editar um rolo.
"""
import unittest

from core.fabric_scraps import FabricScrap
from modules.planejador_queue import RollLimitConfig
from modules.planejador_export import (
    ROLE_MIRROR,
    ROLE_NORMAL,
    ROLE_TMP_MIRROR_PDF,
    ROLE_TMP_NORMAL_PDF,
    decide_scrap_revert,
    main_fabric_of,
    plan_export_steps,
)


def _cfg(*, scraps=None, bleed_m: float = 0.0) -> RollLimitConfig:
    return RollLimitConfig(
        fabrics_map={}, roll_other_m=50.0, use_scraps=False,
        scraps=scraps or [], selected_scrap_keys=None, bleed_m=bleed_m,
    )


class PlanExportStepsTests(unittest.TestCase):
    def test_normal_generates_only_the_normal_pdf(self):
        steps = plan_export_steps("normal", use_printer_folder=False)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].kind, "pdf")
        self.assertFalse(steps[0].mirrored)
        self.assertEqual(steps[0].dest, ROLE_NORMAL)

    def test_normal_ignores_use_printer_folder(self):
        self.assertEqual(
            plan_export_steps("normal", use_printer_folder=True),
            plan_export_steps("normal", use_printer_folder=False),
        )

    def test_mirror_without_printer_folder_uses_only_the_mirror_pdf_as_jpg_source(self):
        steps = plan_export_steps("mirror", use_printer_folder=False)
        kinds = [(s.kind, s.dest, s.mirrored, s.sources) for s in steps]
        self.assertEqual(
            kinds,
            [
                ("pdf", ROLE_TMP_MIRROR_PDF, True, ()),
                ("jpg", ROLE_MIRROR, False, (ROLE_TMP_MIRROR_PDF,)),
                ("cleanup", ROLE_TMP_MIRROR_PDF, False, ()),
            ],
        )

    def test_mirror_with_printer_folder_also_builds_and_cleans_a_temp_normal_pdf(self):
        # Diferente do modo "both": aqui o PDF normal não é uma entrega de
        # verdade (não existe ROLE_NORMAL no plano) — é só um temporário pra
        # compor o JPG final (espelhado + normal), por isso usa
        # ROLE_TMP_NORMAL_PDF e precisa de uma limpeza própria.
        steps = plan_export_steps("mirror", use_printer_folder=True)
        kinds = [(s.kind, s.dest, s.mirrored, s.sources) for s in steps]
        self.assertEqual(
            kinds,
            [
                ("pdf", ROLE_TMP_MIRROR_PDF, True, ()),
                ("pdf", ROLE_TMP_NORMAL_PDF, False, ()),
                ("jpg", ROLE_MIRROR, False, (ROLE_TMP_NORMAL_PDF, ROLE_TMP_MIRROR_PDF)),
                ("cleanup", ROLE_TMP_NORMAL_PDF, False, ()),
                ("cleanup", ROLE_TMP_MIRROR_PDF, False, ()),
            ],
        )
        self.assertNotIn(ROLE_NORMAL, [s.dest for s in steps] + [r for s in steps for r in s.sources])

    def test_both_without_printer_folder_builds_normal_and_mirror_pdfs_and_jpg_from_mirror_only(self):
        steps = plan_export_steps("both", use_printer_folder=False)
        kinds = [(s.kind, s.dest, s.mirrored, s.sources) for s in steps]
        self.assertEqual(
            kinds,
            [
                ("pdf", ROLE_NORMAL, False, ()),
                ("pdf", ROLE_TMP_MIRROR_PDF, True, ()),
                ("jpg", ROLE_MIRROR, False, (ROLE_TMP_MIRROR_PDF,)),
                ("cleanup", ROLE_TMP_MIRROR_PDF, False, ()),
            ],
        )

    def test_both_with_printer_folder_uses_the_real_normal_pdf_as_jpg_source_not_a_temp_copy(self):
        # Diferente do modo "mirror": aqui o PDF normal já é uma entrega de
        # verdade (ROLE_NORMAL) — serve de origem pro JPG final sem precisar
        # de um ROLE_TMP_NORMAL_PDF à parte, e por isso não há limpeza dele.
        steps = plan_export_steps("both", use_printer_folder=True)
        kinds = [(s.kind, s.dest, s.mirrored, s.sources) for s in steps]
        self.assertEqual(
            kinds,
            [
                ("pdf", ROLE_NORMAL, False, ()),
                ("pdf", ROLE_TMP_MIRROR_PDF, True, ()),
                ("jpg", ROLE_MIRROR, False, (ROLE_NORMAL, ROLE_TMP_MIRROR_PDF)),
                ("cleanup", ROLE_TMP_MIRROR_PDF, False, ()),
            ],
        )
        self.assertNotIn(ROLE_TMP_NORMAL_PDF, [s.dest for s in steps])

    def test_unknown_which_generates_nothing(self):
        self.assertEqual(plan_export_steps("", use_printer_folder=False), [])
        self.assertEqual(plan_export_steps("csv", use_printer_folder=True), [])


class MainFabricOfTests(unittest.TestCase):
    def test_returns_the_most_frequent_fabric(self):
        class J:
            def __init__(self, fabric):
                self.fabric = fabric

        jobs = [J("RIBANA"), J("OXFORD"), J("RIBANA"), J("RIBANA")]
        self.assertEqual(main_fabric_of(jobs), "RIBANA")

    def test_ties_go_to_the_fabric_that_appears_first(self):
        class J:
            def __init__(self, fabric):
                self.fabric = fabric

        jobs = [J("OXFORD"), J("RIBANA"), J("OXFORD"), J("RIBANA")]
        self.assertEqual(main_fabric_of(jobs), "OXFORD")


class DecideScrapRevertTests(unittest.TestCase):
    def test_no_previous_scrap_key_never_reverts(self):
        self.assertEqual(decide_scrap_revert("", [], 10.0, _cfg()), ("", False))

    def test_still_fits_keeps_the_scrap_key_unchanged(self):
        scraps = [FabricScrap(key="a", name="A", fabric="RIBANA", length_m=10.0)]
        result = decide_scrap_revert("a", scraps, total_m=8.0, cfg=_cfg(scraps=scraps))
        self.assertEqual(result, ("a", False))

    def test_exceeding_the_scrap_length_reverts_to_no_scrap(self):
        scraps = [FabricScrap(key="a", name="A", fabric="RIBANA", length_m=5.0)]
        result = decide_scrap_revert("a", scraps, total_m=6.0, cfg=_cfg(scraps=scraps))
        self.assertEqual(result, ("", True))

    def test_exceeding_only_because_of_bleed_still_reverts(self):
        scraps = [FabricScrap(key="a", name="A", fabric="RIBANA", length_m=5.0)]
        cfg = _cfg(scraps=scraps, bleed_m=0.0)
        # 5.05 cabe com sangria de 0.05 m habilitada (efetivo = 5.05)...
        cfg_with_bleed = _cfg(scraps=scraps, bleed_m=0.05)
        self.assertEqual(decide_scrap_revert("a", scraps, 5.03, cfg_with_bleed), ("a", False))
        # ...mas não cabe mais sem ela (efetivo = 5.0 exato, 5.03 > 5.0).
        self.assertEqual(decide_scrap_revert("a", scraps, 5.03, cfg), ("", True))

    def test_scrap_key_no_longer_registered_is_treated_as_not_fitting_info_but_does_not_crash(self):
        # Pedaço referenciado não existe mais na lista atual de pedaços
        # (ex.: removido manualmente) — sc vira None, condição "sc and..."
        # é falsa, então não reverte (preserva o scrap_key como estava,
        # mesmo comportamento do código original: só reverte quando acha o
        # pedaço E ele não cabe mais).
        result = decide_scrap_revert("removido", [], total_m=100.0, cfg=_cfg())
        self.assertEqual(result, ("removido", False))


if __name__ == "__main__":
    unittest.main()
