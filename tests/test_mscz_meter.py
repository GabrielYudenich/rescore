import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from rescore.mscz import normalize_mscz_voice_durations, validate_meter_map_mscz


class MuseScoreMeterTests(unittest.TestCase):
    def _write_score(self, measure: ET.Element, folder: str) -> Path:
        root = ET.Element("museScore")
        score = ET.SubElement(root, "Score")
        staff = ET.SubElement(score, "Staff", {"id": "1"})
        staff.append(measure)
        path = Path(folder) / "score.mscz"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("score.mscx", ET.tostring(root, encoding="utf-8"))
        return path

    def _three_four_triplet_measure(self, spacer: bool) -> ET.Element:
        measure = ET.Element("Measure")
        voice = ET.SubElement(measure, "voice")
        time = ET.SubElement(voice, "TimeSig")
        ET.SubElement(time, "sigN").text = "3"
        ET.SubElement(time, "sigD").text = "4"
        tuplet = ET.SubElement(voice, "Tuplet")
        ET.SubElement(tuplet, "normalNotes").text = "2"
        ET.SubElement(tuplet, "actualNotes").text = "3"
        ET.SubElement(tuplet, "baseNote").text = "quarter"
        chord = ET.SubElement(voice, "Chord")
        ET.SubElement(chord, "durationType").text = "half"
        rest = ET.SubElement(voice, "Rest")
        ET.SubElement(rest, "durationType").text = "quarter"
        ET.SubElement(voice, "endTuplet")
        final_rest = ET.SubElement(voice, "Rest")
        if spacer:
            ET.SubElement(final_rest, "visible").text = "0"
            ET.SubElement(final_rest, "dots").text = "2"
        ET.SubElement(final_rest, "durationType").text = (
            "quarter" if not spacer else "quarter"
        )
        return measure

    def test_validator_does_not_treat_location_as_duration(self):
        measure = self._three_four_triplet_measure(spacer=False)
        voice = measure.find("voice")
        triplet_rest = voice.findall("Rest")[0]
        voice.remove(triplet_rest)
        location = ET.SubElement(voice, "location")
        ET.SubElement(location, "fractions").text = "1/6"
        with tempfile.TemporaryDirectory() as folder:
            path = self._write_score(measure, folder)
            result = validate_meter_map_mscz(path, {1: (3, 4)}, 1)
        self.assertFalse(result["valid"])
        self.assertEqual(result["violations"][0]["actual_quarters"], "7/3")

    def test_normalizer_preserves_rest_that_completes_triplet(self):
        measure = self._three_four_triplet_measure(spacer=True)
        with tempfile.TemporaryDirectory() as folder:
            path = self._write_score(measure, folder)
            normalize_mscz_voice_durations(path, {1: (3, 4)}, 1)
            result = validate_meter_map_mscz(path, {1: (3, 4)}, 1)
            with zipfile.ZipFile(path) as archive:
                root = ET.fromstring(archive.read("score.mscx"))
        self.assertTrue(result["valid"])
        rests = root.findall("./Score/Staff/Measure/voice/Rest")
        self.assertEqual([rest.findtext("durationType") for rest in rests], ["quarter", "quarter"])


if __name__ == "__main__":
    unittest.main()
