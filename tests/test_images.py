import tempfile
import unittest
from pathlib import Path

from PIL import Image

from rescore.images import normalize_score_orientation, prepare_omr_image


class ImageTests(unittest.TestCase):
    def test_prepare_omr_image_caps_pixels_and_writes_png(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jpg"
            output = root / "prepared.png"
            Image.new("RGB", (2000, 1000), "white").save(source)
            report = prepare_omr_image(source, output, max_pixels=500_000)
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                self.assertLessEqual(image.width * image.height, 500_000)
            self.assertTrue(report["resized"])
            self.assertEqual(report["original_size"], [2000, 1000])

    def test_rotates_vertical_staff_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sideways.png"
            image = Image.new("RGB", (600, 800), "white")
            for x in range(100, 500, 20):
                for y in range(50, 750):
                    image.putpixel((x, y), (0, 0, 0))
            image.save(path)
            report = normalize_score_orientation(path)
            with Image.open(path) as oriented:
                self.assertEqual(oriented.size, (800, 600))
            self.assertIn(report["rotation_degrees"], {-90, 90})


if __name__ == "__main__":
    unittest.main()
