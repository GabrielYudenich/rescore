from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from rescore.projects import _preflight_musescore_delivery, create_review_project


def _write_overfull_score(path: Path) -> None:
    root = ET.Element("score-partwise", {"version": "4.0"})
    part_list = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(part_list, "score-part", {"id": "P1"})
    ET.SubElement(score_part, "part-name").text = "Basson"
    part = ET.SubElement(root, "part", {"id": "P1"})
    measure = ET.SubElement(part, "measure", {"number": "1"})
    attributes = ET.SubElement(measure, "attributes")
    ET.SubElement(attributes, "divisions").text = "1"
    time = ET.SubElement(attributes, "time")
    ET.SubElement(time, "beats").text = "4"
    ET.SubElement(time, "beat-type").text = "4"
    note = ET.SubElement(measure, "note")
    ET.SubElement(note, "rest")
    ET.SubElement(note, "duration").text = "5"
    ET.SubElement(note, "voice").text = "1"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_review_project_organizes_outputs_and_correction_pack(
    tmp_path: Path,
    monkeypatch,
) -> None:
    score = tmp_path / "score.musicxml"
    source_pdf = tmp_path / "source.pdf"
    _write_overfull_score(score)
    source_pdf.write_bytes(b"private source marker")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "playability-report.json").write_text(
        json.dumps(
            {
                "condensed_chord_notes_removed": 4,
                "ambiguous_chord_groups": [{"measure": 1}, {"measure": 1}],
                "empty_percussion_measures": 0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("rescore.issue_review.find_musescore", lambda _root: None)

    result = create_review_project(
        tmp_path,
        name="Chôros nº 9",
        score=score,
        output_root=tmp_path / "projects",
        source_pdf=source_pdf,
        pages="3-6",
        artifacts_dir=artifacts,
    )

    project = Path(result["project"])
    run = Path(result["run"])
    assert project.name == "choros-no-9"
    assert (run / "index.html").is_file()
    assert (run / "entrada" / "partitura.musicxml").is_file()
    assert not (run / "entrada" / "source.pdf").exists()
    assert result["issues"]["count"] == 1
    assert result["issues"]["by_instrument"] == {"Fagote": 1}
    assert len(result["review_packs"]) == 1
    assert (run / result["review_packs"][0]["manifest"]).is_file()
    manifest = json.loads((run / "run.json").read_text(encoding="utf-8"))
    assert manifest["source_pdf"]["path"] == str(source_pdf.resolve())
    assert manifest["pages"] == "3-6"
    assert manifest["upstream_diagnostics"] == {
        "removed_condensed_pitches": 4,
        "ambiguous_chord_groups": 2,
        "ambiguous_measures": [1],
        "empty_percussion_measures": 0,
    }


def test_musescore_preflight_rejects_roundtrip_with_invalid_measure_duration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    broken = tmp_path / "broken.musicxml"
    source = tmp_path / "score.mscz"
    _write_overfull_score(broken)
    source.write_bytes(b"test placeholder")
    monkeypatch.setattr("rescore.projects.find_musescore", lambda _root: Path("MuseScore"))

    def fake_convert(_musescore, _source, destination, _log_path) -> None:
        shutil.copy2(broken, destination)

    monkeypatch.setattr("rescore.projects.convert_with_musescore", fake_convert)
    with pytest.raises(ValueError, match="reexportação do próprio MuseScore"):
        _preflight_musescore_delivery(tmp_path, source)
