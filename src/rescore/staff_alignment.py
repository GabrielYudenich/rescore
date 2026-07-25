"""Conservative visual-staff alignment for supervised ReScore datasets.

The measure aligner establishes horizontal measure columns.  This module adds
the other structural axis: physical staff bands and their possible MusicXML
targets.  It deliberately does not recognize notes.  Condensed orchestral
staves may point to several expanded parts, while unused manuscript-paper
staves remain explicitly unassigned.
"""

from __future__ import annotations

import html
import json
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .alignment import _file_record, _find_item, _load_manifest, _now, _save_manifest
from .dataset import DatasetError

STAFF_ALIGNMENT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class StaffSpec:
    """One physical source staff and its expanded MusicXML targets."""

    label: str
    targets: tuple[tuple[str, str], ...] = ()
    staff_type: str = "five-line"


@dataclass(frozen=True)
class PageProfile:
    staves: tuple[StaffSpec, ...]
    center_fractions: tuple[float, ...] | None = None


def _targets(*part_ids: str) -> tuple[tuple[str, str], ...]:
    return tuple((part_id, "1") for part_id in part_ids)


_MENINA_PAGE_1 = (
    StaffSpec("Flautim / 2ª flauta", _targets("P1", "P2")),
    StaffSpec("1ª flauta", _targets("P3")),
    StaffSpec("Oboé / corne inglês", _targets("P4", "P5")),
    StaffSpec("Clarinetes / saxofone", _targets("P6", "P7", "P8")),
    StaffSpec("Fagote", _targets("P9")),
    StaffSpec("Trompas", _targets("P10")),
    StaffSpec("Pistão / corneta", _targets("P11")),
    StaffSpec("Trombone", _targets("P12")),
    StaffSpec("Tuba", _targets("P13")),
    StaffSpec("Tímpano", _targets("P14")),
    StaffSpec("Harpa", (("P22", "1"), ("P22", "2"))),
    StaffSpec("Celesta / xilofone", (("P15", "1"), ("P20", "1"), ("P20", "2"))),
    StaffSpec("Bateria", _targets("P16", "P17", "P18", "P19")),
    StaffSpec("Piano — pauta superior", (("P21", "1"),)),
    StaffSpec("Piano — pauta inferior", (("P21", "2"),)),
    StaffSpec("Pauta impressa sem instrumento"),
    StaffSpec("Violinos I", _targets("P23")),
    StaffSpec("Violinos II", _targets("P24")),
    StaffSpec("Violas", _targets("P25")),
    StaffSpec("Violoncelos", _targets("P26")),
    StaffSpec("Contrabaixos", _targets("P27")),
)


_MENINA_PAGE_2 = (
    StaffSpec("Flautas / flautins", _targets("P1", "P2", "P3")),
    StaffSpec("Oboé / corne inglês", _targets("P4", "P5")),
    StaffSpec("Clarinetes / saxofone", _targets("P6", "P7", "P8")),
    StaffSpec("Fagote", _targets("P9")),
    StaffSpec("Trompas — pauta 1", _targets("P10")),
    StaffSpec("Trompas — pauta 2", _targets("P10")),
    StaffSpec("Pistão / corneta", _targets("P11")),
    StaffSpec("Trombone", _targets("P12")),
    StaffSpec("Tuba", _targets("P13")),
    StaffSpec("Tímpano", _targets("P14")),
    *(StaffSpec("Pauta impressa sem instrumento") for _ in range(9)),
    StaffSpec("Violinos I", _targets("P23")),
    StaffSpec("Violinos II", _targets("P24")),
    StaffSpec("Violas", _targets("P25")),
    StaffSpec("Violoncelos", _targets("P26")),
    StaffSpec("Contrabaixos", _targets("P27")),
)


# Fractions measured from the first to the last physical staff centre in the
# opening Eschig system.  Unlike the older OMR crop profile, this sequence keeps
# the one-line percussion staff between timpani and celesta.
_CHOROS9_CENTER_FRACTIONS = (
    0.0,
    0.0377,
    0.0790,
    0.1160,
    0.1550,
    0.1980,
    0.2390,
    0.2780,
    0.3330,
    0.3700,
    0.4120,
    0.4550,
    0.4950,
    0.5370,
    0.5770,
    0.6090,
    0.6490,
    0.6880,
    0.7270,
    0.7660,
    0.8320,
    0.8710,
    0.9130,
    0.9560,
    1.0,
)


_CHOROS9_STAVES = (
    StaffSpec("Piccolo", _targets("P1")),
    StaffSpec("2 flautas", _targets("P2", "P3")),
    StaffSpec("2 oboés", _targets("P4", "P5")),
    StaffSpec("Corne inglês", _targets("P6")),
    StaffSpec("2 clarinetes", _targets("P7", "P8")),
    StaffSpec("Clarinete baixo", _targets("P9")),
    StaffSpec("2 fagotes", _targets("P10", "P11")),
    StaffSpec("Contrafagote", _targets("P12")),
    StaffSpec("Trompas 1–2", _targets("P13", "P14")),
    StaffSpec("Trompas 3–4", _targets("P15", "P16")),
    StaffSpec("4 pistões", _targets("P17", "P18", "P19", "P20")),
    StaffSpec("Trombones 1–2", _targets("P21", "P22")),
    StaffSpec("Trombones 3–4", _targets("P23", "P24")),
    StaffSpec("Tuba", _targets("P25")),
    StaffSpec("Tímpanos", _targets("P26")),
    StaffSpec("Percussão", _targets("P27", "P28"), "one-line"),
    StaffSpec("Celesta — pauta superior", (("P29", "1"),)),
    StaffSpec("Celesta — pauta inferior", (("P29", "2"),)),
    StaffSpec("Harpas — pauta superior", (("P30", "1"),)),
    StaffSpec("Harpas — pauta inferior", (("P30", "2"),)),
    StaffSpec("Violinos I", _targets("P31")),
    StaffSpec("Violinos II", _targets("P32")),
    StaffSpec("Violas", _targets("P33")),
    StaffSpec("Violoncelos", _targets("P34")),
    StaffSpec("Contrabaixos", _targets("P35")),
)


PROFILES: dict[str, dict[int, PageProfile]] = {
    "menina-opening": {
        1: PageProfile(_MENINA_PAGE_1),
        2: PageProfile(_MENINA_PAGE_2),
    },
    "choros9-opening": {
        1: PageProfile(_CHOROS9_STAVES, _CHOROS9_CENTER_FRACTIONS),
    },
}


def _resolve_profile(item: dict[str, Any], requested: str) -> str:
    if requested != "auto":
        if requested not in PROFILES:
            raise DatasetError(f"perfil de pautas desconhecido: {requested}")
        return requested
    text = f"{item.get('id', '')} {item.get('source', {}).get('work', '')}".casefold()
    if "choros9" in text or "chôros nº 9" in text or "chôros n° 9" in text:
        return "choros9-opening"
    if "menina" in text and "nuv" in text:
        return "menina-opening"
    raise DatasetError("não há perfil automático seguro para este item; informe --profile")


def _part_catalog(path: Path) -> dict[str, dict[str, Any]]:
    root = ET.parse(path).getroot()
    names = {
        node.get("id", ""): (node.findtext("part-name") or node.get("id", ""))
        for node in root.findall("./part-list/score-part")
    }
    catalog: dict[str, dict[str, Any]] = {}
    for part in root.findall("./part"):
        part_id = part.get("id", "")
        staves = 1
        for node in part.findall("./measure/attributes/staves"):
            if node.text and node.text.isdigit():
                staves = max(staves, int(node.text))
        catalog[part_id] = {"name": names.get(part_id, part_id), "staves": staves}
    return catalog


def _longest_vertical_extent(
    gray: np.ndarray,
    boundaries: list[int],
    system_y: list[int],
) -> tuple[int, int, float]:
    """Find the continuous orchestral spine already present at a barline."""
    height, width = gray.shape
    hint_top, hint_bottom = max(0, system_y[0]), min(height, system_y[1])
    gap = max(8, round((hint_bottom - hint_top) * 0.0035))
    candidates: list[tuple[int, int]] = []
    radius = max(4, round(width * 0.0015))
    for x in boundaries:
        left, right = max(0, x - radius), min(width, x + radius + 1)
        ink = (gray[hint_top:hint_bottom, left:right] < 175).sum(axis=1) >= 2
        rows = np.where(ink)[0]
        runs: list[list[int]] = []
        for row in rows:
            absolute = int(row) + hint_top
            if not runs or absolute - runs[-1][-1] > gap:
                runs.append([absolute])
            else:
                runs[-1].append(absolute)
        candidates.extend((run[0], run[-1]) for run in runs if len(run) > 1)
    if not candidates:
        raise ValueError("não foi possível confirmar a espinha vertical do sistema")
    top, bottom = max(candidates, key=lambda span: span[1] - span[0])
    coverage = (bottom - top) / max(1, hint_bottom - hint_top)
    if coverage < 0.55:
        raise ValueError("a espinha vertical não cobre o sistema musical com segurança")
    return top, bottom, min(1.0, coverage)


def _estimate_interline(gray: np.ndarray, left: int, right: int, top: int, bottom: int) -> float:
    roi = gray[top:bottom, left:right]
    foreground = cv2.adaptiveThreshold(
        roi,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        10,
    )
    kernel_width = max(40, round(roi.shape[1] * 0.08))
    horizontal = cv2.morphologyEx(
        foreground,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1)),
    )
    weights = (horizontal > 0).sum(axis=1)
    rows = np.where(weights > max(30, roi.shape[1] * 0.06))[0]
    runs: list[list[int]] = []
    for row in rows:
        if not runs or row > runs[-1][-1] + 1:
            runs.append([int(row)])
        else:
            runs[-1].append(int(row))
    lines = np.array([sum(run) / len(run) for run in runs], dtype=float)
    differences = np.diff(lines)
    plausible = differences[(differences >= 4) & (differences <= 28)]
    if len(plausible) < 4:
        raise ValueError("espaçamento entre linhas de pauta não confirmado")
    return float(np.median(plausible))


def _normalized_box(box: dict[str, int], width: int, height: int) -> dict[str, float]:
    return {
        "x": round(box["x"] / width, 8),
        "y": round(box["y"] / height, 8),
        "width": round(box["width"] / width, 8),
        "height": round(box["height"] / height, 8),
    }


def detect_staff_regions(
    image_path: Path,
    measure_page: dict[str, Any],
    page_profile: PageProfile,
    part_catalog: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Locate physical staff bands inside one already aligned page."""
    gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError(f"não foi possível abrir a imagem: {image_path}")
    height, width = gray.shape
    boundaries = [int(value) for value in measure_page["boundaries_x"]]
    top, bottom, spine_confidence = _longest_vertical_extent(
        gray,
        boundaries,
        [int(value) for value in measure_page["system_y"]],
    )
    interline = _estimate_interline(gray, boundaries[0], boundaries[-1], top, bottom)
    first_center = top + 2 * interline
    last_center = bottom - 2 * interline
    count = len(page_profile.staves)
    fractions = page_profile.center_fractions
    if fractions is None:
        fractions = tuple(np.linspace(0.0, 1.0, count).tolist())
    if len(fractions) != count or any(
        right <= left for left, right in zip(fractions, fractions[1:], strict=False)
    ):
        raise ValueError("perfil possui centros de pauta inválidos")
    centers = [first_center + fraction * (last_center - first_center) for fraction in fractions]
    edges = [max(top, round(centers[0] - (centers[1] - centers[0]) / 2))]
    edges.extend(
        round((left + right) / 2) for left, right in zip(centers, centers[1:], strict=False)
    )
    edges.append(min(bottom + 1, round(centers[-1] + (centers[-1] - centers[-2]) / 2)))

    bands: list[dict[str, Any]] = []
    for index, (spec, center, band_top, band_bottom) in enumerate(
        zip(page_profile.staves, centers, edges[:-1], edges[1:], strict=True),
        1,
    ):
        targets = []
        for part_id, staff_number in spec.targets:
            part = part_catalog.get(part_id)
            if part is None:
                raise ValueError(f"perfil aponta para parte ausente: {part_id}")
            if int(staff_number) > int(part["staves"]):
                raise ValueError(f"perfil aponta para pauta ausente: {part_id}/{staff_number}")
            targets.append(
                {
                    "part_id": part_id,
                    "part_name": part["name"],
                    "staff_number": staff_number,
                }
            )
        box = {
            "x": boundaries[0],
            "y": band_top,
            "width": boundaries[-1] - boundaries[0],
            "height": band_bottom - band_top,
        }
        bands.append(
            {
                "id": f"visual-staff-{index:03d}",
                "visual_staff_index": index,
                "source_label": spec.label,
                "staff_type": spec.staff_type,
                "center_y": round(center, 2),
                "mapping_status": "profile-proposed" if targets else "unassigned",
                "targets": targets,
                "bbox_pixels": box,
                "bbox_normalized": _normalized_box(box, width, height),
            }
        )

    cells = []
    for measure in measure_page["regions"]:
        measure_box = measure["bbox_pixels"]
        for band in bands:
            band_box = band["bbox_pixels"]
            box = {
                "x": measure_box["x"],
                "y": band_box["y"],
                "width": measure_box["width"],
                "height": band_box["height"],
            }
            cells.append(
                {
                    "id": f"measure-{int(measure['measure_number']):04d}-staff-{band['visual_staff_index']:03d}",
                    "measure_number": int(measure["measure_number"]),
                    "visual_staff_index": band["visual_staff_index"],
                    "target_refs": [
                        f"{target['part_id']}:{target['staff_number']}"
                        for target in band["targets"]
                    ],
                    "bbox_pixels": box,
                    "bbox_normalized": _normalized_box(box, width, height),
                }
            )
    return {
        "image": {"width": width, "height": height},
        "structural_extent_y": [top, bottom],
        "interline": round(interline, 3),
        "metrics": {"spine_confidence": round(spine_confidence, 4)},
        "staff_bands": bands,
        "cells": cells,
    }


def _write_overlay(source: Path, detection: dict[str, Any], output: Path) -> None:
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"não foi possível abrir a imagem: {source}")
    height, width = image.shape[:2]
    thickness = max(2, round(max(width, height) / 1500))
    font_scale = max(0.55, max(width, height) / 3600)
    colors = ((31, 119, 180), (44, 160, 44))
    overlay = image.copy()
    for band in detection["staff_bands"]:
        box = band["bbox_pixels"]
        color = colors[(band["visual_staff_index"] - 1) % 2]
        cv2.rectangle(
            overlay,
            (box["x"], box["y"]),
            (box["x"] + box["width"], box["y"] + box["height"]),
            color,
            -1,
        )
    cv2.addWeighted(overlay, 0.10, image, 0.90, 0, image)
    for band in detection["staff_bands"]:
        box = band["bbox_pixels"]
        color = colors[(band["visual_staff_index"] - 1) % 2]
        cv2.rectangle(
            image,
            (box["x"], box["y"]),
            (box["x"] + box["width"], box["y"] + box["height"]),
            color,
            thickness,
        )
        readable = unicodedata.normalize("NFKD", band["source_label"])
        readable = "".join(character for character in readable if ord(character) < 128)
        label = f"{band['visual_staff_index']:02d} {readable}"
        y = max(24, round(band["center_y"] + 5 * font_scale))
        cv2.putText(
            image,
            label,
            (max(5, box["x"] + 6), y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 255, 255),
            thickness + 3,
            cv2.LINE_AA,
        )
        cv2.putText(
            image,
            label,
            (max(5, box["x"] + 6), y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (0, 0, 0),
            thickness,
            cv2.LINE_AA,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), image):
        raise OSError(f"não foi possível gravar: {output}")


def _write_review_html(item: dict[str, Any], pages: list[dict[str, Any]], output: Path) -> None:
    cards = []
    for page in pages:
        assigned = sum(bool(band["targets"]) for band in page["staff_bands"])
        cards.append(
            f"""
            <section><h2>Página {page["image_page"]} — {len(page["staff_bands"])} pautas</h2>
            <p>{assigned} pautas com alvos propostos; {len(page["staff_bands"]) - assigned}
            permanecem sem instrumento. Células: {len(page["cells"])}.</p>
            <img src="{html.escape(page["preview_relative"])}" alt="Pautas propostas">
            </section>
            """
        )
    output.write_text(
        f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Revisão de pautas — {html.escape(item["id"])}</title>
        <style>body{{font-family:Segoe UI,sans-serif;margin:0;background:#f2efe9}}
        header,section{{padding:22px}}header{{background:#173a37;color:white}}
        section{{margin:20px;background:white;border-radius:10px}}img{{width:100%;height:auto}}
        </style></head><body><header><h1>{html.escape(item["source"]["work"])}</h1>
        <p>Proposta estrutural da máquina. Confirme abreviações, pautas condensadas e
        linhas vazias antes de promover o estado para revisado.</p></header>{"".join(cards)}</body></html>""",
        encoding="utf-8",
    )


def align_dataset_staffs(
    dataset_root: Path,
    *,
    item_id: str,
    profile: str = "auto",
    force: bool = False,
) -> dict[str, Any]:
    """Attach machine-proposed staff bands and measure/staff cells to an item."""
    dataset_root = dataset_root.resolve()
    manifest = _load_manifest(dataset_root)
    item = _find_item(manifest, item_id)
    profile_name = _resolve_profile(item, profile)
    alignment = item.get("alignment", {})
    measure_record = alignment.get("regions_file")
    if not isinstance(measure_record, dict):
        raise DatasetError("execute dataset-align antes de alinhar as pautas")
    measure_path = dataset_root / measure_record["path"]
    measure_data = json.loads(measure_path.read_text(encoding="utf-8"))
    item_dir = dataset_root / "items" / item_id
    alignment_dir = item_dir / "alignment"
    regions_path = alignment_dir / "staff-regions.json"
    if regions_path.exists() and not force:
        raise DatasetError(f"alinhamento de pautas já existe: {regions_path}; use --force")
    catalog = _part_catalog(dataset_root / item["ground_truth"]["musicxml"]["path"])
    profile_pages = PROFILES[profile_name]
    pages = []
    for measure_page in measure_data.get("pages", []):
        page_number = int(measure_page["image_page"])
        page_profile = profile_pages.get(page_number)
        if page_profile is None:
            raise DatasetError(f"perfil {profile_name} não cobre a página {page_number}")
        source = dataset_root / measure_page["source_image"]
        detection = detect_staff_regions(source, measure_page, page_profile, catalog)
        preview = alignment_dir / f"page-{page_number:04d}-staff-overlay.jpg"
        _write_overlay(source, detection, preview)
        pages.append(
            {
                "image_page": page_number,
                "source_image": measure_page["source_image"],
                "preview_relative": preview.name,
                "preview": _file_record(preview, dataset_root),
                **detection,
            }
        )
    payload = {
        "schema": "rescore-staff-alignment",
        "schema_version": STAFF_ALIGNMENT_SCHEMA_VERSION,
        "item_id": item_id,
        "created_at": _now(),
        "review_status": "machine-proposed",
        "profile": profile_name,
        "pages": pages,
    }
    regions_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    review = alignment_dir / "staff-review.html"
    _write_review_html(item, pages, review)
    staff_count = sum(len(page["staff_bands"]) for page in pages)
    cell_count = sum(len(page["cells"]) for page in pages)
    alignment.update(
        {
            "staff_review_status": "machine-proposed",
            "staff_profile": profile_name,
            "staff_region_count": staff_count,
            "staff_cell_count": cell_count,
            "staff_regions_file": _file_record(regions_path, dataset_root),
            "staff_review_html": _file_record(review, dataset_root),
            "staff_preview_images": [page["preview"] for page in pages],
            "updated_at": _now(),
        }
    )
    _save_manifest(dataset_root, manifest)
    validation = validate_staff_alignment(regions_path)
    return {
        "dataset": str(dataset_root),
        "item_id": item_id,
        "profile": profile_name,
        "alignment": str(regions_path),
        "review_html": str(review),
        "pages": len(pages),
        "staff_regions": staff_count,
        "measure_staff_cells": cell_count,
        "validation": validation,
    }


def validate_staff_alignment(path: Path) -> dict[str, Any]:
    """Validate ordering, boxes, references and the measure/staff grid."""
    path = path.resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    errors: list[dict[str, Any]] = []
    if data.get("schema_version") != STAFF_ALIGNMENT_SCHEMA_VERSION:
        errors.append({"kind": "schema_version"})
    total_bands = 0
    total_cells = 0
    for page in data.get("pages", []):
        bands = page.get("staff_bands", [])
        cells = page.get("cells", [])
        total_bands += len(bands)
        total_cells += len(cells)
        indices = [band.get("visual_staff_index") for band in bands]
        if indices != list(range(1, len(bands) + 1)):
            errors.append({"kind": "staff_order", "page": page.get("image_page")})
        previous_bottom = -1
        for band in bands:
            box = band.get("bbox_normalized", {})
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
                errors.append({"kind": "invalid_bbox", "region": band.get("id")})
            pixel_box = band.get("bbox_pixels", {})
            if pixel_box.get("y", -1) < previous_bottom:
                errors.append({"kind": "overlapping_staff_bands", "region": band.get("id")})
            previous_bottom = pixel_box.get("y", 0) + pixel_box.get("height", 0)
            if band.get("mapping_status") == "unassigned" and band.get("targets"):
                errors.append({"kind": "unassigned_with_targets", "region": band.get("id")})
        measures = sorted({int(cell.get("measure_number", 0)) for cell in cells})
        if len(cells) != len(measures) * len(bands):
            errors.append({"kind": "incomplete_measure_staff_grid", "page": page.get("image_page")})
        valid_indices = set(indices)
        if any(cell.get("visual_staff_index") not in valid_indices for cell in cells):
            errors.append({"kind": "unknown_staff_cell", "page": page.get("image_page")})
    return {
        "valid": not errors,
        "path": str(path),
        "pages": len(data.get("pages", [])),
        "staff_regions": total_bands,
        "measure_staff_cells": total_cells,
        "errors": errors,
    }
