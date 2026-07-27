"""Revalidate corrected root-level MuseScore files as new project runs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .pipeline import convert_with_musescore
from .projects import create_review_project, promote_project_run
from .tooling import find_musescore


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _project_source(project_dir: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    selected_run = manifest.get("promoted_run") or manifest.get("latest_run")
    if not selected_run:
        return None
    run_manifest_path = project_dir / selected_run / "run.json"
    if not run_manifest_path.is_file():
        return None
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    return {
        "run": selected_run,
        "source_pdf": run_manifest.get("source_pdf"),
        "pages": run_manifest.get("pages"),
    }


def find_projects_for_pdf(projects_root: Path, pdf_path: Path) -> list[dict[str, Any]]:
    """Find local projects linked to the same PDF by hash, falling back to exact path."""
    projects_root = projects_root.resolve()
    pdf_path = pdf_path.resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    pdf_hash = _sha256(pdf_path)
    matches = []
    if not projects_root.is_dir():
        return matches
    for project_dir in sorted(path for path in projects_root.iterdir() if path.is_dir()):
        manifest_path = project_dir / "project.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source = _project_source(project_dir, manifest)
        if not source or not source["source_pdf"]:
            continue
        source_pdf = source["source_pdf"]
        same_hash = source_pdf.get("sha256") == pdf_hash
        source_path = Path(source_pdf.get("path", ""))
        same_path = bool(str(source_path)) and source_path.resolve() == pdf_path
        if same_hash or same_path:
            matches.append(
                {
                    "project": project_dir,
                    "manifest": manifest,
                    "pages": source["pages"],
                    "matched_by": "sha256" if same_hash else "path",
                }
            )
    return matches


def apply_project_fixes(
    project_root: Path,
    pdf_path: Path,
    *,
    projects_root: Path | None = None,
    output_root: Path | None = None,
) -> dict[str, Any]:
    """Import each corrected root MSCZ, validate it, and promote a new immutable run."""
    project_root = project_root.resolve()
    pdf_path = pdf_path.resolve()
    projects_root = (projects_root or project_root / "projects").resolve()
    output_root = (output_root or project_root / "output" / "fixes").resolve()
    musescore = find_musescore(project_root)
    if musescore is None:
        raise FileNotFoundError("MuseScore não encontrado; execute `rescore doctor`")
    matches = find_projects_for_pdf(projects_root, pdf_path)
    if not matches:
        raise ValueError(
            "nenhum projeto foi associado a este PDF; gere e promova uma primeira versão antes"
        )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    results = []
    for match in matches:
        project_dir: Path = match["project"]
        if (project_dir / "REPROVADO.txt").is_file():
            raise ValueError(
                f"o projeto está marcado como reprovado; revise o marcador antes: {project_dir}"
            )
        corrected_mscz = project_dir / "partitura.mscz"
        if not corrected_mscz.is_file():
            raise FileNotFoundError(
                f"partitura principal para correção não encontrada: {corrected_mscz}"
            )
        fix_dir = output_root / project_dir.name / stamp
        fix_dir.mkdir(parents=True, exist_ok=False)
        corrected_xml = fix_dir / "partitura-corrigida.musicxml"
        corrected_pdf = fix_dir / "partitura-corrigida.pdf"
        convert_with_musescore(
            musescore,
            corrected_mscz,
            corrected_xml,
            fix_dir / "musescore-export-musicxml.log",
        )
        convert_with_musescore(
            musescore,
            corrected_mscz,
            corrected_pdf,
            fix_dir / "musescore-export-pdf.log",
        )
        review = create_review_project(
            project_root,
            name=match["manifest"]["name"],
            score=corrected_xml,
            output_root=projects_root,
            musescore_score=corrected_mscz,
            score_pdf=corrected_pdf,
            source_pdf=pdf_path,
            pages=match["pages"],
            artifacts_dir=fix_dir,
        )
        promotion = promote_project_run(Path(review["project"]), run=Path(review["run"]))
        result = {
            "project": str(project_dir),
            "matched_by": match["matched_by"],
            "pages": match["pages"],
            "fix_output": str(fix_dir),
            "review": review,
            "promotion": promotion,
        }
        (fix_dir / "fix.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        results.append(result)
    return {
        "source_pdf": str(pdf_path),
        "projects_updated": len(results),
        "results": results,
    }
