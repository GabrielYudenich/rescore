"""Conservative measure-region alignment for supervised ReScore datasets.

This module does not attempt to recognize notes. It locates structural vertical
barlines in a source page, assigns the verified MusicXML measure numbers in order,
and writes reviewable regions. The regions are machine proposals until a human
explicitly confirms them.
"""

from __future__ import annotations

import html
import itertools
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .dataset import MANIFEST_NAME, DatasetError

ALIGNMENT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class VerticalCandidate:
    """One clustered vertical-line candidate in detection-image coordinates."""

    x: float
    y0: int
    y1: int
    support: float
    segments: int


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_record(path: Path, root: Path) -> dict[str, str]:
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "sha256": _sha256(path),
    }


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_NAME
    if not path.is_file():
        raise DatasetError(f"manifesto não encontrado: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(root: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = _now()
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _find_item(manifest: dict[str, Any], item_id: str) -> dict[str, Any]:
    for item in manifest.get("items", []):
        if item.get("id") == item_id:
            return item
    raise DatasetError(f"item não encontrado: {item_id}")


def _union_length(spans: list[tuple[int, int]], gap: int) -> int:
    if not spans:
        return 0
    spans = sorted(spans)
    total = 0
    start, end = spans[0]
    for next_start, next_end in spans[1:]:
        if next_start <= end + gap:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def _vertical_candidates(gray: np.ndarray) -> tuple[list[VerticalCandidate], float]:
    """Return Hough line clusters and the scale used for detection."""
    original_height, original_width = gray.shape
    scale = min(1.0, 2400 / max(original_height, original_width))
    if scale < 1:
        resized = cv2.resize(
            gray,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA,
        )
    else:
        resized = gray
    height, width = resized.shape
    edges = cv2.Canny(resized, 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 1800,
        threshold=max(30, round(height * 0.025)),
        minLineLength=max(30, round(height * 0.08)),
        maxLineGap=max(8, round(height * 0.02)),
    )
    segments: list[tuple[float, int, int]] = []
    if lines is not None:
        maximum_dx = max(3, width * 0.003)
        for x1, y1, x2, y2 in lines[:, 0]:
            if abs(x2 - x1) > maximum_dx or abs(y2 - y1) < height * 0.08:
                continue
            segments.append(
                (
                    float(x1 + x2) / 2,
                    int(min(y1, y2)),
                    int(max(y1, y2)),
                )
            )
    segments.sort()
    tolerance = max(5, width * 0.009)
    clusters: list[list[tuple[float, int, int]]] = []
    for segment in segments:
        if not clusters:
            clusters.append([segment])
            continue
        center = float(np.median([existing[0] for existing in clusters[-1]]))
        if segment[0] - center > tolerance:
            clusters.append([segment])
        else:
            clusters[-1].append(segment)

    candidates: list[VerticalCandidate] = []
    for cluster in clusters:
        spans = [(segment[1], segment[2]) for segment in cluster]
        support_pixels = _union_length(spans, max(3, round(height * 0.005)))
        if support_pixels < height * 0.08:
            continue
        x = float(np.median([segment[0] for segment in cluster]))
        if x < width * 0.015 or x > width * 0.985:
            continue
        candidates.append(
            VerticalCandidate(
                x=x,
                y0=min(span[0] for span in spans),
                y1=max(span[1] for span in spans),
                support=support_pixels / height,
                segments=len(cluster),
            )
        )
    return candidates, scale


def _choose_boundaries(
    candidates: list[VerticalCandidate],
    *,
    expected_measures: int,
    width: int,
) -> tuple[list[VerticalCandidate], dict[str, float]]:
    """Choose a regular structural sequence while preferring well-supported lines."""
    required = expected_measures + 1
    if expected_measures < 1:
        raise ValueError("expected_measures precisa ser positivo")
    if len(candidates) < required:
        raise ValueError(
            f"somente {len(candidates)} linhas verticais candidatas; são necessárias {required}"
        )

    viable: list[tuple[float, list[int], float, float]] = []
    for first, last in itertools.combinations(range(len(candidates)), 2):
        if last - first + 1 < required:
            continue
        start = candidates[first].x
        end = candidates[last].x
        step = (end - start) / expected_measures
        coverage = (end - start) / width
        if step < width * 0.045 or coverage < 0.42 or coverage > 0.96:
            continue

        chosen = [first]
        previous = first
        deviation_cost = 0.0
        possible = True
        for position in range(1, required - 1):
            ideal = start + position * step
            latest = last - (required - 1 - position)
            options = range(previous + 1, latest + 1)
            try:
                selected = min(
                    options,
                    key=lambda index: (
                        abs(candidates[index].x - ideal)
                        - min(candidates[index].support, 1.0) * step * 0.12
                    ),
                )
            except ValueError:
                possible = False
                break
            deviation = abs(candidates[selected].x - ideal) / step
            if deviation > 0.45:
                possible = False
                break
            deviation_cost += deviation
            chosen.append(selected)
            previous = selected
        if not possible:
            continue
        chosen.append(last)
        positions = [candidates[index].x for index in chosen]
        spacings = np.diff(positions)
        coefficient = float(np.std(spacings) / np.mean(spacings))
        support = float(np.mean([min(candidates[index].support, 1.0) for index in chosen]))
        score = deviation_cost + coefficient * 2 + abs(coverage - 0.78) * 0.4 - support * 3
        viable.append((score, chosen, coverage, coefficient))

    if not viable:
        raise ValueError(f"não foi encontrada uma sequência de {expected_measures} compassos")
    minimum_score = min(result[0] for result in viable)
    near_optimal = [
        result
        for result in viable
        if result[0] <= minimum_score + 0.15
        and candidates[result[1][0]].x >= width * 0.04
        and candidates[result[1][0]].support >= 0.2
    ]
    # Opening attributes (clef, key and meter) live immediately after the first
    # system line. Within a narrow score tolerance, prefer the leftmost supported
    # sequence so the first-measure crop does not begin on an aligned note stem.
    best = min(
        near_optimal or viable,
        key=lambda result: (candidates[result[1][0]].x, result[0]),
    )
    selected = [candidates[index] for index in best[1]]
    support = float(np.mean([min(candidate.support, 1.0) for candidate in selected]))
    regularity = max(0.0, 1.0 - best[3] * 4)
    coverage_quality = max(0.0, 1.0 - abs(best[2] - 0.78) / 0.78)
    confidence = min(1.0, support * 0.5 + regularity * 0.4 + coverage_quality * 0.1)
    return selected, {
        "confidence": round(confidence, 4),
        "support": round(support, 4),
        "spacing_regularity": round(regularity, 4),
        "page_coverage": round(best[2], 4),
    }


def detect_measure_regions(
    image_path: Path,
    *,
    expected_measures: int,
    first_measure: int,
) -> dict[str, Any]:
    """Detect and number full-system measure columns in one source image."""
    image_path = image_path.resolve()
    gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError(f"não foi possível abrir a imagem: {image_path}")
    original_height, original_width = gray.shape
    candidates, scale = _vertical_candidates(gray)
    detection_width = max(1, round(original_width * scale))
    selected, metrics = _choose_boundaries(
        candidates,
        expected_measures=expected_measures,
        width=detection_width,
    )

    x_positions = [
        max(0, min(original_width - 1, round(candidate.x / scale))) for candidate in selected
    ]
    y0 = max(
        0,
        round(min(candidate.y0 for candidate in selected) / scale) - round(original_height * 0.012),
    )
    y1 = min(
        original_height,
        round(max(candidate.y1 for candidate in selected) / scale) + round(original_height * 0.012),
    )
    if y1 - y0 < original_height * 0.2:
        raise ValueError("as linhas detectadas não cobrem um sistema musical suficiente")

    regions: list[dict[str, Any]] = []
    for offset, (left, right) in enumerate(itertools.pairwise(x_positions)):
        if right <= left:
            raise ValueError("limites de compasso fora de ordem")
        measure_number = first_measure + offset
        regions.append(
            {
                "id": f"measure-{measure_number:04d}",
                "measure_number": measure_number,
                "bbox_pixels": {
                    "x": left,
                    "y": y0,
                    "width": right - left,
                    "height": y1 - y0,
                },
                "bbox_normalized": {
                    "x": round(left / original_width, 8),
                    "y": round(y0 / original_height, 8),
                    "width": round((right - left) / original_width, 8),
                    "height": round((y1 - y0) / original_height, 8),
                },
            }
        )
    return {
        "image": {
            "path": str(image_path),
            "width": original_width,
            "height": original_height,
        },
        "expected_measures": expected_measures,
        "first_measure": first_measure,
        "last_measure": first_measure + expected_measures - 1,
        "boundaries_x": x_positions,
        "system_y": [y0, y1],
        "candidate_count": len(candidates),
        "metrics": metrics,
        "regions": regions,
    }


def _write_overlay(
    source: Path,
    detection: dict[str, Any],
    output: Path,
) -> None:
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"não foi possível abrir a imagem: {source}")
    height, width = image.shape[:2]
    thickness = max(2, round(max(width, height) / 1200))
    font_scale = max(0.6, max(width, height) / 2600)
    overlay = image.copy()
    for region in detection["regions"]:
        box = region["bbox_pixels"]
        left, top = box["x"], box["y"]
        right, bottom = left + box["width"], top + box["height"]
        cv2.rectangle(overlay, (left, top), (right, bottom), (0, 165, 255), -1)
    cv2.addWeighted(overlay, 0.12, image, 0.88, 0, image)
    for region in detection["regions"]:
        box = region["bbox_pixels"]
        left, top = box["x"], box["y"]
        right, bottom = left + box["width"], top + box["height"]
        cv2.rectangle(image, (left, top), (right, bottom), (0, 80, 255), thickness)
        label = f"m. {region['measure_number']}"
        baseline_y = max(30, top + round(34 * font_scale))
        cv2.putText(
            image,
            label,
            (left + thickness * 2, baseline_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (0, 0, 0),
            thickness + 3,
            cv2.LINE_AA,
        )
        cv2.putText(
            image,
            label,
            (left + thickness * 2, baseline_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_AA,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), image):
        raise OSError(f"não foi possível gravar: {output}")


def _write_review_html(
    item: dict[str, Any],
    pages: list[dict[str, Any]],
    output: Path,
) -> None:
    cards = []
    for page in pages:
        measures = ", ".join(str(region["measure_number"]) for region in page["regions"])
        cards.append(
            f"""
            <section class="card">
              <div class="heading">
                <h2>Página fonte {page["image_page"]}</h2>
                <span>{html.escape(measures)}</span>
              </div>
              <img src="{html.escape(page["preview_relative"])}"
                   alt="Proposta de alinhamento da página {page["image_page"]}">
              <dl>
                <dt>Confiança geométrica</dt>
                <dd>{page["metrics"]["confidence"]:.1%}</dd>
                <dt>Compassos</dt>
                <dd>{page["first_measure"]}–{page["last_measure"]}</dd>
                <dt>Estado</dt>
                <dd>Proposta da máquina — requer confirmação humana</dd>
              </dl>
            </section>
            """
        )
    document = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Revisão de alinhamento — {html.escape(item["id"])}</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, Segoe UI, sans-serif; }}
    body {{ margin: 0; background: #f2efe9; color: #211f1b; }}
    header {{ padding: 28px 34px; background: #173a37; color: white; }}
    header h1 {{ margin: 0 0 8px; font-size: 1.55rem; }}
    header p {{ margin: 0; max-width: 72ch; color: #d7e6e2; }}
    main {{ display: grid; gap: 24px; padding: 24px; }}
    .card {{ background: white; border-radius: 12px; padding: 18px;
             box-shadow: 0 3px 14px #0002; }}
    .heading {{ display: flex; align-items: baseline; gap: 16px;
                justify-content: space-between; }}
    h2 {{ margin: 0 0 14px; font-size: 1.15rem; }}
    img {{ display: block; width: 100%; height: auto; border: 1px solid #c9c5bc; }}
    dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; }}
    dt {{ font-weight: 700; }} dd {{ margin: 0; }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(item["source"]["work"])}</h1>
    <p>As caixas laranja são propostas geométricas. Confirme as barras e os números
    dos compassos antes de alterar o estado para revisado.</p>
  </header>
  <main>{"".join(cards)}</main>
</body>
</html>
"""
    output.write_text(document, encoding="utf-8")


def _parse_page_counts(
    value: str | list[int] | None,
    *,
    pages: int,
    total_measures: int,
) -> list[int]:
    if isinstance(value, str):
        try:
            counts = [int(part.strip()) for part in value.split(",") if part.strip()]
        except ValueError as exc:
            raise ValueError("page_measures deve ser uma lista como 8,8") from exc
    elif value is None:
        if total_measures % pages:
            raise ValueError(
                "não é possível distribuir os compassos igualmente; informe --page-measures"
            )
        counts = [total_measures // pages] * pages
    else:
        counts = list(value)
    if len(counts) != pages:
        raise ValueError(f"foram informadas {len(counts)} contagens para {pages} páginas")
    if any(count < 1 for count in counts) or sum(counts) != total_measures:
        raise ValueError(f"page_measures precisa somar {total_measures}: recebido {counts}")
    return counts


def align_dataset_item(
    dataset_root: Path,
    *,
    item_id: str,
    page_measures: str | list[int] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Create machine-proposed page/measure regions and attach them to one item."""
    dataset_root = dataset_root.resolve()
    manifest = _load_manifest(dataset_root)
    item = _find_item(manifest, item_id)
    images = item["source"]["images"]
    measure_range = item["ground_truth"]["measure_range"]
    first_measure = int(measure_range["start"])
    last_measure = int(measure_range["end"])
    total_measures = last_measure - first_measure + 1
    counts = _parse_page_counts(
        page_measures,
        pages=len(images),
        total_measures=total_measures,
    )
    item_dir = dataset_root / "items" / item_id
    alignment_dir = item_dir / "alignment"
    regions_path = alignment_dir / "measure-regions.json"
    if regions_path.exists() and not force:
        raise DatasetError(f"alinhamento já existe: {regions_path}; use --force para refazer")
    alignment_dir.mkdir(parents=True, exist_ok=True)

    pages: list[dict[str, Any]] = []
    next_measure = first_measure
    for image_record, count in zip(images, counts, strict=True):
        source = dataset_root / image_record["path"]
        detection = detect_measure_regions(
            source,
            expected_measures=count,
            first_measure=next_measure,
        )
        preview = alignment_dir / f"page-{image_record['page']:04d}-overlay.jpg"
        _write_overlay(source, detection, preview)
        page = {
            "image_page": image_record["page"],
            "source_image": image_record["path"],
            "preview_relative": preview.name,
            "preview": _file_record(preview, dataset_root),
            "first_measure": detection["first_measure"],
            "last_measure": detection["last_measure"],
            "boundaries_x": detection["boundaries_x"],
            "system_y": detection["system_y"],
            "candidate_count": detection["candidate_count"],
            "metrics": detection["metrics"],
            "regions": detection["regions"],
        }
        pages.append(page)
        next_measure += count

    payload = {
        "schema": "rescore-measure-alignment",
        "schema_version": ALIGNMENT_SCHEMA_VERSION,
        "item_id": item_id,
        "created_at": _now(),
        "review_status": "machine-proposed",
        "measure_range": {"start": first_measure, "end": last_measure},
        "page_measure_counts": counts,
        "pages": pages,
    }
    regions_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    review_html = alignment_dir / "review.html"
    _write_review_html(item, pages, review_html)

    item["alignment"].update(
        {
            "review_status": "machine-proposed",
            "page_measure_counts": counts,
            "measure_region_count": total_measures,
            "regions_file": _file_record(regions_path, dataset_root),
            "review_html": _file_record(review_html, dataset_root),
            "preview_images": [page["preview"] for page in pages],
            "updated_at": _now(),
        }
    )
    _save_manifest(dataset_root, manifest)
    validation = validate_alignment(regions_path)
    return {
        "dataset": str(dataset_root),
        "item_id": item_id,
        "alignment": str(regions_path),
        "review_html": str(review_html),
        "pages": len(pages),
        "measures": total_measures,
        "page_measure_counts": counts,
        "minimum_confidence": min(page["metrics"]["confidence"] for page in pages),
        "validation": validation,
    }


def validate_alignment(path: Path) -> dict[str, Any]:
    """Validate coverage, ordering and normalized boxes in an alignment JSON."""
    path = path.resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    errors: list[dict[str, Any]] = []
    if data.get("schema_version") != ALIGNMENT_SCHEMA_VERSION:
        errors.append({"kind": "schema_version"})
    measure_range = data.get("measure_range", {})
    expected = list(range(int(measure_range.get("start", 1)), int(measure_range.get("end", 0)) + 1))
    regions = [region for page in data.get("pages", []) for region in page.get("regions", [])]
    actual = [int(region.get("measure_number", 0)) for region in regions]
    if actual != expected:
        errors.append(
            {
                "kind": "measure_coverage",
                "expected": expected,
                "actual": actual,
            }
        )
    for region in regions:
        box = region.get("bbox_normalized", {})
        values = [box.get(name) for name in ("x", "y", "width", "height")]
        if (
            any(not isinstance(value, (int, float)) for value in values)
            or box.get("x", -1) < 0
            or box.get("y", -1) < 0
            or box.get("width", 0) <= 0
            or box.get("height", 0) <= 0
            or box.get("x", 0) + box.get("width", 0) > 1.000001
            or box.get("y", 0) + box.get("height", 0) > 1.000001
        ):
            errors.append({"kind": "invalid_bbox", "region": region.get("id")})
    page_counts = [len(page.get("regions", [])) for page in data.get("pages", [])]
    if page_counts != data.get("page_measure_counts"):
        errors.append(
            {
                "kind": "page_measure_counts",
                "expected": data.get("page_measure_counts"),
                "actual": page_counts,
            }
        )
    return {
        "valid": not errors,
        "path": str(path),
        "pages": len(data.get("pages", [])),
        "measures": len(regions),
        "errors": errors,
    }
