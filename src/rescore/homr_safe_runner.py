"""Run homr with a guard for degenerate handwritten staff crops."""

from __future__ import annotations

import numpy as np
from homr import staff_parsing
from homr.main import main

_original_center_image_on_canvas = staff_parsing.center_image_on_canvas


def _safe_center_image_on_canvas(
    image: np.ndarray,
    canvas_size: np.ndarray,
    margin_top: int = 0,
    margin_bottom: int = 0,
) -> np.ndarray:
    safe_size = np.maximum(np.asarray(canvas_size, dtype=int), 1)
    return _original_center_image_on_canvas(
        image,
        safe_size,
        margin_top=margin_top,
        margin_bottom=margin_bottom,
    )


staff_parsing.center_image_on_canvas = _safe_center_image_on_canvas


if __name__ == "__main__":
    main()
