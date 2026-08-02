"""Discover potential score/parts/editable pairs without publishing source names."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .corpus import _sha256

PDF = {".pdf"}
EDITABLE = {".mscz", ".mscx", ".musicxml", ".mxl", ".mus"}
ARCHIVE = {".zip"}


def _identifier(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _safe_archive_assets(path: Path) -> list[dict[str, Any]]:
    assets = []
    with zipfile.ZipFile(path) as archive:
        total = 0
        for member in archive.infolist():
            if member.is_dir():
                continue
            parts = PurePosixPath(member.filename.replace("\\", "/")).parts
            if not parts or ".." in parts or PurePosixPath(*parts).is_absolute():
                raise ValueError("arquivo ZIP contém caminho inseguro")
            total += member.file_size
            if total > 2_000_000_000 or member.file_size > 1_000_000_000:
                raise ValueError("arquivo ZIP excede o limite seguro")
            suffix = Path(parts[-1]).suffix.casefold()
            if suffix in PDF | EDITABLE:
                assets.append(
                    {
                        "kind": "pdf" if suffix in PDF else "editable",
                        "format": suffix.lstrip("."),
                        "bytes": member.file_size,
                        "member": member.filename,
                    }
                )
    return assets


def discover_supervised_candidates(source: Path, output: Path) -> dict[str, Any]:
    source, output = source.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    by_directory: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    errors = []
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        suffix = path.suffix.casefold()
        if suffix in PDF | EDITABLE:
            by_directory[path.parent].append(
                {
                    "container": "file",
                    "kind": "pdf" if suffix in PDF else "editable",
                    "format": suffix.lstrip("."),
                    "bytes": path.stat().st_size,
                    "path": str(path),
                    "sha256": _sha256(path),
                }
            )
        elif suffix in ARCHIVE:
            try:
                assets = _safe_archive_assets(path)
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                errors.append({"path": str(path), "error": str(exc)})
                continue
            archive_digest = _sha256(path)
            for asset in assets:
                by_directory[path.parent].append(
                    {
                        **asset,
                        "container": "archive",
                        "path": str(path),
                        "archive_sha256": archive_digest,
                    }
                )

    public_candidates = []
    private_candidates = []
    for directory, assets in sorted(by_directory.items(), key=lambda item: str(item[0])):
        pdfs = [asset for asset in assets if asset["kind"] == "pdf"]
        editables = [asset for asset in assets if asset["kind"] == "editable"]
        if not pdfs or not editables:
            continue
        relative = directory.relative_to(source).as_posix()
        group_key = relative.split("/", 1)[0] if relative else "_root"
        group_id = _identifier("grp", group_key)
        signature = "|".join(
            sorted(
                asset.get("sha256", asset.get("archive_sha256", ""))
                + ":"
                + asset["kind"]
                for asset in assets
            )
        )
        candidate_id = _identifier("pair", signature)
        matching_cardinality = len(pdfs) == len(editables)
        legacy_only = all(asset["format"] == "mus" for asset in editables)
        archive_roles: dict[str, Counter[str]] = defaultdict(Counter)
        for asset in assets:
            if asset["container"] == "archive":
                archive_roles[asset["path"]][asset["kind"]] += 1
        archive_pdf_counts = {
            counts["pdf"]
            for counts in archive_roles.values()
            if counts["pdf"] and not counts["editable"]
        }
        archive_editable_counts = {
            counts["editable"]
            for counts in archive_roles.values()
            if counts["editable"] and not counts["pdf"]
        }
        matched_archive_count = max(
            archive_pdf_counts & archive_editable_counts,
            default=0,
        )
        strong = (matching_cardinality or matched_archive_count > 0) and not legacy_only
        confidence = (
            "strong-cardinality"
            if strong
            else "partial-or-legacy"
        )
        public_candidates.append(
            {
                "candidate_id": candidate_id,
                "group_id": group_id,
                "pdf_assets": len(pdfs),
                "editable_assets": len(editables),
                "editable_formats": dict(Counter(asset["format"] for asset in editables)),
                "containers": dict(Counter(asset["container"] for asset in assets)),
                "matched_assets": matched_archive_count or (
                    len(pdfs) if matching_cardinality else 0
                ),
                "confidence": confidence,
                "review_state": "candidate-unverified",
                "training_eligible": False,
            }
        )
        private_candidates.append(
            {
                "candidate_id": candidate_id,
                "directory": str(directory),
                "assets": assets,
            }
        )
    public = {
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "summary": {
            "candidates": len(public_candidates),
            "strong_candidates": sum(
                item["confidence"] == "strong-cardinality" for item in public_candidates
            ),
            "training_eligible": 0,
            "errors": len(errors),
        },
        "candidates": public_candidates,
    }
    private = {
        "schema_version": "1.0",
        "candidates": private_candidates,
        "errors": errors,
    }
    public_path = output / "supervised-candidates.json"
    private_path = output / "private-map.json"
    public_path.write_text(
        json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    private_path.write_text(
        json.dumps(private, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "summary": public["summary"],
        "public_candidates": str(public_path.resolve()),
        "private_map": str(private_path.resolve()),
    }
