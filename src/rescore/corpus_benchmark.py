"""Aggregate anonymous corpus and OMR health metrics into one benchmark report."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .privacy_audit import audit_public_json


def build_corpus_benchmark(
    curriculum_path: Path,
    pairs_path: Path,
    probes_path: Path,
    output: Path,
    *,
    digital_comparison: Path | None = None,
) -> dict[str, Any]:
    curriculum = json.loads(curriculum_path.read_text(encoding="utf-8"))
    pairs = json.loads(pairs_path.read_text(encoding="utf-8"))
    probes = json.loads(probes_path.read_text(encoding="utf-8"))
    recognized = [item for item in probes["probes"] if item["status"] == "recognized"]
    failed = [item for item in probes["probes"] if item["status"] != "recognized"]
    elapsed = sum(float(item.get("elapsed_seconds", 0)) for item in probes["probes"])
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "curriculum": curriculum["summary"],
        "supervised_discovery": pairs["summary"],
        "omr_probes": {
            "total": len(probes["probes"]),
            "recognized": len(recognized),
            "failed": len(failed),
            "recognition_rate": round(len(recognized) / max(len(probes["probes"]), 1), 6),
            "elapsed_seconds": round(elapsed, 3),
            "pitched_events": sum(item["metrics"]["pitched_events"] for item in recognized),
            "failed_clusters": [item["cluster"] for item in failed],
            "probes": probes["probes"],
        },
        "ground_truth_policy": {
            "automatic_omr_is_training_eligible": False,
            "required": ["human-reviewed", "human-transcribed"],
        },
    }
    if digital_comparison is not None:
        comparison = json.loads(digital_comparison.read_text(encoding="utf-8"))
        payload["verified_digital_anchor"] = {
            "global_note_rhythm": comparison["global_note_rhythm"],
            "staff_position_note_rhythm": comparison["staff_position_note_rhythm"],
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    privacy = audit_public_json(output)
    if not privacy["valid"]:
        output.unlink(missing_ok=True)
        raise ValueError(f"benchmark reprovado na auditoria de privacidade: {privacy['violations']}")
    return {"output": str(output.resolve()), "privacy": privacy, **payload["omr_probes"]}
