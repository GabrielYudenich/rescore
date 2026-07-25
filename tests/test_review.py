from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rescore.dataset import DatasetError
from rescore.review import review_dataset_alignment


def _record(path: Path, root: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _dataset(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "dataset"
    alignment_dir = root / "items" / "opening" / "alignment"
    alignment_dir.mkdir(parents=True)
    measures = alignment_dir / "measure-regions.json"
    measures.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "review_status": "machine-proposed",
                "measure_range": {"start": 1, "end": 1},
                "page_measure_counts": [1],
                "pages": [
                    {
                        "regions": [
                            {
                                "id": "measure-0001",
                                "measure_number": 1,
                                "bbox_normalized": {
                                    "x": 0.1,
                                    "y": 0.1,
                                    "width": 0.8,
                                    "height": 0.8,
                                },
                            }
                        ]
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    staffs = alignment_dir / "staff-regions.json"
    staffs.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "review_status": "machine-proposed",
                "pages": [
                    {
                        "image_page": 1,
                        "staff_bands": [
                            {
                                "id": "visual-staff-001",
                                "visual_staff_index": 1,
                                "mapping_status": "profile-proposed",
                                "targets": [{"part_id": "P1", "staff_number": "1"}],
                                "bbox_pixels": {"x": 10, "y": 10, "width": 80, "height": 20},
                                "bbox_normalized": {
                                    "x": 0.1,
                                    "y": 0.1,
                                    "width": 0.8,
                                    "height": 0.2,
                                },
                            }
                        ],
                        "cells": [
                            {
                                "id": "measure-0001-staff-001",
                                "measure_number": 1,
                                "visual_staff_index": 1,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "items": [
            {
                "id": "opening",
                "source": {"work": "Work"},
                "ground_truth": {"verification": "human-transcribed"},
                "alignment": {
                    "review_status": "machine-proposed",
                    "staff_review_status": "machine-proposed",
                    "regions_file": _record(measures, root),
                    "staff_regions_file": _record(staffs, root),
                },
                "training": {"sample_count": 1},
            }
        ],
    }
    (root / "rescore-dataset.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root, measures, staffs


def test_review_approves_both_layers_and_marks_training_stale(tmp_path: Path) -> None:
    root, measures, staffs = _dataset(tmp_path)
    result = review_dataset_alignment(
        root,
        item_id="opening",
        reviewer="Reviewer",
        approve_measures=True,
        approve_staffs=True,
        note="Compared against the source.",
    )
    assert result["approved_layers"] == ["measures", "staffs"]
    assert json.loads(measures.read_text(encoding="utf-8"))["review_status"] == "human-reviewed"
    assert json.loads(staffs.read_text(encoding="utf-8"))["review_status"] == "human-reviewed"
    manifest = json.loads((root / "rescore-dataset.json").read_text(encoding="utf-8"))
    item = manifest["items"][0]
    assert item["alignment"]["review_status"] == "human-reviewed"
    assert item["alignment"]["staff_review_status"] == "human-reviewed"
    assert item["training"]["stale"] is True
    log = root / item["alignment"]["review_log"]["path"]
    audit = json.loads(log.read_text(encoding="utf-8"))
    assert audit["reviewer"] == "Reviewer"
    assert audit["approved_layers"] == ["measures", "staffs"]


def test_review_refuses_staff_approval_before_measure_review(tmp_path: Path) -> None:
    root, _measures, _staffs = _dataset(tmp_path)
    with pytest.raises(DatasetError, match="aprove primeiro os compassos"):
        review_dataset_alignment(
            root,
            item_id="opening",
            reviewer="Reviewer",
            approve_staffs=True,
        )
