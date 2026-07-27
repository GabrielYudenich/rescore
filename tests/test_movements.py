from __future__ import annotations

from pathlib import Path

import fitz

from rescore.movements import detect_score_movements


def _write_pdf(path: Path, pages: int, headings: dict[int, str] | None = None) -> None:
    headings = headings or {}
    document = fitz.open()
    for page_number in range(1, pages + 1):
        page = document.new_page(width=600, height=800)
        heading = headings.get(page_number)
        if heading:
            page.insert_textbox(
                fitz.Rect(200, 40, 400, 110),
                heading,
                fontsize=28,
                align=fitz.TEXT_ALIGN_CENTER,
            )
    document.save(path)
    document.close()


def test_detects_verified_sinfonia10_profile(tmp_path: Path) -> None:
    source = tmp_path / "HVL_Sinfonia-n10_partitura.pdf"
    _write_pdf(source, 200)

    result = detect_score_movements(source)

    assert result["detected"] is True
    assert result["method"] == "verified-profile-sinfonia10"
    assert [(item["start_page"], item["end_page"]) for item in result["movements"]] == [
        (7, 41),
        (42, 66),
        (67, 99),
        (100, 200),
    ]


def test_detects_sequential_centered_roman_headings(tmp_path: Path) -> None:
    source = tmp_path / "digital-score.pdf"
    _write_pdf(source, 6, {2: "I.", 4: "II."})

    result = detect_score_movements(source)

    assert result["detected"] is True
    assert result["method"] == "embedded-text-roman-headings"
    assert [(item["start_page"], item["end_page"]) for item in result["movements"]] == [
        (2, 3),
        (4, 6),
    ]


def test_refuses_to_invent_movements_without_evidence(tmp_path: Path) -> None:
    source = tmp_path / "unknown-score.pdf"
    _write_pdf(source, 3)

    result = detect_score_movements(source)

    assert result["detected"] is False
    assert result["movements"] == []
    assert "--pages" in result["warnings"][0]
