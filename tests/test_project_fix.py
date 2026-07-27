from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rescore.project_fix import apply_project_fixes, find_projects_for_pdf


def _write_project(projects: Path, slug: str, source_pdf: Path, source_hash: str) -> Path:
    project = projects / slug
    run = project / "runs" / "run-001"
    run.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps(
            {
                "name": slug,
                "latest_run": "runs/run-001",
                "promoted_run": "runs/run-001",
            }
        ),
        encoding="utf-8",
    )
    (run / "run.json").write_text(
        json.dumps(
            {
                "pages": "7-41",
                "source_pdf": {
                    "path": str(source_pdf.resolve()),
                    "sha256": source_hash,
                },
            }
        ),
        encoding="utf-8",
    )
    return project


def test_finds_corrected_projects_by_source_pdf_hash(tmp_path: Path) -> None:
    source = tmp_path / "score.pdf"
    source.write_bytes(b"score source")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    projects = tmp_path / "projects"
    expected = _write_project(projects, "matching", source, source_hash)
    _write_project(projects, "different", tmp_path / "other.pdf", "0" * 64)

    result = find_projects_for_pdf(projects, source)

    assert len(result) == 1
    assert result[0]["project"] == expected
    assert result[0]["matched_by"] == "sha256"
    assert result[0]["pages"] == "7-41"


def test_fix_reexports_corrected_root_score_and_promotes_new_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "score.pdf"
    source.write_bytes(b"score source")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    projects = tmp_path / "projects"
    project = _write_project(projects, "matching", source, source_hash)
    (project / "partitura.mscz").write_bytes(b"corrected score")
    calls = []

    monkeypatch.setattr("rescore.project_fix.find_musescore", lambda _root: Path("MuseScore"))

    def fake_convert(_musescore, corrected, destination, _log) -> None:
        calls.append((corrected, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"converted")

    def fake_review(_root, **kwargs):
        calls.append(("review", kwargs))
        run = project / "runs" / "run-002"
        run.mkdir()
        return {"project": str(project), "run": str(run)}

    def fake_promote(project_path, *, run):
        calls.append(("promote", project_path, run))
        return {"project": str(project_path), "promoted_run": str(run)}

    monkeypatch.setattr("rescore.project_fix.convert_with_musescore", fake_convert)
    monkeypatch.setattr("rescore.project_fix.create_review_project", fake_review)
    monkeypatch.setattr("rescore.project_fix.promote_project_run", fake_promote)

    result = apply_project_fixes(
        tmp_path,
        source,
        projects_root=projects,
        output_root=tmp_path / "fixes",
    )

    assert result["projects_updated"] == 1
    assert calls[0][0] == project / "partitura.mscz"
    assert calls[0][1].name == "partitura-corrigida.musicxml"
    assert calls[1][1].name == "partitura-corrigida.pdf"
    assert calls[-1][0] == "promote"
