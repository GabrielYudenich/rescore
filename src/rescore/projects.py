"""Organized, resumable review projects for generated scores."""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import tempfile
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .instruments import (
    canonical_instrument_label,
    identify_instrument,
    identify_instruments,
    instrument_catalog,
)
from .issue_review import build_review_pack, detect_score_issues
from .musicxml import _read_musicxml, parse_musicxml
from .pipeline import convert_with_musescore
from .tooling import find_musescore

PROJECT_SCHEMA_VERSION = "1.0"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    result = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if not result:
        raise ValueError("o nome do projeto precisa conter letras ou números")
    return result


def _record(path: Path, relative_to: Path | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    display = (
        resolved.relative_to(relative_to.resolve()).as_posix()
        if relative_to and resolved.is_relative_to(relative_to.resolve())
        else str(resolved)
    )
    return {"path": display, "sha256": _sha256(resolved), "bytes": resolved.stat().st_size}


def _copy_score_to_musicxml(project_root: Path, source: Path, destination: Path) -> None:
    suffix = source.suffix.casefold()
    if suffix in {".musicxml", ".xml"}:
        shutil.copy2(source, destination)
    elif suffix == ".mxl":
        destination.write_bytes(_read_musicxml(source))
    elif suffix == ".mscz":
        musescore = find_musescore(project_root)
        if musescore is None:
            raise FileNotFoundError("MuseScore não encontrado; execute `rescore doctor`")
        convert_with_musescore(musescore, source, destination, destination.with_suffix(".log"))
    else:
        raise ValueError(f"formato de partitura não suportado: {source.suffix}")
    parse_musicxml(destination, include_rests=True)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_logs(source: Path | None, destination: Path) -> list[dict[str, Any]]:
    if source is None:
        return []
    source = source.resolve()
    if not source.is_dir():
        raise NotADirectoryError(source)
    records = []
    for path in sorted(source.iterdir()):
        if not path.is_file() or path.suffix.casefold() not in {".json", ".log", ".txt"}:
            continue
        target = destination / path.name
        shutil.copy2(path, target)
        records.append(_record(target, destination.parent))
    return records


def _read_upstream_diagnostics(source: Path | None) -> dict[str, Any]:
    if source is None:
        return {}
    playability_path = source.resolve() / "playability-report.json"
    if not playability_path.is_file():
        return {}
    payload = json.loads(playability_path.read_text(encoding="utf-8"))
    ambiguous = payload.get("ambiguous_chord_groups", [])
    return {
        "removed_condensed_pitches": int(payload.get("condensed_chord_notes_removed", 0)),
        "ambiguous_chord_groups": len(ambiguous),
        "ambiguous_measures": sorted(
            {int(item["measure"]) for item in ambiguous if item.get("measure") is not None}
        ),
        "empty_percussion_measures": int(payload.get("empty_percussion_measures", 0)),
    }


def _preflight_musescore_delivery(project_root: Path, source: Path) -> dict[str, Any]:
    """Reject an MSCZ whose own MusicXML export contains incomplete/long bars."""
    musescore = find_musescore(project_root)
    if musescore is None:
        raise FileNotFoundError("MuseScore não encontrado; execute `rescore doctor`")
    with tempfile.TemporaryDirectory(prefix="rescore-mscz-roundtrip-") as temporary:
        temporary_dir = Path(temporary)
        roundtrip = temporary_dir / "roundtrip.musicxml"
        convert_with_musescore(
            musescore,
            source,
            roundtrip,
            temporary_dir / "musescore.log",
        )
        detection = detect_score_issues(roundtrip, temporary_dir / "issues")
        issues = [
            json.loads(line)
            for line in Path(detection["issues"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    critical_kinds = {"measure-incomplete", "measure-long", "negative-voice-start"}
    critical = [issue for issue in issues if issue["kind"] in critical_kinds]
    if critical:
        locations = ", ".join(
            f"compasso {issue['measure']} / {issue['possible_instrument']} / pauta {issue['staff']}"
            for issue in critical[:8]
        )
        raise ValueError(
            "o MSCZ não passou pela reexportação do próprio MuseScore: "
            f"{len(critical)} erro(s) estrutural(is): {locations}"
        )
    return {
        "valid": True,
        "issues": len(issues),
        "critical_issues": 0,
        "by_kind": dict(sorted(Counter(issue["kind"] for issue in issues).items())),
    }


def _write_project_html(
    path: Path,
    *,
    name: str,
    score: dict[str, Any],
    issue_summary: dict[str, Any],
    artifacts: list[dict[str, Any]],
    logs: list[dict[str, Any]],
    packs: list[dict[str, Any]],
    upstream_diagnostics: dict[str, Any],
) -> None:
    artifact_items = "".join(
        f'<li><a href="{html.escape(item["path"])}">{html.escape(item["label"])}</a></li>'
        for item in artifacts
    )
    pack_items = (
        "".join(
            "<li>"
            f"Pacote {item['number']}: compassos {html.escape(item['measure_text'])} - "
            f'<a href="{html.escape(item["mscz"])}">MuseScore</a> - '
            f'<a href="{html.escape(item["pdf"])}">PDF</a> - '
            f'<a href="{html.escape(item["manifest"])}">manifesto</a>'
            "</li>"
            for item in packs
        )
        or "<li>Nenhum pacote necessário.</li>"
    )
    log_items = (
        "".join(
            f'<li><a href="{html.escape(item["path"])}">'
            f"{html.escape(Path(item['path']).name)}</a></li>"
            for item in logs
        )
        or "<li>Nenhum log copiado.</li>"
    )
    diagnostic_cards = ""
    if upstream_diagnostics:
        diagnostic_cards = (
            '<div class="card"><strong>'
            f"{upstream_diagnostics['ambiguous_chord_groups']}</strong><br>grupos de alturas "
            "ambíguos</div>"
            '<div class="card"><strong>'
            f"{upstream_diagnostics['removed_condensed_pitches']}</strong><br>alturas "
            "descartadas pela regra de tocabilidade</div>"
        )
    kind_rows = "".join(
        f"<tr><td>{html.escape(kind)}</td><td>{count}</td></tr>"
        for kind, count in issue_summary["by_kind"].items()
    )
    instrument_rows = "".join(
        f"<tr><td>{html.escape(instrument)}</td><td>{count}</td></tr>"
        for instrument, count in issue_summary["by_instrument"].items()
    )
    path.write_text(
        f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(name)} - ReScore</title><style>
body{{font-family:Segoe UI,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;
background:#f5f2ec;color:#202825}}h1,h2{{color:#173a37}}.cards{{display:flex;gap:14px;
flex-wrap:wrap}}.card{{background:white;border:1px solid #d8d2c7;border-radius:8px;
padding:14px;min-width:150px}}table{{border-collapse:collapse;background:white;min-width:320px}}
th,td{{border:1px solid #d8d2c7;padding:8px;text-align:left}}a{{color:#075f56}}
</style></head><body><h1>{html.escape(name)}</h1><div class="cards">
<div class="card"><strong>{score["measures"]}</strong><br>compassos</div>
<div class="card"><strong>{score["parts_count"]}</strong><br>partes</div>
<div class="card"><strong>{issue_summary["count"]}</strong><br>suspeitas</div>
<div class="card"><strong>{issue_summary["measure_count"]}</strong><br>compassos para revisar</div>
{diagnostic_cards}
</div><h2>Entregas</h2><ul>{artifact_items}</ul>
<p><a href="issues/issues.html">Abrir relatório detalhado de problemas</a></p>
<h2>Pacotes de correção</h2><ul>{pack_items}</ul>
<h2>Relatórios e logs da geração</h2><ul>{log_items}</ul>
<h2>Problemas por tipo</h2><table><tr><th>Tipo</th><th>Quantidade</th></tr>{kind_rows}</table>
<h2>Problemas por instrumento</h2><table><tr><th>Instrumento</th><th>Quantidade</th></tr>
{instrument_rows}</table></body></html>""",
        encoding="utf-8",
    )


def create_review_project(
    project_root: Path,
    *,
    name: str,
    score: Path,
    output_root: Path,
    musescore_score: Path | None = None,
    score_pdf: Path | None = None,
    source_pdf: Path | None = None,
    pages: str | None = None,
    artifacts_dir: Path | None = None,
    batch_size: int = 20,
    meter: str | None = None,
) -> dict[str, Any]:
    """Create one immutable review run below projects/<slug>/runs/."""
    if batch_size < 1 or batch_size > 100:
        raise ValueError("--batch-size precisa estar entre 1 e 100")
    project_root = project_root.resolve()
    score = score.resolve()
    if not score.is_file():
        raise FileNotFoundError(score)
    delivery_roundtrip_validation = None
    if musescore_score is not None:
        musescore_score = musescore_score.resolve()
        if not musescore_score.is_file():
            raise FileNotFoundError(musescore_score)
        delivery_roundtrip_validation = _preflight_musescore_delivery(project_root, musescore_score)
    output_root = output_root.resolve()
    project_dir = output_root / _slug(name)
    run_dir = project_dir / "runs" / _stamp()
    input_dir = run_dir / "entrada"
    delivery_dir = run_dir / "entregas"
    issues_dir = run_dir / "issues"
    review_dir = run_dir / "correcoes"
    logs_dir = run_dir / "logs"
    for directory in (input_dir, delivery_dir, issues_dir, review_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=False)

    score_xml = input_dir / "partitura.musicxml"
    _copy_score_to_musicxml(project_root, score, score_xml)
    parsed = parse_musicxml(score_xml, include_rests=True)
    original_copy = input_dir / f"partitura-original{score.suffix.casefold()}"
    if score.resolve() != score_xml.resolve():
        shutil.copy2(score, original_copy)

    deliveries: list[dict[str, Any]] = []
    for label, source, filename in (
        ("Partitura MuseScore", musescore_score, "partitura.mscz"),
        ("PDF da partitura", score_pdf, "partitura.pdf"),
    ):
        if source is None:
            continue
        source = source.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        target = delivery_dir / filename
        shutil.copy2(source, target)
        deliveries.append({"label": label, "path": target.relative_to(run_dir).as_posix()})
    deliveries.insert(
        0,
        {"label": "MusicXML analisado", "path": score_xml.relative_to(run_dir).as_posix()},
    )
    copied_logs = _copy_logs(artifacts_dir, logs_dir)
    upstream_diagnostics = _read_upstream_diagnostics(artifacts_dir)

    resolution = []
    for part in parsed["parts"]:
        identity = identify_instrument(part["name"])
        identities = identify_instruments(part["name"])
        resolution.append(
            {
                "part_id": part["id"],
                "source_name": part["name"],
                "canonical_name": canonical_instrument_label(part["name"]),
                "instrument_id": identity["id"] if identity else None,
                "instrument_ids": [item["id"] for item in identities],
                "family": identity["family"] if identity else None,
                "families": list(dict.fromkeys(item["family"] for item in identities)),
                "confidence": identity["confidence"] if identity else 0.0,
            }
        )
    resolution_path = run_dir / "instrumentos.json"
    _write_json(resolution_path, resolution)
    _write_json(project_dir / "dicionario-instrumentos.json", instrument_catalog())

    detection = detect_score_issues(score_xml, issues_dir, meter=meter)
    issues = [
        json.loads(line)
        for line in Path(detection["issues"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    measures = sorted({int(issue["measure"]) for issue in issues})
    packs = []
    for offset in range(0, len(measures), batch_size):
        batch_measures = measures[offset : offset + batch_size]
        batch_issues = [issue for issue in issues if int(issue["measure"]) in batch_measures]
        number = offset // batch_size + 1
        batch_dir = review_dir / f"pacote-{number:03d}"
        batch_issues_path = batch_dir.parent / f"pacote-{number:03d}-issues.jsonl"
        batch_issues_path.write_text(
            "".join(json.dumps(issue, ensure_ascii=False) + "\n" for issue in batch_issues),
            encoding="utf-8",
        )
        result = build_review_pack(
            project_root,
            score_xml,
            batch_dir,
            issues_path=batch_issues_path,
            meter=meter,
        )
        packs.append(
            {
                "number": number,
                "measures": batch_measures,
                "measure_text": ", ".join(str(measure) for measure in batch_measures),
                "issues": len(batch_issues),
                "mscz": Path(result["mscz"]).relative_to(run_dir).as_posix()
                if result["mscz"]
                else "",
                "pdf": Path(result["pdf"]).relative_to(run_dir).as_posix() if result["pdf"] else "",
                "manifest": Path(result["manifest"]).relative_to(run_dir).as_posix(),
            }
        )

    issue_summary = {
        "count": len(issues),
        "measure_count": len(measures),
        "measures": measures,
        "by_kind": dict(sorted(Counter(issue["kind"] for issue in issues).items())),
        "by_instrument": dict(
            Counter(issue["possible_instrument"] for issue in issues).most_common()
        ),
        "by_severity": dict(sorted(Counter(issue["severity"] for issue in issues).items())),
    }
    source_record = None
    if source_pdf is not None:
        source_pdf = source_pdf.resolve()
        if not source_pdf.is_file():
            raise FileNotFoundError(source_pdf)
        source_record = _record(source_pdf)
    run_manifest = {
        "schema": "rescore-review-project-run",
        "schema_version": PROJECT_SCHEMA_VERSION,
        "created_at": _now(),
        "name": name,
        "project_slug": project_dir.name,
        "pages": pages,
        "source_pdf": source_record,
        "score_source": _record(score),
        "score": {
            "musicxml": _record(score_xml, run_dir),
            "parts": parsed["parts_count"],
            "measures": parsed["measures"],
            "events": parsed["events_count"],
        },
        "instrument_resolution": _record(resolution_path, run_dir),
        "issues": {
            **issue_summary,
            "jsonl": _record(Path(detection["issues"]), run_dir),
            "html": _record(Path(detection["html"]), run_dir),
        },
        "review_packs": packs,
        "copied_logs": copied_logs,
        "upstream_diagnostics": upstream_diagnostics,
        "deliveries": deliveries,
        "delivery_roundtrip_validation": delivery_roundtrip_validation,
    }
    run_manifest_path = run_dir / "run.json"
    _write_json(run_manifest_path, run_manifest)
    _write_project_html(
        run_dir / "index.html",
        name=name,
        score=parsed,
        issue_summary=issue_summary,
        artifacts=deliveries,
        logs=copied_logs,
        packs=packs,
        upstream_diagnostics=upstream_diagnostics,
    )
    project_manifest_path = project_dir / "project.json"
    previous = (
        json.loads(project_manifest_path.read_text(encoding="utf-8"))
        if project_manifest_path.is_file()
        else {
            "schema": "rescore-review-project",
            "schema_version": PROJECT_SCHEMA_VERSION,
            "name": name,
            "slug": project_dir.name,
            "created_at": run_manifest["created_at"],
            "runs": [],
        }
    )
    previous["updated_at"] = run_manifest["created_at"]
    previous["latest_run"] = run_dir.relative_to(project_dir).as_posix()
    previous["runs"].append(
        {
            "created_at": run_manifest["created_at"],
            "path": run_dir.relative_to(project_dir).as_posix(),
            "issues": len(issues),
            "review_packs": len(packs),
        }
    )
    _write_json(project_manifest_path, previous)
    (project_dir / "LEIA-ME.txt").write_text(
        "ReScore - projeto de revisão\n\n"
        "Abra o arquivo index.html dentro da pasta indicada por latest_run em project.json.\n"
        "As partituras editáveis ficam em entregas/ e os formulários em correcoes/.\n"
        "A fonte PDF não é copiada; somente seu caminho e hash ficam no manifesto local.\n",
        encoding="utf-8",
    )
    return {
        "project": str(project_dir),
        "run": str(run_dir),
        "index": str(run_dir / "index.html"),
        "manifest": str(run_manifest_path),
        "score": {"parts": parsed["parts_count"], "measures": parsed["measures"]},
        "issues": issue_summary,
        "review_packs": packs,
    }
