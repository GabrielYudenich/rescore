from __future__ import annotations

import copy
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

from .musicxml import _read_musicxml


# Stable top-to-bottom orchestral order used throughout the scanned Eschig
# edition. Compound labels intentionally retain the original French wording.
CHOROS9_PART_NAMES = (
    "Piccolo",
    "2 Flûtes",
    "2 Hautbois",
    "Cor anglais",
    "2 Clarinettes (Si♭)",
    "Clarinette basse (Si♭)",
    "2 Bassons",
    "Contrebasson",
    "Cors 1–2 (Fa)",
    "Cors 3–4 (Fa)",
    "4 Pistons (Si♭)",
    "Trombones 1–2",
    "Trombones 3–4",
    "Tuba",
    "Timbales",
    "Percussion",
    "Célesta",
    "Harpes 1–2",
    "Violons I",
    "Violons II",
    "Altos",
    "Violoncelles",
    "Contrebasses",
)


def _fraction_text(value: Fraction) -> str:
    return (
        str(value.numerator)
        if value.denominator == 1
        else f"{value.numerator}/{value.denominator}"
    )


def _position_groups(events: list[dict]) -> list[list[dict]]:
    """Collect notes that visually belong to the same chord/onset."""
    raw_groups: list[list[dict]] = []
    for event in events:
        if event.get("chord") and raw_groups:
            raw_groups[-1].append(event)
        else:
            raw_groups.append([event])
    raw_groups.sort(
        key=lambda group: min(float(event["default_x"]) for event in group)
    )
    merged: list[list[dict]] = []
    for group in raw_groups:
        position = statistics.median(float(event["default_x"]) for event in group)
        if merged:
            previous = statistics.median(
                float(event["default_x"]) for event in merged[-1]
            )
            if abs(position - previous) <= 6:
                merged[-1].extend(group)
                continue
        merged.append(group)
    return merged


def _estimate_sixteenth_step(streams: list[list[list[dict]]]) -> float | None:
    """Estimate the horizontal distance of one sixteenth from dense OMR lines."""
    gaps: list[float] = []
    for groups in streams:
        positions = [
            statistics.median(float(event["default_x"]) for event in group)
            for group in groups
        ]
        for left, right, left_group, right_group in zip(
            positions, positions[1:], groups, groups[1:]
        ):
            types = {
                event.get("type")
                for event in (*left_group, *right_group)
                if event.get("type")
            }
            gap = right - left
            if types & {"16th", "32nd"} and 16 <= gap <= 48:
                gaps.append(gap)
    if len(gaps) < 3:
        return None
    center = statistics.median(gaps)
    inliers = [gap for gap in gaps if center * 0.65 <= gap <= center * 1.35]
    return statistics.median(inliers) if inliers else center


def reconstruct_scanned_rhythm(score: dict, meter: str) -> dict:
    """Recover dense OMR timing from horizontal note positions.

    Audiveris often finds the note heads in a dense scan but assigns a quarter,
    whole or breve duration to one of the first notes. Its cumulative cursor then
    pushes the remainder beyond the bar. This pass changes timing only when a
    stream contains at least five positioned onsets and the page provides a stable
    sixteenth-note spacing. Sparse/sustained streams and recognized tuplets remain
    untouched.
    """
    beats_text, beat_type_text = meter.split("/", 1)
    measure_duration = Fraction(int(beats_text) * 4, int(beat_type_text))
    sixteenth_slots = int(measure_duration * 4)
    if sixteenth_slots < 1:
        return {"applied": False, "reason": "fórmula sem subdivisão utilizável"}

    by_measure_stream: dict[
        tuple[int, str, str, str], list[dict]
    ] = defaultdict(list)
    for event in score["events"]:
        if (
            event.get("pitch")
            and not event.get("grace")
            and event.get("default_x") is not None
        ):
            key = (
                int(event["measure_index"]),
                event["part_id"],
                event.get("staff", "1"),
                event.get("voice", "1"),
            )
            by_measure_stream[key].append(event)

    removed_ids: set[int] = set()
    reconstructed_streams = 0
    repositioned_events = 0
    duration_repairs = 0
    impossible_prefixes_removed = 0
    removed_prefixes: list[dict] = []
    thirty_second_streams = 0
    measure_steps: dict[int, float] = {}

    measure_numbers = sorted({key[0] for key in by_measure_stream})
    for measure_index in measure_numbers:
        current = {
            key: _position_groups(events)
            for key, events in by_measure_stream.items()
            if key[0] == measure_index
        }
        dense_groups = [groups for groups in current.values() if len(groups) >= 5]
        step = _estimate_sixteenth_step(dense_groups)
        if step is None:
            continue
        measure_steps[measure_index] = round(step, 3)

        for key, groups in current.items():
            if len(groups) < 5:
                continue
            if any(event.get("tuplet") for group in groups for event in group):
                continue

            first_duration = max(Fraction(event["duration"]) for event in groups[0])
            if first_duration >= measure_duration and len(groups) >= 8:
                for event in groups.pop(0):
                    removed_ids.add(id(event))
                    impossible_prefixes_removed += 1
                    removed_prefixes.append(
                        {
                            "part_id": event["part_id"],
                            "measure": int(event["measure_index"]),
                            "voice": event.get("voice", "1"),
                            "pitch": event.get("pitch"),
                            "duration": event["duration"],
                            "default_x": event.get("default_x"),
                            "reason": "duração de compasso inteiro antes de uma linha densa na mesma voz",
                        }
                    )

            if len(groups) < 5 or len(groups) > int(measure_duration * 8):
                continue

            slots_per_quarter = 8 if len(groups) > sixteenth_slots else 4
            available_slots = int(measure_duration * slots_per_quarter)
            if slots_per_quarter == 8:
                thirty_second_streams += 1
            positions = [
                statistics.median(float(event["default_x"]) for event in group)
                for group in groups
            ]
            base = positions[0]
            slots: list[int] = []
            for position in positions:
                slot = max(
                    0,
                    round(
                        (position - base)
                        / step
                        * Fraction(slots_per_quarter, 4)
                    ),
                )
                if slots:
                    slot = max(slot, slots[-1] + 1)
                slots.append(slot)
            if slots[-1] >= available_slots:
                span = positions[-1] - positions[0]
                if span <= 0:
                    continue
                slots = [
                    round((position - positions[0]) / span * (available_slots - 1))
                    for position in positions
                ]
                # Project to a strictly increasing lattice without pushing the
                # final onset outside the measure. The backward pass reserves
                # one slot for every remaining recognized onset.
                for index in range(len(slots) - 2, -1, -1):
                    slots[index] = min(slots[index], slots[index + 1] - 1)
                for index in range(len(slots)):
                    slots[index] = max(slots[index], index)
                if slots[-1] >= available_slots:
                    continue

            onsets = [Fraction(slot, slots_per_quarter) for slot in slots]
            gaps = [
                right - left for left, right in zip(onsets, onsets[1:]) if right > left
            ]
            fallback_duration = (
                statistics.median(gaps)
                if gaps
                else Fraction(1, slots_per_quarter)
            )
            for group_index, group in enumerate(groups):
                onset = onsets[group_index]
                if group_index + 1 < len(groups):
                    duration = onsets[group_index + 1] - onset
                else:
                    duration = min(fallback_duration, measure_duration - onset)
                if duration <= 0:
                    continue
                for event in group:
                    if Fraction(event["onset"]) != onset:
                        repositioned_events += 1
                    if Fraction(event["duration"]) != duration:
                        duration_repairs += 1
                    event["onset"] = _fraction_text(onset)
                    event["duration"] = _fraction_text(duration)
            reconstructed_streams += 1

    if removed_ids:
        score["events"] = [
            event for event in score["events"] if id(event) not in removed_ids
        ]
        score["events_count"] = len(score["events"])
    return {
        "applied": bool(reconstructed_streams),
        "method": "posição horizontal quantizada em semicolcheias ou fusas",
        "meter": meter,
        "measure_sixteenth_steps": measure_steps,
        "reconstructed_streams": reconstructed_streams,
        "repositioned_events": repositioned_events,
        "duration_repairs": duration_repairs,
        "impossible_prefix_events_removed": impossible_prefixes_removed,
        "removed_prefixes": removed_prefixes,
        "streams_using_thirty_second_grid": thirty_second_streams,
    }


def _pitch_number(pitch: str | None) -> int | None:
    if not pitch or pitch.startswith("unpitched:"):
        return None
    steps = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    step = pitch[0]
    index = 1
    alter = 0
    while index < len(pitch) and pitch[index] in "#b":
        alter += 1 if pitch[index] == "#" else -1
        index += 1
    try:
        octave = int(pitch[index:])
    except ValueError:
        return None
    return (octave + 1) * 12 + steps.get(step, 0) + alter


def _part_measure_tokens(score: dict) -> dict[tuple[str, int], dict[tuple[Fraction, Fraction], tuple[int, ...]]]:
    """Return chord-aware rhythmic/pitch tokens for cross-staff comparison."""
    grouped: dict[tuple[str, int, Fraction, Fraction], list[int]] = defaultdict(list)
    for event in score["events"]:
        number = _pitch_number(event.get("pitch"))
        if number is None:
            continue
        key = (
            event["part_id"],
            int(event["measure_index"]),
            Fraction(event["onset"]),
            Fraction(event["duration"]),
        )
        grouped[key].append(number)
    result: dict[tuple[str, int], dict[tuple[Fraction, Fraction], tuple[int, ...]]] = defaultdict(dict)
    for (part_id, measure, onset, duration), pitches in grouped.items():
        result[(part_id, measure)][(onset, duration)] = tuple(sorted(pitches))
    return result


def _comparison_for_measure(
    left: dict[tuple[Fraction, Fraction], tuple[int, ...]],
    right: dict[tuple[Fraction, Fraction], tuple[int, ...]],
) -> dict | None:
    left_positions = set(left)
    right_positions = set(right)
    union = left_positions | right_positions
    common = left_positions & right_positions
    if not union:
        return None
    timing_ratio = len(common) / len(union)
    offsets: list[int] = []
    comparable = 0
    for position in common:
        left_chord = left[position]
        right_chord = right[position]
        if len(left_chord) != len(right_chord):
            continue
        comparable += 1
        offsets.extend(right_pitch - left_pitch for left_pitch, right_pitch in zip(left_chord, right_chord))
    offset = offsets[0] if offsets and len(set(offsets)) == 1 else None
    pitch_ratio = comparable / len(common) if common else 0.0
    return {
        "timing_ratio": round(timing_ratio, 4),
        "common_positions": len(common),
        "positions_left": len(left_positions),
        "positions_right": len(right_positions),
        "same_chord_shape_ratio": round(pitch_ratio, 4),
        "constant_semitone_offset": offset,
    }


def _is_expected_doubling_pair(left_name: str, right_name: str) -> bool:
    """Limit weak rhythmic leads to families that commonly share a line here."""
    left = left_name.casefold()
    right = right_name.casefold()
    woodwind_markers = (
        "piccolo",
        "flûte",
        "hautbois",
        "cor anglais",
        "clarinette",
        "basson",
        "contrebasson",
    )
    string_markers = ("violons", "altos")
    left_woodwind = any(marker in left for marker in woodwind_markers)
    right_woodwind = any(marker in right for marker in woodwind_markers)
    left_strings = any(marker in left for marker in string_markers)
    right_strings = any(marker in right for marker in string_markers)
    return (left_woodwind and right_strings) or (right_woodwind and left_strings)


def analyze_doublings(score: dict, *, meter: str | None = None) -> dict:
    """Find evidence of doubled material without copying any notes.

    A candidate is only reported when the onset/duration grid agrees. Equal
    pitches or one stable transposition then distinguish an actual doubling from
    coincidental rhythmic similarity. The report is advisory: it never changes
    the recognised notes.
    """
    tokens = _part_measure_tokens(score)
    parts = score["parts"]
    measure_count = score.get("measures", 0)
    candidates: list[dict] = []
    rhythmic_leads: list[dict] = []
    for left_index, left_part in enumerate(parts):
        for right_part in parts[left_index + 1 :]:
            per_measure = []
            for measure in range(1, measure_count + 1):
                comparison = _comparison_for_measure(
                    tokens.get((left_part["id"], measure), {}),
                    tokens.get((right_part["id"], measure), {}),
                )
                if comparison is None or comparison["common_positions"] < 2:
                    continue
                comparison["measure"] = measure
                per_measure.append(comparison)
            if not per_measure:
                continue
            rhythmic = sum(item["timing_ratio"] for item in per_measure) / len(per_measure)
            strong = [item for item in per_measure if item["timing_ratio"] >= 0.9]
            offsets = {
                item["constant_semitone_offset"]
                for item in strong
                if item["constant_semitone_offset"] is not None
            }
            relation = None
            if strong and len(offsets) == 1:
                relation = "uníssono" if next(iter(offsets)) == 0 else "transposição constante"
            if rhythmic < 0.65 or not relation:
                if (
                    rhythmic >= 0.55
                    and _is_expected_doubling_pair(left_part["name"], right_part["name"])
                ):
                    rhythmic_leads.append(
                        {
                            "left": left_part,
                            "right": right_part,
                            "measures_with_rhythmic_evidence": [
                                item["measure"] for item in per_measure if item["timing_ratio"] >= 0.55
                            ],
                            "rhythmic_similarity": round(rhythmic, 4),
                            "reason": "ritmo parecido, mas alturas insuficientes para confirmar a duplicação",
                            "action": "comparar a imagem original antes de usar uma linha para corrigir a outra",
                        }
                    )
                continue
            candidates.append(
                {
                    "left": left_part,
                    "right": right_part,
                    "measures_with_evidence": [item["measure"] for item in strong],
                    "rhythmic_similarity": round(rhythmic, 4),
                    "relation": relation,
                    "semitone_offset_right_from_left": next(iter(offsets)),
                    "per_measure": per_measure,
                    "action": "revisar os dois instrumentos juntos; nenhuma nota foi copiada automaticamente",
                }
            )
    candidates.sort(
        key=lambda item: (
            -len(item["measures_with_evidence"]),
            -item["rhythmic_similarity"],
            item["left"]["id"],
            item["right"]["id"],
        )
    )
    return {
        "meter": meter,
        "method": (
            "compara posições de início, durações, acordes e deslocamento de altura; "
            "não cria nem substitui notas"
        ),
        "confirmed_doublings": candidates,
        "rhythmic_review_leads": sorted(
            rhythmic_leads,
            key=lambda item: (-item["rhythmic_similarity"], item["left"]["id"], item["right"]["id"]),
        ),
    }


def audit_measure_structure(score: dict, meter: str) -> dict:
    """Summarise recognized material per part/measure against a fixed meter."""
    beats_text, beat_type_text = meter.split("/", 1)
    expected = Fraction(int(beats_text) * 4, int(beat_type_text))
    events: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for event in score["events"]:
        events[(event["part_id"], int(event["measure_index"]))].append(event)
    measures = []
    for part in score["parts"]:
        for measure in range(1, score["measures"] + 1):
            current = events.get((part["id"], measure), [])
            pitched = [event for event in current if event.get("pitch")]
            ends = [Fraction(event["onset"]) + Fraction(event["duration"]) for event in current]
            maximum = max(ends, default=Fraction(0))
            measures.append(
                {
                    "part_id": part["id"],
                    "part_name": part["name"],
                    "measure": measure,
                    "pitched_events": len(pitched),
                    "last_event_end_quarters": str(maximum),
                    "expected_quarters": str(expected),
                    "within_meter": maximum <= expected,
                }
            )
    return {
        "meter": meter,
        "expected_quarters": str(expected),
        "measures": measures,
        "invalid_entries": [item for item in measures if not item["within_meter"]],
    }


def merge_measure_candidates(sources: list[Path], output: Path) -> dict:
    """Merge one-measure OMR exports while preserving their vertical part order."""
    if not sources:
        raise ValueError("nenhum compasso foi fornecido para reunião")
    roots = [ET.fromstring(_read_musicxml(source)) for source in sources]
    part_counts = [len(root.findall("part")) for root in roots]
    if len(set(part_counts)) != 1:
        raise ValueError(
            "o número de partes variou entre os compassos isolados: "
            + ", ".join(str(value) for value in part_counts)
        )
    root = copy.deepcopy(roots[0])
    base_parts = root.findall("part")
    source_parts = [item.findall("part") for item in roots]
    for part_index, base_part in enumerate(base_parts):
        for measure in list(base_part.findall("measure")):
            base_part.remove(measure)
        for measure_index, parts in enumerate(source_parts, 1):
            measures = parts[part_index].findall("measure")
            if not measures:
                raise ValueError(
                    f"a parte {part_index + 1} não contém o compasso isolado {measure_index}"
                )
            measure = copy.deepcopy(measures[0])
            measure.set("number", str(measure_index))
            if measure_index > 1:
                for print_node in list(measure.findall("print")):
                    measure.remove(print_node)
            base_part.append(measure)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    return {
        "output": str(output.resolve()),
        "measures": len(sources),
        "parts": part_counts[0],
        "sources": [str(source.resolve()) for source in sources],
    }


def apply_choros9_part_profile(source: Path, output: Path) -> dict:
    """Replace unreliable OCR labels using the edition's stable staff order."""
    root = ET.fromstring(_read_musicxml(source))
    score_parts = root.findall("./part-list/score-part")
    if len(score_parts) != len(CHOROS9_PART_NAMES):
        return {
            "applied": False,
            "reason": (
                f"foram reconhecidas {len(score_parts)} partes; "
                f"o perfil espera {len(CHOROS9_PART_NAMES)}"
            ),
            "recognized_parts": len(score_parts),
            "expected_parts": len(CHOROS9_PART_NAMES),
        }
    resolved = []
    for index, (score_part, name) in enumerate(
        zip(score_parts, CHOROS9_PART_NAMES), 1
    ):
        part_name = score_part.find("part-name")
        if part_name is None:
            part_name = ET.SubElement(score_part, "part-name")
        ocr_name = part_name.text or ""
        part_name.text = name
        abbreviation = score_part.find("part-abbreviation")
        if abbreviation is None:
            abbreviation = ET.SubElement(score_part, "part-abbreviation")
        abbreviation.text = name
        resolved.append(
            {
                "order": index,
                "id": score_part.get("id", ""),
                "ocr_name": ocr_name,
                "resolved_name": name,
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    return {
        "applied": True,
        "output": str(output.resolve()),
        "recognized_parts": len(score_parts),
        "expected_parts": len(CHOROS9_PART_NAMES),
        "parts": resolved,
    }
