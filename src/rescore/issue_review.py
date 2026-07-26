"""Issue detection and MuseScore correction-pack generation."""

from __future__ import annotations

import copy
import hashlib
import html
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any

from .mscz import set_page_layout
from .musicxml import _read_musicxml, _strip_namespaces, parse_musicxml
from .normalize import validate_meter_score
from .pipeline import convert_with_musescore
from .tooling import find_musescore

ISSUE_SCHEMA_VERSION = "1.0"
REVIEW_PACK_SCHEMA_VERSION = "1.0"


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_record(path: Path, root: Path) -> dict[str, str]:
    return {"path": path.resolve().relative_to(root.resolve()).as_posix(), "sha256": _sha256(path)}


def _meter_duration(meter: str) -> Fraction:
    match = re.fullmatch(r"(\d+)/(\d+)", meter.strip())
    if not match:
        raise ValueError(f"fórmula de compasso inválida: {meter}")
    beats, beat_type = (int(value) for value in match.groups())
    if beats < 1 or beat_type < 1:
        raise ValueError(f"fórmula de compasso inválida: {meter}")
    return Fraction(beats * 4, beat_type)


def _fraction_text(value: Fraction) -> str:
    return (
        str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    )


def _effective_meter_map(score: dict[str, Any], override: str | None) -> dict[tuple[str, int], str]:
    if override:
        _meter_duration(override)
        return {
            (part["id"], measure): override
            for part in score["parts"]
            for measure in range(1, score["measure_counts"].get(part["id"], 0) + 1)
        }
    changes: dict[str, list[tuple[int, str]]] = defaultdict(list)
    global_changes: dict[int, str] = {}
    for time in score.get("time_signatures", []):
        if time.get("beats") and time.get("beat_type"):
            meter = f"{time['beats']}/{time['beat_type']}"
            measure = int(time["measure_index"])
            changes[time["part_id"]].append((measure, meter))
            global_changes.setdefault(measure, meter)
    result: dict[tuple[str, int], str] = {}
    for part in score["parts"]:
        current: str | None = None
        local = dict(changes.get(part["id"], []))
        for measure in range(1, score["measure_counts"].get(part["id"], 0) + 1):
            current = local.get(measure, global_changes.get(measure, current))
            if current:
                result[(part["id"], measure)] = current
    return result


def _issue_id(
    measure: int,
    part_id: str,
    staff: str,
    voice: str,
    kind: str,
) -> str:
    safe_part = re.sub(r"[^A-Za-z0-9]+", "", part_id) or "PART"
    safe_kind = re.sub(r"[^A-Za-z0-9]+", "-", kind).strip("-").upper()
    return f"RS-M{measure:04d}-{safe_part}-S{int(staff):02d}-V{voice}-{safe_kind}"


def _write_issue_html(source: Path, issues: list[dict[str, Any]], output: Path) -> None:
    rows = []
    for issue in issues:
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(issue['id'])}</code></td>"
            f"<td>{html.escape(issue['severity'])}</td>"
            f"<td>{issue['measure']}</td>"
            f"<td>{html.escape(issue['possible_instrument'])}</td>"
            f"<td>{html.escape(issue['staff'])}</td>"
            f"<td>{html.escape(issue['message'])}</td>"
            "</tr>"
        )
    output.write_text(
        f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Problemas de leitura — {html.escape(source.name)}</title>
        <style>body{{font-family:Segoe UI,sans-serif;margin:28px;background:#f5f2ec}}
        table{{border-collapse:collapse;width:100%;background:white}}th,td{{padding:9px;
        border:1px solid #ccc;text-align:left}}th{{background:#173a37;color:white}}
        code{{white-space:nowrap}}</style></head><body><h1>Problemas de leitura</h1>
        <p>Fonte: <code>{html.escape(str(source))}</code>. Cada linha é uma hipótese
        estrutural e requer revisão humana.</p><table><thead><tr><th>ID</th><th>Nível</th>
        <th>Compasso</th><th>Instrumento provável</th><th>Pauta</th><th>Motivo</th>
        </tr></thead><tbody>{"".join(rows)}</tbody></table></body></html>""",
        encoding="utf-8",
    )


def detect_score_issues(
    source: Path,
    output_dir: Path,
    *,
    meter: str | None = None,
) -> dict[str, Any]:
    """Detect metric and representation anomalies in a generated MusicXML score."""
    source = source.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    score = parse_musicxml(source, include_rests=True)
    meters = _effective_meter_map(score, meter)
    grouped: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for event in score["events"]:
        grouped[
            (
                event["part_id"],
                event.get("staff", "1"),
                event.get("voice", "1"),
                int(event["measure_index"]),
            )
        ].append(event)
    names = {part["id"]: part["name"] for part in score["parts"]}
    issues: list[dict[str, Any]] = []
    for (part_id, staff, voice, measure), events in sorted(grouped.items()):
        expected_meter = meters.get((part_id, measure))
        if not expected_meter:
            issues.append(
                {
                    "kind": "meter-unknown",
                    "severity": "warning",
                    "measure": measure,
                    "part_id": part_id,
                    "possible_instrument": names.get(part_id, part_id),
                    "staff": staff,
                    "voice": voice,
                    "message": "fórmula de compasso não encontrada para validar a duração",
                }
            )
            continue
        expected = _meter_duration(expected_meter)
        sounding = [event for event in events if not event.get("grace")]
        starts = [Fraction(event["onset"]) for event in sounding]
        ends = [Fraction(event["onset"]) + Fraction(event["duration"]) for event in sounding]
        found = max(ends, default=Fraction(0))
        if any(start < 0 for start in starts):
            issues.append(
                {
                    "kind": "negative-onset",
                    "severity": "error",
                    "measure": measure,
                    "part_id": part_id,
                    "possible_instrument": names.get(part_id, part_id),
                    "staff": staff,
                    "voice": voice,
                    "message": "uma voz retorna para antes do início do compasso",
                    "meter": expected_meter,
                }
            )
        if found != expected:
            relation = "long" if found > expected else "incomplete"
            issues.append(
                {
                    "kind": f"measure-{relation}",
                    "severity": "error" if found > expected else "warning",
                    "measure": measure,
                    "part_id": part_id,
                    "possible_instrument": names.get(part_id, part_id),
                    "staff": staff,
                    "voice": voice,
                    "message": (
                        f"voz {'ultrapassa' if found > expected else 'não completa'} o compasso: "
                        f"encontrado {_fraction_text(found)}, esperado {expected_meter}"
                    ),
                    "found_duration": _fraction_text(found),
                    "expected_duration": _fraction_text(expected),
                    "meter": expected_meter,
                }
            )
        for event in events:
            if not event.get("rest") and not event.get("pitch"):
                issues.append(
                    {
                        "kind": "pitch-unknown",
                        "severity": "warning",
                        "measure": measure,
                        "part_id": part_id,
                        "possible_instrument": names.get(part_id, part_id),
                        "staff": staff,
                        "voice": voice,
                        "message": f"evento sem altura confirmada no tempo {event['onset']}",
                    }
                )
            denominator = Fraction(event["duration"]).denominator
            if denominator & (denominator - 1) and not event.get("tuplet"):
                issues.append(
                    {
                        "kind": "irregular-duration-without-tuplet",
                        "severity": "warning",
                        "measure": measure,
                        "part_id": part_id,
                        "possible_instrument": names.get(part_id, part_id),
                        "staff": staff,
                        "voice": voice,
                        "message": (
                            f"duração {event['duration']} no tempo {event['onset']} "
                            "não possui marca de quiáltera"
                        ),
                    }
                )
    for issue in issues:
        issue["id"] = _issue_id(
            int(issue["measure"]),
            issue["part_id"],
            issue["staff"],
            issue["voice"],
            issue["kind"],
        )
        issue["schema_version"] = ISSUE_SCHEMA_VERSION
    # One visual stream can trigger several events of the same kind. Keep the
    # report compact while retaining different reasons.
    unique = {}
    for issue in issues:
        unique.setdefault(issue["id"], issue)
    issues = list(unique.values())
    issues_path = output_dir / "issues.jsonl"
    issues_path.write_text(
        "".join(
            json.dumps(issue, ensure_ascii=False, separators=(",", ":")) + "\n" for issue in issues
        ),
        encoding="utf-8",
    )
    html_path = output_dir / "issues.html"
    _write_issue_html(source, issues, html_path)
    counts = Counter(issue["severity"] for issue in issues)
    return {
        "source": str(source),
        "issues": str(issues_path),
        "html": str(html_path),
        "count": len(issues),
        "severity_counts": dict(sorted(counts.items())),
    }


def _load_issues(path: Path) -> list[dict[str, Any]]:
    issues = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            issue = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON inválido em {path}, linha {line_number}: {exc}") from exc
        for field in ("measure", "part_id", "staff", "possible_instrument", "message"):
            if field not in issue:
                raise ValueError(f"issue sem {field}, linha {line_number}")
        issue.setdefault("voice", "1")
        issue.setdefault("kind", "manual-review")
        issue.setdefault("severity", "warning")
        issue.setdefault(
            "id",
            _issue_id(
                int(issue["measure"]),
                issue["part_id"],
                issue["staff"],
                issue["voice"],
                issue["kind"],
            ),
        )
        issues.append(issue)
    if not issues:
        raise ValueError("nenhum problema foi informado para o pacote de revisão")
    return issues


def _effective_attributes(part: ET.Element, measure_index: int) -> ET.Element | None:
    latest: dict[tuple[str, str], ET.Element] = {}
    order = {"divisions": 0, "key": 1, "time": 2, "staves": 3, "clef": 4, "transpose": 5}
    measures = part.findall("measure")
    for measure in measures[:measure_index]:
        for attributes in measure.findall("attributes"):
            for child in attributes:
                if child.tag not in order:
                    continue
                latest[(child.tag, child.get("number", ""))] = copy.deepcopy(child)
    if not latest:
        return None
    attributes = ET.Element("attributes")
    for key, child in sorted(latest.items(), key=lambda item: (order[item[0][0]], item[0][1])):
        del key
        attributes.append(child)
    return attributes


def _review_direction(
    issues: list[dict[str, Any]],
    original_measure: int,
    review_id: str,
) -> ET.Element:
    direction = ET.Element("direction", {"placement": "above"})
    direction_type = ET.SubElement(direction, "direction-type")
    ET.SubElement(direction_type, "rehearsal", {"enclosure": "rectangle"}).text = review_id
    words_type = ET.SubElement(direction, "direction-type")
    descriptions = "; ".join(
        f"{issue['possible_instrument']} | pauta {issue['staff']} | {issue['kind']}"
        for issue in issues
    )
    ET.SubElement(
        words_type, "words", {"font-size": "9"}
    ).text = f"{review_id} | Compasso original {original_measure} | {descriptions}"
    ET.SubElement(direction, "staff").text = str(issues[0]["staff"])
    return direction


def _blank_measure_attributes(
    source_part: ET.Element,
    original_measure: int,
    *,
    meter_override: str | None,
    minimum_staves: int,
) -> tuple[ET.Element, Fraction, int]:
    attributes = _effective_attributes(source_part, original_measure)
    if attributes is None:
        attributes = ET.Element("attributes")
    time = attributes.find("time")
    if meter_override:
        _meter_duration(meter_override)
        beats, beat_type = meter_override.split("/", 1)
        if time is None:
            time = ET.SubElement(attributes, "time")
        for child in list(time):
            time.remove(child)
        ET.SubElement(time, "beats").text = beats
        ET.SubElement(time, "beat-type").text = beat_type
    if time is None:
        raise ValueError(
            f"fórmula de compasso ausente em {source_part.get('id', '')}, "
            f"compasso {original_measure}; informe --meter"
        )
    meter = f"{time.findtext('beats', '')}/{time.findtext('beat-type', '')}"
    duration = _meter_duration(meter)
    divisions_node = attributes.find("divisions")
    divisions = int(divisions_node.text) if divisions_node is not None else 1
    divisions = math.lcm(max(1, divisions), duration.denominator)
    if divisions_node is None:
        divisions_node = ET.Element("divisions")
        attributes.insert(0, divisions_node)
    divisions_node.text = str(divisions)
    declared_staves = int(attributes.findtext("staves", "1"))
    clef_staves = max(
        (int(clef.get("number", "1")) for clef in attributes.findall("clef")),
        default=1,
    )
    staff_count = max(1, minimum_staves, declared_staves, clef_staves)
    if staff_count > 1:
        staves_node = attributes.find("staves")
        if staves_node is None:
            staves_node = ET.Element("staves")
            insertion = next(
                (
                    index
                    for index, child in enumerate(attributes)
                    if child.tag in {"clef", "transpose"}
                ),
                len(attributes),
            )
            attributes.insert(insertion, staves_node)
        staves_node.text = str(staff_count)
    return attributes, duration, staff_count


def _append_blank_staves(
    measure: ET.Element,
    *,
    duration: Fraction,
    divisions: int,
    staff_count: int,
) -> None:
    duration_units = duration * divisions
    if duration_units.denominator != 1:
        raise ValueError(f"duração de compasso não representável: {duration}")
    units = str(duration_units.numerator)
    for staff in range(1, staff_count + 1):
        if staff > 1:
            backup = ET.SubElement(measure, "backup")
            ET.SubElement(backup, "duration").text = units
        note = ET.SubElement(measure, "note")
        ET.SubElement(note, "rest", {"measure": "yes"})
        ET.SubElement(note, "duration").text = units
        ET.SubElement(note, "voice").text = "1"
        if staff_count > 1:
            ET.SubElement(note, "staff").text = str(staff)


def _validate_review_musicxml(path: Path) -> dict[str, Any]:
    score = parse_musicxml(path, include_rests=True)
    meters = _effective_meter_map(score, None)

    def duration_for(part_id: str, measure: int) -> Fraction:
        meter = meters.get((part_id, measure))
        if not meter:
            raise ValueError(f"fórmula ausente no pacote: {part_id}, compasso {measure}")
        return _meter_duration(meter)

    validation = validate_meter_score(score, duration_for)
    if not validation["valid"]:
        raise ValueError(f"pacote de revisão metricamente inválido: {validation['violations'][:3]}")
    return validation


def _source_musicxml(project_root: Path, source: Path, output_dir: Path) -> Path:
    source = source.resolve()
    if source.suffix.casefold() in {".musicxml", ".xml"}:
        return source
    if source.suffix.casefold() == ".mxl":
        unpacked = output_dir / "source.musicxml"
        unpacked.write_bytes(_read_musicxml(source))
        return unpacked
    if source.suffix.casefold() == ".mscz":
        musescore = find_musescore(project_root)
        if musescore is None:
            raise FileNotFoundError("MuseScore não encontrado; execute `rescore doctor`")
        unpacked = output_dir / "source.musicxml"
        convert_with_musescore(musescore, source, unpacked, output_dir / "source-export.log")
        return unpacked
    raise ValueError(f"formato de partitura não suportado: {source.suffix}")


def build_review_pack(
    project_root: Path,
    source: Path,
    output_dir: Path,
    *,
    issues_path: Path | None = None,
    meter: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Build a small editable score containing only measures that need review."""
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    manifest_path = output_dir / "review-pack.json"
    if manifest_path.exists() and not force:
        raise FileExistsError(f"pacote já existe: {manifest_path}; use --force")
    output_dir.mkdir(parents=True, exist_ok=True)
    source_xml = _source_musicxml(project_root, source, output_dir)
    if issues_path is None:
        detection = detect_score_issues(source_xml, output_dir / "detected-issues", meter=meter)
        issues_path = Path(detection["issues"])
    else:
        issues_path = issues_path.resolve()
    issues = _load_issues(issues_path)

    root = _strip_namespaces(ET.fromstring(_read_musicxml(source_xml)))
    parts = {part.get("id", ""): part for part in root.findall("part")}
    selected_parts = {issue["part_id"] for issue in issues}
    missing = sorted(selected_parts - parts.keys())
    if missing:
        raise ValueError(f"partes dos problemas não existem na partitura: {', '.join(missing)}")
    by_measure: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_measure_part: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for issue in issues:
        measure = int(issue["measure"])
        by_measure[measure].append(issue)
        by_measure_part[(measure, issue["part_id"])].append(issue)
    original_measures = sorted(by_measure)
    maximum_staff_by_part: dict[str, int] = defaultdict(lambda: 1)
    for issue in issues:
        maximum_staff_by_part[issue["part_id"]] = max(
            maximum_staff_by_part[issue["part_id"]], int(issue["staff"])
        )

    pack_root = copy.deepcopy(root)
    part_list = pack_root.find("part-list")
    if part_list is None:
        raise ValueError("MusicXML sem part-list")
    for child in list(part_list):
        if child.tag == "part-group" or (
            child.tag == "score-part" and child.get("id") not in selected_parts
        ):
            part_list.remove(child)
    for child in list(pack_root):
        if child.tag == "part" and child.get("id") not in selected_parts:
            pack_root.remove(child)
    work = pack_root.find("work")
    if work is None:
        work = ET.Element("work")
        pack_root.insert(0, work)
    title = work.find("work-title")
    if title is None:
        title = ET.SubElement(work, "work-title")
    original_title = title.text or source_xml.stem
    title.text = f"ReScore - correções - {original_title}"

    mappings = []
    for review_number, original_measure in enumerate(original_measures, 1):
        mappings.append(
            {
                "review_id": f"RS-REVIEW-{review_number:04d}",
                "review_measure": review_number,
                "original_measure": original_measure,
                "issue_ids": [issue["id"] for issue in by_measure[original_measure]],
                "parts": sorted({issue["part_id"] for issue in by_measure[original_measure]}),
                "staffs": sorted(
                    {
                        f"{issue['part_id']}:{issue['staff']}"
                        for issue in by_measure[original_measure]
                    }
                ),
            }
        )
    for pack_part in pack_root.findall("part"):
        part_id = pack_part.get("id", "")
        source_part = parts[part_id]
        source_measures = source_part.findall("measure")
        for child in list(pack_part):
            pack_part.remove(child)
        for review_number, original_measure in enumerate(original_measures, 1):
            if original_measure < 1 or original_measure > len(source_measures):
                raise ValueError(f"compasso {original_measure} não existe em {part_id}")
            measure = ET.Element("measure", {"number": str(review_number)})
            measure.append(ET.Element("print", {"new-system": "yes"}))
            attributes, measure_duration, staff_count = _blank_measure_attributes(
                source_part,
                original_measure,
                meter_override=meter,
                minimum_staves=maximum_staff_by_part[part_id],
            )
            measure.append(attributes)
            relevant = by_measure_part.get((original_measure, part_id), [])
            if relevant:
                measure.append(
                    _review_direction(
                        relevant,
                        original_measure,
                        f"RS-REVIEW-{review_number:04d}",
                    ),
                )
            divisions = int(attributes.findtext("divisions", "1"))
            _append_blank_staves(
                measure,
                duration=measure_duration,
                divisions=divisions,
                staff_count=staff_count,
            )
            pack_part.append(measure)

    pack_xml = output_dir / "review-pack.musicxml"
    ET.ElementTree(pack_root).write(pack_xml, encoding="utf-8", xml_declaration=True)
    validation = {"musicxml": _validate_review_musicxml(pack_xml), "musescore_roundtrip": None}
    mscz = output_dir / "review-pack.mscz"
    pdf = output_dir / "review-pack.pdf"
    roundtrip_xml = output_dir / "review-pack-roundtrip.musicxml"
    musescore = find_musescore(project_root)
    if musescore is not None:
        convert_with_musescore(musescore, pack_xml, mscz, output_dir / "musescore-mscz.log")
        spatium = 1.3 if len(selected_parts) <= 4 else 0.9 if len(selected_parts) <= 10 else 0.6
        set_page_layout(mscz, paper="A4", landscape=True, spatium_mm=spatium)
        convert_with_musescore(
            musescore,
            mscz,
            roundtrip_xml,
            output_dir / "musescore-roundtrip.log",
        )
        validation["musescore_roundtrip"] = _validate_review_musicxml(roundtrip_xml)
        convert_with_musescore(musescore, mscz, pdf, output_dir / "musescore-pdf.log")
    validation_path = output_dir / "review-pack-validation.json"
    validation_path.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": "rescore-review-pack",
        "schema_version": REVIEW_PACK_SCHEMA_VERSION,
        "created_at": _now(),
        "source": {"path": str(source.resolve()), "sha256": _sha256(source.resolve())},
        "source_musicxml": {"path": str(source_xml.resolve()), "sha256": _sha256(source_xml)},
        "issues": {"path": str(issues_path.resolve()), "sha256": _sha256(issues_path)},
        "pack_musicxml": _file_record(pack_xml, output_dir),
        "pack_mscz": _file_record(mscz, output_dir) if mscz.is_file() else None,
        "pack_pdf": _file_record(pdf, output_dir) if pdf.is_file() else None,
        "validation": _file_record(validation_path, output_dir),
        "mappings": mappings,
        "policy": "IDs visíveis e o sidecar devem permanecer juntos até a importação.",
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "output": str(output_dir),
        "manifest": str(manifest_path),
        "musicxml": str(pack_xml),
        "mscz": str(mscz) if mscz.is_file() else None,
        "pdf": str(pdf) if pdf.is_file() else None,
        "validation": str(validation_path),
        "issues": len(issues),
        "review_measures": len(mappings),
        "parts": len(selected_parts),
    }
