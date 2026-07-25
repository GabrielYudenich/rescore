import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from rescore.scan import (
    CHOROS9_STAFF_CENTER_FRACTIONS,
    create_choros9_family_crops,
    suppress_cross_staff_annotations,
)


class ScanAnnotationTests(unittest.TestCase):
    def _score_image(self) -> np.ndarray:
        image = np.full((620, 920), 255, dtype=np.uint8)
        for staff_top in (90, 250, 410):
            for offset in range(5):
                y = staff_top + offset * 12
                cv2.line(image, (50, y), (870, y), 0, 2)
        return image

    def test_preserves_normal_hairpin(self):
        image = self._score_image()
        cv2.line(image, (300, 180), (520, 187), 0, 3)
        cv2.line(image, (300, 194), (520, 187), 0, 3)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.png"
            output = Path(folder) / "output.png"
            cv2.imwrite(str(source), image)
            report = suppress_cross_staff_annotations(source, output)
            result = cv2.imread(str(output), cv2.IMREAD_GRAYSCALE)
        self.assertEqual(report["annotations_detected"], 0)
        self.assertEqual(int(result[187, 520]), 0)

    def test_removes_continuous_wedge_crossing_staves(self):
        image = self._score_image()
        cv2.line(image, (280, 180), (760, 270), 0, 8)
        cv2.line(image, (280, 360), (760, 270), 0, 8)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.png"
            output = Path(folder) / "output.png"
            cv2.imwrite(str(source), image)
            report = suppress_cross_staff_annotations(source, output)
            result = cv2.imread(str(output), cv2.IMREAD_GRAYSCALE)
        self.assertEqual(report["annotations_detected"], 1)
        self.assertGreater(report["pixels_removed"], 500)
        self.assertGreater(int(result[225, 520]), 240)
        # A staff line crossed by the annotation is reconstructed.
        self.assertLess(int(result[274, 760]), 20)

    def test_creates_zoomed_family_crops_from_orchestral_grid(self):
        image = np.full((2400, 1200), 255, dtype=np.uint8)
        first_centre = 100
        last_centre = 2200
        centres = [
            first_centre + fraction * (last_centre - first_centre)
            for fraction in CHOROS9_STAFF_CENTER_FRACTIONS
        ]
        for centre in centres:
            for offset in (-16, -8, 0, 8, 16):
                y = int(round(centre + offset))
                cv2.line(image, (70, y), (1130, y), 0, 1)
        for column in (200, 600, 1000):
            cv2.line(image, (column, 70), (column, 2230), 0, 2)

        report = {
            "barline_columns": [200, 600, 1000],
            "annotation_filter": {"interline": 8.0},
        }
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.png"
            output = Path(folder) / "families"
            cv2.imwrite(str(source), image)
            result = create_choros9_family_crops(source, report, output, scale=2.0)
            keys_harp = cv2.imread(
                result["families"]["keys-harp"]["path"],
                cv2.IMREAD_GRAYSCALE,
            )
            strings = cv2.imread(
                result["families"]["strings"]["path"],
                cv2.IMREAD_GRAYSCALE,
            )

        self.assertGreaterEqual(result["detected_staff_groups"], 20)
        self.assertEqual(result["families"]["keys-harp"]["expected_staves"], 4)
        self.assertEqual(result["families"]["strings"]["expected_staves"], 5)
        self.assertIsNotNone(keys_harp)
        self.assertIsNotNone(strings)
        self.assertEqual(keys_harp.shape[1], 2400)
        self.assertEqual(strings.shape[1], 2400)


if __name__ == "__main__":
    unittest.main()
