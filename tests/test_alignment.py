from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np

from rescore.alignment import (
    align_dataset_item,
    detect_measure_regions,
    validate_alignment,
)
from rescore.dataset import add_pair, initialize_dataset, validate_dataset


def _write_score_image(path: Path, boundaries: list[int]) -> None:
    image = np.full((1400, 1200), 255, dtype=np.uint8)
    top, bottom = 220, 1240
    for staff_top in range(top, bottom, 120):
        for offset in range(0, 25, 6):
            cv2.line(
                image,
                (boundaries[0], staff_top + offset),
                (boundaries[-1], staff_top + offset),
                0,
                2,
            )
    for boundary in boundaries:
        cv2.line(image, (boundary, top), (boundary, bottom), 0, 5)
    cv2.imwrite(str(path), image)


def _write_musicxml(path: Path, measures: int) -> None:
    root = ET.Element("score-partwise", {"version": "4.0"})
    part_list = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(part_list, "score-part", {"id": "P1"})
    ET.SubElement(score_part, "part-name").text = "Violin"
    part = ET.SubElement(root, "part", {"id": "P1"})
    for number in range(1, measures + 1):
        measure = ET.SubElement(part, "measure", {"number": str(number)})
        if number == 1:
            attributes = ET.SubElement(measure, "attributes")
            ET.SubElement(attributes, "divisions").text = "1"
            time = ET.SubElement(attributes, "time")
            ET.SubElement(time, "beats").text = "2"
            ET.SubElement(time, "beat-type").text = "4"
        note = ET.SubElement(measure, "note")
        ET.SubElement(note, "rest")
        ET.SubElement(note, "duration").text = "2"
        ET.SubElement(note, "voice").text = "1"
        ET.SubElement(note, "type").text = "half"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_detect_measure_regions_numbers_regular_barlines(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    boundaries = [150, 440, 735, 1050]
    _write_score_image(image, boundaries)
    result = detect_measure_regions(
        image,
        expected_measures=3,
        first_measure=12,
    )
    assert [region["measure_number"] for region in result["regions"]] == [12, 13, 14]
    assert len(result["boundaries_x"]) == 4
    for actual, expected in zip(result["boundaries_x"], boundaries, strict=True):
        assert abs(actual - expected) <= 8
    assert result["metrics"]["confidence"] > 0.7


def test_align_dataset_item_writes_reviewable_private_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    initialize_dataset(root, dataset_id="seed", name="Seed")
    image = tmp_path / "page.png"
    score = tmp_path / "score.musicxml"
    _write_score_image(image, [140, 510, 1060])
    _write_musicxml(score, 2)
    add_pair(
        tmp_path,
        root,
        item_id="handwritten-opening",
        images=[image],
        score=score,
        composer="Composer",
        work="Work",
        source_type="handwritten",
        visibility="private",
        rights_status="private-reference",
        source_license="all-rights-reserved",
        redistributable=False,
        measure_start=1,
        measure_end=2,
        verification="human-transcribed",
        alignment_status="inferred",
    )

    result = align_dataset_item(root, item_id="handwritten-opening")
    alignment = Path(result["alignment"])
    review = Path(result["review_html"])
    assert result["validation"]["valid"]
    assert alignment.is_file()
    assert review.is_file()
    assert "Proposta da máquina" in review.read_text(encoding="utf-8")

    payload = json.loads(alignment.read_text(encoding="utf-8"))
    assert payload["review_status"] == "machine-proposed"
    assert payload["page_measure_counts"] == [2]
    assert validate_alignment(alignment)["valid"]

    dataset_validation = validate_dataset(root)
    assert dataset_validation["valid"]
    assert dataset_validation["private_items"] == 1
    assert dataset_validation["checked_files"] == 6
