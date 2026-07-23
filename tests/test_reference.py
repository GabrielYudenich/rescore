import unittest
from pathlib import Path

from rescore.mscz import inspect_mscz
from rescore.musicxml import parse_musicxml


ROOT = Path(__file__).resolve().parents[1]


class ReferenceTests(unittest.TestCase):
    def test_reference_mscz_structure(self):
        path = ROOT / "III. Scherzo.mscz"
        if not path.exists():
            self.skipTest("gabarito .mscz não está presente")
        summary = inspect_mscz(path)
        self.assertEqual(summary["parts_count"], 30)
        self.assertEqual(summary["staves_count"], 34)
        self.assertEqual(summary["measures"], 8)

    def test_reference_musicxml_structure(self):
        path = ROOT / "III. Scherzo (descompactado).musicxml"
        if not path.exists():
            self.skipTest("gabarito MusicXML não está presente")
        score = parse_musicxml(path)
        self.assertEqual(score["parts_count"], 30)
        self.assertEqual(score["measures"], 8)
        self.assertGreater(score["events_count"], 100)


if __name__ == "__main__":
    unittest.main()
