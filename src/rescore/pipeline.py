from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .mscz import (
    extract_score_style,
    graft_reference_measures,
    normalize_fixed_meter_padding,
    normalize_mscz_voice_durations,
    normalize_meter_map_padding,
    remove_leading_empty_vboxes,
    replace_score_style,
    set_automatic_beaming,
    sha256,
    validate_fixed_meter_mscz,
    validate_meter_map_mscz,
    validate_scherzo_mscz,
)
from .musicxml import compare_scores, parse_musicxml, write_canonical
from .choros9 import (
    analyze_doublings,
    audit_measure_structure,
    merge_measure_candidates,
)
from .normalize import (
    MOVEMENT1_METER_CHANGES,
    SCHERZO_METER_CHANGES,
    build_choros9_reference_musicxml,
    build_meter_locked_musicxml,
    build_movement1_block_7_12,
    build_movement1_complete,
    build_normalized_musicxml,
    build_scherzo_complete,
)
from .pages import parse_page_spec
from .pdf import images_to_tiff, pdf_info, render_pages
from .scan import (
    CHOROS9_AUDIVERIS_CONSTANTS,
    reinforce_orchestral_barlines,
    rescale_scan_image,
    split_orchestral_measure_images,
)
from .tooling import find_audiveris, find_musescore


def _run_logged(command: list[str], log_path: Path, cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "COMMAND\n" + subprocess.list2cmdline(command) + "\n\nSTDOUT\n" + result.stdout
        + "\n\nSTDERR\n" + result.stderr,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"comando falhou com código {result.returncode}; consulte {log_path}"
        )
    return result


def run_audiveris(
    audiveris: Path,
    input_path: Path,
    pages: list[int],
    output_dir: Path,
    log_path: Path,
    force: bool = False,
    constants: dict[str, str] | None = None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(output_dir.rglob("*.mxl"))
    if existing and not force:
        return existing
    command = [
        str(audiveris),
        "-batch",
        "-constant",
        "org.audiveris.omr.step.LoadStep.maxPixelCount=50000000",
    ]
    for key, value in sorted((constants or {}).items()):
        command.extend(["-constant", f"{key}={value}"])
    command.extend([
        "-transcribe",
        "-export",
        "-save",
        "-swap",
        "-output",
        str(output_dir.resolve()),
        "-sheets",
        *[str(page) for page in pages],
        "--",
        str(input_path.resolve()),
    ])
    _run_logged(command, log_path, input_path.parent)
    return sorted(output_dir.rglob("*.mxl"))


def _run_scan_aware_audiveris(
    audiveris: Path,
    omr_input: Path,
    omr_pages: list[int],
    output_dir: Path,
    log_path: Path,
    *,
    force: bool,
    scan_profile: bool,
    rendered: list[Path],
    scan_reports: list[dict],
) -> list[Path]:
    """Run a full sheet first, then isolate real measures if a dense scan fails."""
    cached_fallback = output_dir.parent / "audiveris-measures" / "merged.musicxml"
    if scan_profile and cached_fallback.is_file() and not force:
        return [cached_fallback]
    primary_error: Exception | None = None
    try:
        candidates = run_audiveris(
            audiveris,
            omr_input,
            omr_pages,
            output_dir,
            log_path,
            force=force,
            constants=CHOROS9_AUDIVERIS_CONSTANTS if scan_profile else None,
        )
    except RuntimeError as exc:
        primary_error = exc
        candidates = []
    if candidates or not scan_profile or len(rendered) != 1 or not scan_reports:
        if primary_error and not candidates:
            raise primary_error
        return candidates

    fallback_root = output_dir.parent / "audiveris-measures"
    crops = split_orchestral_measure_images(
        rendered[0], scan_reports[0], fallback_root / "images"
    )
    chosen: list[Path] = []
    attempts: list[dict] = []
    for crop in crops:
        result: list[Path] = []
        for label, factor in (("native", 1.0), ("upscaled", 7 / 6), ("downscaled", 5 / 6)):
            image = crop
            if factor != 1.0:
                image = rescale_scan_image(
                    crop,
                    fallback_root / "images" / label / crop.name,
                    factor,
                )
            attempt_dir = fallback_root / crop.stem / label
            try:
                result = run_audiveris(
                    audiveris,
                    image,
                    [1],
                    attempt_dir,
                    fallback_root / f"{crop.stem}-{label}.log",
                    force=force,
                    constants=CHOROS9_AUDIVERIS_CONSTANTS,
                )
                error = None
            except RuntimeError as exc:
                result = []
                error = str(exc)
            attempts.append(
                {
                    "measure": crop.stem,
                    "variant": label,
                    "image": str(image.resolve()),
                    "success": bool(result),
                    "error": error,
                }
            )
            if result:
                chosen.append(max(result, key=lambda item: item.stat().st_mtime))
                break
        if not result:
            raise RuntimeError(
                f"o fallback isolado não reconheceu {crop.stem}; consulte {fallback_root}"
            )
    merged = fallback_root / "merged.musicxml"
    merge_summary = merge_measure_candidates(chosen, merged)
    (fallback_root / "fallback-report.json").write_text(
        json.dumps(
            {
                "reason": str(primary_error) if primary_error else "nenhum MXL na página completa",
                "attempts": attempts,
                "merge": merge_summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return [merged]


def _render_omr_pages(
    pdf_path: Path,
    page_spec: str,
    output_dir: Path,
    dpi: int,
    scan_profile: bool,
) -> tuple[list[Path], list[dict]]:
    if not scan_profile:
        return render_pages(pdf_path, page_spec, output_dir / "pages", dpi=dpi), []
    raw_pages = render_pages(pdf_path, page_spec, output_dir / "pages-raw", dpi=dpi)
    processed = []
    reports = []
    for raw_page in raw_pages:
        destination = output_dir / "pages" / raw_page.name
        reports.append(reinforce_orchestral_barlines(raw_page, destination))
        processed.append(destination)
    report_path = output_dir / "scan-preprocess.json"
    report_path.write_text(
        json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return processed, reports


def extract_omr_candidate(
    project_root: Path,
    pdf_path: Path,
    page_spec: str,
    output_dir: Path,
    *,
    force: bool = False,
    omr_dpi: int = 450,
    scan_profile: bool = False,
) -> Path:
    """Render a page block and return its raw, reusable Audiveris MusicXML."""
    pages = parse_page_spec(page_spec)
    audiveris = find_audiveris(project_root)
    if not audiveris:
        raise FileNotFoundError("Audiveris não encontrado; execute `rescore doctor`")
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered, scan_reports = _render_omr_pages(
        pdf_path, page_spec, output_dir, omr_dpi, scan_profile
    )
    if len(pages) == 1:
        omr_input = rendered[0]
        omr_pages = [1]
    else:
        omr_input = images_to_tiff(
            rendered, output_dir / "pages" / "omr-input.tiff", omr_dpi
        )
        omr_pages = list(range(1, len(pages) + 1))
    candidates = _run_scan_aware_audiveris(
        audiveris,
        omr_input,
        omr_pages,
        output_dir / "audiveris",
        output_dir / "audiveris.log",
        force=force,
        scan_profile=scan_profile,
        rendered=rendered,
        scan_reports=scan_reports,
    )
    if not candidates:
        raise RuntimeError("Audiveris terminou sem produzir arquivo .mxl")
    return max(candidates, key=lambda item: item.stat().st_mtime)


def convert_with_musescore(
    musescore: Path,
    source: Path,
    destination: Path,
    log_path: Path,
    style: Path | None = None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [str(musescore), "-f"]
    if style:
        command.extend(["-S", str(style.resolve())])
    command.extend(["-o", str(destination.resolve()), str(source.resolve())])
    _run_logged(
        command,
        log_path,
        source.parent,
    )
    if not destination.is_file():
        raise RuntimeError(f"MuseScore não criou {destination}")


def convert(
    project_root: Path,
    pdf_path: Path,
    page_spec: str,
    output_dir: Path,
    reference: Path | None = None,
    force: bool = False,
    reference_mscz: Path | None = None,
    omr_dpi: int = 450,
    meter: str | None = None,
    scan_profile: bool = False,
) -> dict:
    pages = parse_page_spec(page_spec)
    audiveris = find_audiveris(project_root)
    musescore = find_musescore(project_root)
    if not audiveris:
        raise FileNotFoundError("Audiveris não encontrado; execute `rescore doctor`")
    if not musescore:
        raise FileNotFoundError("MuseScore não encontrado; execute `rescore doctor`")

    output_dir.mkdir(parents=True, exist_ok=True)
    rendered, scan_preprocessing = _render_omr_pages(
        pdf_path, page_spec, output_dir, omr_dpi, scan_profile
    )
    if len(pages) == 1:
        omr_input = rendered[0]
        omr_pages = [1]
    else:
        omr_input = images_to_tiff(rendered, output_dir / "pages" / "omr-input.tiff", omr_dpi)
        omr_pages = list(range(1, len(pages) + 1))
    candidates = _run_scan_aware_audiveris(
        audiveris,
        omr_input,
        omr_pages,
        output_dir / "audiveris",
        output_dir / "audiveris.log",
        force=force,
        scan_profile=scan_profile,
        rendered=rendered,
        scan_reports=scan_preprocessing,
    )
    if not candidates:
        raise RuntimeError("Audiveris terminou sem produzir arquivo .mxl")
    candidate = max(candidates, key=lambda item: item.stat().st_mtime)
    candidate_mscz = output_dir / "candidate.mscz"
    convert_with_musescore(
        musescore,
        candidate,
        candidate_mscz,
        output_dir / "musescore.log",
    )

    candidate_score = parse_musicxml(candidate)
    canonical_path = output_dir / "candidate.canonical.json"
    write_canonical(candidate_score, canonical_path)
    instrument_map_path = output_dir / "instrument-map.json"
    instrument_map_path.write_text(
        json.dumps(
            {
                "source_pages": pages,
                "rule": "A identificação usa a abreviação/nome reconhecido no início da pauta; a posição vertical não é usada como identidade.",
                "detected_parts": [
                    {"order": index, "id": part["id"], "ocr_name": part["name"]}
                    for index, part in enumerate(candidate_score["parts"], 1)
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    comparison_path = None
    normalized_xml_path = None
    normalized_mscz_path = None
    normalized_pdf_path = None
    normalized_preview_paths: list[Path] = []
    normalized_comparison_path = None
    meter_validation_path = None
    normalization_summary = None
    resolved_instrument_map_path = None
    musescore_validation_path = None
    choros_doublings_path = None
    choros_measure_audit_path = None
    if reference:
        if reference_mscz is None and not scan_profile:
            inferred_reference = project_root / "III. Scherzo.mscz"
            reference_mscz = inferred_reference if inferred_reference.is_file() else None
        style_path = (
            extract_score_style(reference_mscz, output_dir / "reference-style.mss")
            if reference_mscz and not scan_profile
            else None
        )
        reference_score = parse_musicxml(reference)
        normalized_xml_path = output_dir / "normalized.musicxml"
        if scan_profile and pages == [3]:
            normalization_summary = build_choros9_reference_musicxml(
                candidate,
                reference,
                normalized_xml_path,
                verified_measures=3,
            )
            comparison = normalization_summary["reference_calibration"]
        else:
            normalization_summary = build_normalized_musicxml(
                candidate, reference, normalized_xml_path
            )
            comparison = compare_scores(reference_score, candidate_score)
        comparison_path = output_dir / "comparison.json"
        comparison_path.write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        meter_validation_path = output_dir / "meter-validation.json"
        meter_validation_path.write_text(
            json.dumps(normalization_summary["meter_validation"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        normalized_mscz_path = output_dir / "normalized.mscz"
        convert_with_musescore(
            musescore,
            normalized_xml_path,
            normalized_mscz_path,
            output_dir / "musescore-normalized.log",
            style=style_path,
        )
        if style_path:
            replace_score_style(normalized_mscz_path, style_path)
        if scan_profile and pages == [3]:
            removed_cover_frames = remove_leading_empty_vboxes(normalized_mscz_path)
            musescore_validation = validate_fixed_meter_mscz(
                normalized_mscz_path, 4, 4
            )
            musescore_validation["verified_reference_measures"] = 3
            musescore_validation["ignored_reference_measure"] = 4
            musescore_validation["removed_empty_cover_frames"] = removed_cover_frames
            if not musescore_validation["valid"]:
                raise ValueError(
                    "validação do MuseScore falhou: "
                    f"{musescore_validation['violations'][:3]}"
                )
            musescore_validation_path = output_dir / "musescore-validation.json"
            musescore_validation_path.write_text(
                json.dumps(musescore_validation, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        elif reference_mscz:
            graft_reference_measures(reference_mscz, normalized_mscz_path, measure_count=8)
            automatic_beaming = set_automatic_beaming(normalized_mscz_path, start_measure=9)
            musescore_validation = validate_scherzo_mscz(
                reference_mscz, normalized_mscz_path, reference_measures=8
            )
            musescore_validation["automatic_beaming"] = automatic_beaming
            if not musescore_validation["valid"]:
                raise ValueError(
                    f"validação do MuseScore falhou: {musescore_validation['violations'][:3]}"
                )
            musescore_validation_path = output_dir / "musescore-validation.json"
            musescore_validation_path.write_text(
                json.dumps(musescore_validation, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        normalized_pdf_path = output_dir / "normalized.pdf"
        convert_with_musescore(
            musescore,
            normalized_mscz_path,
            normalized_pdf_path,
            output_dir / "musescore-normalized-pdf.log",
        )
        normalized_page_count = pdf_info(normalized_pdf_path)["pages"]
        normalized_preview_paths = render_pages(
            normalized_pdf_path,
            f"1-{normalized_page_count}",
            output_dir / "preview",
            dpi=180,
        )
        normalized_score = parse_musicxml(normalized_xml_path)
        write_canonical(normalized_score, output_dir / "normalized.canonical.json")
        normalized_comparison_path = output_dir / "comparison-normalized.json"
        normalized_comparison_path.write_text(
            json.dumps(compare_scores(reference_score, normalized_score), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    elif meter:
        normalized_xml_path = output_dir / "meter-locked.musicxml"
        normalization_summary = build_meter_locked_musicxml(
            candidate,
            normalized_xml_path,
            meter,
            score_profile=(
                "choros9-opening"
                if scan_profile and pages == [3]
                else "choros9" if scan_profile else None
            ),
        )
        meter_validation_path = output_dir / "meter-validation.json"
        meter_validation_path.write_text(
            json.dumps(normalization_summary["meter_validation"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        normalized_mscz_path = output_dir / "meter-locked.mscz"
        convert_with_musescore(
            musescore,
            normalized_xml_path,
            normalized_mscz_path,
            output_dir / "musescore-meter-locked.log",
        )
        meter_beats, meter_beat_type = (int(value) for value in meter.split("/", 1))
        padding_repairs = normalize_fixed_meter_padding(
            normalized_mscz_path, meter_beats, meter_beat_type
        )
        automatic_beaming = set_automatic_beaming(normalized_mscz_path, start_measure=1)
        musescore_validation = validate_fixed_meter_mscz(
            normalized_mscz_path, meter_beats, meter_beat_type
        )
        musescore_validation["padding_repairs"] = padding_repairs
        musescore_validation["automatic_beaming"] = automatic_beaming
        if not musescore_validation["valid"]:
            raise ValueError(
                f"validação do MuseScore falhou: {musescore_validation['violations'][:3]}"
            )
        musescore_validation_path = output_dir / "musescore-validation.json"
        musescore_validation_path.write_text(
            json.dumps(musescore_validation, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        normalized_pdf_path = output_dir / "meter-locked.pdf"
        convert_with_musescore(
            musescore,
            normalized_mscz_path,
            normalized_pdf_path,
            output_dir / "musescore-meter-locked-pdf.log",
        )
        normalized_page_count = pdf_info(normalized_pdf_path)["pages"]
        normalized_preview_paths = render_pages(
            normalized_pdf_path,
            f"1-{normalized_page_count}",
            output_dir / "preview",
            dpi=180,
        )
        write_canonical(
            parse_musicxml(normalized_xml_path), output_dir / "meter-locked.canonical.json"
        )

    if normalized_xml_path:
        resolved_score = parse_musicxml(normalized_xml_path)
        resolved_instrument_map_path = output_dir / "instrument-map-resolved.json"
        resolved_instrument_map_path.write_text(
            json.dumps(
                {
                    "source_pages": pages,
                    "parts": [
                        {"order": index, "id": part["id"], "name": part["name"]}
                        for index, part in enumerate(resolved_score["parts"], 1)
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if scan_profile and meter:
            audit_score = parse_musicxml(normalized_xml_path, include_rests=True)
            choros_doublings_path = output_dir / "doubling-analysis.json"
            choros_doublings_path.write_text(
                json.dumps(analyze_doublings(audit_score, meter=meter), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            choros_measure_audit_path = output_dir / "measure-audit.json"
            choros_measure_audit_path.write_text(
                json.dumps(audit_measure_structure(audit_score, meter), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "pdf": str(pdf_path.resolve()),
            "sha256": sha256(pdf_path),
            "pdf_info": pdf_info(pdf_path),
            "pages": pages,
            "omr_dpi": omr_dpi,
            "omr_input": str(omr_input.resolve()),
            "reference": str(reference.resolve()) if reference else None,
            "reference_mscz": str(reference_mscz.resolve()) if reference_mscz else None,
            "meter": meter,
            "scan_profile": "choros9" if scan_profile else None,
            "scan_preprocessing": scan_preprocessing,
        },
        "tools": {"audiveris": str(audiveris), "musescore": str(musescore)},
        "artifacts": {
            "rendered_pages": [str(path.resolve()) for path in rendered],
            "scan_preprocess": str((output_dir / "scan-preprocess.json").resolve())
            if scan_profile
            else None,
            "musicxml": str(candidate.resolve()),
            "musescore": str(candidate_mscz.resolve()),
            "canonical": str(canonical_path.resolve()),
            "instrument_map": str(instrument_map_path.resolve()),
            "resolved_instrument_map": str(resolved_instrument_map_path.resolve())
            if resolved_instrument_map_path
            else None,
            "doubling_analysis": str(choros_doublings_path.resolve())
            if choros_doublings_path
            else None,
            "measure_audit": str(choros_measure_audit_path.resolve())
            if choros_measure_audit_path
            else None,
            "comparison": str(comparison_path.resolve()) if comparison_path else None,
            "normalized_musicxml": str(normalized_xml_path.resolve()) if normalized_xml_path else None,
            "normalized_musescore": str(normalized_mscz_path.resolve()) if normalized_mscz_path else None,
            "normalized_pdf": str(normalized_pdf_path.resolve()) if normalized_pdf_path else None,
            "normalized_previews": [str(path.resolve()) for path in normalized_preview_paths],
            "meter_validation": str(meter_validation_path.resolve())
            if meter_validation_path
            else None,
            "musescore_validation": str(musescore_validation_path.resolve())
            if musescore_validation_path
            else None,
            "normalized_comparison": str(normalized_comparison_path.resolve())
            if normalized_comparison_path
            else None,
        },
        "normalization": normalization_summary,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def assemble_scherzo_67_69(
    project_root: Path,
    candidate_67_68: Path,
    candidate_69: Path,
    template_musicxml: Path,
    reference_mscz: Path,
    output_dir: Path,
) -> dict:
    """Assemble the approved page 67, recognized pages 68–69, and strict MSCZ checks."""
    musescore = find_musescore(project_root)
    if not musescore:
        raise FileNotFoundError("MuseScore não encontrado; execute `rescore doctor`")
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_xml = output_dir / "normalized.musicxml"
    summary = build_normalized_musicxml(
        candidate_67_68,
        template_musicxml,
        normalized_xml,
        page69_candidate_path=candidate_69,
    )
    meter_validation_path = output_dir / "meter-validation.json"
    meter_validation_path.write_text(
        json.dumps(summary["meter_validation"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    style = extract_score_style(reference_mscz, output_dir / "reference-style.mss")
    normalized_mscz = output_dir / "normalized.mscz"
    convert_with_musescore(
        musescore,
        normalized_xml,
        normalized_mscz,
        output_dir / "musescore-normalized.log",
        style=style,
    )
    replace_score_style(normalized_mscz, style)
    graft_reference_measures(reference_mscz, normalized_mscz, measure_count=8)
    automatic_beaming = set_automatic_beaming(normalized_mscz, start_measure=9)
    expected_tuplets = [
        (staff_id, 18, "3", "4", "eighth")
        for staff_id in ("30", "31", "32")
        for _ in range(3)
    ]
    musescore_validation = validate_scherzo_mscz(
        reference_mscz,
        normalized_mscz,
        reference_measures=8,
        time_signature_measures=(9, 18),
        expected_additional_tuplets=expected_tuplets,
    )
    musescore_validation["automatic_beaming"] = automatic_beaming
    if not musescore_validation["valid"]:
        raise ValueError(
            f"validação do MuseScore falhou: {musescore_validation['violations'][:3]}"
        )
    musescore_validation_path = output_dir / "musescore-validation.json"
    musescore_validation_path.write_text(
        json.dumps(musescore_validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    normalized_pdf = output_dir / "normalized.pdf"
    convert_with_musescore(
        musescore,
        normalized_mscz,
        normalized_pdf,
        output_dir / "musescore-normalized-pdf.log",
    )
    normalized_midi = output_dir / "normalized.mid"
    convert_with_musescore(
        musescore,
        normalized_mscz,
        normalized_midi,
        output_dir / "musescore-normalized-midi.log",
    )
    page_count = pdf_info(normalized_pdf)["pages"]
    previews = render_pages(
        normalized_pdf, f"1-{page_count}", output_dir / "preview", dpi=180
    )
    normalized_score = parse_musicxml(normalized_xml)
    canonical_path = output_dir / "normalized.canonical.json"
    write_canonical(normalized_score, canonical_path)
    instrument_map = output_dir / "instrument-map-resolved.json"
    instrument_map.write_text(
        json.dumps(
            {
                "source_pages": [67, 68, 69],
                "parts": [
                    {"order": index, "id": part["id"], "name": part["name"]}
                    for index, part in enumerate(normalized_score["parts"], 1)
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "pages": [67, 68, 69],
            "candidate_67_68": str(candidate_67_68.resolve()),
            "candidate_69": str(candidate_69.resolve()),
            "template_musicxml": str(template_musicxml.resolve()),
            "reference_mscz": str(reference_mscz.resolve()),
        },
        "normalization": summary,
        "artifacts": {
            "normalized_musicxml": str(normalized_xml.resolve()),
            "normalized_musescore": str(normalized_mscz.resolve()),
            "normalized_pdf": str(normalized_pdf.resolve()),
            "normalized_midi": str(normalized_midi.resolve()),
            "normalized_previews": [str(path.resolve()) for path in previews],
            "canonical": str(canonical_path.resolve()),
            "instrument_map": str(instrument_map.resolve()),
            "meter_validation": str(meter_validation_path.resolve()),
            "musescore_validation": str(musescore_validation_path.resolve()),
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def assemble_movement1_pages_7_12(
    project_root: Path,
    candidate_7_8: Path,
    candidate_9_12: Path,
    output_dir: Path,
    candidate_13: Path | None = None,
) -> dict:
    """Assemble the first reviewed block of movement I with its exact meter map."""
    musescore = find_musescore(project_root)
    if not musescore:
        raise FileNotFoundError("MuseScore não encontrado; execute `rescore doctor`")
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_xml = output_dir / "normalized.musicxml"
    summary = build_movement1_block_7_12(
        candidate_7_8, candidate_9_12, normalized_xml, candidate_13
    )
    end_measure = summary["measures"]
    source_pages = summary["pages"]
    meter_validation_path = output_dir / "meter-validation.json"
    meter_validation_path.write_text(
        json.dumps(summary["meter_validation"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    normalized_mscz = output_dir / "normalized.mscz"
    convert_with_musescore(
        musescore,
        normalized_xml,
        normalized_mscz,
        output_dir / "musescore-normalized.log",
    )
    meter_changes = {
        measure: meter
        for measure, meter in MOVEMENT1_METER_CHANGES.items()
        if measure <= end_measure
    }
    padding_repairs = normalize_mscz_voice_durations(
        normalized_mscz, meter_changes, end_measure=end_measure
    )
    automatic_beaming = set_automatic_beaming(normalized_mscz, start_measure=1)
    musescore_validation = validate_meter_map_mscz(
        normalized_mscz,
        meter_changes,
        end_measure=end_measure,
    )
    musescore_validation["automatic_beaming"] = automatic_beaming
    musescore_validation["padding_repairs"] = padding_repairs
    if not musescore_validation["valid"]:
        raise ValueError(
            f"validação do MuseScore falhou: {musescore_validation['violations'][:3]}"
        )
    # A second native save is the closest automated equivalent to the user
    # opening the score in MuseScore. Validate that stabilized representation
    # and deliver it, preventing importer repairs from surfacing interactively.
    open_save_check = output_dir / ".normalized-open-save-check.mscz"
    try:
        convert_with_musescore(
            musescore,
            normalized_mscz,
            open_save_check,
            output_dir / "musescore-open-save-check.log",
        )
        open_save_validation = validate_meter_map_mscz(
            open_save_check, meter_changes, end_measure=end_measure
        )
        if not open_save_validation["valid"]:
            raise ValueError(
                "validação após abrir/salvar no MuseScore falhou: "
                f"{open_save_validation['violations'][:3]}"
            )
        open_save_check.replace(normalized_mscz)
    finally:
        if open_save_check.exists():
            open_save_check.unlink()
    musescore_validation = validate_meter_map_mscz(
        normalized_mscz, meter_changes, end_measure=end_measure
    )
    musescore_validation["automatic_beaming"] = automatic_beaming
    musescore_validation["padding_repairs"] = padding_repairs
    musescore_validation["open_save_validation"] = open_save_validation
    musescore_validation_path = output_dir / "musescore-validation.json"
    musescore_validation_path.write_text(
        json.dumps(musescore_validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    normalized_pdf = output_dir / "normalized.pdf"
    convert_with_musescore(
        musescore,
        normalized_mscz,
        normalized_pdf,
        output_dir / "musescore-normalized-pdf.log",
    )
    normalized_midi = output_dir / "normalized.mid"
    convert_with_musescore(
        musescore,
        normalized_mscz,
        normalized_midi,
        output_dir / "musescore-normalized-midi.log",
    )
    page_count = pdf_info(normalized_pdf)["pages"]
    previews = render_pages(
        normalized_pdf, f"1-{page_count}", output_dir / "preview", dpi=180
    )
    normalized_score = parse_musicxml(normalized_xml)
    canonical_path = output_dir / "normalized.canonical.json"
    write_canonical(normalized_score, canonical_path)
    instrument_map = output_dir / "instrument-map-resolved.json"
    instrument_map.write_text(
        json.dumps(
            {
                "source_pages": source_pages,
                "parts": [
                    {"order": index, "id": part["id"], "name": part["name"]}
                    for index, part in enumerate(normalized_score["parts"], 1)
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "pages": source_pages,
            "candidate_7_8": str(candidate_7_8.resolve()),
            "candidate_9_12": str(candidate_9_12.resolve()),
            "candidate_13": str(candidate_13.resolve()) if candidate_13 else None,
        },
        "normalization": summary,
        "artifacts": {
            "normalized_musicxml": str(normalized_xml.resolve()),
            "normalized_musescore": str(normalized_mscz.resolve()),
            "normalized_pdf": str(normalized_pdf.resolve()),
            "normalized_midi": str(normalized_midi.resolve()),
            "normalized_previews": [str(path.resolve()) for path in previews],
            "canonical": str(canonical_path.resolve()),
            "instrument_map": str(instrument_map.resolve()),
            "meter_validation": str(meter_validation_path.resolve()),
            "musescore_validation": str(musescore_validation_path.resolve()),
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def assemble_movement1_complete(
    project_root: Path,
    base_musicxml: Path,
    page_candidates: dict[int, Path],
    output_dir: Path,
) -> dict:
    """Assemble and native-validate all 239 measures of movement I."""
    musescore = find_musescore(project_root)
    if not musescore:
        raise FileNotFoundError("MuseScore não encontrado; execute `rescore doctor`")
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_xml = output_dir / "normalized.musicxml"
    summary = build_movement1_complete(base_musicxml, page_candidates, normalized_xml)
    end_measure = summary["measures"]
    meter_validation_path = output_dir / "meter-validation.json"
    meter_validation_path.write_text(
        json.dumps(summary["meter_validation"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    page_audit_path = output_dir / "page-mapping-audit.json"
    page_audit_path.write_text(
        json.dumps(summary["page_audit"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    normalized_mscz = output_dir / "normalized.mscz"
    convert_with_musescore(
        musescore,
        normalized_xml,
        normalized_mscz,
        output_dir / "musescore-normalized.log",
    )
    meter_changes = {
        measure: meter
        for measure, meter in MOVEMENT1_METER_CHANGES.items()
        if measure <= end_measure
    }
    padding_repairs = normalize_mscz_voice_durations(
        normalized_mscz, meter_changes, end_measure=end_measure
    )
    automatic_beaming = set_automatic_beaming(normalized_mscz, start_measure=1)
    musescore_validation = validate_meter_map_mscz(
        normalized_mscz, meter_changes, end_measure=end_measure
    )
    musescore_validation["automatic_beaming"] = automatic_beaming
    musescore_validation["padding_repairs"] = padding_repairs
    if not musescore_validation["valid"]:
        raise ValueError(
            "validação do movimento completo no MuseScore falhou: "
            f"{musescore_validation['violations'][:3]}"
        )

    open_save_check = output_dir / ".normalized-open-save-check.mscz"
    try:
        convert_with_musescore(
            musescore,
            normalized_mscz,
            open_save_check,
            output_dir / "musescore-open-save-check.log",
        )
        open_save_validation = validate_meter_map_mscz(
            open_save_check, meter_changes, end_measure=end_measure
        )
        if not open_save_validation["valid"]:
            raise ValueError(
                "validação após abrir/salvar o movimento completo falhou: "
                f"{open_save_validation['violations'][:3]}"
            )
        open_save_check.replace(normalized_mscz)
    finally:
        if open_save_check.exists():
            open_save_check.unlink()

    musescore_validation = validate_meter_map_mscz(
        normalized_mscz, meter_changes, end_measure=end_measure
    )
    musescore_validation["automatic_beaming"] = automatic_beaming
    musescore_validation["padding_repairs"] = padding_repairs
    musescore_validation["open_save_validation"] = open_save_validation
    musescore_validation_path = output_dir / "musescore-validation.json"
    musescore_validation_path.write_text(
        json.dumps(musescore_validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    normalized_pdf = output_dir / "normalized.pdf"
    convert_with_musescore(
        musescore,
        normalized_mscz,
        normalized_pdf,
        output_dir / "musescore-normalized-pdf.log",
    )
    normalized_midi = output_dir / "normalized.mid"
    convert_with_musescore(
        musescore,
        normalized_mscz,
        normalized_midi,
        output_dir / "musescore-normalized-midi.log",
    )
    page_count = pdf_info(normalized_pdf)["pages"]
    previews = render_pages(
        normalized_pdf, f"1-{page_count}", output_dir / "preview", dpi=180
    )
    normalized_score = parse_musicxml(normalized_xml)
    canonical_path = output_dir / "normalized.canonical.json"
    write_canonical(normalized_score, canonical_path)
    instrument_map = output_dir / "instrument-map-resolved.json"
    instrument_map.write_text(
        json.dumps(
            {
                "source_pages": list(range(7, 42)),
                "parts": [
                    {"order": index, "id": part["id"], "name": part["name"]}
                    for index, part in enumerate(normalized_score["parts"], 1)
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "pages": list(range(7, 42)),
            "base_musicxml": str(base_musicxml.resolve()),
            "individual_candidates": {
                str(page): str(path.resolve())
                for page, path in sorted(page_candidates.items())
            },
        },
        "normalization": summary,
        "artifacts": {
            "normalized_musicxml": str(normalized_xml.resolve()),
            "normalized_musescore": str(normalized_mscz.resolve()),
            "normalized_pdf": str(normalized_pdf.resolve()),
            "normalized_midi": str(normalized_midi.resolve()),
            "normalized_previews": [str(path.resolve()) for path in previews],
            "canonical": str(canonical_path.resolve()),
            "instrument_map": str(instrument_map.resolve()),
            "page_mapping_audit": str(page_audit_path.resolve()),
            "meter_validation": str(meter_validation_path.resolve()),
            "musescore_validation": str(musescore_validation_path.resolve()),
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def assemble_scherzo_complete(
    project_root: Path,
    base_musicxml: Path,
    base_mscz: Path,
    page_candidates: dict[int, Path],
    output_dir: Path,
) -> dict:
    """Assemble and native-validate all PDF pages 67-99 of III. Scherzo."""
    musescore = find_musescore(project_root)
    if not musescore:
        raise FileNotFoundError("MuseScore não encontrado; execute `rescore doctor`")
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_xml = output_dir / "normalized.musicxml"
    summary = build_scherzo_complete(base_musicxml, page_candidates, normalized_xml)
    end_measure = summary["measures"]
    meter_validation_path = output_dir / "meter-validation.json"
    meter_validation_path.write_text(
        json.dumps(summary["meter_validation"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    page_audit_path = output_dir / "page-mapping-audit.json"
    page_audit_path.write_text(
        json.dumps(summary["page_audit"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    style = extract_score_style(base_mscz, output_dir / "reference-style.mss")
    normalized_mscz = output_dir / "normalized.mscz"
    convert_with_musescore(
        musescore,
        normalized_xml,
        normalized_mscz,
        output_dir / "musescore-normalized.log",
        style=style,
    )
    replace_score_style(normalized_mscz, style)
    validation_meter_map = {
        1: (9, 8),
        **{
            measure: meter
            for measure, meter in SCHERZO_METER_CHANGES.items()
            if measure != 26 and measure <= end_measure
        },
    }
    padding_repairs = normalize_mscz_voice_durations(
        normalized_mscz,
        validation_meter_map,
        end_measure=end_measure,
        start_measure=26,
    )
    automatic_beaming = set_automatic_beaming(normalized_mscz, start_measure=26)
    musescore_validation = validate_meter_map_mscz(
        normalized_mscz,
        validation_meter_map,
        end_measure=end_measure,
        start_measure=26,
    )
    musescore_validation["automatic_beaming"] = automatic_beaming
    musescore_validation["padding_repairs"] = padding_repairs
    if not musescore_validation["valid"]:
        raise ValueError(
            "validação do Scherzo completo no MuseScore falhou: "
            f"{musescore_validation['violations'][:3]}"
        )

    open_save_check = output_dir / ".normalized-open-save-check.mscz"
    try:
        convert_with_musescore(
            musescore,
            normalized_mscz,
            open_save_check,
            output_dir / "musescore-open-save-check.log",
        )
        open_save_validation = validate_meter_map_mscz(
            open_save_check,
            validation_meter_map,
            end_measure=end_measure,
            start_measure=26,
        )
        if not open_save_validation["valid"]:
            raise ValueError(
                "validação após abrir/salvar o Scherzo completo falhou: "
                f"{open_save_validation['violations'][:3]}"
            )
        open_save_check.replace(normalized_mscz)
    finally:
        if open_save_check.exists():
            open_save_check.unlink()

    musescore_validation = validate_meter_map_mscz(
        normalized_mscz,
        validation_meter_map,
        end_measure=end_measure,
        start_measure=26,
    )
    musescore_validation["automatic_beaming"] = automatic_beaming
    musescore_validation["padding_repairs"] = padding_repairs
    musescore_validation["open_save_validation"] = open_save_validation
    musescore_validation_path = output_dir / "musescore-validation.json"
    musescore_validation_path.write_text(
        json.dumps(musescore_validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    normalized_pdf = output_dir / "normalized.pdf"
    convert_with_musescore(
        musescore,
        normalized_mscz,
        normalized_pdf,
        output_dir / "musescore-normalized-pdf.log",
    )
    normalized_midi = output_dir / "normalized.mid"
    convert_with_musescore(
        musescore,
        normalized_mscz,
        normalized_midi,
        output_dir / "musescore-normalized-midi.log",
    )
    page_count = pdf_info(normalized_pdf)["pages"]
    previews = render_pages(
        normalized_pdf, f"1-{page_count}", output_dir / "preview", dpi=180
    )
    normalized_score = parse_musicxml(normalized_xml)
    canonical_path = output_dir / "normalized.canonical.json"
    write_canonical(normalized_score, canonical_path)
    instrument_map = output_dir / "instrument-map-resolved.json"
    instrument_map.write_text(
        json.dumps(
            {
                "source_pages": list(range(67, 100)),
                "parts": [
                    {"order": index, "id": part["id"], "name": part["name"]}
                    for index, part in enumerate(normalized_score["parts"], 1)
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "pages": list(range(67, 100)),
            "base_musicxml": str(base_musicxml.resolve()),
            "base_mscz": str(base_mscz.resolve()),
            "individual_candidates": {
                str(page): str(path.resolve())
                for page, path in sorted(page_candidates.items())
            },
        },
        "normalization": summary,
        "artifacts": {
            "normalized_musicxml": str(normalized_xml.resolve()),
            "normalized_musescore": str(normalized_mscz.resolve()),
            "normalized_pdf": str(normalized_pdf.resolve()),
            "normalized_midi": str(normalized_midi.resolve()),
            "normalized_previews": [str(path.resolve()) for path in previews],
            "canonical": str(canonical_path.resolve()),
            "instrument_map": str(instrument_map.resolve()),
            "page_mapping_audit": str(page_audit_path.resolve()),
            "meter_validation": str(meter_validation_path.resolve()),
            "musescore_validation": str(musescore_validation_path.resolve()),
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
