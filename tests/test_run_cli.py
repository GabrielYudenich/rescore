from __future__ import annotations

from pathlib import Path

import run


def test_accepts_requested_file_and_misspelled_movement_detection_syntax() -> None:
    args = run._parser().parse_args(["--file", "arquivo.pdf", "--detect-moviments", "true"])

    assert args.file == Path("arquivo.pdf")
    assert args.detect_movements is True


def test_accepts_pages_without_requiring_a_fixed_meter() -> None:
    args = run._parser().parse_args(["--file", "arquivo.pdf", "--pages", "40-50"])

    assert args.pages == "40-50"
    assert args.meter is None
    assert args.detect_movements is False


def test_accepts_fix_ok_and_legacy_pdf_alias() -> None:
    args = run._parser().parse_args(["--pdf", "arquivo.pdf", "--fix", "OK"])

    assert args.file == Path("arquivo.pdf")
    assert args.fix == "ok"
