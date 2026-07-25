"""Import corrected review packs as versioned, auditable dataset overrides."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .alignment import _file_record, _find_item, _load_manifest, _now, _save_manifest
from .dataset import DatasetError
from .musicxml import _read_musicxml, _strip_namespaces, normalize_part_name, parse_musicxml
from .pipeline import convert_with_musescore
from .tooling import find_musescore
from .training_export import _effective_meters, _event_lookup, _hash_json, tokenize_events

CORRECTION_SCHEMA_VERSION = "1.0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_pack_file(pack_path: Path, record: dict[str, Any]) -> Path:
    candidate = Path(record["path"])
    return (
        candidate.resolve() if candidate.is_absolute() else (pack_path.parent / candidate).resolve()
    )


def _to_musicxml(
    project_root: Path,
    source: Path,
    destination: Path,
    log_path: Path,
) -> Path:
    suffix = source.suffix.casefold()
    if suffix in {".musicxml", ".xml"}:
        shutil.copy2(source, destination)
    elif suffix == ".mxl":
        destination.write_bytes(_read_musicxml(source))
    elif suffix == ".mscz":
        musescore = find_musescore(project_root)
        if musescore is None:
            raise FileNotFoundError("MuseScore não encontrado; execute `rescore doctor`")
        convert_with_musescore(musescore, source, destination, log_path)
    else:
        raise ValueError(f"formato corrigido não suportado: {source.suffix}")
    parse_musicxml(destination, include_rests=True)
    return destination


def _measure_ids(path: Path) -> dict[int, set[str]]:
    root = _strip_namespaces(ET.fromstring(_read_musicxml(path)))
    ids: dict[int, set[str]] = defaultdict(set)
    for part in root.findall("part"):
        for measure_index, measure in enumerate(part.findall("measure"), 1):
            for node in measure.findall(".//rehearsal") + measure.findall(".//words"):
                ids[measure_index].update(re.findall(r"RS-[A-Z0-9-]+", node.text or ""))
    return ids


def _part_mapping(pack: dict[str, Any], corrected: dict[str, Any]) -> dict[str, str]:
    corrected_ids = {part["id"] for part in corrected["parts"]}
    by_name: dict[str, list[str]] = {}
    for part in corrected["parts"]:
        by_name.setdefault(normalize_part_name(part["name"]), []).append(part["id"])
    mapping = {}
    for part in pack["parts"]:
        if part["id"] in corrected_ids:
            mapping[part["id"]] = part["id"]
            continue
        matches = by_name.get(normalize_part_name(part["name"]), [])
        if len(matches) != 1:
            raise DatasetError(
                f"não foi possível reencontrar a parte corrigida: {part['name']} ({part['id']})"
            )
        mapping[part["id"]] = matches[0]
    return mapping


def _load_issue_map(pack_manifest: dict[str, Any], pack_path: Path) -> dict[str, dict[str, Any]]:
    issues_path = Path(pack_manifest["issues"]["path"])
    if not issues_path.is_absolute():
        issues_path = (pack_path.parent / issues_path).resolve()
    issues = {}
    for line in issues_path.read_text(encoding="utf-8").splitlines():
        issue = json.loads(line)
        issues[issue["id"]] = issue
    return issues


def apply_dataset_fix(
    project_root: Path,
    dataset_root: Path,
    *,
    item_id: str,
    pack_path: Path,
    corrected: Path,
    reviewer: str,
    note: str = "",
) -> dict[str, Any]:
    """Store corrected review measures and expose them as latest target overrides."""
    project_root = project_root.resolve()
    dataset_root = dataset_root.resolve()
    pack_path = pack_path.resolve()
    corrected = corrected.resolve()
    reviewer = reviewer.strip()
    note = note.strip()
    if not reviewer:
        raise DatasetError("informe o nome do revisor")
    if not pack_path.is_file() or not corrected.is_file():
        raise FileNotFoundError(pack_path if not pack_path.is_file() else corrected)

    manifest = _load_manifest(dataset_root)
    item = _find_item(manifest, item_id)
    pack_manifest = _load_json(pack_path)
    if (
        pack_manifest.get("schema") != "rescore-review-pack"
        or pack_manifest.get("schema_version") != "1.0"
        or not pack_manifest.get("mappings")
    ):
        raise DatasetError("review-pack.json inválido ou sem mapeamentos")
    pack_xml = _resolve_pack_file(pack_path, pack_manifest["pack_musicxml"])
    if _sha256(pack_xml) != pack_manifest["pack_musicxml"]["sha256"]:
        raise DatasetError("o MusicXML do pacote mudou depois de sua criação")
    original_issues = _resolve_pack_file(pack_path, pack_manifest["issues"])
    if _sha256(original_issues) != pack_manifest["issues"]["sha256"]:
        raise DatasetError("a lista de problemas mudou depois da criação do pacote")
    dataset_score_path = dataset_root / item["ground_truth"]["musicxml"]["path"]
    if _sha256(dataset_score_path) != pack_manifest["source_musicxml"]["sha256"]:
        raise DatasetError("o pacote não foi criado a partir do gabarito deste item")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    correction_id = f"correction-{stamp}"
    correction_dir = dataset_root / "items" / item_id / "corrections" / correction_id
    if correction_dir.exists():
        raise DatasetError(f"correção já existe: {correction_dir}")
    correction_dir.mkdir(parents=True)
    try:
        corrected_source = correction_dir / f"corrected-source{corrected.suffix.casefold()}"
        shutil.copy2(corrected, corrected_source)
        corrected_xml = correction_dir / "corrected.musicxml"
        _to_musicxml(
            project_root,
            corrected,
            corrected_xml,
            correction_dir / "musescore-export.log",
        )
        pack_copy = correction_dir / "review-pack.json"
        pack_xml_copy = correction_dir / "review-pack.musicxml"
        issues_copy = correction_dir / "issues.jsonl"
        shutil.copy2(pack_xml, pack_xml_copy)
        shutil.copy2(original_issues, issues_copy)
        preserved_pack = dict(pack_manifest)
        preserved_pack["source"] = {
            "path": "external-source-not-copied",
            "sha256": pack_manifest["source"]["sha256"],
        }
        preserved_pack["source_musicxml"] = {
            "path": Path(os.path.relpath(dataset_score_path, correction_dir)).as_posix(),
            "sha256": _sha256(dataset_score_path),
        }
        preserved_pack["pack_musicxml"] = _file_record(pack_xml_copy, correction_dir)
        preserved_pack["issues"] = _file_record(issues_copy, correction_dir)
        pack_copy.write_text(
            json.dumps(preserved_pack, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        pack_score = parse_musicxml(pack_xml, include_rests=True)
        corrected_score = parse_musicxml(corrected_xml, include_rests=True)
        review_count = len(pack_manifest["mappings"])
        if corrected_score["measures"] != review_count:
            raise DatasetError(
                f"arquivo corrigido possui {corrected_score['measures']} compassos; "
                f"o pacote exige {review_count}"
            )
        visible = _measure_ids(corrected_xml)
        missing_ids = []
        for mapping in pack_manifest["mappings"]:
            found = visible.get(int(mapping["review_measure"]), set())
            review_id = mapping.get("review_id")
            if not review_id or review_id not in found:
                missing_ids.append(review_id or f"compasso de revisão {mapping['review_measure']}")
        if missing_ids:
            raise DatasetError(
                "identificadores removidos ou deslocados no arquivo corrigido: "
                + ", ".join(missing_ids[:8])
            )

        issue_map = _load_issue_map(pack_manifest, pack_path)
        part_map = _part_mapping(pack_score, corrected_score)
        pack_events = _event_lookup(pack_score)
        corrected_events = _event_lookup(corrected_score)
        pack_meters = _effective_meters(pack_score)
        corrected_meters = _effective_meters(corrected_score)
        dataset_score = parse_musicxml(dataset_score_path, include_rests=True)
        dataset_parts = {part["id"] for part in dataset_score["parts"]}
        overrides = []
        seen: set[tuple[int, str, str]] = set()
        changed = 0
        for mapping in pack_manifest["mappings"]:
            review_measure = int(mapping["review_measure"])
            original_measure = int(mapping["original_measure"])
            for issue_id in mapping["issue_ids"]:
                issue = issue_map.get(issue_id)
                if issue is None:
                    raise DatasetError(f"issue ausente no sidecar: {issue_id}")
                part_id = issue["part_id"]
                staff = str(issue["staff"])
                key = (original_measure, part_id, staff)
                if key in seen:
                    continue
                seen.add(key)
                if part_id not in dataset_parts:
                    raise DatasetError(
                        f"parte corrigida não existe no gabarito do dataset: {part_id}"
                    )
                corrected_part = part_map[part_id]
                before_events = pack_events.get((part_id, staff, review_measure), [])
                after_events = corrected_events.get((corrected_part, staff, review_measure), [])
                before_meter = pack_meters.get((part_id, review_measure))
                after_meter = corrected_meters.get((corrected_part, review_measure))
                before_tokens = tokenize_events(before_events, before_meter)
                after_tokens = tokenize_events(after_events, after_meter)
                stream_changed = _hash_json(before_tokens) != _hash_json(after_tokens)
                changed += stream_changed
                overrides.append(
                    {
                        "original_measure": original_measure,
                        "target_part_id": part_id,
                        "target_staff": staff,
                        "possible_instrument": issue["possible_instrument"],
                        "issue_ids": sorted(
                            {
                                candidate
                                for candidate in mapping["issue_ids"]
                                if issue_map[candidate]["part_id"] == part_id
                                and str(issue_map[candidate]["staff"]) == staff
                            }
                        ),
                        "meter": after_meter,
                        "events": after_events,
                        "tokens": after_tokens,
                        "changed": stream_changed,
                    }
                )
        override_payload = {
            "schema": "rescore-correction-overrides",
            "schema_version": CORRECTION_SCHEMA_VERSION,
            "correction_id": correction_id,
            "item_id": item_id,
            "reviewer": reviewer,
            "created_at": _now(),
            "status": "human-corrected",
            "note": note,
            "overrides": overrides,
        }
        overrides_path = correction_dir / "overrides.json"
        overrides_path.write_text(
            json.dumps(override_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        comparison = {
            "streams": len(overrides),
            "changed_streams": changed,
            "confirmed_unchanged_streams": len(overrides) - changed,
            "details": [
                {
                    "measure": override["original_measure"],
                    "target": f"{override['target_part_id']}:{override['target_staff']}",
                    "changed": override["changed"],
                    "issues": override["issue_ids"],
                }
                for override in overrides
            ],
        }
        comparison_path = correction_dir / "comparison.json"
        comparison_path.write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        record = {
            "id": correction_id,
            "status": "human-corrected",
            "reviewer": reviewer,
            "created_at": override_payload["created_at"],
            "note": note,
            "changed_streams": changed,
            "confirmed_unchanged_streams": len(overrides) - changed,
            "corrected_source": _file_record(corrected_source, dataset_root),
            "corrected_musicxml": _file_record(corrected_xml, dataset_root),
            "pack": _file_record(pack_copy, dataset_root),
            "pack_musicxml": _file_record(pack_xml_copy, dataset_root),
            "issues": _file_record(issues_copy, dataset_root),
            "overrides": _file_record(overrides_path, dataset_root),
            "comparison": _file_record(comparison_path, dataset_root),
        }
        item.setdefault("corrections", []).append(record)
        training = item.get("training")
        if isinstance(training, dict):
            training["stale"] = True
            training["stale_reason"] = "human-correction-added"
            training["stale_at"] = override_payload["created_at"]
        _save_manifest(dataset_root, manifest)
    except Exception:
        shutil.rmtree(correction_dir, ignore_errors=True)
        raise
    return {
        "dataset": str(dataset_root),
        "item_id": item_id,
        "correction_id": correction_id,
        "directory": str(correction_dir),
        "reviewed_streams": len(overrides),
        "changed_streams": changed,
        "confirmed_unchanged_streams": len(overrides) - changed,
        "training_export_stale": isinstance(item.get("training"), dict),
        "next_step": "execute dataset-export-training --force para aplicar as correções",
    }
