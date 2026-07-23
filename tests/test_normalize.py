import unittest
from fractions import Fraction

from rescore.normalize import (
    MOVEMENT1_CLEF_CHANGES,
    _normalize_final_two_note_tremolos,
    _normalize_scherzo_tuplet_artifacts,
    _restore_movement1_review_tuplets,
    _restore_verified_violin2_quintuplets,
    _scherzo_layout_for_page,
    _split_paired_melodic_part,
    map_sinfonia10_page67,
    map_sinfonia10_page69,
    movement1_meter,
    scherzo_meter,
    validate_meter_score,
)


def event(part_id, pitch, onset="0", duration="1", staff="1"):
    return {
        "part_id": part_id,
        "part_name": part_id,
        "part_key": part_id.lower(),
        "measure_index": 1,
        "measure_number": "1",
        "onset": onset,
        "duration": duration,
        "pitch": pitch,
        "rest": False,
        "grace": False,
        "chord": False,
        "voice": "1",
        "staff": staff,
        "type": "quarter",
        "dots": 0,
        "tuplet": None,
        "ties": [],
        "articulations": [],
    }


class NormalizeTests(unittest.TestCase):
    def test_scherzo_confirmed_meter_changes(self):
        self.assertEqual(scherzo_meter(26)[:2], (9, 8))
        self.assertEqual(scherzo_meter(74)[:2], (6, 8))
        self.assertEqual(scherzo_meter(119)[:2], (9, 8))
        self.assertEqual(scherzo_meter(172)[:2], (4, 4))
        self.assertEqual(scherzo_meter(187)[:2], (6, 8))

    def test_scherzo_page80_keeps_vocals_before_strings(self):
        names = [
            "Picc.", "Fl.", "Ob.", "C. I.", "Cl.", "Cl. B.", "Fg.",
            "Cfg.", "Voice", "Tpa.", "Voice", "Trp.", "Trb.", "Voice",
            "Tb.", "Timp.", "Pno.", "Voice", "Voice", "Vl. I", "Vl. II",
            "Vla.", "Vc.", "Cb.",
        ]
        parts = [{"id": f"P{index}", "name": name} for index, name in enumerate(names, 1)]
        layout, _audit = _scherzo_layout_for_page(80, parts)
        self.assertEqual(layout[16], ("P23", "P24", "P25"))
        self.assertEqual(layout[-7:], ["P39", "P40", "P26", "P27", "P28", "P29", "P30"])

    def test_movement1_confirmed_meter_changes(self):
        expected = {
            1: (4, 4),
            12: (3, 4),
            23: (2, 4),
            26: (3, 4),
            28: (4, 4),
            29: (3, 4),
            30: (2, 4),
            31: (4, 4),
            37: (5, 8),
            61: (4, 4),
            84: (2, 4),
            85: (4, 4),
            150: (3, 4),
            177: (2, 4),
            180: (4, 4),
        }
        for measure, meter in expected.items():
            self.assertEqual(movement1_meter(measure)[:2], meter)

    def test_movement1_verified_clef_changes(self):
        harp = MOVEMENT1_CLEF_CHANGES["P32"]
        piano = MOVEMENT1_CLEF_CHANGES["P33"]
        self.assertIn((6, Fraction(0), 1, "G", 2), harp)
        self.assertIn((6, Fraction(0), 2, "G", 2), harp)
        self.assertIn((18, Fraction(0), 2, "F", 4), harp)
        self.assertIn((22, Fraction(3), 2, "F", 4), piano)
        self.assertIn((32, Fraction(7, 2), 1, "F", 4), piano)
        self.assertIn((31, Fraction(0), 1, "C", 4), MOVEMENT1_CLEF_CHANGES["P26"])

    def test_splits_paired_flutes_and_duplicates_unison(self):
        lower = event("P15", "C5")
        upper = event("P15", "E5")
        unison = event("P15", "G5", onset="1")
        split = _split_paired_melodic_part([lower, upper, unison], "P15", "P45")
        first = [item["pitch"] for item in split if item["part_id"] == "P15"]
        second = [item["pitch"] for item in split if item["part_id"] == "P45"]
        self.assertEqual(first, ["E5", "G5"])
        self.assertEqual(second, ["C5", "G5"])
        self.assertTrue(all(not item["chord"] for item in split))

    def test_restores_both_violin2_quintuplet_voices(self):
        source = []
        for measure in range(4, 11):
            item = event("P35", "G4")
            item["measure_index"] = measure
            item["measure_number"] = str(measure)
            source.append(item)
        restored = _restore_verified_violin2_quintuplets(source)
        self.assertEqual(restored, 140)
        for measure in range(4, 11):
            notes = [item for item in source if item["measure_index"] == measure]
            self.assertEqual(len(notes), 20)
            self.assertEqual({item["voice"] for item in notes}, {"1", "2"})
            self.assertTrue(all(item["duration"] == "1/5" for item in notes))
            self.assertTrue(
                all(item["tuplet"] == {"actual": "5", "normal": "4"} for item in notes)
            )
            self.assertEqual(len({item["tuplet_group"] for item in notes}), 4)

    def test_normalizes_page41_two_note_tremolo_pairs(self):
        source = []
        for index, pitch in enumerate(("C6", "D6", "E6", "F6")):
            item = event("P15", pitch, onset=str(Fraction(index, 4)), duration="1/4")
            item["measure_index"] = 234
            item["measure_number"] = "234"
            source.append(item)
        changed = _normalize_final_two_note_tremolos(source)
        self.assertEqual(changed, 4)
        self.assertEqual([item["onset"] for item in source], ["0", "1", "2", "3"])
        self.assertEqual(
            [item["tremolo"]["type"] for item in source],
            ["start", "stop", "start", "stop"],
        )

    def test_scherzo_string_tremolo_keeps_the_recognized_chord(self):
        source = [event("P26", "A4", duration="2/3")]
        source[0]["measure_index"] = 172
        source[0]["tuplet"] = {"actual": "3", "normal": "2"}
        report = _normalize_scherzo_tuplet_artifacts(source)
        self.assertEqual(report["converted_tremolo_tuplets"], 1)
        self.assertEqual(len(source), 1)
        self.assertEqual(source[0]["pitch"], "A4")
        self.assertEqual(source[0]["duration"], "1")
        self.assertIsNone(source[0]["tuplet"])
        self.assertEqual(source[0]["tremolo"], {"type": "single", "marks": 3})

    def test_restores_reviewed_measure_34_quintuplets(self):
        source = []
        for part_id in ("P17", "P19", "P34", "P35"):
            item = event(part_id, "C4")
            item["measure_index"] = 34
            item["measure_number"] = "34"
            source.append(item)
        restored = _restore_movement1_review_tuplets(source)
        self.assertGreaterEqual(restored, 60)
        for part_id, expected in (("P17", 20), ("P19", 20), ("P34", 10), ("P35", 10)):
            notes = [item for item in source if item["part_id"] == part_id]
            self.assertEqual(len(notes), expected)
            self.assertTrue(all(item["duration"] == "1/5" for item in notes))
            self.assertTrue(
                all(item["tuplet"] == {"actual": "5", "normal": "4"} for item in notes)
            )
            self.assertTrue(all(Fraction(item["onset"]) < 4 for item in notes))

    def test_splits_shared_wind_chord_and_maps_bass(self):
        candidate = {
            "events": [
                event("P1", "C5"),
                event("P1", "E5"),
                event("P17", "C2"),
            ]
        }
        mapped = map_sinfonia10_page67(candidate)
        self.assertEqual([item["pitch"] for item in mapped["P1"]], ["E5"])
        self.assertEqual([item["pitch"] for item in mapped["P2"]], ["C5"])
        self.assertEqual([item["pitch"] for item in mapped["P30"]], ["C2"])

    def test_meter_validation_rejects_overrun(self):
        score = {"events": [event("P1", "C5", onset="3", duration="2")]}
        report = validate_meter_score(score, lambda _part, _measure: Fraction(4))
        self.assertFalse(report["valid"])
        self.assertEqual(report["overruns"], 1)

    def test_meter_validation_accepts_exact_bar(self):
        score = {"events": [event("P1", "C5", onset="0", duration="4")]}
        report = validate_meter_score(score, lambda _part, _measure: Fraction(4))
        self.assertTrue(report["valid"])

    def test_meter_validation_accepts_short_secondary_voice(self):
        primary = event("P1", "C5", onset="0", duration="4")
        secondary = event("P1", "E5", onset="0", duration="2")
        secondary["voice"] = "2"
        score = {"events": [primary, secondary]}
        report = validate_meter_score(score, lambda _part, _measure: Fraction(4))
        self.assertTrue(report["valid"])

    def test_page69_restores_three_four_in_the_time_of_three_tuplets(self):
        strings = []
        for part_id in ("P15", "P16", "P17"):
            for index in range(12):
                item = event(
                    part_id,
                    "C5",
                    onset=str(Fraction(index, 4)),
                    duration="1/4",
                )
                item["type"] = "16th"
                strings.append(item)
        mapped = map_sinfonia10_page69({"events": strings})
        for target in ("P26", "P27", "P28"):
            notes = mapped[target]
            self.assertEqual(len(notes), 12)
            self.assertTrue(all(note["measure_index"] == 18 for note in notes))
            self.assertTrue(all(note["duration"] == "3/8" for note in notes))
            self.assertTrue(all(note["tuplet"] == {"actual": "4", "normal": "3"} for note in notes))
            self.assertEqual(len({note["tuplet_group"] for note in notes}), 3)


if __name__ == "__main__":
    unittest.main()
