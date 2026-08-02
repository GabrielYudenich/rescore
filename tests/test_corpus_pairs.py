import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from rescore.corpus_pairs import discover_supervised_candidates


class CorpusPairTests(unittest.TestCase):
    def test_discovers_archive_pair_without_public_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "secret-work"
            source.mkdir()
            with zipfile.ZipFile(source / "private-pdfs.zip", "w") as archive:
                archive.writestr("named movement.pdf", b"pdf")
            with zipfile.ZipFile(source / "private-editables.zip", "w") as archive:
                archive.writestr("named movement.mscz", b"score")
            output = root / "output"
            result = discover_supervised_candidates(root, output)
            public = json.loads((output / "supervised-candidates.json").read_text())
            serialized = json.dumps(public)
            self.assertEqual(result["summary"]["strong_candidates"], 1)
            self.assertNotIn("secret-work", serialized)
            self.assertNotIn("named movement", serialized)
            self.assertFalse(public["candidates"][0]["training_eligible"])

    def test_rejects_unsafe_archive_member(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            with zipfile.ZipFile(source / "unsafe.zip", "w") as archive:
                archive.writestr("../escape.musicxml", b"score")
            result = discover_supervised_candidates(source, root / "output")
            self.assertEqual(result["summary"]["errors"], 1)
            self.assertEqual(result["summary"]["candidates"], 0)


if __name__ == "__main__":
    unittest.main()
