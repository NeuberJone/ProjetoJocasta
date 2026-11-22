import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.fabrics import canonical_fabric_name, infer_fabric_from_filename, load_fabrics, register_fabric_name


class CanonicalFabricNameTests(unittest.TestCase):
    def setUp(self):
        self.fabrics_map = {
            "Dryfit": {"aliases": ["dryfit", "dry fit", "dry-fit", "drifit"], "roll_length_m": 90.0},
            "Jaquard Corinthians": {"aliases": ["CORINTHIANS"], "roll_length_m": 60.0},
        }

    def test_matches_canonical_name_case_insensitive(self):
        self.assertEqual(canonical_fabric_name("dryfit", self.fabrics_map), "Dryfit")

    def test_matches_alias_with_different_spacing(self):
        self.assertEqual(canonical_fabric_name("Dry Fit", self.fabrics_map), "Dryfit")
        self.assertEqual(canonical_fabric_name("DRY-FIT", self.fabrics_map), "Dryfit")

    def test_matches_alias_regardless_of_case(self):
        self.assertEqual(canonical_fabric_name("corinthians", self.fabrics_map), "Jaquard Corinthians")

    def test_unregistered_name_returns_empty(self):
        self.assertEqual(canonical_fabric_name("Tecido Novo", self.fabrics_map), "")

    def test_substring_does_not_match(self):
        # "Dry" sozinho não deve casar com "Dryfit" (evita falsos positivos).
        self.assertEqual(canonical_fabric_name("Dry", self.fabrics_map), "")

    def test_empty_input_returns_empty(self):
        self.assertEqual(canonical_fabric_name("", self.fabrics_map), "")


class InferFabricFromFilenameTests(unittest.TestCase):
    """Reconhecimento de tecido em nomes de arquivo — tanto na convenção
    estruturada dos logs ("data - tecido - pedido") quanto em fotos soltas,
    sem deixar substring solta casar errado (pedido real do usuário:
    "Favo"/"Madri" só devem casar se estiverem cadastrados)."""

    def setUp(self):
        self.fabrics_map = {
            "Favo": {"aliases": [], "roll_length_m": 60.0},
            "Madri": {"aliases": [], "roll_length_m": 60.0},
            "Telinha": {"aliases": [], "roll_length_m": 60.0},
            "Ribana": {"aliases": [], "roll_length_m": 60.0},
            "Faixa de Capitão": {"aliases": ["faixa cap"], "roll_length_m": 60.0},
            "Crepe": {"aliases": [], "roll_length_m": 60.0},
        }

    def test_structured_name_uses_positional_segment(self):
        self.assertEqual(
            infer_fabric_from_filename(
                "13-11 - Favo - Escolinha Douglas América 2 (Barcelona).jpeg", self.fabrics_map
            ),
            "Favo",
        )
        self.assertEqual(
            infer_fabric_from_filename(
                "13-11 - Telinha - Escolinha Douglas América 2.jpeg", self.fabrics_map
            ),
            "Telinha",
        )
        self.assertEqual(
            infer_fabric_from_filename(
                "13-11 - Madri - Escolinha Douglas América 2.jpeg", self.fabrics_map
            ),
            "Madri",
        )
        self.assertEqual(
            infer_fabric_from_filename("13-11 - Ribana - Pedido.jpeg", self.fabrics_map),
            "Ribana",
        )

    def test_unregistered_fabric_in_positional_segment_falls_back_to_outro(self):
        self.assertEqual(
            infer_fabric_from_filename("13-11 - TecidoNuncaVisto - Pedido.jpeg", self.fabrics_map),
            "Outro",
        )

    def test_loose_photo_matches_exact_token(self):
        self.assertEqual(infer_fabric_from_filename("foto_ribana_01.jpg", self.fabrics_map), "Ribana")

    def test_loose_photo_matches_multiword_alias_by_word_boundary(self):
        self.assertEqual(
            infer_fabric_from_filename("faixa cap azul.jpg", self.fabrics_map), "Faixa de Capitão"
        )

    def test_short_alias_does_not_match_inside_unrelated_word(self):
        # "crepe" não deve casar dentro de "discrepeancia" (nome inventado,
        # só pra garantir que não é um "contém" solto).
        self.assertEqual(
            infer_fabric_from_filename("foto_discrepeancia_01.jpg", self.fabrics_map), "Outro"
        )

    def test_unknown_filename_returns_outro(self):
        self.assertEqual(infer_fabric_from_filename("IMG_0001.jpg", self.fabrics_map), "Outro")


class RegisterFabricNameTests(unittest.TestCase):
    """register_fabric_name — cadastro compartilhado usado tanto pelo
    Planejador quanto pela Operação (ver modules/planejador.py
    register_new_fabric e modules/operacao/ui.py _canonicalize_fabric_name)."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.store_path = Path(self._tmp_dir.name) / "fabrics.json"
        self._patcher = patch("core.fabrics._fabrics_store_path", return_value=self.store_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def test_registers_brand_new_fabric(self):
        canonical = register_fabric_name("Oxford Premium")
        self.assertEqual(canonical, "Oxford Premium")
        self.assertIn("Oxford Premium", load_fabrics())

    def test_reuses_existing_entry_case_insensitively(self):
        register_fabric_name("Oxford Premium")
        before = len(load_fabrics())

        canonical = register_fabric_name("oxford premium")
        self.assertEqual(canonical, "Oxford Premium")
        self.assertEqual(len(load_fabrics()), before)

    def test_blank_name_raises(self):
        with self.assertRaises(ValueError):
            register_fabric_name("   ")


if __name__ == "__main__":
    unittest.main()
