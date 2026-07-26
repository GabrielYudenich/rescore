from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
import pytest

from rescore.dataset import DatasetError, add_pair, initialize_dataset, validate_dataset
from rescore.dataset_fix import apply_dataset_fix
from rescore.issue_review import build_review_pack, detect_score_issues
from rescore.musicxml import _strip_namespaces, parse_musicxml
from rescore.training_export import _apply_corrections


def _write_score(
    path: Path,
    *,
    overfull: bool = False,
    part_id: str = "P1",
    part_name: str = "Bassoon",
) -> None:
    root = ET.Element("score-partwise", {"version": "4.0"})
    work = ET.SubElement(root, "work")
    ET.SubElement(work, "work-title").text = "Test score"
    part_list = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(part_list, "score-part", {"id": part_id})
    ET.SubElement(score_part, "part-name").text = part_name
    part = ET.SubElement(root, "part", {"id": part_id})
    for number, step in ((1, "C"), (2, "D")):
        measure = ET.SubElement(part, "measure", {"number": str(number)})
        if number == 1:
            attributes = ET.SubElement(measure, "attributes")
            ET.SubElement(attributes, "divisions").text = "1"
            time = ET.SubElement(attributes, "time")
            ET.SubElement(time, "beats").text = "4"
            ET.SubElement(time, "beat-type").text = "4"
            clef = ET.SubElement(attributes, "clef")
            ET.SubElement(clef, "sign").text = "F"
            ET.SubElement(clef, "line").text = "4"
        note = ET.SubElement(measure, "note")
        pitch = ET.SubElement(note, "pitch")
        ET.SubElement(pitch, "step").text = step
        ET.SubElement(pitch, "octave").text = "4"
        ET.SubElement(note, "duration").text = "5" if overfull and number == 2 else "4"
        ET.SubElement(note, "voice").text = "1"
        ET.SubElement(note, "type").text = "whole"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _write_image(path: Path) -> None:
    image = np.full((200, 400, 3), 255, dtype=np.uint8)
    for y in (70, 76, 82, 88, 94):
        cv2.line(image, (30, y), (370, y), (0, 0, 0), 1)
    cv2.imwrite(str(path), image)


def _manual_issue(path: Path) -> str:
    issue_id = "RS-M0002-P1-S01-V1-MANUAL-REVIEW"
    issue = {
        "id": issue_id,
        "schema_version": "1.0",
        "kind": "manual-review",
        "severity": "warning",
        "measure": 2,
        "part_id": "P1",
        "possible_instrument": "Bassoon",
        "staff": "1",
        "voice": "1",
        "message": "altura ambígua",
    }
    path.write_text(json.dumps(issue) + "\n", encoding="utf-8")
    return issue_id


def test_detect_score_issues_reports_overfull_voice(tmp_path: Path) -> None:
    score = tmp_path / "score.musicxml"
    _write_score(score, overfull=True)
    result = detect_score_issues(score, tmp_path / "issues")
    issues = [
        json.loads(line) for line in Path(result["issues"]).read_text(encoding="utf-8").splitlines()
    ]
    overfull = [issue for issue in issues if issue["kind"] == "measure-long"]
    assert len(overfull) == 1
    assert overfull[0]["measure"] == 2
    assert overfull[0]["possible_instrument"] == "Bassoon"
    assert "encontrado 5" in overfull[0]["message"]
    assert Path(result["html"]).is_file()


def test_detect_score_issues_allows_secondary_voice_to_end_early(tmp_path: Path) -> None:
    score = tmp_path / "score.musicxml"
    _write_score(score)
    tree = ET.parse(score)
    measure = tree.find("./part/measure")
    assert measure is not None
    backup = ET.SubElement(measure, "backup")
    ET.SubElement(backup, "duration").text = "4"
    note = ET.SubElement(measure, "note")
    pitch = ET.SubElement(note, "pitch")
    ET.SubElement(pitch, "step").text = "E"
    ET.SubElement(pitch, "octave").text = "4"
    ET.SubElement(note, "duration").text = "1"
    ET.SubElement(note, "voice").text = "2"
    ET.SubElement(note, "type").text = "quarter"
    tree.write(score, encoding="utf-8", xml_declaration=True)
    result = detect_score_issues(score, tmp_path / "issues")
    issues = [
        json.loads(line) for line in Path(result["issues"]).read_text(encoding="utf-8").splitlines()
    ]
    assert not [issue for issue in issues if issue["kind"] == "measure-incomplete"]


def test_review_pack_keeps_visible_id_and_inherited_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    score = tmp_path / "score.musicxml"
    issues = tmp_path / "issues.jsonl"
    output = tmp_path / "pack"
    _write_score(score)
    _manual_issue(issues)
    monkeypatch.setattr("rescore.issue_review.find_musescore", lambda _root: None)
    result = build_review_pack(tmp_path, score, output, issues_path=issues)
    assert result["review_measures"] == 1
    assert result["mscz"] is None
    root = _strip_namespaces(ET.parse(result["musicxml"]).getroot())
    measure = root.find("./part/measure")
    assert measure is not None
    assert measure.get("number") == "1"
    visible_text = " ".join(node.text or "" for node in measure.findall(".//words"))
    assert "RS-REVIEW-0001" in visible_text
    assert "Compasso original 2" in visible_text
    assert measure.findtext("./attributes/time/beats") == "4"
    assert measure.findtext("./attributes/clef/sign") == "F"
    notes = measure.findall("note")
    assert len(notes) == 1
    assert notes[0].find("rest") is not None
    assert notes[0].find("pitch") is None
    validation = json.loads(Path(result["validation"]).read_text(encoding="utf-8"))
    assert validation["musicxml"]["valid"]
    pack = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert pack["mappings"][0]["original_measure"] == 2
    assert pack["mappings"][0]["review_id"] == "RS-REVIEW-0001"


def test_dataset_fix_maps_corrected_review_measure_back_to_original(
    tmp_path: Path,
    monkeypatch,
) -> None:
    score = tmp_path / "score.musicxml"
    issues = tmp_path / "issues.jsonl"
    pack_dir = tmp_path / "pack"
    image = tmp_path / "page.png"
    _write_score(score)
    _write_image(image)
    _manual_issue(issues)
    monkeypatch.setattr("rescore.issue_review.find_musescore", lambda _root: None)
    pack_result = build_review_pack(tmp_path, score, pack_dir, issues_path=issues)
    corrected = tmp_path / "corrected.musicxml"
    tree = ET.parse(pack_result["musicxml"])
    note = tree.find("./part/measure/note")
    assert note is not None
    rest = note.find("rest")
    assert rest is not None
    note.remove(rest)
    pitch = ET.Element("pitch")
    ET.SubElement(pitch, "step").text = "E"
    ET.SubElement(pitch, "octave").text = "4"
    note.insert(0, pitch)
    ET.SubElement(note, "type").text = "whole"
    tree.write(corrected, encoding="utf-8", xml_declaration=True)

    dataset = tmp_path / "dataset"
    initialize_dataset(dataset, dataset_id="corrections", name="Corrections")
    add_pair(
        tmp_path,
        dataset,
        item_id="manuscript",
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
        alignment_status="inferred",
    )
    without_id = tmp_path / "corrected-without-id.musicxml"
    invalid_tree = ET.parse(pack_result["musicxml"])
    for node in invalid_tree.findall(".//rehearsal") + invalid_tree.findall(".//words"):
        node.text = "identificador removido"
    invalid_tree.write(without_id, encoding="utf-8", xml_declaration=True)
    with pytest.raises(DatasetError, match="identificadores removidos ou deslocados"):
        apply_dataset_fix(
            tmp_path,
            dataset,
            item_id="manuscript",
            pack_path=Path(pack_result["manifest"]),
            corrected=without_id,
            reviewer="Reviewer",
        )

    result = apply_dataset_fix(
        tmp_path,
        dataset,
        item_id="manuscript",
        pack_path=Path(pack_result["manifest"]),
        corrected=corrected,
        reviewer="Reviewer",
        note="Corrected against the manuscript.",
    )
    assert result["changed_streams"] == 1
    manifest = json.loads((dataset / "rescore-dataset.json").read_text(encoding="utf-8"))
    correction = manifest["items"][0]["corrections"][0]
    preserved_pack = json.loads((dataset / correction["pack"]["path"]).read_text(encoding="utf-8"))
    assert preserved_pack["source"]["path"] == "external-source-not-copied"
    assert str(tmp_path) not in json.dumps(preserved_pack)
    overrides = json.loads((dataset / correction["overrides"]["path"]).read_text(encoding="utf-8"))
    override = overrides["overrides"][0]
    assert override["original_measure"] == 2
    assert override["target_part_id"] == "P1"
    assert override["events"][0]["pitch"] == "E4"
    assert validate_dataset(dataset)["valid"]
    assert parse_musicxml(dataset / correction["corrected_musicxml"]["path"])["measures"] == 1

    events = {("P1", "1", 2): [{"pitch": "D4"}]}
    meters = {("P1", 2): "4/4"}
    applied = _apply_corrections(dataset, manifest["items"][0], events, meters)
    assert events[("P1", "1", 2)][0]["pitch"] == "E4"
    assert applied[("P1", "1", 2)] == correction["id"]


def test_dataset_fix_accepts_confirmed_order_and_explicit_instrument_map(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "candidate.musicxml"
    target = tmp_path / "ground-truth.musicxml"
    issues = tmp_path / "issues.jsonl"
    image = tmp_path / "page.png"
    _write_score(source, part_id="P1", part_name="Celesta lower")
    _write_score(target, part_id="P29", part_name="Celesta")
    _write_image(image)
    _manual_issue(issues)
    monkeypatch.setattr("rescore.issue_review.find_musescore", lambda _root: None)
    pack_result = build_review_pack(tmp_path, source, tmp_path / "pack", issues_path=issues)

    corrected = tmp_path / "corrected-without-id.musicxml"
    tree = ET.parse(pack_result["musicxml"])
    for node in tree.findall(".//rehearsal") + tree.findall(".//words"):
        node.text = ""
    note = tree.find("./part/measure/note")
    assert note is not None
    rest = note.find("rest")
    assert rest is not None
    note.remove(rest)
    pitch = ET.Element("pitch")
    ET.SubElement(pitch, "step").text = "F"
    ET.SubElement(pitch, "octave").text = "4"
    note.insert(0, pitch)
    ET.SubElement(note, "type").text = "whole"
    tree.write(corrected, encoding="utf-8", xml_declaration=True)

    dataset = tmp_path / "dataset"
    initialize_dataset(dataset, dataset_id="mapped", name="Mapped corrections")
    add_pair(
        tmp_path,
        dataset,
        item_id="manuscript",
        images=[image],
        score=target,
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
        alignment_status="inferred",
    )
    result = apply_dataset_fix(
        tmp_path,
        dataset,
        item_id="manuscript",
        pack_path=Path(pack_result["manifest"]),
        corrected=corrected,
        reviewer="Reviewer",
        target_map={("P1", "1"): ("P29", "1")},
        confirm_order=True,
    )
    assert not result["base_matches_ground_truth"]
    assert result["id_mapping_mode"] == "positional-confirmed"
    manifest = json.loads((dataset / "rescore-dataset.json").read_text(encoding="utf-8"))
    correction = manifest["items"][0]["corrections"][0]
    overrides = json.loads((dataset / correction["overrides"]["path"]).read_text(encoding="utf-8"))
    override = overrides["overrides"][0]
    assert override["source_part_id"] == "P1"
    assert override["target_part_id"] == "P29"
    assert override["events"][0]["pitch"] == "F4"
    assert validate_dataset(dataset)["valid"]
