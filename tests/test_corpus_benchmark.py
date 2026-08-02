import json
import tempfile
import unittest
from pathlib import Path

from rescore.corpus_benchmark import build_corpus_benchmark


class CorpusBenchmarkTests(unittest.TestCase):
    def test_builds_private_free_aggregate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            curriculum = root / "curriculum.json"
            pairs = root / "pairs.json"
            probes = root / "probes.json"
            output = root / "benchmark.json"
            curriculum.write_text(json.dumps({"summary": {"samples": 2}}))
            pairs.write_text(json.dumps({"summary": {"candidates": 1}}))
            probes.write_text(
                json.dumps(
                    {
                        "probes": [
                            {
                                "cluster": 0,
                                "sample_id": "anonymous",
                                "split": "test",
                                "origin": "raster",
                                "distance": 0.1,
                                "status": "recognized",
                                "elapsed_seconds": 2,
                                "metrics": {
                                    "parts": 1,
                                    "measures": 2,
                                    "pitched_events": 3,
                                    "time_signatures": 1,
                                },
                                "training_eligible": False,
                            }
                        ]
                    }
                )
            )
            report = build_corpus_benchmark(curriculum, pairs, probes, output)
            self.assertEqual(report["recognition_rate"], 1.0)
            self.assertTrue(report["privacy"]["valid"])
            self.assertNotIn(str(root), output.read_text())


if __name__ == "__main__":
    unittest.main()
