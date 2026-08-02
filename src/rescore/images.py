from __future__ import annotations

import math
from pathlib import Path


def normalize_score_orientation(path: Path) -> dict[str, object]:
    """Rotate pages whose long staff lines are predominantly vertical."""
    import cv2
    import numpy as np

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"não foi possível abrir a imagem: {path}")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = min(1.0, 1200 / max(gray.shape))
    detection = (
        cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if scale < 1
        else gray
    )
    ink = ((detection < 190).astype(np.uint8) * 255)
    horizontal = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(15, detection.shape[1] // 25), 1)
        ),
    )
    vertical = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (1, max(15, detection.shape[0] // 25))
        ),
    )
    horizontal_score = float((horizontal > 0).mean())
    vertical_score = float((vertical > 0).mean())
    rotation = 0
    if vertical_score > horizontal_score * 1.35 and vertical_score > 0.004:
        clockwise = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        counterclockwise = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)

        def left_bias(candidate: np.ndarray) -> float:
            candidate_gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY)
            height, width = candidate_gray.shape
            band = max(1, width // 5)
            margin = max(1, height // 30)
            body = candidate_gray[margin : height - margin]
            return float((body[:, :band] < 190).mean() - (body[:, -band:] < 190).mean())

        if left_bias(clockwise) >= left_bias(counterclockwise):
            image, rotation = clockwise, 90
        else:
            image, rotation = counterclockwise, -90
        if not cv2.imwrite(str(path), image, [cv2.IMWRITE_PNG_COMPRESSION, 6]):
            raise RuntimeError(f"não foi possível gravar imagem orientada: {path}")
    return {
        "rotation_degrees": rotation,
        "horizontal_line_density": round(horizontal_score, 6),
        "vertical_line_density": round(vertical_score, 6),
    }


def prepare_omr_image(
    source: Path,
    output: Path,
    *,
    max_pixels: int = 48_000_000,
) -> dict[str, object]:
    """Normalize a raster image to a bounded, orientation-correct PNG for OMR."""
    from PIL import Image, ImageOps

    if max_pixels < 1:
        raise ValueError("max_pixels deve ser positivo")
    if not source.is_file():
        raise FileNotFoundError(f"imagem não encontrada: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        original_size = image.size
        original_pixels = image.width * image.height
        resized = original_pixels > max_pixels
        if resized:
            scale = math.sqrt(max_pixels / original_pixels)
            size = (
                max(1, math.floor(image.width * scale)),
                max(1, math.floor(image.height * scale)),
            )
            image = image.resize(size, Image.Resampling.LANCZOS)
        if image.mode not in {"L", "RGB"}:
            image = image.convert("RGB")
        image.save(output, format="PNG", optimize=True)
        final_size = image.size
    orientation = normalize_score_orientation(output)
    if orientation["rotation_degrees"]:
        with Image.open(output) as oriented:
            final_size = oriented.size
    return {
        "source": str(source.resolve()),
        "output": str(output.resolve()),
        "original_size": list(original_size),
        "size": list(final_size),
        "pixels": final_size[0] * final_size[1],
        "resized": resized,
        "orientation": orientation,
    }
