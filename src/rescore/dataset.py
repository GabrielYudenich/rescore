"""Versioned training-dataset support for ReScore.

The dataset is deliberately separate from the source-code repository. A dataset
directory contains a JSON manifest plus copied source images and verified
MusicXML. Each item carries explicit provenance, rights, visibility and
verification metadata so a private score can never silently enter a public
catalog or training run.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from .mscz import inspect_mscz
from .musicxml import parse_musicxml
from .pipeline import convert_with_musescore
from .tooling import find_musescore

SCHEMA_VERSION = "1.0"
MANIFEST_NAME = "rescore-dataset.json"
VISIBILITIES = {"public", "private"}
SOURCE_TYPES = {"printed", "handwritten", "mixed"}
ALIGNMENT_STATUSES = {"verified", "inferred", "unassigned"}
VERIFICATION_LEVELS = {
    "human-transcribed",
    "human-reviewed",
    "partially-reviewed",
    "machine-generated",
}


class DatasetError(ValueError):
    """Raised when a dataset operation would create ambiguous or unsafe data."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not normalized:
        raise DatasetError("identificador vazio depois da normalização")
    return normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _safe_resolve(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise DatasetError(f"caminho sai do dataset: {relative}") from exc
    return candidate


def _manifest_path(root: Path) -> Path:
    return root / MANIFEST_NAME


def _load(root: Path) -> dict[str, Any]:
    path = _manifest_path(root)
    if not path.is_file():
        raise DatasetError(f"manifesto não encontrado: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DatasetError("manifesto precisa ser um objeto JSON")
    return data


def _save(root: Path, manifest: dict[str, Any]) -> Path:
    manifest["updated_at"] = _now()
    path = _manifest_path(root)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def initialize_dataset(
    root: Path,
    *,
    dataset_id: str,
    name: str,
    default_annotation_license: str = "CC-BY-4.0",
) -> dict[str, Any]:
    """Create an empty ReScore dataset directory."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = _manifest_path(root)
    if path.exists():
        raise DatasetError(f"dataset já existe: {path}")
    now = _now()
    manifest: dict[str, Any] = {
        "schema": "https://rescore.org/schemas/dataset-v1.json",
        "schema_version": SCHEMA_VERSION,
        "dataset": {
            "id": _slug(dataset_id),
            "name": name.strip(),
            "default_annotation_license": default_annotation_license,
            "description": "",
        },
        "created_at": now,
        "updated_at": now,
        "items": [],
    }
    (root / "items").mkdir(exist_ok=True)
    _save(root, manifest)
    return {
        "root": str(root),
        "manifest": str(path),
        "dataset_id": manifest["dataset"]["id"],
    }


def _copy_images(images: list[Path], item_dir: Path, dataset_root: Path) -> list[dict]:
    if not images:
        raise DatasetError("é necessária pelo menos uma imagem")
    source_dir = item_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    for page_number, source in enumerate(images, 1):
        source = source.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        suffix = source.suffix.casefold()
        if suffix not in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
            raise DatasetError(f"formato de imagem não suportado: {source}")
        destination = source_dir / f"page-{page_number:04d}{suffix}"
        shutil.copy2(source, destination)
        with Image.open(destination) as image:
            width, height = image.size
        records.append(
            {
                "page": page_number,
                "path": _relative(destination, dataset_root),
                "sha256": _sha256(destination),
                "width": width,
                "height": height,
                "original_name": source.name,
            }
        )
    return records


def _copy_ground_truth(
    project_root: Path,
    score: Path,
    item_dir: Path,
    dataset_root: Path,
) -> tuple[dict, dict]:
    score = score.resolve()
    if not score.is_file():
        raise FileNotFoundError(score)
    annotation_dir = item_dir / "annotation"
    annotation_dir.mkdir(parents=True, exist_ok=True)
    source_copy = annotation_dir / f"source{score.suffix.casefold()}"
    shutil.copy2(score, source_copy)
    musicxml = annotation_dir / "ground-truth.musicxml"

    if score.suffix.casefold() == ".mscz":
        musescore = find_musescore(project_root)
        if musescore is None:
            raise DatasetError("MuseScore não encontrado para extrair o MusicXML")
        convert_with_musescore(
            musescore,
            source_copy,
            musicxml,
            annotation_dir / "musescore-export.log",
        )
        inspection = inspect_mscz(score)
        summary = {
            "parts": inspection["parts_count"],
            "staves": inspection["staves_count"],
            "measures": inspection["measures"],
            "title": inspection["work_title"],
        }
    elif score.suffix.casefold() in {".musicxml", ".xml", ".mxl"}:
        if source_copy.suffix.casefold() == ".mxl":
            parsed = parse_musicxml(source_copy, include_rests=True)
            musescore = find_musescore(project_root)
            if musescore is None:
                raise DatasetError("MuseScore não encontrado para expandir o MXL")
            convert_with_musescore(
                musescore,
                source_copy,
                musicxml,
                annotation_dir / "musescore-export.log",
            )
        else:
            shutil.copy2(source_copy, musicxml)
            parsed = parse_musicxml(musicxml, include_rests=True)
        summary = {
            "parts": parsed["parts_count"],
            "staves": None,
            "measures": parsed["measures"],
            "title": "",
        }
    else:
        raise DatasetError(f"formato de gabarito não suportado: {score.suffix}")

    parse_musicxml(musicxml, include_rests=True)
    record = {
        "musicxml": {
            "path": _relative(musicxml, dataset_root),
            "sha256": _sha256(musicxml),
        },
        "source_score": {
            "path": _relative(source_copy, dataset_root),
            "sha256": _sha256(source_copy),
            "format": score.suffix.casefold().lstrip("."),
            "original_name": score.name,
        },
    }
    return record, summary


def add_pair(
    project_root: Path,
    dataset_root: Path,
    *,
    item_id: str,
    images: list[Path],
    score: Path,
    composer: str,
    work: str,
    source_type: str,
    visibility: str,
    rights_status: str,
    source_license: str,
    redistributable: bool,
    measure_start: int,
    measure_end: int,
    verification: str,
    alignment_status: str,
    writer: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Copy one image/score pair into a dataset with strict provenance."""
    dataset_root = dataset_root.resolve()
    manifest = _load(dataset_root)
    normalized_id = _slug(item_id)
    if any(item.get("id") == normalized_id for item in manifest.get("items", [])):
        raise DatasetError(f"item já existe: {normalized_id}")
    if source_type not in SOURCE_TYPES:
        raise DatasetError(f"source_type inválido: {source_type}")
    if visibility not in VISIBILITIES:
        raise DatasetError(f"visibilidade inválida: {visibility}")
    if alignment_status not in ALIGNMENT_STATUSES:
        raise DatasetError(f"alinhamento inválido: {alignment_status}")
    if verification not in VERIFICATION_LEVELS:
        raise DatasetError(f"verificação inválida: {verification}")
    if measure_start < 1 or measure_end < measure_start:
        raise DatasetError("intervalo de compassos inválido")
    if visibility == "public" and not redistributable:
        raise DatasetError("item público precisa ter redistributable=true")
    if visibility == "public" and not source_license.strip():
        raise DatasetError("item público precisa declarar a licença da fonte")

    item_dir = dataset_root / "items" / normalized_id
    if item_dir.exists():
        raise DatasetError(f"diretório do item já existe: {item_dir}")
    item_dir.mkdir(parents=True)
    try:
        image_records = _copy_images(images, item_dir, dataset_root)
        ground_truth, score_summary = _copy_ground_truth(
            project_root.resolve(),
            score,
            item_dir,
            dataset_root,
        )
        if measure_end > int(score_summary["measures"]):
            raise DatasetError(
                f"gabarito possui {score_summary['measures']} compassos; "
                f"foi solicitado até {measure_end}"
            )
        item = {
            "id": normalized_id,
            "visibility": visibility,
            "include_in_public_training": visibility == "public",
            "source": {
                "composer": composer.strip(),
                "work": work.strip(),
                "writer_or_copyist": writer.strip(),
                "type": source_type,
                "images": image_records,
            },
            "ground_truth": {
                **ground_truth,
                "measure_range": {"start": measure_start, "end": measure_end},
                "verification": verification,
                "score_summary": score_summary,
            },
            "alignment": {
                "status": alignment_status,
                "image_pages": [record["page"] for record in image_records],
                "score_measures": [measure_start, measure_end],
            },
            "rights": {
                "status": rights_status.strip(),
                "source_license": source_license.strip(),
                "annotation_license": manifest["dataset"]["default_annotation_license"],
                "redistributable": bool(redistributable),
            },
            "split_group": _slug(
                "-".join(value for value in (composer, work, writer or "unknown-writer") if value)
            ),
            "notes": notes.strip(),
            "created_at": _now(),
        }
        manifest.setdefault("items", []).append(item)
        _save(dataset_root, manifest)
    except Exception:
        shutil.rmtree(item_dir, ignore_errors=True)
        raise
    return {
        "dataset": str(dataset_root),
        "item": item,
    }


def validate_dataset(root: Path, *, verify_hashes: bool = True) -> dict[str, Any]:
    """Validate structure, privacy rules, file existence and checksums."""
    root = root.resolve()
    errors: list[dict] = []
    warnings: list[dict] = []
    try:
        manifest = _load(root)
    except (OSError, ValueError) as exc:
        return {"valid": False, "root": str(root), "errors": [{"message": str(exc)}]}

    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            {
                "kind": "schema_version",
                "expected": SCHEMA_VERSION,
                "actual": manifest.get("schema_version"),
            }
        )
    items = manifest.get("items")
    if not isinstance(items, list):
        errors.append({"kind": "items", "message": "items precisa ser uma lista"})
        items = []
    seen: set[str] = set()
    public_count = 0
    private_count = 0
    checked_files = 0
    for item in items:
        item_id = item.get("id", "")
        if not item_id or item_id in seen:
            errors.append({"kind": "duplicate_or_empty_id", "item": item_id})
        seen.add(item_id)
        visibility = item.get("visibility")
        if visibility == "public":
            public_count += 1
            if not item.get("rights", {}).get("redistributable"):
                errors.append({"kind": "public_not_redistributable", "item": item_id})
            if item.get("include_in_public_training") is not True:
                warnings.append({"kind": "public_training_disabled", "item": item_id})
        elif visibility == "private":
            private_count += 1
            if item.get("include_in_public_training"):
                errors.append({"kind": "private_in_public_training", "item": item_id})
        else:
            errors.append({"kind": "invalid_visibility", "item": item_id})

        file_records = list(item.get("source", {}).get("images", []))
        ground_truth = item.get("ground_truth", {})
        for name in ("musicxml", "source_score"):
            if isinstance(ground_truth.get(name), dict):
                file_records.append(ground_truth[name])
        alignment = item.get("alignment", {})
        for name in (
            "regions_file",
            "review_html",
            "staff_regions_file",
            "staff_review_html",
            "review_log",
        ):
            if isinstance(alignment.get(name), dict):
                file_records.append(alignment[name])
        file_records.extend(alignment.get("preview_images", []))
        file_records.extend(alignment.get("staff_preview_images", []))
        training = item.get("training", {})
        for name in ("index", "summary"):
            if isinstance(training.get(name), dict):
                file_records.append(training[name])
        for correction in item.get("corrections", []):
            for name in (
                "corrected_source",
                "corrected_musicxml",
                "source_musicxml",
                "pack",
                "pack_musicxml",
                "issues",
                "validation",
                "overrides",
                "comparison",
            ):
                if isinstance(correction.get(name), dict):
                    file_records.append(correction[name])
        for record in file_records:
            relative = record.get("path", "")
            try:
                path = _safe_resolve(root, relative)
            except DatasetError as exc:
                errors.append({"kind": "unsafe_path", "item": item_id, "message": str(exc)})
                continue
            if not path.is_file():
                errors.append({"kind": "missing_file", "item": item_id, "path": relative})
                continue
            checked_files += 1
            if verify_hashes and record.get("sha256") != _sha256(path):
                errors.append({"kind": "checksum", "item": item_id, "path": relative})
    return {
        "valid": not errors,
        "root": str(root),
        "schema_version": manifest.get("schema_version"),
        "items": len(items),
        "public_items": public_count,
        "private_items": private_count,
        "checked_files": checked_files,
        "errors": errors,
        "warnings": warnings,
    }


def write_public_catalog(root: Path, output: Path) -> dict[str, Any]:
    """Write metadata for public items only, never paths to private material."""
    root = root.resolve()
    validation = validate_dataset(root)
    if not validation["valid"]:
        raise DatasetError("dataset inválido; execute dataset-validate")
    manifest = _load(root)
    public_items = [item for item in manifest["items"] if item.get("visibility") == "public"]
    catalog = {
        "schema_version": SCHEMA_VERSION,
        "dataset": manifest["dataset"],
        "generated_at": _now(),
        "items": public_items,
    }
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "output": str(output),
        "public_items": len(public_items),
        "excluded_private_items": len(manifest["items"]) - len(public_items),
    }
