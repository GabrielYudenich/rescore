import unittest

from rescore.corpus_probe import select_representatives


class CorpusProbeTests(unittest.TestCase):
    def test_prefers_test_representative_nearest_center(self):
        curriculum = {
            "visual_model": {
                "mean": [0.0],
                "scale": [1.0],
                "centers": [[0.0]],
            },
            "samples": [
                {"sample_id": "train", "style_cluster": 0, "split": "train", "origin": "digital", "features": [0.0]},
                {"sample_id": "far", "style_cluster": 0, "split": "test", "origin": "raster", "features": [2.0]},
                {"sample_id": "near", "style_cluster": 0, "split": "test", "origin": "raster", "features": [1.0]},
            ],
        }
        selected = select_representatives(curriculum)
        self.assertEqual(selected[0]["sample_id"], "near")
        self.assertEqual(selected[0]["split"], "test")


if __name__ == "__main__":
    unittest.main()
