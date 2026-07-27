"""Conservative movement discovery for PDF scores."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import fitz

ROMAN_NUMERALS = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "VII": 7,
    "VIII": 8,
}
NUMBER_TO_ROMAN = {number: roman for roman, number in ROMAN_NUMERALS.items()}

SINFONIA10_MOVEMENTS = (
    {"number": 1, "title": "Primeiro Movimento", "start_page": 7, "end_page": 41},
    {"number": 2, "title": "Segundo Movimento", "start_page": 42, "end_page": 66},
    {"number": 3, "title": "Terceiro Movimento", "start_page": 67, "end_page": 99},
    {"number": 4, "title": "Quarto Movimento", "start_page": 100, "end_page": 200},
)


def _normalized_name(path: Path) -> str:
    value = unicodedata.normalize("NFKD", path.stem.casefold())
    return value.encode("ascii", "ignore").decode("ascii")


def _is_sinfonia10(path: Path, page_count: int) -> bool:
    name = re.sub(r"[^a-z0-9]+", "", _normalized_name(path))
    return page_count == 200 and "sinfonia" in name and ("n10" in name or "no10" in name)


def _is_choros9(path: Path, page_count: int) -> bool:
    name = re.sub(r"[^a-z0-9]+", "", _normalized_name(path))
    return page_count >= 3 and "choros" in name and ("n9" in name or "no9" in name)


def _large_centered_roman_heading(page: fitz.Page) -> tuple[int, str] | None:
    page_dict = page.get_text("dict")
    candidates: list[tuple[float, float, str]] = []
    for block in page_dict.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip().upper().rstrip(".")
                if text not in ROMAN_NUMERALS:
                    continue
                x0, y0, x1, _y1 = span.get("bbox", (0, 0, 0, 0))
                center = (x0 + x1) / 2
                page_center = page.rect.width / 2
                if y0 > page.rect.height * 0.3:
                    continue
                if abs(center - page_center) > page.rect.width * 0.25:
                    continue
                candidates.append((float(span.get("size", 0)), y0, text))
    if not candidates:
        return None
    _size, _y, roman = max(candidates)
    return ROMAN_NUMERALS[roman], roman


def _text_movements(document: fitz.Document) -> list[dict[str, Any]]:
    headings: list[tuple[int, int, str]] = []
    for index, page in enumerate(document):
        heading = _large_centered_roman_heading(page)
        if heading:
            number, roman = heading
            headings.append((index + 1, number, roman))
    headings = list(dict.fromkeys(headings))
    if len(headings) < 2 or headings[0][1] != 1:
        return []
    if [number for _page, number, _roman in headings] != list(range(1, len(headings) + 1)):
        return []
    movements = []
    for index, (start_page, number, roman) in enumerate(headings):
        end_page = headings[index + 1][0] - 1 if index + 1 < len(headings) else document.page_count
        movements.append(
            {
                "number": number,
                "roman": roman,
                "title": f"Movimento {roman}",
                "start_page": start_page,
                "end_page": end_page,
            }
        )
    return movements


def detect_score_movements(pdf_path: Path) -> dict[str, Any]:
    """Detect only movement boundaries supported by strong profile or text evidence."""
    pdf_path = pdf_path.resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    with fitz.open(pdf_path) as document:
        page_count = document.page_count
        if _is_sinfonia10(pdf_path, page_count):
            movements = [dict(item) for item in SINFONIA10_MOVEMENTS]
            for movement in movements:
                movement["roman"] = NUMBER_TO_ROMAN[movement["number"]]
                movement["project_name"] = f"Sinfonia 10 - {movement['title']}"
            return {
                "detected": True,
                "method": "verified-profile-sinfonia10",
                "confidence": 1.0,
                "pages": page_count,
                "movements": movements,
                "warnings": [],
            }
        if _is_choros9(pdf_path, page_count):
            return {
                "detected": True,
                "method": "verified-continuous-profile-choros9",
                "confidence": 1.0,
                "pages": page_count,
                "movements": [
                    {
                        "number": 1,
                        "roman": "I",
                        "title": "Obra completa",
                        "project_name": "Choros 9 - Obra completa",
                        "start_page": 3,
                        "end_page": page_count,
                    }
                ],
                "warnings": ["A obra é contínua; o perfil ignora as duas páginas iniciais."],
            }
        movements = _text_movements(document)
    if movements:
        for movement in movements:
            movement["project_name"] = f"{pdf_path.stem} - {movement['title']}"
        return {
            "detected": True,
            "method": "embedded-text-roman-headings",
            "confidence": 0.9,
            "pages": page_count,
            "movements": movements,
            "warnings": [],
        }
    return {
        "detected": False,
        "method": "no-confident-boundaries",
        "confidence": 0.0,
        "pages": page_count,
        "movements": [],
        "warnings": [
            "Nenhum limite de movimento foi reconhecido com segurança. "
            "Use --pages ou --detect-movements false para processar o arquivo inteiro."
        ],
    }
