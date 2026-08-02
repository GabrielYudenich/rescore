"""Build an anonymous, leakage-safe visual curriculum from a local score corpus."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import fitz
import numpy as np
from PIL import Image, ImageOps

from .corpus import SUPPORTED, _sha256

RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
FEATURE_NAMES = (
    "aspect_ratio",
    "ink_density",
    "contrast",
    "entropy",
    "edge_density",
    "staff_line_density",
    "component_density",
    "colorfulness",
)


def _anonymous_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _sample_pages(count: int, limit: int) -> list[int]:
    if count < 1 or limit < 1:
        return []
    if count <= limit:
        return list(range(count))
    if limit == 1:
        return [count // 2]
    return sorted({round(index * (count - 1) / (limit - 1)) for index in range(limit)})


def _bounded_pixmap(page: fitz.Page, max_pixels: int) -> fitz.Pixmap:
    area = max(1.0, page.rect.width * page.rect.height)
    scale = min(1.0, math.sqrt(max_pixels / area))
    return page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)


def _visual_features(image: np.ndarray) -> list[float]:
    height, width = image.shape[:2]
    scale = min(1.0, 768 / max(height, width))
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    if image.ndim == 2:
        gray = image
        colorfulness = 0.0
    else:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        b, g, r = cv2.split(image.astype(np.float32))
        rg, yb = r - g, (r + g) / 2 - b
        colorfulness = float(
            math.sqrt(float(rg.std()) ** 2 + float(yb.std()) ** 2)
            + 0.3 * math.sqrt(float(rg.mean()) ** 2 + float(yb.mean()) ** 2)
        ) / 255
    normalized = gray.astype(np.float32) / 255
    ink = normalized < 0.82
    edges = cv2.Canny(gray, 60, 160) > 0
    binary = (ink.astype(np.uint8) * 255)
    horizontal = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, gray.shape[1] // 35), 1)),
    )
    components = cv2.connectedComponentsWithStats(binary, connectivity=8)[2]
    meaningful = sum(
        2 <= area <= gray.size * 0.02 for area in components[1:, cv2.CC_STAT_AREA]
    )
    histogram = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    probabilities = histogram[histogram > 0] / gray.size
    entropy = float(-(probabilities * np.log2(probabilities)).sum() / 8)
    return [
        round(width / max(height, 1), 6),
        round(float(ink.mean()), 6),
        round(float(normalized.std()), 6),
        round(entropy, 6),
        round(float(edges.mean()), 6),
        round(float((horizontal > 0).mean()), 6),
        round(float(meaningful / max(gray.size / 10_000, 1)), 6),
        round(colorfulness, 6),
    ]


def _write_thumbnail(array: np.ndarray, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    height, width = array.shape[:2]
    scale = min(1.0, 1400 / max(height, width))
    if scale < 1:
        array = cv2.resize(array, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    if not cv2.imwrite(str(output), array, [cv2.IMWRITE_PNG_COMPRESSION, 7]):
        raise RuntimeError(f"não foi possível gravar imagem: {output}")


def _pdf_samples(path: Path, pages_per_document: int, thumbnails: Path) -> list[dict[str, Any]]:
    records = []
    with fitz.open(path) as document:
        for page_index in _sample_pages(document.page_count, pages_per_document):
            page = document[page_index]
            pixmap = _bounded_pixmap(page, 2_000_000)
            array = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height, pixmap.width, pixmap.n
            )
            if pixmap.n == 4:
                array = cv2.cvtColor(array, cv2.COLOR_RGBA2BGR)
            else:
                array = cv2.cvtColor(array, cv2.COLOR_RGB2BGR)
            sample_id = f"p{page_index + 1:05d}"
            output = thumbnails / f"{sample_id}.png"
            _write_thumbnail(array, output)
            drawings = len(page.get_drawings())
            images = len(page.get_images(full=True))
            origin = "digital" if drawings > 20 and images == 0 else "raster"
            records.append(
                {
                    "page": page_index + 1,
                    "page_count": document.page_count,
                    "origin": origin,
                    "features": _visual_features(array),
                    "thumbnail": output,
                }
            )
    return records


def _image_sample(path: Path, thumbnails: Path) -> list[dict[str, Any]]:
    with Image.open(path) as opened:
        rgb = np.asarray(ImageOps.exif_transpose(opened).convert("RGB"))
    array = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    output = thumbnails / "p00001.png"
    _write_thumbnail(array, output)
    return [
        {
            "page": 1,
            "page_count": 1,
            "origin": "raster",
            "features": _visual_features(array),
            "thumbnail": output,
        }
    ]


def _assign_splits(records: list[dict[str, Any]]) -> None:
    """Assign whole source groups while keeping the sample ratio near 80/10/10."""
    counts = Counter(record["group_id"] for record in records)
    total = sum(counts.values())
    targets = {"train": total * 0.8, "validation": total * 0.1, "test": total * 0.1}
    assigned = {name: 0 for name in targets}
    group_splits: dict[str, str] = {}
    ordered = sorted(counts, key=lambda group: (-counts[group], group))
    for group in ordered:
        split = min(
            targets,
            key=lambda name: (
                assigned[name] / max(targets[name], 1),
                -targets[name],
            ),
        )
        group_splits[group] = split
        assigned[split] += counts[group]
    for record in records:
        record["split"] = group_splits[record["group_id"]]


def _cluster(records: list[dict[str, Any]], clusters: int) -> dict[str, Any]:
    if not records:
        return {"clusters": 0, "mean": [], "scale": [], "centers": []}
    training = [record for record in records if record.get("split") == "train"]
    if not training:
        raise ValueError("o split de treino está vazio")
    training_matrix = np.asarray(
        [record["features"] for record in training], dtype=np.float32
    )
    mean, std = training_matrix.mean(axis=0), training_matrix.std(axis=0)
    safe_std = np.where(std < 1e-6, 1, std)
    standardized = (training_matrix - mean) / safe_std
    count = min(max(1, clusters), len(training))
    cv2.setRNGSeed(20260801)
    _, _, centers = cv2.kmeans(
        standardized,
        count,
        None,
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-4),
        10,
        cv2.KMEANS_PP_CENTERS,
    )
    matrix = np.asarray([record["features"] for record in records], dtype=np.float32)
    distances = ((matrix - mean) / safe_std)[:, None, :] - centers[None, :, :]
    labels = np.square(distances).sum(axis=2).argmin(axis=1)
    for record, label in zip(records, labels, strict=True):
        record["style_cluster"] = int(label)
    return {
        "schema_version": "1.0",
        "feature_names": list(FEATURE_NAMES),
        "training_samples": len(training),
        "clusters": count,
        "mean": [round(float(value), 8) for value in mean],
        "scale": [round(float(value), 8) for value in safe_std],
        "centers": [
            [round(float(value), 8) for value in center] for center in centers
        ],
    }


def build_visual_curriculum(
    source: Path,
    output: Path,
    *,
    pages_per_document: int = 3,
    clusters: int = 12,
) -> dict[str, Any]:
    """Extract anonymous visual examples; labels remain unsupervised and local."""
    source, output = source.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    public_records: list[dict[str, Any]] = []
    private_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    paths = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.casefold() in SUPPORTED
    )
    groups: dict[str, str] = {}
    cached_by_content: dict[str, list[dict[str, Any]]] = {}
    cached_private: dict[str, dict[str, Any]] = {}
    public_cache = output / "visual-curriculum.json"
    private_cache = output / "private-map.json"
    if public_cache.is_file() and private_cache.is_file():
        previous_public = json.loads(public_cache.read_text(encoding="utf-8"))
        previous_private = json.loads(private_cache.read_text(encoding="utf-8"))
        for record in previous_public.get("samples", []):
            cached_by_content.setdefault(record["content_id"], []).append(record)
        cached_private = {
            record["sample_id"]: record
            for record in previous_private.get("samples", [])
            if record.get("sample_id")
        }
    cached_documents = 0
    for path in paths:
        if path.suffix.casefold() not in RASTER_SUFFIXES | {".pdf"}:
            continue
        digest = _sha256(path)
        if digest in seen:
            continue
        seen.add(digest)
        relative = path.relative_to(source)
        private_group = relative.parts[0] if len(relative.parts) > 1 else "_root"
        group_id = groups.setdefault(private_group, _anonymous_id("grp", private_group))
        content_id = f"sha256:{digest}"
        document_id = _anonymous_id("doc", digest)
        thumbnail_root = output / "private-thumbnails" / document_id
        cached = cached_by_content.get(content_id, [])
        if cached:
            expected = min(int(cached[0].get("page_count", 0)), pages_per_document)
            private_matches = [cached_private.get(record["sample_id"]) for record in cached]
            if (
                len(cached) == expected
                and expected > 0
                and all(
                    match
                    and Path(match["thumbnail"]).is_file()
                    for match in private_matches
                )
            ):
                for record, private_record in zip(cached, private_matches, strict=True):
                    reused = copy.deepcopy(record)
                    reused["group_id"] = group_id
                    reused.pop("split", None)
                    reused.pop("style_cluster", None)
                    public_records.append(reused)
                    private_records.append(
                        {
                            **private_record,
                            "path": str(path),
                        }
                    )
                cached_documents += 1
                continue
        try:
            samples = (
                _pdf_samples(path, pages_per_document, thumbnail_root)
                if path.suffix.casefold() == ".pdf"
                else _image_sample(path, thumbnail_root)
            )
        except Exception as exc:  # noqa: BLE001 - corpus intake must continue per file.
            private_records.append(
                {"content_id": content_id, "path": str(path), "error": str(exc)}
            )
            continue
        for sample in samples:
            sample_id = _anonymous_id("sample", f"{digest}:{sample['page']}")
            public_records.append(
                {
                    "sample_id": sample_id,
                    "document_id": document_id,
                    "group_id": group_id,
                    "content_id": content_id,
                    "page": sample["page"],
                    "page_count": sample["page_count"],
                    "origin": sample["origin"],
                    "feature_names": list(FEATURE_NAMES),
                    "features": sample["features"],
                    "label_state": "unlabeled-visual",
                    "training_use": "self-supervised-only",
                }
            )
            private_records.append(
                {
                    "sample_id": sample_id,
                    "path": str(path),
                    "page": sample["page"],
                    "thumbnail": str(sample["thumbnail"]),
                }
            )
    _assign_splits(public_records)
    visual_model = _cluster(public_records, clusters)
    summary = {
        "documents": len({record["document_id"] for record in public_records}),
        "samples": len(public_records),
        "groups": len({record["group_id"] for record in public_records}),
        "splits": dict(Counter(record["split"] for record in public_records)),
        "origins": dict(Counter(record["origin"] for record in public_records)),
        "style_clusters": dict(
            sorted(Counter(str(record["style_cluster"]) for record in public_records).items())
        ),
        "errors": sum("error" in record for record in private_records),
        "cached_documents": cached_documents,
    }
    public = {
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "sampling": {"pages_per_document": pages_per_document},
        "feature_names": list(FEATURE_NAMES),
        "visual_model": visual_model,
        "summary": summary,
        "samples": public_records,
    }
    private = {
        "schema_version": "1.0",
        "groups": groups,
        "samples": private_records,
    }
    (output / "visual-curriculum.json").write_text(
        json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "visual-model.json").write_text(
        json.dumps(visual_model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "private-map.json").write_text(
        json.dumps(private, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "summary": summary,
        "public_curriculum": str((output / "visual-curriculum.json").resolve()),
        "visual_model": str((output / "visual-model.json").resolve()),
        "private_map": str((output / "private-map.json").resolve()),
        "thumbnails": str((output / "private-thumbnails").resolve()),
    }


def rebalance_visual_curriculum(path: Path) -> dict[str, Any]:
    """Reassign group-safe splits without touching private images or features."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("samples", [])
    _assign_splits(records)
    model = _cluster(records, int(payload.get("visual_model", {}).get("clusters", 12)))
    payload["visual_model"] = model
    payload["summary"]["splits"] = dict(Counter(record["split"] for record in records))
    payload["summary"]["style_clusters"] = dict(
        sorted(Counter(str(record["style_cluster"]) for record in records).items())
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (path.parent / "visual-model.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return validate_visual_curriculum(path)


def validate_visual_curriculum(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("samples", [])
    errors: list[str] = []
    warnings: list[str] = []
    groups: dict[str, set[str]] = {}
    sample_ids: set[str] = set()
    for index, record in enumerate(records, start=1):
        sample_id = record.get("sample_id")
        if sample_id in sample_ids:
            errors.append(f"sample_id duplicado: {sample_id}")
        sample_ids.add(sample_id)
        groups.setdefault(record.get("group_id", ""), set()).add(record.get("split", ""))
        features = record.get("features", [])
        if len(features) != len(FEATURE_NAMES) or not all(
            isinstance(value, (int, float)) and math.isfinite(value) for value in features
        ):
            errors.append(f"features inválidas na amostra {index}")
        forbidden = {"path", "name", "title", "composer", "work", "thumbnail"}
        leaked = forbidden & set(record)
        if leaked:
            errors.append(f"campos privados na amostra {index}: {sorted(leaked)}")
    for group, splits in groups.items():
        if len(splits) != 1:
            errors.append(f"grupo {group} aparece em múltiplos splits: {sorted(splits)}")
    split_counts = Counter(record.get("split") for record in records)
    cluster_counts = Counter(str(record.get("style_cluster")) for record in records)
    for required in ("train", "validation", "test"):
        if not split_counts[required]:
            errors.append(f"split vazio: {required}")
    all_clusters = {str(record.get("style_cluster")) for record in records}
    for split in ("validation", "test"):
        present = {
            str(record.get("style_cluster"))
            for record in records
            if record.get("split") == split
        }
        missing = sorted(all_clusters - present)
        if missing:
            warnings.append(
                f"clusters ausentes em {split}: {', '.join(missing)}; "
                "grupos foram mantidos inteiros para impedir vazamento"
            )
    return {
        "valid": not errors,
        "samples": len(records),
        "groups": len(groups),
        "splits": dict(split_counts),
        "style_clusters": dict(sorted(cluster_counts.items())),
        "errors": errors,
        "warnings": warnings,
    }
