from __future__ import annotations

import copy
import re
import statistics
import unicodedata
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

# Mapping from the 24 staves retained by the opening-page OMR to the expanded
# orchestral template supplied by the user. The reference IDs are top-to-bottom
# MuseScore/MusicXML part IDs; staff numbers distinguish grand staves.
CHOROS9_OPENING_REFERENCE_MAP: dict[str, tuple[tuple[str, str | None], ...]] = {
    "P1": (("P1", None),),
    "P2": (("P2", None), ("P3", None)),
    "P3": (("P4", None), ("P5", None)),
    "P4": (("P6", None),),
    "P5": (("P7", None), ("P8", None)),
    "P6": (("P9", None),),
    "P7": (("P10", None), ("P11", None)),
    "P8": (("P12", None),),
    "P9": (("P13", None), ("P14", None)),
    "P10": (("P15", None), ("P16", None)),
    "P11": (("P17", None), ("P18", None), ("P19", None), ("P20", None)),
    "P12": (("P21", None), ("P22", None)),
    "P13": (("P23", None), ("P24", None)),
    "P14": (("P25", None),),
    "P15": (("P26", None),),
    "P16": (("P29", "1"),),
    "P17": (("P29", "2"),),
    "P18": (("P30", "1"),),
    "P19": (("P30", "2"),),
    "P20": (("P31", None),),
    "P21": (("P32", None),),
    "P22": (("P33", None),),
    "P23": (("P34", None),),
    "P24": (("P35", None),),
}

CHOROS9_OPENING_STAFF_ROLES = (
    "piccolo",
    "flute",
    "oboe",
    "english-horn",
    "clarinet",
    "bass-clarinet",
    "bassoon",
    "contrabassoon",
    "horn",
    "horn",
    "trumpet",
    "trombone",
    "trombone",
    "tuba",
    "timpani",
    "celesta",
    "celesta",
    "harp",
    "harp",
    "violin",
    "violin",
    "viola",
    "cello",
    "bass",
)


def _ocr_staff_role(name: str) -> str | None:
    text = unicodedata.normalize("NFKD", name.casefold())
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"[^a-z]+", "", text)
    markers = (
        ("piccolo", ("pic", "pier")),
        ("flute", ("fl",)),
        ("oboe", ("haut", "hlb", "hub")),
        ("english-horn", ("cang", "corang")),
        ("bass-clarinet", ("clb", "clarb")),
        ("clarinet", ("clar", "clnr", "chr")),
        ("contrabassoon", ("cbon", "cbonn", "cbdon")),
        ("bassoon", ("bon", "basson")),
        ("horn", ("cor", "con")),
        ("trumpet", ("pist", "pin")),
        ("trombone", ("trb",)),
        ("tuba", ("tuba", "tub")),
        ("timpani", ("timb",)),
        ("celesta", ("cel",)),
        ("harp", ("hpe", "harp")),
        ("violin", ("viol", "lives", "iol")),
        ("viola", ("alt", "all")),
        ("cello", ("vcl",)),
        ("bass", ("cb", "cd")),
    )
    for role, aliases in markers:
        if any(text.startswith(alias) for alias in aliases):
            return role
    return None


def _align_opening_parts(names: list[str]) -> list[int]:
    """Align incomplete OMR part lists to the fixed 24-staff opening order."""
    roles = [_ocr_staff_role(name) for name in names]
    target = CHOROS9_OPENING_STAFF_ROLES
    source_count = len(roles)
    target_count = len(target)
    costs: dict[tuple[int, int], tuple[int, list[int]]] = {}

    def solve(source_index: int, target_index: int) -> tuple[int, list[int]]:
        key = (source_index, target_index)
        if key in costs:
            return costs[key]
        if source_index == source_count:
            result = ((target_count - target_index) * 2, [])
        elif target_count - target_index < source_count - source_index:
            result = (10**9, [])
        else:
            role = roles[source_index]
            match_penalty = 1 if role is None else 0 if role == target[target_index] else 10
            matched_cost, matched_path = solve(source_index + 1, target_index + 1)
            skipped_cost, skipped_path = solve(source_index, target_index + 1)
            match = (match_penalty + matched_cost, [target_index] + matched_path)
            skip = (2 + skipped_cost, skipped_path)
            result = min(match, skip, key=lambda item: item[0])
        costs[key] = result
        return result

    cost, mapping = solve(0, 0)
    if cost >= 10**9 or len(mapping) != source_count:
        raise ValueError("não foi possível alinhar as pautas reconhecidas à grade de abertura")
    return mapping


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


def _event_counter(
    events: list[dict], *, include_pitch: bool
) -> dict[tuple, int]:
    counter: dict[tuple, int] = defaultdict(int)
    for event in events:
        key = (
            int(event["measure_index"]),
            event["onset"],
            event["duration"],
            event.get("pitch") if include_pitch else bool(event.get("pitch")),
        )
        counter[key] += 1
    return counter


def _counter_metric(reference: dict[tuple, int], candidate: dict[tuple, int]) -> dict:
    keys = set(reference) | set(candidate)
    matched = sum(min(reference.get(key, 0), candidate.get(key, 0)) for key in keys)
    reference_count = sum(reference.values())
    candidate_count = sum(candidate.values())
    precision = matched / candidate_count if candidate_count else 0.0
    recall = matched / reference_count if reference_count else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "matched": matched,
        "reference": reference_count,
        "candidate": candidate_count,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def analyze_reference_calibration(
    candidate: dict, reference: dict, *, verified_measures: int = 3
) -> dict:
    """Compare condensed OMR with an expanded, manually verified reference."""
    reconstruction = reconstruct_scanned_rhythm(candidate, "4/4")
    candidate_parts = {part["id"]: part["name"] for part in candidate["parts"]}
    reference_parts = {part["id"]: part["name"] for part in reference["parts"]}
    per_source = []
    identical_target_pairs = []
    reference_events_by_part: dict[str, list[dict]] = defaultdict(list)
    for event in reference["events"]:
        if int(event["measure_index"]) <= verified_measures and event.get("pitch"):
            reference_events_by_part[event["part_id"]].append(event)

    for source_id, targets in CHOROS9_OPENING_REFERENCE_MAP.items():
        source_events = [
            event
            for event in candidate["events"]
            if event["part_id"] == source_id
            and int(event["measure_index"]) <= verified_measures
            and event.get("pitch")
        ]
        target_events = []
        target_names = []
        target_token_sets: list[tuple[str, dict[tuple, int]]] = []
        for target_id, staff in targets:
            selected = [
                event
                for event in reference_events_by_part.get(target_id, [])
                if staff is None or event.get("staff", "1") == staff
            ]
            target_events.extend(selected)
            label = reference_parts.get(target_id, target_id)
            if staff:
                label = f"{label} — pauta {staff}"
            target_names.append(label)
            target_token_sets.append((label, _event_counter(selected, include_pitch=True)))
        for left_index, (left_name, left_tokens) in enumerate(target_token_sets):
            for right_name, right_tokens in target_token_sets[left_index + 1 :]:
                if left_tokens and left_tokens == right_tokens:
                    identical_target_pairs.append(
                        {
                            "source_part": source_id,
                            "left": left_name,
                            "right": right_name,
                            "relation": "duplicação exata nos compassos verificados",
                        }
                    )
        per_source.append(
            {
                "source_part": source_id,
                "source_name": candidate_parts.get(source_id, source_id),
                "reference_targets": target_names,
                "pitch_and_timing": _counter_metric(
                    _event_counter(target_events, include_pitch=True),
                    _event_counter(source_events, include_pitch=True),
                ),
                "timing_only": _counter_metric(
                    _event_counter(target_events, include_pitch=False),
                    _event_counter(source_events, include_pitch=False),
                ),
                "reference_tuplet_events": sum(
                    bool(event.get("tuplet")) for event in target_events
                ),
                "candidate_tuplet_events": sum(
                    bool(event.get("tuplet")) for event in source_events
                ),
            }
        )

    reference_tuplet_parts = [
        {
            "part_id": part_id,
            "part_name": reference_parts.get(part_id, part_id),
            "events": sum(bool(event.get("tuplet")) for event in events),
        }
        for part_id, events in reference_events_by_part.items()
        if any(event.get("tuplet") for event in events)
    ]
    return {
        "verified_measures": verified_measures,
        "candidate_position_reconstruction": reconstruction,
        "source_to_reference_map": per_source,
        "identical_reference_targets": identical_target_pairs,
        "reference_tuplet_parts": reference_tuplet_parts,
        "ignored_reference_measures": list(
            range(verified_measures + 1, reference.get("measures", 0) + 1)
        ),
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
    maximum_parts = max(part_counts)
    if len(set(part_counts)) != 1 and maximum_parts != len(CHOROS9_OPENING_STAFF_ROLES):
        raise ValueError(
            "o número de partes variou entre os compassos isolados: "
            + ", ".join(str(value) for value in part_counts)
        )
    template_index = part_counts.index(maximum_parts)
    root = copy.deepcopy(roots[template_index])
    base_parts = root.findall("part")
    source_parts = [item.findall("part") for item in roots]
    source_names = [
        {
            score_part.get("id", ""): score_part.findtext("part-name") or ""
            for score_part in item.findall("./part-list/score-part")
        }
        for item in roots
    ]
    alignments = []
    for index, parts in enumerate(source_parts):
        if len(parts) == maximum_parts:
            alignments.append(list(range(maximum_parts)))
        else:
            names = [
                source_names[index].get(part.get("id", ""), "")
                for part in parts
            ]
            alignments.append(_align_opening_parts(names))
    padded_parts: list[dict] = []
    for part_index, base_part in enumerate(base_parts):
        for measure in list(base_part.findall("measure")):
            base_part.remove(measure)
        for measure_index, (parts, alignment) in enumerate(
            zip(source_parts, alignments), 1
        ):
            source_part_index = next(
                (
                    index
                    for index, target_part_index in enumerate(alignment)
                    if target_part_index == part_index
                ),
                None,
            )
            if source_part_index is None:
                measure = ET.Element("measure")
                template_measure = roots[template_index].findall("part")[
                    part_index
                ].find("measure")
                if template_measure is not None:
                    attributes = template_measure.find("attributes")
                    if attributes is not None:
                        measure.append(copy.deepcopy(attributes))
                padded_parts.append(
                    {"measure": measure_index, "part": part_index + 1}
                )
            else:
                measures = parts[source_part_index].findall("measure")
                if not measures:
                    raise ValueError(
                        f"a parte {source_part_index + 1} não contém "
                        f"o compasso isolado {measure_index}"
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
        "parts": maximum_parts,
        "source_part_counts": part_counts,
        "padded_parts": padded_parts,
        "sources": [str(source.resolve()) for source in sources],
    }


def extract_measure_candidate(
    source: Path, output: Path, measure_index: int
) -> dict:
    """Create a standalone candidate from one measure of a full-page export."""
    root = ET.fromstring(_read_musicxml(source))
    parts = root.findall("part")
    if not parts:
        raise ValueError("o candidato não contém partes")
    extracted_number = None
    for part_index, part in enumerate(parts, 1):
        measures = part.findall("measure")
        if not measures:
            raise ValueError(f"a parte {part_index} não contém compassos")
        try:
            selected = measures[measure_index]
        except IndexError as exc:
            raise ValueError(
                f"a parte {part_index} não contém o compasso solicitado"
            ) from exc
        if extracted_number is None:
            extracted_number = selected.get("number")
        selected_copy = copy.deepcopy(selected)
        selected_copy.set("number", "1")
        for measure in measures:
            part.remove(measure)
        part.append(selected_copy)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    return {
        "source": str(source.resolve()),
        "output": str(output.resolve()),
        "measure_index": measure_index,
        "source_measure_number": extracted_number,
        "parts": len(parts),
    }


def _pitch_rank(note: ET.Element) -> int:
    pitch = note.find("pitch")
    if pitch is None:
        return -10**6
    steps = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    step = steps.get(pitch.findtext("step") or "", 0)
    alter = int(float(pitch.findtext("alter") or "0"))
    octave = int(pitch.findtext("octave") or "0")
    return (octave + 1) * 12 + step + alter


def _pitch_label(note: ET.Element) -> str | None:
    pitch = note.find("pitch")
    if pitch is None:
        return None
    alter = int(float(pitch.findtext("alter") or "0"))
    accidental = "#" * max(0, alter) + "b" * max(0, -alter)
    return f"{pitch.findtext('step')}{accidental}{pitch.findtext('octave')}"


def _remove_print_nodes(measure: ET.Element) -> None:
    for print_node in list(measure.findall("print")):
        measure.remove(print_node)


def _split_melodic_measure(
    source: ET.Element,
    *,
    target_slot: int,
    target_count: int,
    source_part: str,
    target_part: str,
    global_measure: int,
    report: dict,
) -> ET.Element:
    """Turn a condensed wind/brass chord into one playable line per player."""
    measure = copy.deepcopy(source)
    _remove_print_nodes(measure)
    children = list(measure)
    groups: list[list[ET.Element]] = []
    current: list[ET.Element] | None = None
    for child in children:
        if child.tag != "note":
            continue
        if child.find("chord") is None or current is None:
            current = [child]
            groups.append(current)
        else:
            current.append(child)
    for group in groups:
        pitched = [note for note in group if note.find("pitch") is not None]
        if len(pitched) <= 1:
            continue
        ordered = sorted(pitched, key=_pitch_rank, reverse=True)
        if target_count == 1:
            selected_index = len(ordered) // 2
        else:
            selected_index = round(
                target_slot * (len(ordered) - 1) / (target_count - 1)
            )
        selected = ordered[selected_index]
        removed = []
        for note in pitched:
            if note is selected:
                chord = note.find("chord")
                if chord is not None:
                    note.remove(chord)
                continue
            removed.append(_pitch_label(note))
            measure.remove(note)
        report["condensed_chord_notes_removed"] += len(removed)
        report["condensed_chord_repairs"].append(
            {
                "measure": global_measure,
                "source_part": source_part,
                "target_part": target_part,
                "target_slot": target_slot + 1,
                "target_count": target_count,
                "kept_pitch": _pitch_label(selected),
                "removed_pitches": removed,
            }
        )
        if len(ordered) > target_count and target_slot == 0:
            report["ambiguous_chord_groups"].append(
                {
                    "measure": global_measure,
                    "source_part": source_part,
                    "recognized_pitches": [
                        _pitch_label(note) for note in ordered
                    ],
                    "available_players": target_count,
                }
            )
    return measure


def _set_staff_number(element: ET.Element, staff_number: str) -> None:
    for note in element.iter("note"):
        staff = note.find("staff")
        if staff is None:
            staff = ET.SubElement(note, "staff")
        staff.text = staff_number
    for direction in element.iter("direction"):
        staff = direction.find("staff")
        if staff is None:
            staff = ET.SubElement(direction, "staff")
        staff.text = staff_number


def _combine_grand_staff_measure(
    upper_source: ET.Element,
    lower_source: ET.Element,
    target_part: ET.Element,
    number: int,
) -> ET.Element:
    upper = copy.deepcopy(upper_source)
    lower = copy.deepcopy(lower_source)
    _remove_print_nodes(upper)
    _remove_print_nodes(lower)
    _set_staff_number(upper, "1")
    _set_staff_number(lower, "2")
    result = ET.Element("measure", {"number": str(number)})

    upper_attributes = upper.find("attributes")
    if upper_attributes is not None:
        attributes = copy.deepcopy(upper_attributes)
    else:
        attributes = ET.Element("attributes")
        ET.SubElement(attributes, "divisions").text = "3360"
        time = ET.SubElement(attributes, "time")
        ET.SubElement(time, "beats").text = "4"
        ET.SubElement(time, "beat-type").text = "4"
    staves = attributes.find("staves")
    if staves is None:
        staves = ET.SubElement(attributes, "staves")
    staves.text = "2"
    for clef in list(attributes.findall("clef")):
        attributes.remove(clef)
    reference_attributes = target_part.find("./measure/attributes")
    if reference_attributes is not None:
        for clef in reference_attributes.findall("clef"):
            attributes.append(copy.deepcopy(clef))
    result.append(attributes)

    upper_barlines = [copy.deepcopy(node) for node in upper.findall("barline")]
    lower_barlines = [copy.deepcopy(node) for node in lower.findall("barline")]
    for child in list(upper):
        if child.tag not in {"attributes", "print", "barline"}:
            result.append(copy.deepcopy(child))
    divisions = int(attributes.findtext("divisions") or "3360")
    backup = ET.SubElement(result, "backup")
    ET.SubElement(backup, "duration").text = str(divisions * 4)
    for child in list(lower):
        if child.tag not in {"attributes", "print", "barline"}:
            result.append(copy.deepcopy(child))
    for barline in lower_barlines or upper_barlines:
        result.append(barline)
    return result


def _full_measure_rest(number: int, divisions: int = 3360) -> ET.Element:
    measure = ET.Element("measure", {"number": str(number)})
    attributes = ET.SubElement(measure, "attributes")
    ET.SubElement(attributes, "divisions").text = str(divisions)
    time = ET.SubElement(attributes, "time")
    ET.SubElement(time, "beats").text = "4"
    ET.SubElement(time, "beat-type").text = "4"
    note = ET.SubElement(measure, "note")
    ET.SubElement(note, "rest", {"measure": "yes"})
    ET.SubElement(note, "duration").text = str(divisions * 4)
    ET.SubElement(note, "voice").text = "1"
    ET.SubElement(note, "type").text = "whole"
    return measure


def build_choros9_continuous_musicxml(
    opening: Path,
    continuations: list[Path],
    output: Path,
) -> dict:
    """Expand scanned continuation pages into the verified 35-part template."""
    root = ET.fromstring(_read_musicxml(opening))
    target_parts = {part.get("id", ""): part for part in root.findall("part")}
    if len(target_parts) != 35:
        raise ValueError(
            f"a abertura precisa ter 35 partes; encontradas {len(target_parts)}"
        )
    opening_measures = {
        len(part.findall("measure")) for part in target_parts.values()
    }
    if opening_measures != {3}:
        raise ValueError(
            "a abertura contínua precisa conter exatamente três compassos verificados"
        )
    for part in target_parts.values():
        for index, measure in enumerate(part.findall("measure"), 1):
            measure.set("number", str(index))
            _remove_print_nodes(measure)

    target_mapping: dict[str, tuple[str, str | None, int, int]] = {}
    for source_id, targets in CHOROS9_OPENING_REFERENCE_MAP.items():
        melodic_targets = [target for target in targets if target[1] is None]
        for target_id, staff in targets:
            slot = (
                melodic_targets.index((target_id, staff))
                if staff is None
                else 0
            )
            target_mapping[target_id] = (
                source_id,
                staff,
                slot,
                len(melodic_targets) if staff is None else 1,
            )

    report = {
        "opening": str(opening.resolve()),
        "continuations": [str(path.resolve()) for path in continuations],
        "parts": 35,
        "staves": 37,
        "verified_opening_measures": 3,
        "continuation_measures": 0,
        "condensed_chord_notes_removed": 0,
        "condensed_chord_repairs": [],
        "ambiguous_chord_groups": [],
        "empty_percussion_measures": 0,
        "page_break_measures": [],
    }
    global_measure = 3
    polyphonic_sources = {
        "P15",
        "P16",
        "P17",
        "P18",
        "P19",
        "P20",
        "P21",
        "P22",
        "P23",
        "P24",
    }
    for continuation in continuations:
        continuation_root = ET.fromstring(_read_musicxml(continuation))
        source_parts = {
            part.get("id", ""): part for part in continuation_root.findall("part")
        }
        if len(source_parts) != 24:
            raise ValueError(
                f"{continuation} precisa ter 24 pautas condensadas; "
                f"foram encontradas {len(source_parts)}"
            )
        measure_counts = {
            len(part.findall("measure")) for part in source_parts.values()
        }
        if len(measure_counts) != 1:
            raise ValueError(
                f"{continuation} possui contagens de compassos divergentes: "
                f"{sorted(measure_counts)}"
            )
        page_measure_count = measure_counts.pop()
        if page_measure_count < 1:
            raise ValueError(f"{continuation} não contém compassos")
        for local_measure in range(page_measure_count):
            global_measure += 1
            if local_measure == 0:
                report["page_break_measures"].append(global_measure)
            for target_id, target_part in target_parts.items():
                if target_id in {"P27", "P28"}:
                    measure = _full_measure_rest(global_measure)
                    report["empty_percussion_measures"] += 1
                elif target_id == "P29":
                    measure = _combine_grand_staff_measure(
                        source_parts["P16"].findall("measure")[local_measure],
                        source_parts["P17"].findall("measure")[local_measure],
                        target_part,
                        global_measure,
                    )
                elif target_id == "P30":
                    measure = _combine_grand_staff_measure(
                        source_parts["P18"].findall("measure")[local_measure],
                        source_parts["P19"].findall("measure")[local_measure],
                        target_part,
                        global_measure,
                    )
                else:
                    source_id, _, target_slot, target_count = target_mapping[
                        target_id
                    ]
                    source_measure = source_parts[source_id].findall("measure")[
                        local_measure
                    ]
                    if source_id in polyphonic_sources:
                        measure = copy.deepcopy(source_measure)
                        _remove_print_nodes(measure)
                    else:
                        measure = _split_melodic_measure(
                            source_measure,
                            target_slot=target_slot,
                            target_count=target_count,
                            source_part=source_id,
                            target_part=target_id,
                            global_measure=global_measure,
                            report=report,
                        )
                    measure.set("number", str(global_measure))
                if target_id == "P1" and local_measure == 0:
                    page_break = ET.Element("print", {"new-page": "yes"})
                    measure.insert(0, page_break)
                target_part.append(measure)
            report["continuation_measures"] += 1

    work_title = root.find("./work/work-title")
    if work_title is not None:
        work_title.text = "Choros No. 9 - abertura (rascunho OMR)"
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    report["measures"] = global_measure
    report["output"] = str(output.resolve())
    return report


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
