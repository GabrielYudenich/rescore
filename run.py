from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rescore.movements import SINFONIA10_MOVEMENTS, detect_score_movements  # noqa: E402
from rescore.musicxml import parse_musicxml  # noqa: E402
from rescore.pages import compact_page_spec, parse_page_spec  # noqa: E402
from rescore.pdf import pdf_info  # noqa: E402
from rescore.pipeline import (  # noqa: E402
    assemble_choros9_continuous,
    assemble_movement1_complete,
    assemble_movement1_pages_7_12,
    assemble_scherzo_67_69,
    assemble_scherzo_complete,
    convert,
    convert_with_musescore,
    extract_omr_candidate,
)
from rescore.project_fix import apply_project_fixes  # noqa: E402
from rescore.projects import create_review_project, promote_project_run  # noqa: E402
from rescore.tooling import find_musescore  # noqa: E402

DEFAULT_PDF = PROJECT_ROOT / "HVL_Sinfonia-n10-Sume-Pater-Patrium_partitura©ABM.pdf"
SCHERZO_XML = PROJECT_ROOT / "III. Scherzo (descompactado).musicxml"
SCHERZO_MSCZ = PROJECT_ROOT / "III. Scherzo.mscz"
SINFONIA10_MOVEMENT_MAP = {
    item["number"]: {
        "pages": (item["start_page"], item["end_page"]),
        "name": f"Sinfonia 10 - {item['title']}",
    }
    for item in SINFONIA10_MOVEMENTS
}


def _boolean(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "sim", "on"}:
        return True
    if normalized in {"0", "false", "no", "não", "nao", "off"}:
        return False
    raise argparse.ArgumentTypeError("use true/false, sim/não ou 1/0")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analisa páginas da partitura e gera MusicXML, MSCZ, PDF e relatórios."
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--pages", help="páginas, por exemplo: 7-8, 67-69 ou 70,72")
    selection.add_argument(
        "--movement",
        type=int,
        choices=tuple(SINFONIA10_MOVEMENT_MAP),
        help="movimento completo da Sinfonia 10 nesta edição (1, 2, 3 ou 4)",
    )
    parser.add_argument(
        "--file",
        "--pdf",
        dest="file",
        type=Path,
        default=DEFAULT_PDF,
        help="arquivo PDF de entrada; --pdf continua aceito por compatibilidade",
    )
    parser.add_argument(
        "--detect-movements",
        "--detect-moviments",
        dest="detect_movements",
        type=_boolean,
        default=False,
        metavar="true|false",
        help="detecta e processa movimentos separadamente; aceita a grafia moviments",
    )
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
    parser.add_argument(
        "--reference-mscz",
        type=Path,
        help=(
            "referência manual do MuseScore; no perfil choros9 somente os "
            "três primeiros compassos são considerados"
        ),
    )
    parser.add_argument("--force", action="store_true", help="refaz o OMR já armazenado")
    parser.add_argument(
        "--promote",
        action="store_true",
        help="organiza e publica o movimento validado em projects/<movimento>/partitura.*",
    )
    parser.add_argument(
        "--project-name",
        help="nome do projeto ao promover um intervalo que não possui perfil conhecido",
    )
    parser.add_argument(
        "--fix",
        type=str.casefold,
        choices=("ok",),
        help="revalida os partitura.mscz corrigidos associados ao PDF (--fix ok)",
    )
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
    reference_musicxml: Path | None = None,
    reference_mscz: Path | None = None,
) -> dict:
    """Recover pages independently, then publish one continuous review score."""
    output.mkdir(parents=True, exist_ok=True)
    successes = []
    failures = []
    for page in pages:
        page_output = output / f"page-{page:04d}"
        # The opening remains in 4/4 through PDF page 7. Later pages are not
        # locked until a printed change or a user-supplied meter is confirmed.
        page_meter = meter or ("4/4" if 3 <= page <= 7 else None)
        print(f"Choros Nº 9: analisando página {page} em {dpi} dpi...")
        if page_meter and not meter:
            print(f"  fórmula inicial confirmada: {page_meter}")
        try:
            page_manifest = convert(
                PROJECT_ROOT,
                pdf,
                str(page),
                page_output,
                reference=reference_musicxml if page == 3 else None,
                reference_mscz=reference_mscz if page == 3 else None,
                force=force,
                omr_dpi=dpi,
                meter=page_meter,
                scan_profile=True,
            )
        except Exception as exc:
            failures.append({"page": page, "error": str(exc), "output": str(page_output.resolve())})
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
            part["name"].strip().casefold() in {"", "voice"} for part in score["parts"]
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
                    "tuplet_events": sum(bool(event.get("tuplet")) for event in score["events"]),
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
            "pages_with_warnings": sum(bool(item["quality"]["warnings"]) for item in successes),
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
    can_assemble = (
        reference_mscz is not None
        and reference_mscz.is_file()
        and pages == list(range(3, pages[-1] + 1))
        and len(pages) > 1
        and not failures
        and [item["page"] for item in successes] == pages
    )
    if can_assemble:
        print("Choros Nº 9: montando uma partitura contínua e o PDF A3...")
        try:
            continuous = assemble_choros9_continuous(
                PROJECT_ROOT,
                Path(successes[0]["musicxml"]),
                [Path(item["musicxml"]) for item in successes[1:]],
                reference_mscz,
                output / "continuous",
            )
        except Exception as exc:
            batch["continuous_error"] = str(exc)
            print(f"  montagem contínua marcada para revisão: {exc}")
        else:
            continuous_artifacts = continuous["artifacts"]
            batch["continuous"] = continuous
            batch["summary"]["continuous_score"] = True
            batch["artifacts"].update(
                {
                    "normalized_musicxml": continuous_artifacts["normalized_musicxml"],
                    "normalized_musescore": continuous_artifacts["normalized_musescore"],
                    "normalized_pdf": continuous_artifacts["normalized_pdf"],
                    "normalized_previews": continuous_artifacts["normalized_previews"],
                    "playability_report": continuous_artifacts["playability_report"],
                }
            )
    else:
        batch["summary"]["continuous_score"] = False
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


def _convert_unlocked_pages(
    pdf: Path,
    page_spec: str,
    output: Path,
    *,
    force: bool,
    dpi: int,
) -> dict:
    """Run generic OMR without inventing one fixed meter for the whole interval."""
    manifest = convert(
        PROJECT_ROOT,
        pdf,
        page_spec,
        output,
        force=force,
        omr_dpi=dpi,
    )
    musescore = find_musescore(PROJECT_ROOT)
    if musescore is None:
        raise FileNotFoundError("MuseScore não encontrado; execute `rescore doctor`")
    candidate_pdf = output / "candidate.pdf"
    convert_with_musescore(
        musescore,
        Path(manifest["artifacts"]["musescore"]),
        candidate_pdf,
        output / "musescore-candidate-pdf.log",
    )
    manifest["artifacts"]["score_pdf"] = str(candidate_pdf.resolve())
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def _run_detected_movements(args: argparse.Namespace, pdf: Path) -> int:
    detection = detect_score_movements(pdf)
    print(json.dumps(detection, ensure_ascii=False, indent=2))
    if not detection["detected"]:
        raise ValueError(detection["warnings"][0])
    if args.meter:
        raise ValueError(
            "--meter não pode travar uma obra inteira detectada; use --pages para um "
            "trecho cuja fórmula seja constante e confirmada"
        )
    statuses = []
    for movement in detection["movements"]:
        child = ["--file", str(pdf), "--detect-movements", "false"]
        if detection["method"] == "verified-profile-sinfonia10":
            child.extend(["--movement", str(movement["number"])])
        else:
            child.extend(
                [
                    "--pages",
                    f"{movement['start_page']}-{movement['end_page']}",
                    "--project-name",
                    movement["project_name"],
                ]
            )
        if args.output:
            child.extend(["--output", str(args.output / f"movement-{movement['number']:02d}")])
        if args.dpi:
            child.extend(["--dpi", str(args.dpi)])
        if args.profile != "auto":
            child.extend(["--profile", args.profile])
        if args.reference_mscz:
            child.extend(["--reference-mscz", str(args.reference_mscz)])
        if args.force:
            child.append("--force")
        if args.promote:
            child.append("--promote")
        print(
            f"\nProcessando {movement['title']}: "
            f"páginas {movement['start_page']}-{movement['end_page']}"
        )
        statuses.append(main(child))
    return 1 if any(status != 0 for status in statuses) else 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        pdf = args.file.resolve()
        if not pdf.is_file():
            raise FileNotFoundError(f"PDF não encontrado: {pdf}")
        choros9 = _is_choros9(pdf, args.profile)
        if args.fix:
            if args.pages or args.movement or args.detect_movements:
                raise ValueError("--fix ok não pode ser combinado com páginas ou movimentos")
            result = apply_project_fixes(PROJECT_ROOT, pdf)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.detect_movements:
            if args.pages or args.movement:
                raise ValueError(
                    "--detect-movements true não pode ser combinado com --pages ou --movement"
                )
            return _run_detected_movements(args, pdf)
        if args.promote and args.movement is None and not args.project_name:
            raise ValueError(
                "ao promover páginas avulsas, informe --project-name para definir o destino"
            )
        if args.movement is not None and args.meter:
            raise ValueError(
                "--meter não pode travar um movimento inteiro; as mudanças devem vir da fonte"
            )
        whole_file = args.pages is None and args.movement is None
        if args.movement is not None:
            movement = SINFONIA10_MOVEMENT_MAP[args.movement]
            page_text = f"{movement['pages'][0]}-{movement['pages'][1]}"
            print(
                f"{movement['name']}: páginas PDF {page_text}; "
                "as fórmulas serão preservadas da fonte."
            )
        elif whole_file:
            whole_detection = detect_score_movements(pdf)
            first_page = (
                min(item["start_page"] for item in whole_detection["movements"])
                if whole_detection["detected"]
                else 1
            )
            page_text = f"{first_page}-{pdf_info(pdf)['pages']}"
            print(f"Detecção de movimentos desativada: processando o PDF inteiro ({page_text}).")
        else:
            page_text = args.pages
        pages = parse_page_spec(page_text)
        page_spec = compact_page_spec(pages)
        dpi = args.dpi or (300 if choros9 else 450)

        if choros9:
            if pages[0] < 3:
                raise ValueError("a partitura do Choros Nº 9 começa na página 3")
            output = (
                args.output or PROJECT_ROOT / "output" / f"choros9-pages-{page_spec}"
            ).resolve()
            reference_mscz = args.reference_mscz
            if reference_mscz is None:
                automatic_reference = PROJECT_ROOT / "Choros 9.mscz"
                reference_mscz = automatic_reference if automatic_reference.is_file() else None
            reference_musicxml = None
            if reference_mscz is not None and 3 in pages:
                reference_mscz = reference_mscz.resolve()
                if not reference_mscz.is_file():
                    raise FileNotFoundError(
                        f"referência MuseScore não encontrada: {reference_mscz}"
                    )
                reference_folder = output / "reference"
                reference_folder.mkdir(parents=True, exist_ok=True)
                reference_musicxml = reference_folder / "choros9-reference.musicxml"
                musescore = find_musescore(PROJECT_ROOT)
                if musescore is None:
                    raise FileNotFoundError("MuseScore não encontrado; execute `rescore doctor`")
                convert_with_musescore(
                    musescore,
                    reference_mscz,
                    reference_musicxml,
                    reference_folder / "export.log",
                )
                print(
                    "Referência manual: usando somente os compassos 1–3; "
                    "o compasso 4 será ignorado."
                )
            manifest = _convert_choros9_pages(
                pdf,
                pages,
                output,
                dpi=dpi,
                force=args.force,
                meter=args.meter,
                reference_musicxml=reference_musicxml,
                reference_mscz=reference_mscz,
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
                    PROJECT_ROOT / "output" / "movement1-omr-pages" / f"page-{page:04d}",
                    force=args.force,
                    omr_dpi=dpi,
                )
            output = (args.output or PROJECT_ROOT / "output" / "movement1-complete").resolve()
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
                args.output or PROJECT_ROOT / "output" / f"movement1-pages-7-{pages[-1]}"
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
                    PROJECT_ROOT / "output" / "scherzo-omr-pages" / f"page-{page:04d}",
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
        elif args.movement in {2, 4} or whole_file:
            output = (
                args.output
                or PROJECT_ROOT
                / "output"
                / (f"movement{args.movement}-complete" if args.movement else f"complete-{pdf.stem}")
            ).resolve()
            manifest = _convert_unlocked_pages(
                pdf,
                page_spec,
                output,
                force=args.force,
                dpi=dpi,
            )
        else:
            output = (args.output or PROJECT_ROOT / "output" / f"pages-{page_spec}").resolve()
            if args.meter:
                meter = _meter_for(pages, args.meter)
                manifest = convert(
                    PROJECT_ROOT,
                    pdf,
                    page_spec,
                    output,
                    force=args.force,
                    omr_dpi=dpi,
                    meter=meter,
                )
            else:
                manifest = _convert_unlocked_pages(
                    pdf,
                    page_spec,
                    output,
                    force=args.force,
                    dpi=dpi,
                )

        artifacts = manifest["artifacts"]
        print("\nConcluído.")
        musescore_artifact = (
            artifacts.get("normalized_musescore")
            or artifacts.get("musescore")
            or artifacts.get("editable_musescore")
        )
        print(f"MuseScore: {musescore_artifact}")
        score_pdf_artifact = artifacts.get("normalized_pdf") or artifacts.get("score_pdf")
        if score_pdf_artifact:
            print(f"PDF:       {score_pdf_artifact}")
        if manifest.get("summary"):
            print(
                "Páginas editáveis/revisão: "
                f"{manifest['summary']['editable_pages']}/"
                f"{manifest['summary']['review_required']}"
            )
        if args.promote:
            score_artifact = artifacts.get("normalized_musicxml") or artifacts.get("musicxml")
            musescore_artifact = artifacts.get("normalized_musescore") or artifacts.get("musescore")
            pdf_artifact = artifacts.get("normalized_pdf") or artifacts.get("score_pdf")
            if not score_artifact:
                raise ValueError("a geração não produziu MusicXML para organizar")
            project = create_review_project(
                PROJECT_ROOT,
                name=(
                    SINFONIA10_MOVEMENT_MAP[args.movement]["name"]
                    if args.movement
                    else args.project_name
                ),
                score=Path(score_artifact),
                output_root=PROJECT_ROOT / "projects",
                musescore_score=Path(musescore_artifact) if musescore_artifact else None,
                score_pdf=Path(pdf_artifact) if pdf_artifact else None,
                source_pdf=pdf,
                pages=page_spec,
                artifacts_dir=output,
            )
            promotion = promote_project_run(
                Path(project["project"]),
                run=Path(project["run"]),
            )
            manifest["project"] = {"review": project, "promotion": promotion}
            (output / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"Projeto:   {promotion['project']}")
            print(f"Atual:     {promotion['index']}")
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
