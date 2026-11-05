import unittest

from PIL import Image

from modules.operacao.exporters import _apply_rotation


class ApplyRotationTests(unittest.TestCase):
    """Orientação do JPG de registro (Configurações · Operação/Planejador) —
    0/90/180/270, girando sem reamostrar já que é sempre reta."""

    def setUp(self):
        self.img = Image.new("RGB", (40, 100), "white")

    def test_zero_degrees_keeps_image_unchanged(self):
        out = _apply_rotation(self.img, 0)
        self.assertEqual(out.size, (40, 100))
        self.assertIs(out, self.img)

    def test_90_and_270_swap_width_and_height(self):
        for degrees in (90, 270):
            out = _apply_rotation(self.img, degrees)
            self.assertEqual(out.size, (100, 40), degrees)

    def test_180_keeps_dimensions(self):
        out = _apply_rotation(self.img, 180)
        self.assertEqual(out.size, (40, 100))

    def test_negative_and_over_360_normalize(self):
        self.assertEqual(_apply_rotation(self.img, -90).size, _apply_rotation(self.img, 270).size)
        self.assertEqual(_apply_rotation(self.img, 450).size, _apply_rotation(self.img, 90).size)


if __name__ == "__main__":
    unittest.main()
