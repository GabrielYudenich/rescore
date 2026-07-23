import tempfile
import unittest
from pathlib import Path

from rescore.musicxml import compare_scores, parse_musicxml


SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Flute 1</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>2</divisions><time><beats>3</beats><beat-type>4</beat-type></time></attributes>
    <note><pitch><step>C</step><octave>5</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><notations><ornaments><tremolo type="single">3</tremolo></ornaments></notations><lyric number="1"><syllabic>begin</syllabic><text>Sum</text><extend type="start"/></lyric></note>
    <note><rest/><duration>4</duration><voice>1</voice><type>half</type></note>
  </measure></part>
</score-partwise>
"""


class MusicXmlTests(unittest.TestCase):
    def test_parse_and_compare(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "score.musicxml"
            path.write_text(SCORE, encoding="utf-8")
            score = parse_musicxml(path)
        self.assertEqual(score["parts_count"], 1)
        self.assertEqual(score["events_count"], 1)
        self.assertEqual(score["events"][0]["pitch"], "C5")
        self.assertEqual(score["events"][0]["duration"], "1")
        self.assertEqual(score["events"][0]["tremolo"], {"type": "single", "marks": 3})
        self.assertEqual(
            score["events"][0]["lyrics"],
            [{"text": "Sum", "syllabic": "begin", "extend": "start", "number": "1"}],
        )
        report = compare_scores(score, score)
        self.assertEqual(report["global_note_rhythm"]["f1"], 1.0)


if __name__ == "__main__":
    unittest.main()
