"""Run resumable OMR probes on anonymous visual-cluster representatives."""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .musicxml import parse_musicxml
from .pipeline import extract_image_omr_candidate, extract_omr_candidate


def select_representatives(curriculum: dict[str, Any]) -> list[dict[str, Any]]:
    model = curriculum["visual_model"]
    mean, scale, centers = model["mean"], model["scale"], model["centers"]
    by_cluster: dict[int, list[dict[str, Any]]] = {}
    for record in curriculum.get("samples", []):
        by_cluster.setdefault(int(record["style_cluster"]), []).append(record)
    representatives = []
    split_priority = {"test": 0, "validation": 1, "train": 2}
    for cluster, records in sorted(by_cluster.items()):
        center = centers[cluster]

        def key(record: dict[str, Any]) -> tuple[int, float, str]:
            normalized = [
                (value - location) / divisor
                for value, location, divisor in zip(
                    record["features"], mean, scale, strict=True
                )
            ]
            distance = math.sqrt(
                sum((value - target) ** 2 for value, target in zip(normalized, center, strict=True))
            )
            return split_priority.get(record["split"], 3), distance, record["sample_id"]

        selected = min(records, key=key)
        representatives.append(
            {
                "cluster": cluster,
                "sample_id": selected["sample_id"],
                "split": selected["split"],
                "origin": selected["origin"],
                "distance": round(key(selected)[1], 6),
            }
        )
    return representatives


def run_corpus_omr_probes(
    project_root: Path,
    curriculum_path: Path,
    private_map_path: Path,
    output: Path,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    curriculum = json.loads(curriculum_path.read_text(encoding="utf-8"))
    private = json.loads(private_map_path.read_text(encoding="utf-8"))
    private_samples = {
        record["sample_id"]: record
        for record in private.get("samples", [])
        if record.get("sample_id")
    }
    representatives = select_representatives(curriculum)
    if limit is not None:
        representatives = representatives[: max(0, limit)]
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "omr-probes.json"
    existing: dict[int, dict[str, Any]] = {}
    if report_path.is_file():
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        existing = {int(item["cluster"]): item for item in previous.get("probes", [])}
    probes = []
    private_results = []
    for representative in representatives:
        cluster = representative["cluster"]
        cached = existing.get(cluster)
        if (
            cached
            and cached.get("sample_id") == representative["sample_id"]
            and cached.get("status") == "recognized"
        ):
            probes.append(cached)
            continue
        private_sample = private_samples.get(representative["sample_id"])
        if not private_sample:
            probes.append({**representative, "status": "missing-private-sample"})
            continue
        started = time.perf_counter()
        error = None
        candidate = None
        try:
            source = Path(private_sample["path"])
            run_output = output / "private-runs" / f"cluster-{cluster:02d}"
            if source.suffix.casefold() == ".pdf":
                candidate = extract_omr_candidate(
                    project_root,
                    source,
                    str(private_sample["page"]),
                    run_output,
                    force=False,
                    omr_dpi=300,
                    scan_profile=False,
                )
            else:
                result = extract_image_omr_candidate(
                    project_root,
                    source,
                    run_output,
                    force=False,
                )
                candidate = Path(result["candidate"])
            score = parse_musicxml(candidate)
            metrics = {
                "parts": score["parts_count"],
                "measures": score["measures"],
                "pitched_events": sum(bool(event.get("pitch")) for event in score["events"]),
                "time_signatures": len(score["time_signatures"]),
            }
            status = "recognized"
        except Exception as exc:  # noqa: BLE001 - a failed style is benchmark data.
            error = str(exc)
            metrics = {"parts": 0, "measures": 0, "pitched_events": 0, "time_signatures": 0}
            status = "failed"
        elapsed = round(time.perf_counter() - started, 3)
        probes.append(
            {
                **representative,
                "status": status,
                "elapsed_seconds": elapsed,
                "metrics": metrics,
                "training_eligible": False,
            }
        )
        private_results.append(
            {
                "cluster": cluster,
                "sample_id": representative["sample_id"],
                "thumbnail": private_sample["thumbnail"],
                "candidate": str(candidate) if candidate else None,
                "error": error,
            }
        )
        payload = {
            "schema_version": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
            "summary": dict(Counter(item["status"] for item in probes)),
            "probes": probes,
        }
        report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    payload = {
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "summary": dict(Counter(item["status"] for item in probes)),
        "probes": probes,
    }
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "private-map.json").write_text(
        json.dumps({"results": private_results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"summary": payload["summary"], "report": str(report_path.resolve())}
