from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from fractions import Fraction
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_mscz(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        score_names = [name for name in names if name.lower().endswith(".mscx")]
        if len(score_names) != 1:
            raise ValueError(f"esperado um .mscx interno; encontrados: {score_names}")
        score_name = score_names[0]
        root = ET.fromstring(archive.read(score_name))

    score = root.find("Score")
    if score is None:
        raise ValueError("arquivo MuseScore sem elemento Score")
    parts = []
    for part in score.findall("Part"):
        parts.append(
            {
                "id": part.get("id"),
                "name": part.findtext("trackName", ""),
                "long_name": part.findtext("./Instrument/longName", ""),
                "instrument_id": part.findtext("./Instrument/instrumentId", ""),
                "staves": len(part.findall("Staff")),
            }
        )

    score_staves = score.findall("Staff")
    time_signatures: list[dict] = []
    tuplets: list[dict] = []
    measure_counts: list[int] = []
    for staff in score_staves:
        staff_id = staff.get("id")
        measures = staff.findall("Measure")
        measure_counts.append(len(measures))
        for measure_index, measure in enumerate(measures, 1):
            for signature in measure.iter("TimeSig"):
                time_signatures.append(
                    {
                        "staff_id": staff_id,
                        "measure": measure_index,
                        "numerator": signature.findtext("sigN"),
                        "denominator": signature.findtext("sigD"),
                        "stretch_n": signature.findtext("stretchN"),
                        "stretch_d": signature.findtext("stretchD"),
                    }
                )
            for tuplet in measure.iter("Tuplet"):
                tuplets.append(
                    {
                        "staff_id": staff_id,
                        "measure": measure_index,
                        "normal_notes": tuplet.findtext("normalNotes"),
                        "actual_notes": tuplet.findtext("actualNotes"),
                        "base_note": tuplet.findtext("baseNote"),
                    }
                )

    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "archive_entries": names,
        "internal_score": score_name,
        "format_version": root.get("version"),
        "program_version": score.findtext("programVersion") or root.findtext("programVersion"),
        "work_title": score.find("metaTag[@name='workTitle']").text
        if score.find("metaTag[@name='workTitle']") is not None
        else "",
        "parts_count": len(parts),
        "staves_count": len(score_staves),
        "measures": max(measure_counts, default=0),
        "parts": parts,
        "time_signatures": time_signatures,
        "tuplets": tuplets,
    }


def extract_score_style(path: Path, output: Path) -> Path:
    with zipfile.ZipFile(path) as archive:
        style_names = [name for name in archive.namelist() if name.endswith("score_style.mss")]
        if len(style_names) != 1:
            raise ValueError(f"estilo interno não encontrado em {path}")
        data = archive.read(style_names[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return output


def replace_score_style(path: Path, style_path: Path) -> None:
    """Replace only ``score_style.mss`` in a generated MuseScore archive."""
    style_data = style_path.read_bytes()
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}-", suffix=".mscz", dir=path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as destination:
            destination.comment = source.comment
            for info in source.infolist():
                if info.filename == "score_style.mss":
                    destination.writestr(info, style_data)
                else:
                    destination.writestr(info, source.read(info.filename))
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _mscx_member(archive: zipfile.ZipFile) -> str:
    members = [name for name in archive.namelist() if name.lower().endswith(".mscx")]
    if len(members) != 1:
        raise ValueError(f"esperado um .mscx interno; encontrados: {members}")
    return members[0]


def _read_mscx(path: Path) -> tuple[ET.Element, str]:
    with zipfile.ZipFile(path) as archive:
        member = _mscx_member(archive)
        return ET.fromstring(archive.read(member)), member


def remove_leading_empty_vboxes(path: Path) -> int:
    """Remove empty cover-page frames introduced by a MusicXML round trip."""
    root, member = _read_mscx(path)
    score = root.find("Score")
    if score is None:
        raise ValueError("arquivo MuseScore sem elemento Score")
    removed = 0
    for staff in score.findall("Staff"):
        for child in list(staff):
            if child.tag == "Measure":
                break
            if child.tag != "VBox":
                continue
            meaningful = [
                node
                for node in child
                if node.tag not in {"height", "width", "eid"} and (node.text or "").strip()
            ]
            if meaningful:
                continue
            staff.remove(child)
            removed += 1
    if not removed:
        return 0
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}-", suffix=".mscz", dir=path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as destination:
            destination.comment = source.comment
            for info in source.infolist():
                destination.writestr(
                    info, data if info.filename == member else source.read(info.filename)
                )
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return removed


def graft_reference_measures(reference: Path, target: Path, measure_count: int) -> None:
    """Replace the opening measures of a generated score with the exact MSCX reference."""
    reference_root, _ = _read_mscx(reference)
    target_root, target_member = _read_mscx(target)
    reference_score = reference_root.find("Score")
    target_score = target_root.find("Score")
    if reference_score is None or target_score is None:
        raise ValueError("arquivo MuseScore sem elemento Score")
    reference_staves = {staff.get("id", ""): staff for staff in reference_score.findall("Staff")}
    target_staves = {staff.get("id", ""): staff for staff in target_score.findall("Staff")}
    if set(reference_staves) != set(target_staves):
        raise ValueError("as pautas do gabarito e do resultado não coincidem")
    for staff_id, target_staff in target_staves.items():
        reference_measures = reference_staves[staff_id].findall("Measure")
        target_measures = target_staff.findall("Measure")
        if len(reference_measures) < measure_count or len(target_measures) < measure_count:
            raise ValueError(f"pauta {staff_id} não possui {measure_count} compassos")
        for index in range(measure_count):
            old_measure = target_measures[index]
            child_index = list(target_staff).index(old_measure)
            target_staff.remove(old_measure)
            target_staff.insert(child_index, copy.deepcopy(reference_measures[index]))
        for appended_measure in target_staff.findall("Measure")[measure_count:]:
            for signature in appended_measure.iter("TimeSig"):
                courtesy = signature.find("showCourtesySig")
                if courtesy is None:
                    courtesy = ET.Element("showCourtesySig")
                    signature.insert(0, courtesy)
                courtesy.text = "0"

    data = ET.tostring(target_root, encoding="utf-8", xml_declaration=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{target.stem}-", suffix=".mscz", dir=target.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(target, "r") as source, zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as destination:
            destination.comment = source.comment
            for info in source.infolist():
                destination.writestr(info, data if info.filename == target_member else source.read(info.filename))
        os.replace(temporary_path, target)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def set_automatic_beaming(path: Path, start_measure: int = 1) -> dict:
    """Return imported notes to MuseScore's meter-aware automatic beaming.

    MusicXML imports can write ``<BeamMode>no</BeamMode>`` on every note, which
    forces otherwise beamable eighth notes to remain separated.  Removing only
    those explicit overrides lets MuseScore apply the score's 9/8 beat groups.
    """
    root, member = _read_mscx(path)
    score = root.find("Score")
    if score is None:
        raise ValueError("arquivo MuseScore sem elemento Score")
    removed = 0
    affected_measures: set[tuple[str, int]] = set()
    for staff in score.findall("Staff"):
        staff_id = staff.get("id", "")
        for measure_index, measure in enumerate(staff.findall("Measure"), 1):
            if measure_index < start_measure:
                continue
            for parent in measure.iter():
                for beam_mode in list(parent.findall("BeamMode")):
                    if beam_mode.text == "no":
                        parent.remove(beam_mode)
                        removed += 1
                        affected_measures.add((staff_id, measure_index))

    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}-", suffix=".mscz", dir=path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as destination:
            destination.comment = source.comment
            for info in source.infolist():
                destination.writestr(info, data if info.filename == member else source.read(info.filename))
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return {
        "mode": "automatic",
        "start_measure": start_measure,
        "removed_no_beam_overrides": removed,
        "affected_staff_measures": len(affected_measures),
    }


def validate_scherzo_mscz(
    reference: Path,
    target: Path,
    reference_measures: int = 8,
    time_signature_measures: tuple[int, ...] = (9,),
    expected_additional_tuplets: list[tuple[str, int, str, str, str]] | None = None,
) -> dict:
    """Audit the final MuseScore structure, including exact measures and real tuplets."""
    reference_root, _ = _read_mscx(reference)
    target_root, _ = _read_mscx(target)
    reference_score = reference_root.find("Score")
    target_score = target_root.find("Score")
    if reference_score is None or target_score is None:
        raise ValueError("arquivo MuseScore sem elemento Score")
    reference_staves = {staff.get("id", ""): staff for staff in reference_score.findall("Staff")}
    target_staves = {staff.get("id", ""): staff for staff in target_score.findall("Staff")}
    violations: list[dict] = []
    exact_opening = 0
    repeated_time_signatures = 0
    for staff_id, reference_staff in reference_staves.items():
        target_staff = target_staves.get(staff_id)
        if target_staff is None:
            violations.append({"staff": staff_id, "kind": "missing_staff"})
            continue
        ref_measures = reference_staff.findall("Measure")
        out_measures = target_staff.findall("Measure")
        if len(out_measures) <= reference_measures:
            violations.append({"staff": staff_id, "kind": "missing_appended_measures"})
            continue
        for index in range(reference_measures):
            if ET.tostring(ref_measures[index]) != ET.tostring(out_measures[index]):
                violations.append(
                    {"staff": staff_id, "measure": index + 1, "kind": "reference_changed"}
                )
            else:
                exact_opening += 1
        for index, measure in enumerate(out_measures[reference_measures:], reference_measures + 1):
            custom_length = measure.get("len")
            if custom_length not in {None, "9/8"}:
                violations.append(
                    {
                        "staff": staff_id,
                        "measure": index,
                        "kind": "invalid_measure_length",
                        "value": custom_length,
                    }
                )
        for signature_measure in time_signature_measures:
            if len(out_measures) < signature_measure:
                violations.append(
                    {"staff": staff_id, "measure": signature_measure, "kind": "missing_measure"}
                )
                continue
            signatures = [
                (item.findtext("sigN"), item.findtext("sigD"))
                for item in out_measures[signature_measure - 1].iter("TimeSig")
            ]
            if ("9", "8") not in signatures:
                violations.append(
                    {
                        "staff": staff_id,
                        "measure": signature_measure,
                        "kind": "missing_9_8_signature",
                    }
                )
            else:
                repeated_time_signatures += 1

    reference_tuplets = [
        (
            staff.get("id"),
            index,
            tuplet.findtext("normalNotes"),
            tuplet.findtext("actualNotes"),
            tuplet.findtext("baseNote"),
        )
        for staff in reference_score.findall("Staff")
        for index, measure in enumerate(staff.findall("Measure")[:reference_measures], 1)
        for tuplet in measure.iter("Tuplet")
    ]
    target_tuplets = [
        (
            staff.get("id"),
            index,
            tuplet.findtext("normalNotes"),
            tuplet.findtext("actualNotes"),
            tuplet.findtext("baseNote"),
        )
        for staff in target_score.findall("Staff")
        for index, measure in enumerate(staff.findall("Measure")[:reference_measures], 1)
        for tuplet in measure.iter("Tuplet")
    ]
    if target_tuplets != reference_tuplets:
        violations.append({"kind": "reference_tuplet_mismatch"})
    additional_tuplets = [
        (
            staff.get("id"),
            index,
            tuplet.findtext("normalNotes"),
            tuplet.findtext("actualNotes"),
            tuplet.findtext("baseNote"),
        )
        for staff in target_score.findall("Staff")
        for index, measure in enumerate(staff.findall("Measure")[reference_measures:], reference_measures + 1)
        for tuplet in measure.iter("Tuplet")
    ]
    if expected_additional_tuplets is not None and additional_tuplets != expected_additional_tuplets:
        violations.append(
            {
                "kind": "additional_tuplet_mismatch",
                "expected": expected_additional_tuplets,
                "actual": additional_tuplets,
            }
        )
    return {
        "valid": not violations,
        "staves": len(target_staves),
        "exact_reference_measures": exact_opening,
        "expected_exact_reference_measures": len(reference_staves) * reference_measures,
        "repeated_9_8_signatures": repeated_time_signatures,
        "reference_tuplets": reference_tuplets,
        "target_tuplets": target_tuplets,
        "additional_tuplets": additional_tuplets,
        "violations": violations,
    }


def validate_fixed_meter_mscz(path: Path, beats: int, beat_type: int) -> dict:
    """Verify that MuseScore retained one exact fixed meter on every staff."""
    root, _ = _read_mscx(path)
    score = root.find("Score")
    if score is None:
        raise ValueError("arquivo MuseScore sem elemento Score")
    expected = Fraction(beats, beat_type)
    violations: list[dict] = []
    checked_measures = 0
    for staff in score.findall("Staff"):
        staff_id = staff.get("id", "")
        measures = staff.findall("Measure")
        if not measures:
            violations.append({"staff": staff_id, "kind": "missing_measures"})
            continue
        first_signatures = [
            (item.findtext("sigN"), item.findtext("sigD"))
            for item in measures[0].iter("TimeSig")
        ]
        if (str(beats), str(beat_type)) not in first_signatures:
            violations.append(
                {"staff": staff_id, "measure": 1, "kind": "missing_time_signature"}
            )
        for index, measure in enumerate(measures, 1):
            checked_measures += 1
            custom_length = measure.get("len")
            if custom_length is not None and Fraction(custom_length) != expected:
                violations.append(
                    {
                        "staff": staff_id,
                        "measure": index,
                        "kind": "invalid_measure_length",
                        "value": custom_length,
                    }
                )
    return {
        "valid": not violations,
        "meter": f"{beats}/{beat_type}",
        "staves": len(score.findall("Staff")),
        "checked_measures": checked_measures,
        "violations": violations,
    }


def validate_meter_map_mscz(
    path: Path,
    meter_changes: dict[int, tuple[int, int]],
    end_measure: int,
    start_measure: int = 1,
) -> dict:
    """Verify a mixed-meter MuseScore result against explicit change points."""
    root, _ = _read_mscx(path)
    score = root.find("Score")
    if score is None:
        raise ValueError("arquivo MuseScore sem elemento Score")
    violations: list[dict] = []
    checked = 0
    checked_voices = 0
    duration_quarters = {
        "long": Fraction(16),
        "breve": Fraction(8),
        "whole": Fraction(4),
        "half": Fraction(2),
        "quarter": Fraction(1),
        "eighth": Fraction(1, 2),
        "16th": Fraction(1, 4),
        "32nd": Fraction(1, 8),
        "64th": Fraction(1, 16),
        "128th": Fraction(1, 32),
    }
    change_measures = sorted(index for index in meter_changes if index <= end_measure)
    for staff in score.findall("Staff"):
        staff_id = staff.get("id", "")
        measures = staff.findall("Measure")
        if len(measures) != end_measure:
            violations.append(
                {
                    "staff": staff_id,
                    "kind": "measure_count",
                    "expected": end_measure,
                    "actual": len(measures),
                }
            )
            continue
        active = meter_changes[change_measures[0]]
        for measure_index, measure in enumerate(measures, 1):
            if measure_index in meter_changes:
                active = meter_changes[measure_index]
            if measure_index < start_measure:
                continue
            if measure_index in meter_changes:
                signatures = [
                    (item.findtext("sigN"), item.findtext("sigD"))
                    for item in measure.iter("TimeSig")
                ]
                expected_signature = (str(active[0]), str(active[1]))
                if expected_signature not in signatures:
                    violations.append(
                        {
                            "staff": staff_id,
                            "measure": measure_index,
                            "kind": "missing_time_signature",
                            "expected": f"{active[0]}/{active[1]}",
                            "actual": signatures,
                        }
                    )
            expected_length = Fraction(active[0], active[1])
            custom_length = measure.get("len")
            if custom_length is not None and Fraction(custom_length) != expected_length:
                violations.append(
                    {
                        "staff": staff_id,
                        "measure": measure_index,
                        "kind": "invalid_measure_length",
                        "expected": str(expected_length),
                        "actual": custom_length,
                    }
                )
            expected_quarters = expected_length * 4
            voice_ends: list[Fraction] = []
            for voice_index, voice in enumerate(measure.findall("voice"), 1):
                cursor = Fraction(0)
                last_chord_end = Fraction(0)
                ratio = Fraction(1)
                stack: list[Fraction] = []
                rhythmic = False
                for item in voice:
                    if item.tag == "location":
                        # MuseScore's integrity checker does not count native
                        # cursor locations as voice duration.  Mirroring that
                        # behaviour is essential: a score can play correctly
                        # yet still open with "corrupted measure" warnings if
                        # a location is the only thing filling the bar.
                        continue
                    elif item.tag == "Tuplet":
                        stack.append(ratio)
                        ratio *= Fraction(
                            int(item.findtext("normalNotes", "1")),
                            int(item.findtext("actualNotes", "1")),
                        )
                    elif item.tag == "endTuplet":
                        ratio = stack.pop() if stack else Fraction(1)
                    elif item.tag in {"Chord", "Rest"}:
                        explicit = item.findtext("duration")
                        if explicit:
                            value = Fraction(explicit) * 4
                        elif item.findtext("durationType") == "measure":
                            value = expected_quarters
                        else:
                            value = duration_quarters.get(
                                item.findtext("durationType", ""), Fraction(0)
                            )
                            dots = int(item.findtext("dots", "0"))
                            value *= sum(
                                Fraction(1, 2**dot) for dot in range(dots + 1)
                            )
                            value *= ratio
                        cursor += value
                        rhythmic = True
                        if item.tag == "Chord":
                            last_chord_end = cursor
                if not rhythmic:
                    continue
                checked_voices += 1
                voice_ends.append(cursor)
                if cursor > expected_quarters:
                    violations.append(
                        {
                            "staff": staff_id,
                            "measure": measure_index,
                            "voice": voice_index,
                            "kind": "voice_overrun",
                            "expected_quarters": str(expected_quarters),
                            "actual_quarters": str(cursor),
                        }
                    )
                if last_chord_end > expected_quarters:
                    violations.append(
                        {
                            "staff": staff_id,
                            "measure": measure_index,
                            "voice": voice_index,
                            "kind": "voice_note_overrun",
                            "expected_quarters": str(expected_quarters),
                            "actual_quarters": str(last_chord_end),
                        }
                    )
            if voice_ends and max(voice_ends) < expected_quarters:
                violations.append(
                    {
                        "staff": staff_id,
                        "measure": measure_index,
                        "kind": "incomplete_staff_measure",
                        "expected_quarters": str(expected_quarters),
                        "actual_quarters": str(max(voice_ends)),
                    }
                )
            checked += 1
    return {
        "valid": not violations,
        "staves": len(score.findall("Staff")),
        "measures": end_measure,
        "start_measure": start_measure,
        "checked_staff_measures": checked,
        "checked_voices": checked_voices,
        "meter_changes": {
            str(measure): f"{meter_changes[measure][0]}/{meter_changes[measure][1]}"
            for measure in change_measures
        },
        "violations": violations,
    }


def normalize_fixed_meter_padding(path: Path, beats: int, beat_type: int) -> dict:
    """Remove only provable trailing-rest padding added by MuseScore's importer."""
    root, member = _read_mscx(path)
    score = root.find("Score")
    if score is None:
        raise ValueError("arquivo MuseScore sem elemento Score")
    expected = Fraction(beats, beat_type)
    repairs: list[dict] = []
    duration_types = {
        Fraction(1): "whole",
        Fraction(1, 2): "half",
        Fraction(1, 4): "quarter",
        Fraction(1, 8): "eighth",
        Fraction(1, 16): "16th",
    }
    for staff in score.findall("Staff"):
        staff_id = staff.get("id", "")
        for index, measure in enumerate(staff.findall("Measure"), 1):
            custom_length = measure.get("len")
            if custom_length is None:
                continue
            actual = Fraction(custom_length)
            excess = actual - expected
            if excess <= 0:
                continue
            expected_type = duration_types.get(excess)
            if expected_type is None:
                raise ValueError(
                    f"pauta {staff_id}, compasso {index}: excesso não reparável {excess}"
                )
            repaired_voices = 0
            for voice in measure.findall("voice"):
                measure_rest = next(
                    (
                        child
                        for child in voice.findall("Rest")
                        if child.findtext("durationType") == "measure"
                        and child.findtext("duration") == custom_length
                    ),
                    None,
                )
                if measure_rest is not None:
                    measure_rest.find("duration").text = f"{beats}/{beat_type}"
                    repaired_voices += 1
                    continue
                trailing_rest = next(
                    (
                        child
                        for child in reversed(list(voice))
                        if child.tag == "Rest"
                        and child.findtext("durationType") == expected_type
                    ),
                    None,
                )
                if trailing_rest is not None:
                    voice.remove(trailing_rest)
                    repaired_voices += 1
            if repaired_voices == 0:
                raise ValueError(
                    f"pauta {staff_id}, compasso {index}: excesso {excess} não é pausa final"
                )
            del measure.attrib["len"]
            repairs.append(
                {
                    "staff": staff_id,
                    "measure": index,
                    "removed_rest": expected_type,
                    "voices": repaired_voices,
                }
            )

    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}-", suffix=".mscz", dir=path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as destination:
            destination.comment = source.comment
            for info in source.infolist():
                destination.writestr(info, data if info.filename == member else source.read(info.filename))
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return {"repairs": repairs, "count": len(repairs)}


def normalize_meter_map_padding(
    path: Path, meter_changes: dict[int, tuple[int, int]]
) -> dict:
    """Remove importer-only hidden padding using each measure's active meter.

    MuseScore can extend a mixed-meter MusicXML measure and append an invisible
    rest whose duration is the extension.  Our MusicXML writer never emits
    invisible rests, so ``visible=0`` reliably identifies this import artefact.
    Hidden whole-measure rests are resized rather than removed because another
    voice may still use them as placeholders.
    """
    root, member = _read_mscx(path)
    score = root.find("Score")
    if score is None:
        raise ValueError("arquivo MuseScore sem elemento Score")
    repairs: list[dict] = []
    change_measures = sorted(meter_changes)
    for staff in score.findall("Staff"):
        staff_id = staff.get("id", "")
        active = meter_changes[change_measures[0]]
        for measure_index, measure in enumerate(staff.findall("Measure"), 1):
            if measure_index in meter_changes:
                active = meter_changes[measure_index]
            custom_length = measure.get("len")
            if custom_length is None:
                continue
            expected = Fraction(active[0], active[1])
            actual = Fraction(custom_length)
            excess = actual - expected
            if excess <= 0:
                continue
            repaired_voices = 0
            removed: list[str] = []
            for voice in measure.findall("voice"):
                changed = False
                removed_tuplet_ids: set[str] = set()
                for child in list(voice):
                    if child.tag != "Rest" or child.findtext("visible") != "0":
                        continue
                    if child.findtext("durationType") == "measure":
                        duration = child.find("duration")
                        if duration is None:
                            duration = ET.SubElement(child, "duration")
                        duration.text = f"{active[0]}/{active[1]}"
                        removed.append("measure-rest-resized")
                    else:
                        tuplet_id = child.findtext("Tuplet")
                        if tuplet_id:
                            removed_tuplet_ids.add(tuplet_id)
                        removed.append(child.findtext("durationType", "rest"))
                        voice.remove(child)
                    changed = True

                referenced_tuplet_ids = {
                    item.findtext("Tuplet")
                    for item in voice
                    if item.tag in {"Chord", "Rest"} and item.findtext("Tuplet")
                }
                for child in list(voice):
                    if (
                        child.tag == "Tuplet"
                        and child.get("id") in removed_tuplet_ids
                        and child.get("id") not in referenced_tuplet_ids
                    ):
                        voice.remove(child)
                if changed:
                    repaired_voices += 1
            if repaired_voices == 0:
                # MuseScore copies the custom score-timeline length to every
                # staff, including staves that did not receive a hidden rest.
                # The explicit TimeSig safely supplies the intended duration.
                removed.append("score-timeline-reset")
            del measure.attrib["len"]
            repairs.append(
                {
                    "staff": staff_id,
                    "measure": measure_index,
                    "excess": str(excess),
                    "removed": removed,
                    "voices": repaired_voices,
                }
            )

    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}-", suffix=".mscz", dir=path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as destination:
            destination.comment = source.comment
            for info in source.infolist():
                destination.writestr(info, data if info.filename == member else source.read(info.filename))
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return {"repairs": repairs, "count": len(repairs)}


def normalize_mscz_voice_durations(
    path: Path,
    meter_changes: dict[int, tuple[int, int]],
    end_measure: int,
    start_measure: int = 1,
) -> dict:
    """Rebuild importer padding so every native MuseScore voice ends exactly.

    MusicXML imports containing incomplete OCR tuplets can make MuseScore
    right-align later voices with ``location`` offsets and append rests beyond
    the time signature.  The generated MusicXML already has exact note onsets;
    therefore those native offsets are importer artefacts.  This pass preserves
    every chord through the final pitched event, removes only its generated
    suffix, and writes one exact hidden padding rest to the barline.
    """
    root, member = _read_mscx(path)
    score = root.find("Score")
    if score is None:
        raise ValueError("arquivo MuseScore sem elemento Score")

    base_quarters = {
        "long": Fraction(16),
        "breve": Fraction(8),
        "whole": Fraction(4),
        "half": Fraction(2),
        "quarter": Fraction(1),
        "eighth": Fraction(1, 2),
        "16th": Fraction(1, 4),
        "32nd": Fraction(1, 8),
        "64th": Fraction(1, 16),
        "128th": Fraction(1, 32),
    }

    def rhythmic_duration(item: ET.Element, ratio: Fraction) -> Fraction:
        if item.tag not in {"Chord", "Rest"}:
            return Fraction(0)
        explicit = item.findtext("duration")
        if explicit:
            return Fraction(explicit) * 4
        value = base_quarters.get(item.findtext("durationType", ""), Fraction(0))
        dots = int(item.findtext("dots", "0"))
        value *= sum(Fraction(1, 2**index) for index in range(dots + 1))
        return value * ratio

    def nominal_duration(item: ET.Element) -> Fraction:
        value = base_quarters.get(item.findtext("durationType", ""), Fraction(0))
        dots = int(item.findtext("dots", "0"))
        return value * sum(Fraction(1, 2**index) for index in range(dots + 1))

    def set_notated_duration(item: ET.Element, quarters: Fraction) -> bool:
        for duration_type, base in base_quarters.items():
            value = base
            for dots in range(4):
                if value == quarters:
                    node = item.find("durationType")
                    if node is None:
                        node = ET.SubElement(item, "durationType")
                    node.text = duration_type
                    dots_node = item.find("dots")
                    if dots:
                        if dots_node is None:
                            dots_node = ET.SubElement(item, "dots")
                        dots_node.text = str(dots)
                    elif dots_node is not None:
                        item.remove(dots_node)
                    return True
                value += base / (2 ** (dots + 1))
        return False

    def clear_rest_notation(rest: ET.Element, duration_type: str) -> None:
        """Give an imported spacer one unambiguous native duration."""
        for tag in ("duration", "dots", "NoteDot", "Tuplet"):
            for node in list(rest.findall(tag)):
                rest.remove(node)
        node = rest.find("durationType")
        if node is None:
            node = ET.SubElement(rest, "durationType")
        node.text = duration_type

    def stabilize_complete_tuplet_groups(voice: ET.Element) -> str | None:
        """Repair three importer patterns without replacing time with locations.

        MusicXML spacer rests have an exact playback duration but no written
        type.  MuseScore guesses a dotted binary value and compensates it with
        ``location``.  Its score-integrity checker deliberately ignores that
        compensation.  Convert the spacer into the missing member of the
        surrounding triplet, or into the ordinary rest following it.
        """
        rhythmic = [
            item
            for item in voice
            if item.tag in {"Tuplet", "endTuplet", "Chord", "Rest", "location"}
        ]

        # half-note triplet + quarter-triplet rest + ordinary quarter rest.
        # This is a complete 3/4 bar; only the final spacer's guessed spelling
        # is wrong.
        if (
            len(rhythmic) == 5
            and [item.tag for item in rhythmic]
            == ["Tuplet", "Chord", "Rest", "endTuplet", "Rest"]
            and rhythmic[1].findtext("durationType") == "half"
            and rhythmic[2].findtext("durationType") == "quarter"
        ):
            clear_rest_notation(rhythmic[4], "quarter")
            return "triplet_then_quarter"

        # A triplet begins with an exact 2/3-quarter spacer.  MuseScore placed
        # that spacer before the Tuplet and invented a third rest at its end.
        # Move the spacer into the group and discard the invented suffix.
        if (
            len(rhythmic) in {7, 8}
            and rhythmic[0].tag == "Rest"
            and rhythmic[1].tag == "location"
            and rhythmic[2].tag == "Tuplet"
            and [item.tag for item in rhythmic[3:7]]
            == ["Chord", "Chord", "Rest", "endTuplet"]
            and all(
                item.findtext("durationType") == "quarter"
                for item in rhythmic[3:6]
            )
        ):
            spacer, location, tuplet = rhythmic[:3]
            invented_rest = rhythmic[5]
            suffix = rhythmic[7] if len(rhythmic) == 8 else None
            clear_rest_notation(spacer, "quarter")
            voice.remove(location)
            voice.remove(spacer)
            voice.insert(list(voice).index(tuplet) + 1, spacer)
            voice.remove(invented_rest)
            if suffix is not None and suffix.tag == "Rest":
                voice.remove(suffix)
            return "leading_triplet_rest"

        # A 3/4 stream with a 1/3-quarter lead-in and a 2/3-quarter
        # tail. Spell it as two complete triplets:
        #   (eighth rest + quarter chord), then
        #   (quarter chord + quarter chord + quarter rest).
        if (
            len(rhythmic) in {8, 9}
            and rhythmic[0].tag == "Rest"
            and rhythmic[1].tag == "location"
            and rhythmic[2].tag == "Tuplet"
            and [item.tag for item in rhythmic[3:8]]
            == ["Chord", "Chord", "Chord", "endTuplet", "Rest"]
            and all(
                item.findtext("durationType") == "quarter"
                for item in rhythmic[3:6]
            )
        ):
            spacer, location, tuplet, first, second, third, end, tail = rhythmic[:8]
            suffix = rhythmic[8] if len(rhythmic) == 9 else None
            second_tuplet = copy.deepcopy(tuplet)
            eid = second_tuplet.find("eid")
            if eid is not None:
                second_tuplet.remove(eid)
            base_note = tuplet.find("baseNote")
            if base_note is None:
                base_note = ET.SubElement(tuplet, "baseNote")
            base_note.text = "eighth"
            clear_rest_notation(spacer, "eighth")
            clear_rest_notation(tail, "quarter")
            voice.remove(location)
            voice.remove(spacer)
            voice.remove(end)
            voice.insert(list(voice).index(tuplet) + 1, spacer)
            voice.insert(list(voice).index(first) + 1, ET.Element("endTuplet"))
            voice.insert(list(voice).index(second), second_tuplet)
            voice.insert(list(voice).index(tail) + 1, ET.Element("endTuplet"))
            if suffix is not None and suffix.tag == "Rest":
                voice.remove(suffix)
            return "split_leadin_triplets"

        # A four-quarter bar encoded as two adjacent triplet groups:
        #   (quarter rest + half chord) + (half chord + quarter chord).
        # The importer merged both groups into one oversized tuplet.
        if (
            len(rhythmic) == 7
            and [item.tag for item in rhythmic]
            == ["Rest", "location", "Tuplet", "Chord", "Chord", "Chord", "endTuplet"]
            and [item.findtext("durationType") for item in rhythmic[3:6]]
            == ["half", "half", "quarter"]
        ):
            spacer, location, tuplet, first, second, third, end = rhythmic
            clear_rest_notation(spacer, "quarter")
            voice.remove(location)
            voice.remove(spacer)
            voice.remove(end)
            voice.insert(list(voice).index(tuplet) + 1, spacer)
            first_index = list(voice).index(first)
            first_end = ET.Element("endTuplet")
            voice.insert(first_index + 1, first_end)
            second_tuplet = copy.deepcopy(tuplet)
            eid = second_tuplet.find("eid")
            if eid is not None:
                second_tuplet.remove(eid)
            voice.insert(list(voice).index(second), second_tuplet)
            voice.insert(list(voice).index(third) + 1, ET.Element("endTuplet"))
            return "split_adjacent_triplets"

        return None

    def flatten_oversized_tuplets(voice: ET.Element) -> int:
        """Flatten OCR tuplets that contain several groups in one container."""
        flattened = 0
        while True:
            children = list(voice)
            start = next(
                (index for index, item in enumerate(children) if item.tag == "Tuplet"),
                None,
            )
            if start is None:
                break
            depth = 0
            end = None
            for index in range(start, len(children)):
                if children[index].tag == "Tuplet":
                    depth += 1
                elif children[index].tag == "endTuplet":
                    depth -= 1
                    if depth == 0:
                        end = index
                        break
            if end is None:
                break
            tuplet = children[start]
            base = base_quarters.get(tuplet.findtext("baseNote", ""), Fraction(0))
            actual = int(tuplet.findtext("actualNotes", "1"))
            block = children[start + 1 : end]
            units = (
                sum(nominal_duration(item) for item in block if item.tag in {"Chord", "Rest"})
                / base
                if base
                else Fraction(0)
            )
            if units <= actual:
                # Skip this well-formed group while still allowing a later one.
                later = next(
                    (item for item in children[end + 1 :] if item.tag == "Tuplet"),
                    None,
                )
                if later is None:
                    break
                # Temporarily mark it so the next search passes over it.
                tuplet.tag = "TupletStable"
                continue
            voice.remove(tuplet)
            voice.remove(children[end])
            for item in block:
                if item.tag == "Rest":
                    voice.remove(item)
            flattened += 1
        for item in voice.findall("TupletStable"):
            item.tag = "Tuplet"
        return flattened

    def completes_open_tuplet(
        items: list[ET.Element], quarters: Fraction, ratio: Fraction
    ) -> bool:
        stack: list[int] = []
        for index, item in enumerate(items):
            if item.tag == "Tuplet":
                stack.append(index)
            elif item.tag == "endTuplet" and stack:
                stack.pop()
        if len(stack) != 1:
            return False
        start = stack[-1]
        tuplet = items[start]
        base = base_quarters.get(tuplet.findtext("baseNote", ""), Fraction(0))
        if not base:
            return False
        actual = int(tuplet.findtext("actualNotes", "1"))
        used = sum(
            nominal_duration(item)
            for item in items[start + 1 :]
            if item.tag in {"Chord", "Rest"}
        ) / base
        added = (quarters / ratio) / base
        return used + added == actual

    def cursor_after(items: list[ET.Element]) -> tuple[Fraction, int, Fraction]:
        cursor = Fraction(0)
        ratio = Fraction(1)
        stack: list[Fraction] = []
        for item in items:
            if item.tag == "Tuplet":
                stack.append(ratio)
                ratio *= Fraction(
                    int(item.findtext("normalNotes", "1")),
                    int(item.findtext("actualNotes", "1")),
                )
            elif item.tag == "endTuplet":
                ratio = stack.pop() if stack else Fraction(1)
            else:
                cursor += rhythmic_duration(item, ratio)
        return cursor, len(stack), ratio

    def append_padding(
        voice: ET.Element,
        quarters: Fraction,
        ratio: Fraction = Fraction(1),
        allow_location: bool = True,
    ) -> bool:
        if quarters <= 0:
            return True
        nominal = quarters / ratio
        for duration_type, base in base_quarters.items():
            value = base
            for dots in range(4):
                if value == nominal:
                    rest = ET.SubElement(voice, "Rest")
                    ET.SubElement(rest, "visible").text = "0"
                    if dots:
                        ET.SubElement(rest, "dots").text = str(dots)
                    ET.SubElement(rest, "durationType").text = duration_type
                    return True
                value += base / (2 ** (dots + 1))
        if not allow_location:
            return False
        # Native ``location`` is MuseScore's exact cursor movement. Unlike a
        # Rest with a mismatched durationType, it cannot acquire an additional
        # notated duration when the file is opened again.
        location = ET.SubElement(voice, "location")
        ET.SubElement(location, "fractions").text = str(quarters / 4)
        return False

    repairs: list[dict] = []
    changes = sorted(index for index in meter_changes if index <= end_measure)
    for staff in score.findall("Staff"):
        active = meter_changes[changes[0]]
        for measure_index, measure in enumerate(staff.findall("Measure"), 1):
            if measure_index > end_measure:
                break
            if measure_index in meter_changes:
                active = meter_changes[measure_index]
            if measure_index < start_measure:
                continue
            expected = Fraction(active[0] * 4, active[1])
            measure.attrib.pop("len", None)
            for voice_index, voice in enumerate(measure.findall("voice"), 1):
                stabilized_tuplets = stabilize_complete_tuplet_groups(voice)
                flattened_tuplets = flatten_oversized_tuplets(voice)
                children = list(voice)
                locations = [item for item in children if item.tag == "location"]
                children = [item for item in children if item.tag != "location"]
                chord_indexes = [
                    index for index, item in enumerate(children) if item.tag == "Chord"
                ]
                preserved_suffix: list[ET.Element] = []
                if chord_indexes:
                    full_cursor, _, _ = cursor_after(children)
                    if not locations and full_cursor == expected:
                        # Already stable: in particular, retain complete
                        # quintuplet/triplet rests that survive a MuseScore
                        # open-save cycle better than a synthetic cursor move.
                        if stabilized_tuplets:
                            repairs.append(
                                {
                                    "staff": staff.get("id", ""),
                                    "measure": measure_index,
                                    "voice": voice_index,
                                    "removed_locations": 0,
                                    "flattened_tuplets": flattened_tuplets,
                                    "stabilized_tuplets": stabilized_tuplets,
                                }
                            )
                        continue
                    last_chord = chord_indexes[-1]
                    prefix = children[: last_chord + 1]
                    preserved_suffix = [
                        item
                        for item in children[last_chord + 1 :]
                        if item.tag not in {"Rest", "Tuplet", "endTuplet"}
                    ]
                    cursor, open_tuplets, active_ratio = cursor_after(prefix)
                    correction: ET.Element | None = None
                    if cursor > expected:
                        excess = cursor - expected
                        last_chord_node = prefix[-1]
                        current_duration = nominal_duration(last_chord_node) * active_ratio
                        replacement = (current_duration - excess) / active_ratio
                        if replacement > 0 and set_notated_duration(
                            last_chord_node, replacement
                        ):
                            cursor = expected
                        else:
                        # A malformed imported tuplet can lengthen a leading
                        # rest while all following notes retain their relative
                        # spacing. Shift that complete stream back by precisely
                        # the excess; no chord duration or pitch is altered.
                            correction = ET.Element("location")
                            ET.SubElement(correction, "fractions").text = str(
                                -excess / 4
                            )
                            cursor = expected
                    for item in list(voice):
                        voice.remove(item)
                    correction_inserted = False
                    for item in prefix:
                        if (
                            correction is not None
                            and not correction_inserted
                            and item.tag in {"Tuplet", "Chord", "Rest"}
                        ):
                            voice.append(correction)
                            correction_inserted = True
                        voice.append(item)
                    if correction is not None and not correction_inserted:
                        voice.append(correction)
                    remaining = expected - cursor
                    padded_inside_tuplet = False
                    if (
                        open_tuplets == 1
                        and remaining > 0
                        and completes_open_tuplet(prefix, remaining, active_ratio)
                    ):
                        padded_inside_tuplet = append_padding(
                            voice, remaining, active_ratio, allow_location=False
                        )
                    for _ in range(open_tuplets):
                        ET.SubElement(voice, "endTuplet")
                    if not padded_inside_tuplet:
                        append_padding(voice, remaining)
                    for item in preserved_suffix:
                        voice.append(item)
                elif voice_index == 1:
                    nonrhythmic = [
                        item
                        for item in children
                        if item.tag not in {"Rest", "Tuplet", "endTuplet"}
                    ]
                    for item in list(voice):
                        voice.remove(item)
                    for item in nonrhythmic:
                        voice.append(item)
                    rest = ET.SubElement(voice, "Rest")
                    ET.SubElement(rest, "durationType").text = "measure"
                    ET.SubElement(rest, "duration").text = f"{active[0]}/{active[1]}"
                else:
                    for item in list(voice):
                        voice.remove(item)
                if locations or chord_indexes:
                    repairs.append(
                        {
                            "staff": staff.get("id", ""),
                            "measure": measure_index,
                            "voice": voice_index,
                            "removed_locations": len(locations),
                            "flattened_tuplets": flattened_tuplets,
                            "stabilized_tuplets": stabilized_tuplets,
                        }
                    )

    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}-", suffix=".mscz", dir=path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as destination:
            destination.comment = source.comment
            for info in source.infolist():
                destination.writestr(
                    info, data if info.filename == member else source.read(info.filename)
                )
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return {
        "repairs": repairs,
        "count": len(repairs),
        "start_measure": start_measure,
    }
