import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image

from rescore.pdf import render_pages


class PdfTests(unittest.TestCase):
    def test_render_pages_caps_all_pages_to_a_common_safe_dpi(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "large.pdf"
            with fitz.open() as document:
                document.new_page(width=1000, height=2000)
                document.new_page(width=2000, height=3000)
                document.save(source)

            outputs = render_pages(
                source, "1-2", root / "pages", dpi=300, max_pixels=1_000_000
            )

            sizes = []
            for output in outputs:
                with Image.open(output) as image:
                    sizes.append(image.size)
                    self.assertLessEqual(image.width * image.height, 1_000_000)
            self.assertEqual(sizes[0][0] * 2, sizes[1][0])

    def test_render_pages_rejects_non_positive_pixel_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "page.pdf"
            with fitz.open() as document:
                document.new_page()
                document.save(source)
            with self.assertRaisesRegex(ValueError, "max_pixels"):
                render_pages(source, "1", root / "pages", max_pixels=0)


if __name__ == "__main__":
    unittest.main()
