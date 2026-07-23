import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from rescore.scan import suppress_cross_staff_annotations


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


if __name__ == "__main__":
    unittest.main()
