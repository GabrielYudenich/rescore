from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

from rescore.manuscript import (
    _duration_pieces,
    _quantize,
    build_menina_das_nuvens_draft,
)
from rescore.musicxml import parse_musicxml


def _write_minimal_omr(path: Path) -> None:
    root = ET.Element("score-partwise", {"version": "4.0"})
    part_list = ET.SubElement(root, "part-list")
    for index in range(1, 22):
        score_part = ET.SubElement(part_list, "score-part", {"id": f"P{index}"})
        ET.SubElement(score_part, "part-name").text = "Voice"
    for index in range(1, 22):
        part = ET.SubElement(root, "part", {"id": f"P{index}"})
        for measure_number in range(1, 9):
            measure = ET.SubElement(part, "measure", {"number": str(measure_number)})
            if measure_number == 1:
                attributes = ET.SubElement(measure, "attributes")
                ET.SubElement(attributes, "divisions").text = "1"
            note = ET.SubElement(measure, "note")
            ET.SubElement(note, "rest")
            ET.SubElement(note, "duration").text = "2"
            ET.SubElement(note, "voice").text = "1"
            ET.SubElement(note, "type").text = "half"
            ET.SubElement(note, "staff").text = "1"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_menina_draft_has_fixed_continuous_meter(tmp_path: Path) -> None:
    source = tmp_path / "source.musicxml"
    _write_minimal_omr(source)
    sources = {
        "page1_upper": source,
        "page1_lower": source,
        "page2_upper": source,
        "page2_lower": source,
        "page3_upper": source,
        "page3_lower": source,
        "page4_upper": source,
        "page4_lower": source,
    }
    output = tmp_path / "draft.musicxml"
    report = build_menina_das_nuvens_draft(sources, output, tmp_path / "report.json")
    parsed = parse_musicxml(output, include_rests=True)

    assert report["measures"] == 26
    assert parsed["parts_count"] == 23
    assert parsed["measures"] == 26
    assert [
        (item["measure_index"], item["beats"], item["beat_type"])
        for item in parsed["time_signatures"]
        if item["part_id"] == "P01"
    ] == [(1, "2", "4"), (19, "3", "4"), (22, "2", "4")]

    lengths: dict[tuple[str, int, str], Fraction] = defaultdict(Fraction)
    for event in parsed["events"]:
        if event.get("chord") or event.get("grace"):
            continue
        key = (event["part_id"], event["measure_index"], event["staff"])
        lengths[key] = max(lengths[key], Fraction(event["onset"]) + Fraction(event["duration"]))
    assert lengths
    for (_part, measure, _staff), duration in lengths.items():
        assert duration == (Fraction(3) if 19 <= measure <= 21 else Fraction(2))


def test_manuscript_timing_uses_native_32nd_note_grid() -> None:
    assert _quantize(Fraction(7, 24)) == Fraction(1, 4)
    assert _quantize(Fraction(11, 24)) == Fraction(1, 2)
    assert _quantize(Fraction(23, 24)) == Fraction(1)
    assert _duration_pieces(Fraction(11, 8)) == [
        Fraction(1),
        Fraction(3, 8),
    ]
