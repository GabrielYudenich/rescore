from __future__ import annotations

import math
from pathlib import Path


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
    return {
        "source": str(source.resolve()),
        "output": str(output.resolve()),
        "original_size": list(original_size),
        "size": list(final_size),
        "pixels": final_size[0] * final_size[1],
        "resized": resized,
    }
