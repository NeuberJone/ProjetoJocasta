import unittest

from core import theme
from core.ui import columns_for_width, make_status_text, page_metrics


class ThemeContractTests(unittest.TestCase):
    def test_prototype_exposes_all_eight_themes_in_order(self):
        self.assertEqual(
            theme.theme_keys_ordered(),
            ["dark", "light", "mid", "dracula", "nord", "solarized", "xp", "win98"],
        )
        for key in theme.theme_keys_ordered():
            spec = theme.get_spec(key)
            self.assertTrue(spec.bg)
            self.assertTrue(spec.panel)
            self.assertTrue(spec.brand)

    def test_picker_shows_every_theme_with_prototype_description(self):
        self.assertEqual(sorted(theme.theme_keys_for_picker()), sorted(theme.theme_keys_ordered()))
        for key in theme.theme_keys_for_picker():
            self.assertTrue(theme.get_spec(key).description)

    def test_prototype_tokens_fall_back_to_base_palette(self):
        dark = theme.get_spec("dark")
        self.assertEqual(theme.tok(dark, "field_bg"), dark.panel)
        self.assertEqual(theme.tok(dark, "heading_bg"), dark.bg)
        self.assertEqual(theme.tok(dark, "nav_active_fg"), dark.brand)
        self.assertEqual(theme.tok(theme.get_spec("xp"), "primary_bg"), "#328e2d")
        self.assertEqual(theme.tok(theme.get_spec("win98"), "table_bg"), "#ffffff")

    def test_retro_themes_keep_retro_widget_contract(self):
        self.assertEqual(theme.get_spec("xp").font_family, "Tahoma")
        self.assertEqual(theme.get_spec("win98").font_family, "Tahoma")
        self.assertEqual(theme.get_spec("xp").relief, "raised")
        self.assertTrue(theme.get_spec("win98").square)

    def test_status_text_has_prototype_structure(self):
        self.assertEqual(make_status_text("Fila pronta", "1 rolo", "39,59 m"),
                         "Fila pronta · 1 rolo · 39,59 m")


    def test_page_metrics_follow_prototype_spacing_contract(self):
        self.assertEqual(page_metrics(), {
            "page_pad": (28, 22, 28, 18),
            "section_gap": 14,
            "card_pad": 14,
            "control_gap": 8,
        })

    def test_responsive_columns_do_not_overflow(self):
        self.assertEqual(columns_for_width(900, minimum=280, maximum=3), 3)
        self.assertEqual(columns_for_width(540, minimum=280, maximum=3), 1)


if __name__ == "__main__":
    unittest.main()
