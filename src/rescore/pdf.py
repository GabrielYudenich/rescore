from __future__ import annotations

import math
from pathlib import Path

from .pages import parse_page_spec


def pdf_info(pdf_path: Path) -> dict:
    import fitz

    with fitz.open(pdf_path) as document:
        return {
            "path": str(pdf_path.resolve()),
            "pages": document.page_count,
            "metadata": document.metadata,
        }


def render_pages(
    pdf_path: Path,
    page_spec: str,
    output_dir: Path,
    dpi: int = 300,
    max_pixels: int | None = None,
) -> list[Path]:
    import fitz

    pages = parse_page_spec(page_spec)
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    with fitz.open(pdf_path) as document:
        invalid = [page for page in pages if page > document.page_count]
        if invalid:
            raise ValueError(f"página fora do PDF ({document.page_count} páginas): {invalid[0]}")
        effective_dpi = dpi
        if max_pixels is not None:
            if max_pixels < 1:
                raise ValueError("max_pixels deve ser positivo")
            largest_area = max(
                document[page_number - 1].rect.width
                * document[page_number - 1].rect.height
                * (dpi / 72) ** 2
                for page_number in pages
            )
            if largest_area > max_pixels:
                effective_dpi = max(1, math.floor(dpi * math.sqrt(max_pixels / largest_area)))
        for page_number in pages:
            page = document[page_number - 1]
            pixmap = page.get_pixmap(dpi=effective_dpi, alpha=False)
            output = output_dir / f"page-{page_number:04d}.png"
            pixmap.save(output)
            rendered.append(output)
    return rendered


def images_to_tiff(images: list[Path], output: Path, dpi: int) -> Path:
    """Join rendered pages without downsampling for multi-page OMR."""
    from PIL import Image

    if not images:
        raise ValueError("nenhuma imagem para montar o TIFF")
    output.parent.mkdir(parents=True, exist_ok=True)
    opened = [Image.open(path).convert("L") for path in images]
    try:
        opened[0].save(
            output,
            save_all=True,
            append_images=opened[1:],
            compression="tiff_deflate",
            dpi=(dpi, dpi),
        )
    finally:
        for image in opened:
            image.close()
    return output
