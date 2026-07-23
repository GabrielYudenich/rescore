from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rescore.pages import compact_page_spec, parse_page_spec  # noqa: E402
from rescore.musicxml import parse_musicxml  # noqa: E402
from rescore.pipeline import (  # noqa: E402
    assemble_movement1_complete,
    assemble_movement1_pages_7_12,
    assemble_scherzo_complete,
    assemble_scherzo_67_69,
    convert,
    convert_with_musescore,
    extract_omr_candidate,
)
from rescore.tooling import find_musescore  # noqa: E402


DEFAULT_PDF = PROJECT_ROOT / "HVL_Sinfonia-n10-Sume-Pater-Patrium_partitura©ABM.pdf"
SCHERZO_XML = PROJECT_ROOT / "III. Scherzo (descompactado).musicxml"
SCHERZO_MSCZ = PROJECT_ROOT / "III. Scherzo.mscz"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analisa páginas da partitura e gera MusicXML, MSCZ, PDF e relatórios."
    )
    parser.add_argument("--pages", help="páginas, por exemplo: 7-8, 67-69 ou 70,72")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--meter", help="fórmula fixa para páginas genéricas, como 4/4 ou 9/8")
    parser.add_argument(
        "--dpi",
        type=int,
        help="resolução do OMR; padrão 450 para PDF digital e 300 para o Choros Nº 9",
    )
    parser.add_argument(
        "--profile",
        choices=("auto", "sinfonia10", "choros9"),
        default="auto",
        help="perfil da partitura; 'auto' reconhece pelo nome do PDF",
    )
    parser.add_argument("--force", action="store_true", help="refaz o OMR já armazenado")
    return parser


def _is_choros9(pdf: Path, profile: str) -> bool:
    if profile != "auto":
        return profile == "choros9"
    normalized = pdf.name.casefold().replace("º", "").replace("°", "")
    return "choros" in normalized and "n9" in normalized.replace(" ", "")


def _convert_choros9_pages(
    pdf: Path,
    pages: list[int],
    output: Path,
    *,
    dpi: int,
    force: bool,
    meter: str | None,
) -> dict:
    """Process scanned pages independently so one difficult page cannot abort a batch."""
    output.mkdir(parents=True, exist_ok=True)
    successes = []
    failures = []
    for page in pages:
        page_output = output / f"page-{page:04d}"
        page_meter = meter or ("4/4" if page == 3 else None)
        print(f"Choros Nº 9: analisando página {page} em {dpi} dpi...")
        if page_meter and not meter:
            print(f"  fórmula inicial confirmada: {page_meter}")
        try:
            page_manifest = convert(
                PROJECT_ROOT,
                pdf,
                str(page),
                page_output,
                force=force,
                omr_dpi=dpi,
                meter=page_meter,
                scan_profile=True,
            )
        except Exception as exc:
            failures.append(
                {"page": page, "error": str(exc), "output": str(page_output.resolve())}
            )
            print(f"  página {page} marcada para revisão: {exc}")
            continue
        artifacts = page_manifest["artifacts"]
        preview_pdf = artifacts.get("normalized_pdf")
        if not preview_pdf and artifacts.get("musescore"):
            preview_path = page_output / "candidate.pdf"
            convert_with_musescore(
                find_musescore(PROJECT_ROOT),
                Path(artifacts["musescore"]),
                preview_path,
                page_output / "musescore-candidate-pdf.log",
            )
            preview_pdf = str(preview_path.resolve())
        resolved_musicxml = artifacts.get("normalized_musicxml") or artifacts["musicxml"]
        score = parse_musicxml(Path(resolved_musicxml), include_rests=True)
        pitched_events = sum(bool(event.get("pitch")) for event in score["events"])
        generic_names = sum(
            part["name"].strip().casefold() in {"", "voice"}
            for part in score["parts"]
        )
        warnings = []
        if not score["time_signatures"]:
            warnings.append("fórmula de compasso precisa ser herdada/confirmada")
        if generic_names:
            warnings.append(
                f"{generic_names} abreviações instrumentais não foram lidas com segurança"
            )
        if pitched_events == 0:
            warnings.append("nenhuma nota foi reconhecida")
        successes.append(
            {
                "page": page,
                "musicxml": resolved_musicxml,
                "musescore": artifacts.get("normalized_musescore") or artifacts.get("musescore"),
                "pdf": preview_pdf,
                "manifest": str((page_output / "manifest.json").resolve()),
                "quality": {
                    "parts": score["parts_count"],
                    "measures": score["measures"],
                    "pitched_events": pitched_events,
                    "tuplet_events": sum(
                        bool(event.get("tuplet")) for event in score["events"]
                    ),
                    "detected_time_signatures": score["time_signatures"],
                    "warnings": warnings,
                },
            }
        )
    batch = {
        "input": {
            "pdf": str(pdf.resolve()),
            "pages": pages,
            "profile": "choros9-scanned",
            "omr_dpi": dpi,
            "meter": meter,
            "known_initial_meter": "4/4",
        },
        "summary": {
            "requested_pages": len(pages),
            "editable_pages": len(successes),
            "review_required": len(failures),
            "pages_with_warnings": sum(
                bool(item["quality"]["warnings"]) for item in successes
            ),
        },
        "successes": successes,
        "failures": failures,
        "artifacts": {
            "editable_musescore": [item["musescore"] for item in successes],
            "musicxml": [item["musicxml"] for item in successes],
            "normalized_musescore": successes[0]["musescore"] if len(successes) == 1 else None,
            "normalized_pdf": successes[0]["pdf"] if len(successes) == 1 else None,
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return batch


def _find_candidate(folder: Path) -> Path | None:
    candidates = sorted((folder / "audiveris").rglob("*.mxl"))
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def _meter_for(pages: list[int], supplied: str | None) -> str:
    if supplied:
        meter = supplied.strip()
    else:
        if pages == [7, 8]:
            default = "4/4"
        elif pages == [109]:
            default = "2/4"
        else:
            default = ""
        if default:
            meter = default
            print(f"Fórmula conhecida para estas páginas: {meter}")
        else:
            meter = input("Fórmula de compasso (ex.: 4/4 ou 9/8): ").strip()
    try:
        beats, beat_type = (int(value) for value in meter.split("/", 1))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("fórmula inválida; use o formato 4/4 ou 9/8") from exc
    if beats < 1 or beat_type not in {1, 2, 4, 8, 16, 32, 64}:
        raise ValueError("fórmula inválida; use o formato 4/4 ou 9/8")
    return f"{beats}/{beat_type}"


def _ensure_scherzo_candidate(
    pdf: Path,
    page_spec: str,
    work_dir: Path,
    force: bool,
    dpi: int,
    meter: str | None = None,
) -> Path:
    candidate = None if force else _find_candidate(work_dir)
    if candidate:
        print(f"Reutilizando OMR: {candidate}")
        return candidate
    kwargs: dict = {"force": force, "omr_dpi": dpi}
    if page_spec == "67-68":
        kwargs.update(reference=SCHERZO_XML, reference_mscz=SCHERZO_MSCZ)
    else:
        kwargs["meter"] = meter
    manifest = convert(PROJECT_ROOT, pdf, page_spec, work_dir, **kwargs)
    return Path(manifest["artifacts"]["musicxml"])


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        page_text = args.pages or input("Quais páginas deseja analisar? (ex.: 67-69): ").strip()
        pages = parse_page_spec(page_text)
        page_spec = compact_page_spec(pages)
        pdf = args.pdf.resolve()
        if not pdf.is_file():
            raise FileNotFoundError(f"PDF não encontrado: {pdf}")
        choros9 = _is_choros9(pdf, args.profile)
        dpi = args.dpi or (300 if choros9 else 450)

        if choros9:
            if pages[0] < 3:
                raise ValueError("a partitura do Choros Nº 9 começa na página 3")
            output = (
                args.output or PROJECT_ROOT / "output" / f"choros9-pages-{page_spec}"
            ).resolve()
            manifest = _convert_choros9_pages(
                pdf,
                pages,
                output,
                dpi=dpi,
                force=args.force,
                meter=args.meter,
            )
        elif pages == list(range(7, 42)):
            base_output = PROJECT_ROOT / "output" / "movement1-pages-7-13"
            base_musicxml = base_output / "normalized.musicxml"
            if args.force or not base_musicxml.is_file():
                candidate_7_8 = extract_omr_candidate(
                    PROJECT_ROOT,
                    pdf,
                    "7-8",
                    PROJECT_ROOT / "output" / "review-pages-7-8",
                    force=args.force,
                    omr_dpi=dpi,
                )
                candidate_9_12 = extract_omr_candidate(
                    PROJECT_ROOT,
                    pdf,
                    "9-12",
                    PROJECT_ROOT / "output" / "movement1-omr-9-12",
                    force=args.force,
                    omr_dpi=dpi,
                )
                candidate_13 = extract_omr_candidate(
                    PROJECT_ROOT,
                    pdf,
                    "13",
                    PROJECT_ROOT / "output" / "movement1-omr-13",
                    force=args.force,
                    omr_dpi=dpi,
                )
                assemble_movement1_pages_7_12(
                    PROJECT_ROOT,
                    candidate_7_8,
                    candidate_9_12,
                    base_output,
                    candidate_13,
                )
            page_candidates = {}
            for page in range(14, 42):
                page_candidates[page] = extract_omr_candidate(
                    PROJECT_ROOT,
                    pdf,
                    str(page),
                    PROJECT_ROOT
                    / "output"
                    / "movement1-omr-pages"
                    / f"page-{page:04d}",
                    force=args.force,
                    omr_dpi=dpi,
                )
            output = (
                args.output or PROJECT_ROOT / "output" / "movement1-complete"
            ).resolve()
            manifest = assemble_movement1_complete(
                PROJECT_ROOT,
                base_musicxml,
                page_candidates,
                output,
            )
        elif pages in (list(range(7, 13)), list(range(7, 14))):
            candidate_7_8 = extract_omr_candidate(
                PROJECT_ROOT,
                pdf,
                "7-8",
                PROJECT_ROOT / "output" / "review-pages-7-8",
                force=args.force,
                omr_dpi=dpi,
            )
            candidate_9_12 = extract_omr_candidate(
                PROJECT_ROOT,
                pdf,
                "9-12",
                PROJECT_ROOT / "output" / "movement1-omr-9-12",
                force=args.force,
                omr_dpi=dpi,
            )
            candidate_13 = None
            if pages[-1] == 13:
                candidate_13 = extract_omr_candidate(
                    PROJECT_ROOT,
                    pdf,
                    "13",
                    PROJECT_ROOT / "output" / "movement1-omr-13",
                    force=args.force,
                    omr_dpi=dpi,
                )
            output = (
                args.output
                or PROJECT_ROOT / "output" / f"movement1-pages-7-{pages[-1]}"
            ).resolve()
            manifest = assemble_movement1_pages_7_12(
                PROJECT_ROOT,
                candidate_7_8,
                candidate_9_12,
                output,
                candidate_13,
            )
        elif pages == list(range(67, 100)):
            if not SCHERZO_XML.is_file() or not SCHERZO_MSCZ.is_file():
                raise FileNotFoundError("os gabaritos III. Scherzo.musicxml/.mscz são necessários")
            base_output = PROJECT_ROOT / "output" / "review-pages-67-69"
            base_musicxml = base_output / "normalized.musicxml"
            base_mscz = base_output / "normalized.mscz"
            if args.force or not base_musicxml.is_file() or not base_mscz.is_file():
                candidate_67_68 = _ensure_scherzo_candidate(
                    pdf,
                    "67-68",
                    PROJECT_ROOT / "output" / "review-pages-67-68",
                    args.force,
                    dpi,
                )
                candidate_69 = _ensure_scherzo_candidate(
                    pdf,
                    "69",
                    PROJECT_ROOT / "output" / "page-69-omr",
                    args.force,
                    dpi,
                    "9/8",
                )
                assemble_scherzo_67_69(
                    PROJECT_ROOT,
                    candidate_67_68,
                    candidate_69,
                    SCHERZO_XML,
                    SCHERZO_MSCZ,
                    base_output,
                )
            page_candidates = {}
            for page in range(70, 100):
                page_candidates[page] = extract_omr_candidate(
                    PROJECT_ROOT,
                    pdf,
                    str(page),
                    PROJECT_ROOT
                    / "output"
                    / "scherzo-omr-pages"
                    / f"page-{page:04d}",
                    force=args.force,
                    omr_dpi=dpi,
                )
            output = (args.output or PROJECT_ROOT / "output" / "scherzo-complete").resolve()
            manifest = assemble_scherzo_complete(
                PROJECT_ROOT,
                base_musicxml,
                base_mscz,
                page_candidates,
                output,
            )
        elif pages == [67, 68, 69]:
            if not SCHERZO_XML.is_file() or not SCHERZO_MSCZ.is_file():
                raise FileNotFoundError("os gabaritos III. Scherzo.musicxml/.mscz são necessários")
            candidate_67_68 = _ensure_scherzo_candidate(
                pdf,
                "67-68",
                PROJECT_ROOT / "output" / "review-pages-67-68",
                args.force,
                dpi,
            )
            candidate_69 = _ensure_scherzo_candidate(
                pdf,
                "69",
                PROJECT_ROOT / "output" / "page-69-omr",
                args.force,
                dpi,
                "9/8",
            )
            output = (args.output or PROJECT_ROOT / "output" / "review-pages-67-69").resolve()
            manifest = assemble_scherzo_67_69(
                PROJECT_ROOT,
                candidate_67_68,
                candidate_69,
                SCHERZO_XML,
                SCHERZO_MSCZ,
                output,
            )
        elif pages == [67, 68]:
            output = (args.output or PROJECT_ROOT / "output" / "review-pages-67-68").resolve()
            manifest = convert(
                PROJECT_ROOT,
                pdf,
                page_spec,
                output,
                SCHERZO_XML,
                args.force,
                SCHERZO_MSCZ,
                dpi,
            )
        else:
            meter = _meter_for(pages, args.meter)
            output = (args.output or PROJECT_ROOT / "output" / f"pages-{page_spec}").resolve()
            manifest = convert(
                PROJECT_ROOT,
                pdf,
                page_spec,
                output,
                force=args.force,
                omr_dpi=dpi,
                meter=meter,
            )

        artifacts = manifest["artifacts"]
        print("\nConcluído.")
        musescore_artifact = (
            artifacts.get("normalized_musescore")
            or artifacts.get("musescore")
            or artifacts.get("editable_musescore")
        )
        print(f"MuseScore: {musescore_artifact}")
        if artifacts.get("normalized_pdf"):
            print(f"PDF:       {artifacts.get('normalized_pdf')}")
        if manifest.get("summary"):
            print(
                "Páginas editáveis/revisão: "
                f"{manifest['summary']['editable_pages']}/"
                f"{manifest['summary']['review_required']}"
            )
        print(f"Relatório: {output / 'manifest.json'}")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nOperação cancelada.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
