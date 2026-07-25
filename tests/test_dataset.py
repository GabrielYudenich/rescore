from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from rescore.dataset import (
    add_pair,
    initialize_dataset,
    validate_dataset,
    write_public_catalog,
)
from rescore.hardware import inspect_hardware


def _write_image(path: Path) -> None:
    Image.new("L", (320, 240), 255).save(path)


def _write_musicxml(path: Path) -> None:
    root = ET.Element("score-partwise", {"version": "4.0"})
    part_list = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(part_list, "score-part", {"id": "P1"})
    ET.SubElement(score_part, "part-name").text = "Violin"
    part = ET.SubElement(root, "part", {"id": "P1"})
    for number in range(1, 3):
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


def test_dataset_keeps_private_items_out_of_public_catalog(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    initialize_dataset(root, dataset_id="seed", name="Seed")
    image = tmp_path / "page.png"
    score = tmp_path / "score.musicxml"
    _write_image(image)
    _write_musicxml(score)

    add_pair(
        tmp_path,
        root,
        item_id="public-page",
        images=[image],
        score=score,
        composer="Composer",
        work="Public work",
        source_type="handwritten",
        visibility="public",
        rights_status="permission-confirmed",
        source_license="CC0-1.0",
        redistributable=True,
        measure_start=1,
        measure_end=2,
        verification="human-transcribed",
        alignment_status="verified",
    )
    add_pair(
        tmp_path,
        root,
        item_id="paid-private-score",
        images=[image],
        score=score,
        composer="Composer",
        work="Private work",
        source_type="printed",
        visibility="private",
        rights_status="private-reference",
        source_license="all-rights-reserved",
        redistributable=False,
        measure_start=1,
        measure_end=2,
        verification="human-reviewed",
        alignment_status="verified",
    )

    validation = validate_dataset(root)
    assert validation["valid"]
    assert validation["public_items"] == 1
    assert validation["private_items"] == 1

    catalog_path = tmp_path / "public.json"
    report = write_public_catalog(root, catalog_path)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert report["excluded_private_items"] == 1
    assert [item["id"] for item in catalog["items"]] == ["public-page"]
    serialized = catalog_path.read_text(encoding="utf-8")
    assert "paid-private-score" not in serialized
    assert "Private work" not in serialized


def test_dataset_validation_detects_modified_source(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    initialize_dataset(root, dataset_id="seed", name="Seed")
    image = tmp_path / "page.png"
    score = tmp_path / "score.musicxml"
    _write_image(image)
    _write_musicxml(score)
    result = add_pair(
        tmp_path,
        root,
        item_id="example",
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
        verification="human-reviewed",
        alignment_status="inferred",
    )
    relative = result["item"]["source"]["images"][0]["path"]
    (root / relative).write_bytes(b"modified")
    validation = validate_dataset(root)
    assert not validation["valid"]
    assert any(error["kind"] == "checksum" for error in validation["errors"])


def test_hardware_inventory_is_privacy_safe(tmp_path: Path) -> None:
    report = inspect_hardware(tmp_path)
    assert report["platform"]["system"]
    assert report["cpu"]["logical_cores"]
    assert report["storage"]["free_gb"] >= 0
    assert "training_guidance" in report
