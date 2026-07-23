from __future__ import annotations

from pathlib import Path


CHOROS9_AUDIVERIS_CONSTANTS = {
    # Old orchestral editions leave wide gaps between instrument families.
    # Audiveris' defaults (2 interlines / 35% white) split one orchestral page
    # into several unrelated systems. These values allow an already detected
    # barline to connect the full page; they do not create note symbols.
    "org.audiveris.omr.sheet.grid.PeakGraph.maxConnectionGap": "12.0",
    "org.audiveris.omr.sheet.grid.PeakGraph.maxConnectionWhiteRatio": "1.0",
    "org.audiveris.omr.sheet.grid.PeakGraph.maxFirstConnectionXOffset": "10.0",
    # Uneven inking makes the same printed bar wider on some staves (where it
    # touches a stem or ledger line). Keep those peaks in one structural bar.
    "org.audiveris.omr.sheet.grid.PeakGraph.maxAlignmentDeltaWidth": "3.0",
    "org.audiveris.omr.sheet.grid.PeakGraph.maxAlignmentSlope": "0.15",
    "org.audiveris.omr.sheet.grid.BarsRetriever.maxColumnDx": "3.0",
}


def suppress_cross_staff_annotations(source: Path, output: Path) -> dict:
    """Remove only oversized handwritten wedges crossing several staves.

    A printed hairpin stays within one staff gap. Conductor annotations in the
    Choros scan can be hundreds of pixels long and open across two or more
    staves. Detection therefore requires two continuous diagonal strokes with
    opposite slopes, a common apex and an opening wider than six interlines.
    Horizontal printed material is restored after erasing the strokes so staff
    lines, ties and other long musical symbols remain available to OMR.
    """
    import cv2
    import math
    import numpy as np

    gray = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError(f"não foi possível abrir a imagem: {source}")
    foreground = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)[1]
    horizontal_kernel = max(48, int(round(gray.shape[1] * 0.027)))
    horizontal = cv2.morphologyEx(
        foreground,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_kernel, 1)),
    )

    horizontal_weight = (horizontal > 0).sum(axis=1)
    rows = np.where(horizontal_weight > gray.shape[1] * 0.25)[0]
    row_runs: list[list[int]] = []
    for row in rows:
        if not row_runs or row > row_runs[-1][-1] + 1:
            row_runs.append([int(row)])
        else:
            row_runs[-1].append(int(row))
    row_centers = [sum(run) // len(run) for run in row_runs]
    center_differences = [
        right - left
        for left, right in zip(row_centers, row_centers[1:])
        if 5 <= right - left <= 30
    ]
    if not center_differences:
        output.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(output), gray):
            raise ValueError(f"não foi possível gravar a imagem: {output}")
        return {
            "source": str(source.resolve()),
            "output": str(output.resolve()),
            "interline": None,
            "annotations_detected": 0,
            "annotations": [],
            "pixels_removed": 0,
            "reason": "espaçamento das pautas não detectado com segurança",
        }
    interline = float(np.median(center_differences))

    nonhorizontal = cv2.subtract(foreground, horizontal)
    closing_size = max(3, int(round(interline * 0.55)))
    if closing_size % 2 == 0:
        closing_size += 1
    joined = cv2.morphologyEx(
        nonhorizontal,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (closing_size, closing_size)
        ),
    )
    lines = cv2.HoughLinesP(
        joined,
        1,
        math.pi / 720,
        threshold=max(30, int(round(interline * 3))),
        minLineLength=max(40, int(round(interline * 6))),
        maxLineGap=max(20, int(round(interline * 8))),
    )
    support_radius = max(2, int(round(interline * 0.2)))
    supported_ink = cv2.dilate(
        nonhorizontal,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (support_radius * 2 + 1, support_radius * 2 + 1),
        ),
    )

    segments: list[dict] = []
    for raw_line in lines[:, 0] if lines is not None else []:
        x1, y1, x2, y2 = (int(value) for value in raw_line)
        if x2 < x1:
            x1, y1, x2, y2 = x2, y2, x1, y1
        dx = x2 - x1
        dy = y2 - y1
        if dx <= 0:
            continue
        length = math.hypot(dx, dy)
        angle = math.degrees(math.atan2(dy, dx))
        if not (6 <= abs(angle) <= 35 and length >= interline * 6):
            continue
        sample_count = max(2, int(round(length)))
        sample_x = np.linspace(x1, x2, sample_count).astype(int)
        sample_y = np.linspace(y1, y2, sample_count).astype(int)
        support = float((supported_ink[sample_y, sample_x] > 0).mean())
        if support < 0.55:
            continue
        segments.append(
            {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "angle": angle,
                "length": length,
                "support": support,
            }
        )

    long_segments = [
        segment
        for segment in segments
        if segment["x2"] - segment["x1"] >= interline * 15
        and abs(segment["y2"] - segment["y1"]) >= interline * 5
    ]
    positive = [segment for segment in long_segments if segment["angle"] > 0]
    negative = [segment for segment in long_segments if segment["angle"] < 0]
    wedge_pairs: list[tuple[dict, dict, float]] = []
    for upper in positive:
        for lower in negative:
            apex_distance = math.hypot(
                upper["x2"] - lower["x2"], upper["y2"] - lower["y2"]
            )
            if apex_distance > interline * 4:
                continue
            overlap_left = max(upper["x1"], lower["x1"])
            overlap_right = min(upper["x2"], lower["x2"])
            if overlap_right - overlap_left < interline * 15:
                continue

            def projected_y(segment: dict, x: float) -> float:
                proportion = (x - segment["x1"]) / (
                    segment["x2"] - segment["x1"]
                )
                return segment["y1"] + proportion * (
                    segment["y2"] - segment["y1"]
                )

            opening = abs(
                projected_y(upper, overlap_left)
                - projected_y(lower, overlap_left)
            )
            if opening >= interline * 6:
                wedge_pairs.append((upper, lower, opening))

    # Hough returns several nearly identical edges for one stroke. Keep one
    # wedge per apex, preferring the pair with the widest detected opening.
    pair_clusters: list[list[tuple[dict, dict, float]]] = []
    for pair in wedge_pairs:
        apex_x = (pair[0]["x2"] + pair[1]["x2"]) / 2
        apex_y = (pair[0]["y2"] + pair[1]["y2"]) / 2
        cluster = next(
            (
                existing
                for existing in pair_clusters
                if math.hypot(
                    apex_x
                    - (
                        existing[0][0]["x2"]
                        + existing[0][1]["x2"]
                    )
                    / 2,
                    apex_y
                    - (
                        existing[0][0]["y2"]
                        + existing[0][1]["y2"]
                    )
                    / 2,
                )
                <= interline * 8
            ),
            None,
        )
        if cluster is None:
            pair_clusters.append([pair])
        else:
            cluster.append(pair)
    selected_pairs = [
        max(
            cluster,
            key=lambda item: (
                (item[0]["x2"] + item[1]["x2"]) / 2,
                min(item[0]["length"], item[1]["length"]),
            ),
        )
        for cluster in pair_clusters
    ]
    deduplicated_pairs: list[tuple[dict, dict, float]] = []
    for pair in sorted(
        selected_pairs,
        key=lambda item: (item[0]["x2"] + item[1]["x2"]) / 2,
        reverse=True,
    ):
        apex_y = (pair[0]["y2"] + pair[1]["y2"]) / 2
        pair_left = min(pair[0]["x1"], pair[1]["x1"])
        pair_right = max(pair[0]["x2"], pair[1]["x2"])
        if any(
            abs(
                apex_y - (existing[0]["y2"] + existing[1]["y2"]) / 2
            )
            <= interline * 8
            and min(
                pair_right,
                max(existing[0]["x2"], existing[1]["x2"]),
            )
            - max(
                pair_left,
                min(existing[0]["x1"], existing[1]["x1"]),
            )
            >= interline * 15
            for existing in deduplicated_pairs
        ):
            continue
        deduplicated_pairs.append(pair)
    selected_pairs = deduplicated_pairs

    erase_mask = np.zeros_like(gray)
    annotations = []
    for upper, lower, opening in selected_pairs:
        related: list[dict] = []

        def distance_to_side(candidate: dict, side: dict) -> float:
            midpoint_x = (candidate["x1"] + candidate["x2"]) / 2
            midpoint_y = (candidate["y1"] + candidate["y2"]) / 2
            side_y = side["y1"] + (
                (midpoint_x - side["x1"])
                / (side["x2"] - side["x1"])
                * (side["y2"] - side["y1"])
            )
            return abs(midpoint_y - side_y)

        for candidate in segments:
            matching_side = upper if candidate["angle"] > 0 else lower
            if abs(candidate["angle"] - matching_side["angle"]) > 14:
                continue
            if candidate["x2"] < matching_side["x1"] - interline * 16:
                continue
            if candidate["x1"] > matching_side["x2"] + interline * 4:
                continue
            if distance_to_side(candidate, matching_side) <= interline * 3:
                related.append(candidate)
        if upper not in related:
            related.append(upper)
        if lower not in related:
            related.append(lower)

        # Hough follows one edge of a thick pencil stroke. Cover both edges
        # and the centerline while still remaining narrower than two spaces.
        line_thickness = max(7, int(round(interline * 1.4)))
        for segment in related:
            cv2.line(
                erase_mask,
                (segment["x1"], segment["y1"]),
                (segment["x2"], segment["y2"]),
                255,
                line_thickness,
            )
        all_x = [
            segment[key]
            for segment in related
            for key in ("x1", "x2")
        ]
        all_y = [
            segment[key]
            for segment in related
            for key in ("y1", "y2")
        ]
        annotations.append(
            {
                "type": "cross-staff-conductor-wedge",
                "bbox": {
                    "left": min(all_x),
                    "top": min(all_y),
                    "right": max(all_x),
                    "bottom": max(all_y),
                },
                "apex": {
                    "x": int(round((upper["x2"] + lower["x2"]) / 2)),
                    "y": int(round((upper["y2"] + lower["y2"]) / 2)),
                },
                "opening_interlines": round(opening / interline, 2),
                "upper_support": round(upper["support"], 4),
                "lower_support": round(lower["support"], 4),
                "segments_removed": len(related),
            }
        )

    if annotations:
        mask_closing = max(5, int(round(interline * 2)))
        if mask_closing % 2 == 0:
            mask_closing += 1
        erase_mask = cv2.morphologyEx(
            erase_mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (mask_closing, mask_closing)
            ),
        )
    repaired = gray.copy()
    repaired[erase_mask > 0] = 255
    protected_horizontal = np.zeros_like(horizontal)
    restore_radius = max(1, int(round(interline * 0.12)))
    for center in row_centers:
        top = max(0, center - restore_radius)
        bottom = min(gray.shape[0], center + restore_radius + 1)
        protected_horizontal[top:bottom] = horizontal[top:bottom]
    repaired[protected_horizontal > 0] = gray[protected_horizontal > 0]
    pixels_removed = int(
        np.count_nonzero((erase_mask > 0) & (foreground > 0) & (horizontal == 0))
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), repaired):
        raise ValueError(f"não foi possível gravar a imagem: {output}")
    return {
        "source": str(source.resolve()),
        "output": str(output.resolve()),
        "interline": interline,
        "annotations_detected": len(annotations),
        "annotations": annotations,
        "pixels_removed": pixels_removed,
        "rule": (
            "somente cunhas diagonais contínuas com ápice comum e abertura "
            "maior que seis espaços de pauta"
        ),
    }


def reinforce_orchestral_barlines(source: Path, output: Path) -> dict:
    """Reconnect barlines already visible across separated instrument families.

    Candidate x positions come from long vertical components in the scan. The
    function never estimates bar positions from rhythmic content and refuses
    to modify a page unless at least two strong, well-separated columns exist.
    """
    import cv2
    import numpy as np

    gray = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError(f"não foi possível abrir a imagem: {source}")
    foreground = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)[1]

    horizontal = cv2.morphologyEx(
        foreground,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (200, 1)),
    )
    horizontal_weight = (horizontal > 0).sum(axis=1)
    staff_rows = np.where(horizontal_weight > max(500, gray.shape[1] // 3))[0]
    if not len(staff_rows):
        raise ValueError("não foi possível localizar a região das pautas")
    top = int(staff_rows.min())
    bottom = int(staff_rows.max())
    score_height = bottom - top + 1

    vertical = cv2.morphologyEx(
        foreground,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (2, 50)),
    )
    vertical_weight = (vertical[top : bottom + 1] > 0).sum(axis=0)
    candidate_columns = np.where(vertical_weight > max(250, int(score_height * 0.15)))[0]
    runs: list[list[int]] = []
    for column in candidate_columns:
        if not runs or column > runs[-1][-1] + 2:
            runs.append([int(column)])
        else:
            runs[-1].append(int(column))
    peaks = [
        max(run, key=lambda column: int(vertical_weight[column]))
        for run in runs
        if run
    ]
    if peaks:
        strongest = int(max(vertical_weight[column] for column in peaks))
        peaks = [
            column
            for column in peaks
            if vertical_weight[column] >= strongest * 0.25
            and gray.shape[1] * 0.05 < column < gray.shape[1] * 0.97
        ]

    # Braces and start barlines may produce two close peaks. Retain only the
    # strongest candidate in a 30-pixel neighborhood.
    selected: list[int] = []
    for column in sorted(peaks):
        if selected and column - selected[-1] <= 30:
            if vertical_weight[column] > vertical_weight[selected[-1]]:
                selected[-1] = column
        else:
            selected.append(column)
    if len(selected) < 2:
        raise ValueError(
            f"somente {len(selected)} barra(s) estrutural(is) foram detectadas com segurança"
        )

    repaired = gray.copy()
    # Match the printed rule thickness. A very thin bridge looks correct to a
    # person but is rejected by Audiveris as a different vertical filament.
    # At the Choros default of 300 dpi this evaluates to about five pixels.
    thickness = max(3, int(round(score_height / 650)))
    for column in selected:
        cv2.line(repaired, (column, top), (column, bottom), 0, thickness)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), repaired):
        raise ValueError(f"não foi possível gravar a imagem: {output}")
    return {
        "source": str(source.resolve()),
        "output": str(output.resolve()),
        "staff_region": {"top": top, "bottom": bottom},
        "barline_columns": selected,
        "barlines_reinforced": len(selected),
        "line_thickness": thickness,
    }


def split_orchestral_measure_images(
    source: Path, report: dict, output_dir: Path
) -> list[Path]:
    """Create small OMR sheets containing one printed measure each.

    The first-page instrument labels, clefs and time signature are retained on
    every image. This is a fallback for exceptionally dense pages where the
    full-page stem graph overwhelms Audiveris. It uses only bar positions that
    were already detected from long printed vertical components.
    """
    import cv2
    import numpy as np

    gray = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError(f"não foi possível abrir a imagem: {source}")
    bars = [int(value) for value in report.get("barline_columns", [])]
    if len(bars) < 2:
        raise ValueError("são necessárias ao menos duas barras para recortar compassos")

    height, width = gray.shape
    thickness = int(report.get("line_thickness", 3))
    # Enough room for the initial clef and meter, but stop before the first
    # noteheads on the opening page. The proportional floor also scales at
    # other render resolutions.
    header_right = min(width, bars[0] + max(80, int(round(width * 0.035))))
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    for index, (left_bar, right_bar) in enumerate(zip(bars, bars[1:]), 1):
        if index == 1:
            image = gray[:, : min(width, right_bar + thickness + 3)].copy()
        else:
            header = gray[:, :header_right]
            body_left = min(width, left_bar + max(1, thickness // 2))
            body = gray[:, body_left : min(width, right_bar + thickness + 3)]
            if not body.size:
                raise ValueError(f"recorte vazio no compasso local {index}")
            # A tiny white seam prevents the old internal bar from fusing with
            # the copied opening bar while preserving continuous staff lines.
            seam = np.full((height, 3), 255, dtype=np.uint8)
            image = np.hstack((header, seam, body))
        path = output_dir / f"measure-{index:03d}.png"
        if not cv2.imwrite(str(path), image):
            raise ValueError(f"não foi possível gravar a imagem: {path}")
        results.append(path)
    return results


def rescale_scan_image(source: Path, output: Path, factor: float) -> Path:
    """Rescale a difficult measure for an alternate OMR pass."""
    import cv2

    if factor <= 0:
        raise ValueError("o fator de escala deve ser positivo")
    gray = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError(f"não foi possível abrir a imagem: {source}")
    interpolation = cv2.INTER_CUBIC if factor > 1 else cv2.INTER_AREA
    resized = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=interpolation)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), resized):
        raise ValueError(f"não foi possível gravar a imagem: {output}")
    return output
