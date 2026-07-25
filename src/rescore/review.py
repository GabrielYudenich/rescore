"""Auditable human approval for dataset measure and staff alignments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .alignment import (
    _file_record,
    _find_item,
    _load_manifest,
    _now,
    _save_manifest,
    validate_alignment,
)
from .dataset import DatasetError
from .staff_alignment import validate_staff_alignment


def _load_recorded_json(
    dataset_root: Path,
    alignment: dict[str, Any],
    field: str,
) -> tuple[Path, dict[str, Any]]:
    record = alignment.get(field)
    if not isinstance(record, dict) or not record.get("path"):
        raise DatasetError(f"arquivo de alinhamento ausente: {field}")
    path = (dataset_root / record["path"]).resolve()
    try:
        path.relative_to(dataset_root)
    except ValueError as exc:
        raise DatasetError(f"caminho de alinhamento sai do dataset: {record['path']}") from exc
    return path, json.loads(path.read_text(encoding="utf-8"))


def _approve_payload(
    payload: dict[str, Any],
    *,
    reviewer: str,
    reviewed_at: str,
    note: str,
) -> None:
    payload["review_status"] = "human-reviewed"
    payload["review"] = {
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "note": note,
    }


def review_dataset_alignment(
    dataset_root: Path,
    *,
    item_id: str,
    reviewer: str,
    approve_measures: bool = False,
    approve_staffs: bool = False,
    note: str = "",
) -> dict[str, Any]:
    """Approve complete alignment layers and append a durable audit record."""
    dataset_root = dataset_root.resolve()
    reviewer = reviewer.strip()
    note = note.strip()
    if not reviewer:
        raise DatasetError("informe o nome do revisor")
    if not approve_measures and not approve_staffs:
        raise DatasetError("selecione --approve-measures e/ou --approve-staffs")

    manifest = _load_manifest(dataset_root)
    item = _find_item(manifest, item_id)
    alignment = item.get("alignment", {})
    reviewed_at = _now()
    approved: list[str] = []

    measure_path: Path | None = None
    measure_payload: dict[str, Any] | None = None
    if approve_measures:
        measure_path, measure_payload = _load_recorded_json(dataset_root, alignment, "regions_file")
        validation = validate_alignment(measure_path)
        if not validation["valid"]:
            raise DatasetError("measure-regions.json inválido; corrija antes de aprovar")
        _approve_payload(
            measure_payload,
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            note=note,
        )
        approved.append("measures")

    staff_path: Path | None = None
    staff_payload: dict[str, Any] | None = None
    if approve_staffs:
        if not approve_measures and alignment.get("review_status") != "human-reviewed":
            raise DatasetError("aprove primeiro os compassos ou use --approve-measures junto")
        staff_path, staff_payload = _load_recorded_json(
            dataset_root, alignment, "staff_regions_file"
        )
        validation = validate_staff_alignment(staff_path)
        if not validation["valid"]:
            raise DatasetError("staff-regions.json inválido; corrija antes de aprovar")
        _approve_payload(
            staff_payload,
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            note=note,
        )
        approved.append("staffs")

    # Write only after every requested layer has validated, avoiding a partial
    # approval if the second file is malformed.
    if measure_path is not None and measure_payload is not None:
        measure_path.write_text(
            json.dumps(measure_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        alignment["review_status"] = "human-reviewed"
        alignment["regions_file"] = _file_record(measure_path, dataset_root)
    if staff_path is not None and staff_payload is not None:
        staff_path.write_text(
            json.dumps(staff_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        alignment["staff_review_status"] = "human-reviewed"
        alignment["staff_regions_file"] = _file_record(staff_path, dataset_root)

    audit = {
        "item_id": item_id,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "approved_layers": approved,
        "note": note,
        "ground_truth_verification": item.get("ground_truth", {}).get("verification"),
    }
    log_path = dataset_root / "items" / item_id / "alignment" / "reviews.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(audit, ensure_ascii=False, separators=(",", ":")) + "\n")
    alignment["review_log"] = _file_record(log_path, dataset_root)
    alignment["updated_at"] = reviewed_at

    training = item.get("training")
    if isinstance(training, dict):
        training["stale"] = True
        training["stale_reason"] = "alignment-review-changed"
        training["stale_at"] = reviewed_at
    _save_manifest(dataset_root, manifest)
    return {
        "dataset": str(dataset_root),
        "item_id": item_id,
        "approved_layers": approved,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "review_log": str(log_path),
        "training_export_stale": isinstance(training, dict),
        "next_step": "execute dataset-export-training --force para atualizar elegibilidade",
    }
