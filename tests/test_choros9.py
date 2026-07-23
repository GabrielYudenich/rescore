import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from rescore.choros9 import analyze_doublings, audit_measure_structure, merge_measure_candidates
from rescore.musicxml import parse_musicxml
from rescore.scan import reinforce_orchestral_barlines


def _score(pitch: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>Fl.</part-name></score-part>
    <score-part id="P2"><part-name>Bon.</part-name></score-part>
  </part-list>
  <part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
    <note><pitch><step>{pitch}</step><octave>5</octave></pitch><duration>1</duration><voice>1</voice><type>quarter</type></note>
  </measure></part>
  <part id="P2"><measure number="1"><attributes><divisions>1</divisions></attributes>
    <note><rest/><duration>1</duration><voice>1</voice><type>quarter</type></note>
  </measure></part>
</score-partwise>"""


class Choros9Tests(unittest.TestCase):
    def test_reports_safe_transposed_doubling_and_meter_audit(self):
        score = {
            "parts": [
                {"id": "P1", "name": "2 Hautbois"},
                {"id": "P2", "name": "Violons I"},
            ],
            "measures": 1,
            "events": [
                {"part_id": part, "measure_index": 1, "onset": onset, "duration": "1", "pitch": pitch}
                for part, pitches in (("P1", ("C5", "D5", "E5")), ("P2", ("C6", "D6", "E6")))
                for onset, pitch in zip(("0", "1", "2"), pitches)
            ],
        }
        doubling = analyze_doublings(score, meter="4/4")
        self.assertEqual(len(doubling["confirmed_doublings"]), 1)
        candidate = doubling["confirmed_doublings"][0]
        self.assertEqual(candidate["relation"], "transposição constante")
        self.assertEqual(candidate["semitone_offset_right_from_left"], 12)
        audit = audit_measure_structure(score, "4/4")
        self.assertEqual(audit["invalid_entries"], [])

    def test_merge_isolated_measure_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.musicxml"
            second = root / "second.musicxml"
            output = root / "merged.musicxml"
            first.write_text(_score("C"), encoding="utf-8")
            second.write_text(_score("D"), encoding="utf-8")
            report = merge_measure_candidates([first, second], output)
            score = parse_musicxml(output)
        self.assertEqual(report["measures"], 2)
        self.assertEqual(score["measure_counts"], {"P1": 2, "P2": 2})
        self.assertEqual([event["pitch"] for event in score["events"]], ["C5", "D5"])

    def test_reinforces_only_detected_structural_bars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "scan.png"
            output = root / "repaired.png"
            image = np.full((700, 800), 255, dtype=np.uint8)
            for staff_top in range(100, 501, 80):
                for offset in (0, 4, 8, 12, 16):
                    cv2.line(image, (100, staff_top + offset), (700, staff_top + offset), 0, 1)
            for column in (120, 400, 700):
                cv2.line(image, (column, 100), (column, 516), 0, 4)
            self.assertTrue(cv2.imwrite(str(source), image))
            report = reinforce_orchestral_barlines(source, output)
            self.assertEqual(len(report["barline_columns"]), 3)
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
