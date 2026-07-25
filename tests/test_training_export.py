from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np

from rescore.dataset import add_pair, initialize_dataset, validate_dataset
from rescore.training_export import (
    export_training_samples,
    tokenize_events,
    validate_training_export,
)


def _write_image(path: Path) -> None:
    image = np.full((200, 400, 3), 255, dtype=np.uint8)
    for y in (60, 66, 72, 78, 84):
        cv2.line(image, (40, y), (360, y), (0, 0, 0), 1)
    for x in (40, 200, 360):
        cv2.line(image, (x, 50), (x, 95), (0, 0, 0), 2)
    cv2.imwrite(str(path), image)


def _write_score(path: Path) -> None:
    root = ET.Element("score-partwise", {"version": "4.0"})
    part_list = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(part_list, "score-part", {"id": "P1"})
    ET.SubElement(score_part, "part-name").text = "Voice"
    part = ET.SubElement(root, "part", {"id": "P1"})
    first = ET.SubElement(part, "measure", {"number": "1"})
    attributes = ET.SubElement(first, "attributes")
    ET.SubElement(attributes, "divisions").text = "2"
    time = ET.SubElement(attributes, "time")
    ET.SubElement(time, "beats").text = "2"
    ET.SubElement(time, "beat-type").text = "4"
    note = ET.SubElement(first, "note")
    pitch = ET.SubElement(note, "pitch")
    ET.SubElement(pitch, "step").text = "C"
    ET.SubElement(pitch, "octave").text = "5"
    ET.SubElement(note, "duration").text = "2"
    ET.SubElement(note, "voice").text = "1"
    ET.SubElement(note, "type").text = "quarter"
    modification = ET.SubElement(note, "time-modification")
    ET.SubElement(modification, "actual-notes").text = "3"
    ET.SubElement(modification, "normal-notes").text = "2"
    lyric = ET.SubElement(note, "lyric")
    ET.SubElement(lyric, "syllabic").text = "single"
    ET.SubElement(lyric, "text").text = "Lá"
    second = ET.SubElement(part, "measure", {"number": "2"})
    rest = ET.SubElement(second, "note")
    ET.SubElement(rest, "rest", {"measure": "yes"})
    ET.SubElement(rest, "duration").text = "4"
    ET.SubElement(rest, "voice").text = "1"
    ET.SubElement(rest, "type").text = "half"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_tokenize_events_preserves_tuplet_and_unicode_lyric() -> None:
    tokens = tokenize_events(
        [
            {
                "onset": "0",
                "duration": "1/3",
                "voice": "1",
                "pitch": "C5",
                "rest": False,
                "tuplet": {"actual": "3", "normal": "2"},
                "lyrics": [{"text": "Lá", "syllabic": "single"}],
            }
        ],
        "2/4",
    )
    assert "<tuplet:3/2>" in tokens
    assert "<char:U+004C>" in tokens
    assert "<char:U+00E1>" in tokens


def test_export_training_samples_writes_crops_and_verified_targets(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    image = tmp_path / "page.png"
    score = tmp_path / "score.musicxml"
    _write_image(image)
    _write_score(score)
    initialize_dataset(dataset, dataset_id="training", name="Training")
    add_pair(
        tmp_path,
        dataset,
        item_id="voice-opening",
        images=[image],
        score=score,
        composer="Composer",
        work="Work",
        source_type="handwritten",
        visibility="private",
        rights_status="private",
        source_license="all-rights-reserved",
        redistributable=False,
        measure_start=1,
        measure_end=2,
        verification="human-transcribed",
        alignment_status="verified",
    )
    manifest_path = dataset / "rescore-dataset.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    item = manifest["items"][0]
    source_path = item["source"]["images"][0]["path"]
    staff_path = dataset / "items" / "voice-opening" / "alignment" / "staff-regions.json"
    staff_path.parent.mkdir(parents=True)
    band = {
        "visual_staff_index": 1,
        "source_label": "Voice",
        "staff_type": "five-line",
        "mapping_status": "profile-proposed",
        "targets": [{"part_id": "P1", "part_name": "Voice", "staff_number": "1"}],
    }
    cells = []
    for measure, x in ((1, 40), (2, 200)):
        cells.append(
            {
                "id": f"measure-{measure:04d}-staff-001",
                "measure_number": measure,
                "visual_staff_index": 1,
                "bbox_pixels": {"x": x, "y": 45, "width": 160, "height": 55},
                "bbox_normalized": {"x": x / 400, "y": 0.225, "width": 0.4, "height": 0.275},
            }
        )
    staff_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "pages": [
                    {
                        "image_page": 1,
                        "source_image": source_path,
                        "staff_bands": [band],
                        "cells": cells,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    item["alignment"].update(
        {
            "review_status": "human-reviewed",
            "staff_review_status": "human-reviewed",
            "staff_regions_file": {
                "path": staff_path.relative_to(dataset).as_posix(),
                "sha256": _sha256(staff_path),
            },
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = export_training_samples(dataset, item_id="voice-opening")
    assert result["samples"] == 2
    assert result["eligibility_counts"] == {"eligible": 2}
    index = Path(result["index"])
    samples = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()]
    assert all(sample["training_eligible"] for sample in samples)
    assert samples[0]["target"]["relation"] == "single-target"
    assert "<tuplet:3/2>" in samples[0]["target"]["tokens"]
    assert samples[1]["target"]["streams"][0]["events"][0]["rest"]
    assert validate_training_export(index)["valid"]
    assert validate_dataset(dataset)["valid"]
