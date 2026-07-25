"""Export reviewable measure/staff crops with deterministic MusicXML targets."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.parse import quote

import cv2

from .alignment import _file_record, _find_item, _load_manifest, _now, _save_manifest
from .dataset import DatasetError
from .musicxml import parse_musicxml

TRAINING_EXPORT_SCHEMA_VERSION = "1.0"
TOKENIZER_VERSION = "musicxml-events-v1"
TRUSTED_GROUND_TRUTH = {"human-transcribed", "human-reviewed"}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _event_sort_key(indexed: tuple[int, dict[str, Any]]) -> tuple[Fraction, str, int]:
    index, event = indexed
    return Fraction(event["onset"]), event.get("voice", "1"), index


def _lyric_tokens(lyric: dict[str, str]) -> list[str]:
    tokens = ["<lyric>"]
    for name in ("number", "name", "syllabic", "extend"):
        value = lyric.get(name)
        if value:
            tokens.append(f"<{name}:{quote(value, safe='')}>")
    text = lyric.get("text")
    if text is not None:
        tokens.append("<lyric-text>")
        tokens.extend(f"<char:U+{ord(character):04X}>" for character in text)
        tokens.append("</lyric-text>")
    tokens.append("</lyric>")
    return tokens


def tokenize_events(events: list[dict[str, Any]], meter: str | None) -> list[str]:
    """Serialize one MusicXML staff stream without part-specific identifiers."""
    tokens = ["<stream>"]
    if meter:
        tokens.append(f"<meter:{meter}>")
    if not events:
        tokens.append("<empty>")
    for event in events:
        tokens.extend(
            (
                "<event>",
                f"<onset:{event['onset']}>",
                f"<duration:{event['duration']}>",
                f"<voice:{event.get('voice', '1')}>",
            )
        )
        if event.get("rest"):
            tokens.append("<rest>")
        elif event.get("pitch"):
            tokens.append(f"<pitch:{event['pitch']}>")
        else:
            tokens.append("<unpitched-unknown>")
        if event.get("type"):
            tokens.append(f"<type:{event['type']}>")
        if event.get("dots"):
            tokens.append(f"<dots:{event['dots']}>")
        if event.get("grace"):
            tokens.append("<grace>")
        if event.get("chord"):
            tokens.append("<chord>")
        tuplet = event.get("tuplet")
        if tuplet:
            tokens.append(f"<tuplet:{tuplet.get('actual')}/{tuplet.get('normal')}>")
        tokens.extend(f"<tie:{value}>" for value in event.get("ties", []))
        tokens.extend(f"<articulation:{value}>" for value in event.get("articulations", []))
        tremolo = event.get("tremolo")
        if tremolo:
            tokens.append(f"<tremolo:{tremolo.get('type')}:{tremolo.get('marks')}>")
        for lyric in event.get("lyrics", []):
            tokens.extend(_lyric_tokens(lyric))
        tokens.append("</event>")
    tokens.append("</stream>")
    return tokens


def _target_event(event: dict[str, Any]) -> dict[str, Any]:
    """Keep only notation fields intended to become supervised output."""
    return {
        "onset": event["onset"],
        "duration": event["duration"],
        "pitch": event.get("pitch"),
        "rest": bool(event.get("rest")),
        "grace": bool(event.get("grace")),
        "chord": bool(event.get("chord")),
        "voice": event.get("voice", "1"),
        "type": event.get("type"),
        "dots": int(event.get("dots", 0)),
        "tuplet": event.get("tuplet"),
        "ties": list(event.get("ties", [])),
        "articulations": list(event.get("articulations", [])),
        "tremolo": event.get("tremolo"),
        "lyrics": list(event.get("lyrics", [])),
    }


def _effective_meters(score: dict[str, Any]) -> dict[tuple[str, int], str]:
    changes: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for time in score.get("time_signatures", []):
        beats, beat_type = time.get("beats"), time.get("beat_type")
        if beats and beat_type:
            changes[time["part_id"]].append((int(time["measure_index"]), f"{beats}/{beat_type}"))
    result: dict[tuple[str, int], str] = {}
    for part in score.get("parts", []):
        current: str | None = None
        ordered = sorted(changes.get(part["id"], []))
        change_index = 0
        maximum = int(score.get("measure_counts", {}).get(part["id"], score.get("measures", 0)))
        for measure in range(1, maximum + 1):
            while change_index < len(ordered) and ordered[change_index][0] <= measure:
                current = ordered[change_index][1]
                change_index += 1
            if current:
                result[(part["id"], measure)] = current
    return result


def _event_lookup(score: dict[str, Any]) -> dict[tuple[str, str, int], list[dict[str, Any]]]:
    lookup: dict[tuple[str, str, int], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, event in enumerate(score.get("events", [])):
        lookup[(event["part_id"], event.get("staff", "1"), int(event["measure_index"]))].append(
            (index, event)
        )
    return {
        key: [_target_event(event) for _, event in sorted(values, key=_event_sort_key)]
        for key, values in lookup.items()
    }


def _build_target(
    targets: list[dict[str, Any]],
    measure: int,
    events: dict[tuple[str, str, int], list[dict[str, Any]]],
    meters: dict[tuple[str, int], str],
) -> tuple[dict[str, Any], str]:
    streams = []
    for target in targets:
        key = (target["part_id"], target["staff_number"], measure)
        stream_events = events.get(key, [])
        meter = meters.get((target["part_id"], measure))
        streams.append(
            {
                "target_ref": f"{target['part_id']}:{target['staff_number']}",
                "part_name": target["part_name"],
                "meter": meter,
                "events": stream_events,
                "tokens": tokenize_events(stream_events, meter),
            }
        )
    if not streams:
        relation = "unassigned"
    elif any(not stream["events"] for stream in streams):
        relation = "missing-target-events"
    elif len(streams) == 1:
        relation = "single-target"
    elif len({_hash_json(stream["tokens"]) for stream in streams}) == 1:
        relation = "equivalent-targets"
    else:
        relation = "multi-target"
    sequence = ["<sample>", f"<streams:{len(streams)}>"]
    for stream in streams:
        sequence.extend(stream["tokens"])
    sequence.append("</sample>")
    target = {
        "tokenizer": TOKENIZER_VERSION,
        "relation": relation,
        "streams": streams,
        "tokens": sequence,
    }
    target["sha256"] = _hash_json(target)
    return target, relation


def _eligibility(item: dict[str, Any], relation: str) -> tuple[bool, list[str]]:
    reasons = []
    alignment = item.get("alignment", {})
    if item.get("ground_truth", {}).get("verification") not in TRUSTED_GROUND_TRUTH:
        reasons.append("ground-truth-not-fully-human")
    if alignment.get("review_status") != "human-reviewed":
        reasons.append("measure-alignment-not-human-reviewed")
    if alignment.get("staff_review_status") != "human-reviewed":
        reasons.append("staff-alignment-not-human-reviewed")
    if relation == "unassigned":
        reasons.append("unassigned-visual-staff")
    if relation == "missing-target-events":
        reasons.append("missing-target-events")
    return not reasons, reasons


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


def export_training_samples(
    dataset_root: Path,
    *,
    item_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """Crop every measure/staff cell and attach an auditable MusicXML target."""
    dataset_root = dataset_root.resolve()
    manifest = _load_manifest(dataset_root)
    item = _find_item(manifest, item_id)
    staff_record = item.get("alignment", {}).get("staff_regions_file")
    if not isinstance(staff_record, dict):
        raise DatasetError("execute dataset-align-staffs antes de exportar amostras")
    staff_path = dataset_root / staff_record["path"]
    staff_data = json.loads(staff_path.read_text(encoding="utf-8"))
    score_path = dataset_root / item["ground_truth"]["musicxml"]["path"]
    score = parse_musicxml(score_path, include_rests=True)
    events = _event_lookup(score)
    meters = _effective_meters(score)

    export_dir = dataset_root / "items" / item_id / "training"
    image_dir = export_dir / "images"
    index_path = export_dir / "samples.jsonl"
    summary_path = export_dir / "summary.json"
    if index_path.exists() and not force:
        raise DatasetError(f"exportação já existe: {index_path}; use --force para refazer")
    image_dir.mkdir(parents=True, exist_ok=True)

    samples: list[dict[str, Any]] = []
    relation_counts: Counter[str] = Counter()
    eligibility_counts: Counter[str] = Counter()
    for page in staff_data.get("pages", []):
        source_path = dataset_root / page["source_image"]
        source = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
        if source is None:
            raise ValueError(f"não foi possível abrir a imagem: {source_path}")
        bands = {int(band["visual_staff_index"]): band for band in page["staff_bands"]}
        for cell in page["cells"]:
            staff_index = int(cell["visual_staff_index"])
            band = bands[staff_index]
            measure = int(cell["measure_number"])
            box = cell["bbox_pixels"]
            left = max(0, int(box["x"]))
            top = max(0, int(box["y"]))
            right = min(source.shape[1], left + int(box["width"]))
            bottom = min(source.shape[0], top + int(box["height"]))
            crop = source[top:bottom, left:right]
            if crop.size == 0:
                raise ValueError(f"recorte vazio: {cell['id']}")
            filename = (
                f"page-{int(page['image_page']):04d}-measure-{measure:04d}"
                f"-staff-{staff_index:03d}.png"
            )
            image_path = image_dir / filename
            if not cv2.imwrite(str(image_path), crop):
                raise OSError(f"não foi possível gravar: {image_path}")
            target, relation = _build_target(band["targets"], measure, events, meters)
            eligible, review_reasons = _eligibility(item, relation)
            relation_counts[relation] += 1
            eligibility_counts["eligible" if eligible else "review-required"] += 1
            samples.append(
                {
                    "schema": "rescore-training-sample",
                    "schema_version": TRAINING_EXPORT_SCHEMA_VERSION,
                    "id": f"{item_id}-p{int(page['image_page']):04d}-m{measure:04d}-s{staff_index:03d}",
                    "item_id": item_id,
                    "split_group": item["split_group"],
                    "source_type": item["source"]["type"],
                    "page": int(page["image_page"]),
                    "measure": measure,
                    "visual_staff_index": staff_index,
                    "source_label": band["source_label"],
                    "staff_type": band["staff_type"],
                    "mapping_status": band["mapping_status"],
                    "training_eligible": eligible,
                    "review_reasons": review_reasons,
                    "image": {
                        **_file_record(image_path, dataset_root),
                        "width": int(crop.shape[1]),
                        "height": int(crop.shape[0]),
                        "source_bbox_pixels": box,
                        "source_bbox_normalized": cell["bbox_normalized"],
                    },
                    "target": target,
                }
            )

    _write_jsonl(index_path, samples)
    summary = {
        "schema": "rescore-training-export",
        "schema_version": TRAINING_EXPORT_SCHEMA_VERSION,
        "tokenizer": TOKENIZER_VERSION,
        "item_id": item_id,
        "created_at": _now(),
        "samples": len(samples),
        "relation_counts": dict(sorted(relation_counts.items())),
        "eligibility_counts": dict(sorted(eligibility_counts.items())),
        "policy": (
            "Amostras só ficam elegíveis após revisão humana dos compassos e das pautas; "
            "recortes não atribuídos ou sem eventos-alvo continuam apenas para revisão."
        ),
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    item["training"] = {
        "schema_version": TRAINING_EXPORT_SCHEMA_VERSION,
        "tokenizer": TOKENIZER_VERSION,
        "sample_count": len(samples),
        "eligible_sample_count": eligibility_counts["eligible"],
        "review_required_count": eligibility_counts["review-required"],
        "index": _file_record(index_path, dataset_root),
        "summary": _file_record(summary_path, dataset_root),
        "updated_at": _now(),
    }
    _save_manifest(dataset_root, manifest)
    validation = validate_training_export(index_path)
    return {
        "dataset": str(dataset_root),
        "item_id": item_id,
        "index": str(index_path),
        "summary": str(summary_path),
        **summary,
        "validation": validation,
    }


def validate_training_export(path: Path, *, verify_hashes: bool = True) -> dict[str, Any]:
    """Validate sample uniqueness, crop integrity and target checksums."""
    path = path.resolve()
    dataset_root = path.parents[3]
    errors: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            samples.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append({"kind": "invalid-jsonl", "line": line_number, "message": str(exc)})
    ids = [sample.get("id") for sample in samples]
    if len(ids) != len(set(ids)):
        errors.append({"kind": "duplicate-sample-id"})
    relation_counts: Counter[str] = Counter()
    eligible = 0
    for sample in samples:
        relation_counts[sample.get("target", {}).get("relation", "missing")] += 1
        eligible += bool(sample.get("training_eligible"))
        record = sample.get("image", {})
        image_path = (dataset_root / record.get("path", "")).resolve()
        try:
            image_path.relative_to(dataset_root)
        except ValueError:
            errors.append({"kind": "unsafe-image-path", "sample": sample.get("id")})
            continue
        if not image_path.is_file():
            errors.append({"kind": "missing-image", "sample": sample.get("id")})
        elif verify_hashes:
            actual = hashlib.sha256(image_path.read_bytes()).hexdigest()
            if actual != record.get("sha256"):
                errors.append({"kind": "image-checksum", "sample": sample.get("id")})
        target = sample.get("target", {})
        expected_hash = target.get("sha256")
        unhashed = {key: value for key, value in target.items() if key != "sha256"}
        if expected_hash != _hash_json(unhashed):
            errors.append({"kind": "target-checksum", "sample": sample.get("id")})
        if sample.get("training_eligible") and sample.get("review_reasons"):
            errors.append({"kind": "eligible-with-review-reasons", "sample": sample.get("id")})
    return {
        "valid": not errors,
        "path": str(path),
        "samples": len(samples),
        "eligible_samples": eligible,
        "review_required_samples": len(samples) - eligible,
        "relation_counts": dict(sorted(relation_counts.items())),
        "errors": errors,
    }
