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
            if vertical_weight[column] >= strongest * 0.35
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
