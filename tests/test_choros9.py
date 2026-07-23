import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np

from rescore.choros9 import (
    analyze_doublings,
    audit_measure_structure,
    merge_measure_candidates,
    reconstruct_scanned_rhythm,
)
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
    def test_reconstructs_dense_scan_from_horizontal_positions(self):
        events = []
        for index in range(16):
            events.append(
                {
                    "part_id": "P1",
                    "measure_index": 1,
                    "onset": str(index),
                    "duration": "1",
                    "pitch": f"C{4 + index % 2}",
                    "voice": "1",
                    "staff": "1",
                    "type": "16th",
                    "chord": False,
                    "grace": False,
                    "tuplet": None,
                    "default_x": 100.0 + index * 30.0,
                }
            )
        score = {
            "parts": [{"id": "P1", "name": "Piccolo"}],
            "measures": 1,
            "events": events,
            "events_count": len(events),
        }
        report = reconstruct_scanned_rhythm(score, "4/4")
        self.assertTrue(report["applied"])
        self.assertEqual(len(score["events"]), 16)
        self.assertEqual(
            [event["onset"] for event in score["events"]],
            [str(Fraction(index, 4)) for index in range(16)],
        )
        self.assertTrue(all(event["duration"] == "1/4" for event in score["events"]))

    def test_keeps_sparse_and_tuplet_streams_unchanged(self):
        sparse = {
            "part_id": "P1",
            "measure_index": 1,
            "onset": "0",
            "duration": "4",
            "pitch": "C3",
            "voice": "1",
            "staff": "1",
            "type": "whole",
            "chord": False,
            "grace": False,
            "tuplet": None,
            "default_x": 80.0,
        }
        tuplets = [
            {
                **sparse,
                "part_id": "P2",
                "onset": str(index),
                "duration": "1/3",
                "pitch": "D4",
                "type": "eighth",
                "tuplet": {"actual": "3", "normal": "2"},
                "default_x": 100.0 + index * 30.0,
            }
            for index in range(6)
        ]
        score = {
            "parts": [{"id": "P1", "name": "Basson"}, {"id": "P2", "name": "Célesta"}],
            "measures": 1,
            "events": [sparse, *tuplets],
            "events_count": 7,
        }
        before = [(event["onset"], event["duration"]) for event in score["events"]]
        reconstruct_scanned_rhythm(score, "4/4")
        after = [(event["onset"], event["duration"]) for event in score["events"]]
        self.assertEqual(after, before)

    def test_fits_irregular_dense_positions_without_losing_the_last_note(self):
        positions = (63, 98, 121, 155, 182, 213, 274, 310, 342, 373, 398, 435, 469, 487, 497, 529)
        events = [
            {
                "part_id": "P1",
                "measure_index": 1,
                "onset": str(index),
                "duration": "1",
                "pitch": "C5",
                "voice": "1",
                "staff": "1",
                "type": "16th",
                "chord": False,
                "grace": False,
                "tuplet": None,
                "default_x": float(position),
            }
            for index, position in enumerate(positions)
        ]
        score = {
            "parts": [{"id": "P1", "name": "Violons II"}],
            "measures": 1,
            "events": events,
            "events_count": len(events),
        }
        reconstruct_scanned_rhythm(score, "4/4")
        self.assertEqual(len(score["events"]), 16)
        self.assertEqual(score["events"][-1]["onset"], "15/4")
        self.assertEqual(score["events"][-1]["duration"], "1/4")

    def test_removes_only_impossible_whole_prefix_before_dense_voice(self):
        positions = (60, 100, 130, 160, 190, 220, 250, 280, 310)
        events = [
            {
                "part_id": "P1",
                "measure_index": 1,
                "onset": str(index),
                "duration": "4" if index == 0 else "1/4",
                "pitch": "C4" if index == 0 else "C6",
                "voice": "1",
                "staff": "1",
                "type": "whole" if index == 0 else "16th",
                "chord": False,
                "grace": False,
                "tuplet": None,
                "default_x": float(position),
            }
            for index, position in enumerate(positions)
        ]
        score = {
            "parts": [{"id": "P1", "name": "Piccolo"}],
            "measures": 1,
            "events": events,
            "events_count": len(events),
        }
        report = reconstruct_scanned_rhythm(score, "4/4")
        self.assertEqual(report["impossible_prefix_events_removed"], 1)
        self.assertEqual([event["pitch"] for event in score["events"]], ["C6"] * 8)

    def test_preserves_more_than_sixteen_recognized_onsets_on_finer_grid(self):
        events = [
            {
                "part_id": "P1",
                "measure_index": 1,
                "onset": str(index),
                "duration": "1/4",
                "pitch": "D5",
                "voice": "1",
                "staff": "1",
                "type": "16th",
                "chord": False,
                "grace": False,
                "tuplet": None,
                "default_x": 80.0 + index * 24.0,
            }
            for index in range(18)
        ]
        score = {
            "parts": [{"id": "P1", "name": "2 Hautbois"}],
            "measures": 1,
            "events": events,
            "events_count": len(events),
        }
        report = reconstruct_scanned_rhythm(score, "4/4")
        self.assertEqual(len(score["events"]), 18)
        self.assertEqual(report["impossible_prefix_events_removed"], 0)
        self.assertEqual(report["streams_using_thirty_second_grid"], 1)
        self.assertLess(Fraction(score["events"][-1]["onset"]), 4)

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
