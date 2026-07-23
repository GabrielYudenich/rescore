from __future__ import annotations

import copy
import html
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

from .musicxml import _read_musicxml, normalize_part_name, parse_musicxml


# 96 covers binary values and triplets; multiplying by 5 and 7 also makes
# quintuplets and septuplets exact without rounding any musical duration.
DIVISIONS = 3360


def _unescape(value: str) -> str:
    previous = value
    for _ in range(3):
        current = html.unescape(previous)
        if current == previous:
            return current
        previous = current
    return previous


def _clone_event(event: dict, target_part: str, staff: str | None = None) -> dict:
    cloned = copy.deepcopy(event)
    cloned["part_id"] = target_part
    if staff is not None:
        cloned["staff"] = staff
    return cloned


def _pitch_number(pitch: str | None) -> int:
    if not pitch:
        return -999
    match = re.fullmatch(r"([A-G])([#b]*)(-?\d+)", pitch)
    if not match:
        return -999
    step, accidentals, octave_text = match.groups()
    semitone = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[step]
    semitone += accidentals.count("#") - accidentals.count("b")
    return (int(octave_text) + 1) * 12 + semitone


def _copy_all(events: list[dict], target: str, staff: str | None = None) -> list[dict]:
    return [_clone_event(event, target, staff) for event in events]


def _split_shared(
    events: list[dict],
    first_target: str,
    second_target: str,
    duplicate_single: bool,
) -> list[dict]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for event in events:
        grouped[
            (
                event["measure_index"],
                event["onset"],
                event["duration"],
                event["staff"],
                event["voice"],
            )
        ].append(event)

    result: list[dict] = []
    for group in grouped.values():
        ordered = sorted(group, key=lambda item: _pitch_number(item.get("pitch")), reverse=True)
        if len(ordered) == 1:
            result.append(_clone_event(ordered[0], first_target))
            if duplicate_single:
                result.append(_clone_event(ordered[0], second_target))
            continue
        split_at = (len(ordered) + 1) // 2
        result.extend(_clone_event(event, first_target) for event in ordered[:split_at])
        result.extend(_clone_event(event, second_target) for event in ordered[split_at:])
    return result


def map_sinfonia10_scherzo(candidate: dict) -> dict[str, list[dict]]:
    """Expand the condensed Scherzo layout into the 30-part target template."""
    source: dict[str, list[dict]] = defaultdict(list)
    for event in candidate["events"]:
        if event.get("pitch"):
            source[event["part_id"]].append(event)

    mapped: dict[str, list[dict]] = defaultdict(list)
    # A single-sheet result is P1..P17. In a two-sheet Audiveris result, the
    # first sheet is P14..P30 because it creates a union of both page layouts.
    page67_ids = [f"P{i}" for i in range(1, 18)]
    if candidate.get("parts_count", 0) > 17:
        page67_ids = [f"P{i}" for i in range(14, 31)]
    page67 = {
        f"P{index}": [event for event in source[source_id] if event["measure_index"] <= 8]
        for index, source_id in enumerate(page67_ids, 1)
    }

    for event in _split_shared(page67["P1"], "P1", "P2", duplicate_single=True):
        mapped[event["part_id"]].append(event)
    for event in _split_shared(page67["P2"], "P3", "P4", duplicate_single=True):
        mapped[event["part_id"]].append(event)
    for event in _split_shared(page67["P3"], "P5", "P6", duplicate_single=True):
        mapped[event["part_id"]].append(event)
    for event in _split_shared(page67["P4"], "P7", "P8", duplicate_single=False):
        mapped[event["part_id"]].append(event)

    mapped["P11"].extend(_copy_all(page67["P5"], "P11"))
    mapped["P12"].extend(_copy_all(page67["P6"], "P12"))
    mapped["P13"].extend(_copy_all(page67["P7"], "P13"))
    mapped["P14"].extend(_copy_all(page67["P7"], "P14"))
    mapped["P15"].extend(_copy_all(page67["P8"], "P15"))
    mapped["P16"].extend(_copy_all(page67["P8"], "P16"))
    mapped["P18"].extend(_copy_all(page67["P9"], "P18"))

    for event in page67["P10"]:
        target = "P24" if event["staff"] == "1" else "P25"
        mapped[target].append(_clone_event(event, target, "1"))
    mapped["P22"].extend(_copy_all(page67["P11"], "P22"))

    for event in _copy_all(page67["P12"], "P23"):
        if event["measure_index"] <= 3:
            event["onset"] = str(Fraction(event["onset"]) * Fraction(3, 2))
            event["duration"] = str(Fraction(event["duration"]) * Fraction(3, 2))
            event["type"] = "eighth"
            event["tuplet"] = {"actual": "6", "normal": "9"}
        mapped["P23"].append(event)

    mapped["P26"].extend(_copy_all(page67["P13"], "P26"))
    mapped["P27"].extend(_copy_all(page67["P14"], "P27"))
    mapped["P28"].extend(_copy_all(page67["P15"], "P28"))
    mapped["P29"].extend(_copy_all(page67["P16"], "P29"))
    mapped["P30"].extend(_copy_all(page67["P17"], "P30"))

    if candidate.get("measures", 0) > 8:
        page68: dict[str, list[dict]] = defaultdict(
            list,
            {
                part_id: [event for event in events if event["measure_index"] >= 9]
                for part_id, events in source.items()
            },
        )
        for event in _split_shared(page68["P1"], "P3", "P4", duplicate_single=True):
            mapped[event["part_id"]].append(event)
        for event in _split_shared(page68["P2"], "P5", "P6", duplicate_single=True):
            mapped[event["part_id"]].append(event)
        for event in _split_shared(page68["P4"], "P7", "P8", duplicate_single=False):
            mapped[event["part_id"]].append(event)
        for event in _split_shared(page68["P5"], "P9", "P10", duplicate_single=True):
            mapped[event["part_id"]].append(event)
        mapped["P11"].extend(_copy_all(page68["P7"], "P11"))
        mapped["P12"].extend(_copy_all(page68["P8"], "P12"))
        mapped["P13"].extend(_copy_all(page68["P9"], "P13"))
        mapped["P14"].extend(_copy_all(page68["P10"], "P14"))
        mapped["P15"].extend(_copy_all(page68["P11"], "P15"))
        mapped["P16"].extend(_copy_all(page68["P12"], "P16"))
        mapped["P18"].extend(_copy_all(page68["P13"], "P18"))
        mapped["P23"].extend(_copy_all(page68["P23"], "P23"))
        mapped["P26"].extend(_copy_all(page68["P31"], "P26"))
        mapped["P27"].extend(_copy_all(page68["P32"], "P27"))
        mapped["P28"].extend(_copy_all(page68["P33"], "P28"))
        mapped["P29"].extend(_copy_all(page68["P34"], "P29"))
        mapped["P30"].extend(_copy_all(page68["P35"], "P30"))
    # At lower resolutions P17 may be absent; the target then remains an empty staff.
    return mapped


# Compatibility with manifests/scripts produced during the page-67 prototype.
map_sinfonia10_page67 = map_sinfonia10_scherzo


def map_sinfonia10_page69(candidate: dict, measure_offset: int = 17) -> dict[str, list[dict]]:
    """Map printed page 63 (PDF page 69) and restore its three 4:3 string tuplets."""
    source: dict[str, list[dict]] = defaultdict(list)
    for event in candidate["events"]:
        if event.get("pitch"):
            source[event["part_id"]].append(event)
    local: dict[str, list[dict]] = defaultdict(list)
    for event in _split_shared(source["P1"], "P3", "P4", duplicate_single=True):
        local[event["part_id"]].append(event)
    for event in _split_shared(source["P2"], "P5", "P6", duplicate_single=True):
        local[event["part_id"]].append(event)
    for event in _split_shared(source["P4"], "P7", "P8", duplicate_single=True):
        local[event["part_id"]].append(event)
    for event in source["P5"]:
        target = "P9" if event.get("voice", "1") == "1" else "P10"
        local[target].append(_clone_event(event, target))
    local["P11"].extend(_copy_all(source["P7"], "P11"))
    local["P12"].extend(_copy_all(source["P8"], "P12"))
    local["P13"].extend(_copy_all(source["P9"], "P13"))
    local["P14"].extend(_copy_all(source["P10"], "P14"))
    local["P15"].extend(_copy_all(source["P11"], "P15"))
    local["P16"].extend(_copy_all(source["P12"], "P16"))
    local["P18"].extend(_copy_all(source["P13"], "P18"))
    local["P23"].extend(_copy_all(source["P14"], "P23"))
    local["P26"].extend(_copy_all(source["P15"], "P26"))
    local["P27"].extend(_copy_all(source["P16"], "P27"))
    local["P28"].extend(_copy_all(source["P17"], "P28"))
    local["P29"].extend(_copy_all(source["P18"], "P29"))
    local["P30"].extend(_copy_all(source["P19"], "P30"))

    mapped: dict[str, list[dict]] = defaultdict(list)
    for target, events in local.items():
        for event in events:
            cloned = copy.deepcopy(event)
            if target in {"P26", "P27", "P28"} and cloned["measure_index"] == 1:
                original_onset = Fraction(cloned["onset"])
                cloned["onset"] = str(original_onset * Fraction(3, 2))
                cloned["duration"] = str(Fraction(cloned["duration"]) * Fraction(3, 2))
                cloned["type"] = "eighth"
                cloned["dots"] = 0
                cloned["tuplet"] = {"actual": "4", "normal": "3"}
                cloned["tuplet_group"] = f"{target}-18-{int(original_onset)}"
            cloned["measure_index"] += measure_offset
            cloned["measure_number"] = str(cloned["measure_index"])
            mapped[target].append(cloned)
    return mapped


def _measure_duration(part_id: str, measure_index: int) -> Fraction:
    if part_id in {"P28", "P29", "P30"} and measure_index <= 3:
        return Fraction(3)
    return Fraction(9, 2)


_DURATION_BASES = {
    "whole": Fraction(4),
    "half": Fraction(2),
    "quarter": Fraction(1),
    "eighth": Fraction(1, 2),
    "16th": Fraction(1, 4),
    "32nd": Fraction(1, 8),
    "64th": Fraction(1, 16),
    "128th": Fraction(1, 32),
}


def _duration_notation(
    duration: Fraction, tuplet: dict | None = None
) -> tuple[str, int] | None:
    nominal = duration
    if tuplet:
        nominal *= Fraction(int(tuplet["actual"]), int(tuplet["normal"]))
    for note_type, base in _DURATION_BASES.items():
        value = base
        for dots in range(4):
            if value == nominal:
                return note_type, dots
            value += base / (2 ** (dots + 1))
    return None


def _inferred_tuplet(duration: Fraction) -> dict | None:
    for actual, normal in ((3, 2), (2, 3), (5, 4), (6, 4), (7, 4), (4, 3), (9, 8)):
        tuplet = {"actual": str(actual), "normal": str(normal)}
        if _duration_notation(duration, tuplet):
            return tuplet
    return None


def _split_notatable_duration(duration: Fraction) -> list[Fraction]:
    choices = sorted(
        {
            base * sum(Fraction(1, 2**index) for index in range(dots + 1))
            for base in _DURATION_BASES.values()
            for dots in range(4)
            if (base * sum(Fraction(1, 2**index) for index in range(dots + 1)) * DIVISIONS).denominator
            == 1
        },
        reverse=True,
    )
    remaining = duration
    pieces: list[Fraction] = []
    while remaining:
        piece = next((choice for choice in choices if choice <= remaining), None)
        if piece is None:
            raise ValueError(f"duração não pode ser grafada exatamente: {duration}")
        pieces.append(piece)
        remaining -= piece
    return pieces


def _append_pitch(note: ET.Element, pitch_text: str | None) -> None:
    if pitch_text and pitch_text.startswith("unpitched:"):
        match = re.fullmatch(r"unpitched:([A-G])(-?\d+)", pitch_text)
        unpitched = ET.SubElement(note, "unpitched")
        ET.SubElement(unpitched, "display-step").text = match.group(1) if match else "C"
        ET.SubElement(unpitched, "display-octave").text = match.group(2) if match else "5"
        return
    match = re.fullmatch(r"([A-G])([#b]*)(-?\d+)", pitch_text or "")
    if not match:
        ET.SubElement(note, "rest")
        return
    step, accidentals, octave = match.groups()
    pitch = ET.SubElement(note, "pitch")
    ET.SubElement(pitch, "step").text = step
    alter = accidentals.count("#") - accidentals.count("b")
    if alter:
        ET.SubElement(pitch, "alter").text = str(alter)
    ET.SubElement(pitch, "octave").text = octave


def _append_note(
    parent: ET.Element,
    event: dict | None,
    duration: Fraction,
    voice: str,
    staff: str,
    chord: bool = False,
    tuplet_marker: str | tuple[str, ...] | None = None,
) -> None:
    note = ET.SubElement(parent, "note")
    if chord:
        ET.SubElement(note, "chord")
    if event is None:
        ET.SubElement(note, "rest")
    else:
        _append_pitch(note, event.get("pitch"))
    duration_value = duration * DIVISIONS
    if duration_value.denominator != 1:
        raise ValueError(f"duração não representável: {duration}")
    ET.SubElement(note, "duration").text = str(duration_value.numerator)
    ET.SubElement(note, "voice").text = voice
    tuplet = event.get("tuplet") if event else None
    notation = _duration_notation(duration, tuplet)
    if notation is None:
        raise ValueError(f"duração sem grafia correspondente: {duration}")
    note_type, dots = notation
    ET.SubElement(note, "type").text = note_type
    for _ in range(dots):
        ET.SubElement(note, "dot")
    if event:
        if tuplet:
            modification = ET.SubElement(note, "time-modification")
            ET.SubElement(modification, "actual-notes").text = tuplet["actual"]
            ET.SubElement(modification, "normal-notes").text = tuplet["normal"]
        for tie_type in event.get("ties", []):
            ET.SubElement(note, "tie", {"type": tie_type})
        if event.get("ties") or event.get("articulations") or tuplet_marker or event.get("tremolo"):
            notations = ET.SubElement(note, "notations")
            for tie_type in event.get("ties", []):
                ET.SubElement(notations, "tied", {"type": tie_type})
            if tuplet_marker:
                markers = (tuplet_marker,) if isinstance(tuplet_marker, str) else tuplet_marker
                for marker in markers:
                    ET.SubElement(notations, "tuplet", {"type": marker, "bracket": "yes"})
            if event.get("articulations"):
                articulations = ET.SubElement(notations, "articulations")
                for articulation in event["articulations"]:
                    ET.SubElement(articulations, articulation)
            if event.get("tremolo"):
                ornaments = ET.SubElement(notations, "ornaments")
                tremolo = ET.SubElement(
                    ornaments,
                    "tremolo",
                    {"type": event["tremolo"]["type"]},
                )
                tremolo.text = str(event["tremolo"].get("marks", 3))
    ET.SubElement(note, "staff").text = staff
    if event:
        for lyric_data in event.get("lyrics", []):
            lyric_attributes = {
                key: lyric_data[key]
                for key in ("number", "name")
                if lyric_data.get(key)
            }
            lyric = ET.SubElement(note, "lyric", lyric_attributes)
            if lyric_data.get("syllabic"):
                ET.SubElement(lyric, "syllabic").text = lyric_data["syllabic"]
            if lyric_data.get("text") is not None:
                ET.SubElement(lyric, "text").text = lyric_data["text"]
            if lyric_data.get("extend"):
                ET.SubElement(lyric, "extend", {"type": lyric_data["extend"]})


def _append_rest_duration(
    measure: ET.Element, duration: Fraction, voice: str, staff: str
) -> None:
    try:
        pieces = _split_notatable_duration(duration)
    except ValueError:
        # An arbitrary tuplet rest used only to fill a cursor gap makes
        # MuseScore create an incomplete tuplet and extend the whole measure.
        # An unprinted spacer rest retains the exact cursor endpoint for
        # validation but omits ``type``/``time-modification`` so MuseScore does
        # not invent a standalone, incomplete tuplet around it.
        note = ET.SubElement(measure, "note", {"print-object": "no"})
        ET.SubElement(note, "rest")
        value = duration * DIVISIONS
        if value.denominator != 1:
            raise ValueError(f"deslocamento não representável: {duration}")
        ET.SubElement(note, "duration").text = str(value.numerator)
        ET.SubElement(note, "voice").text = voice
        ET.SubElement(note, "staff").text = staff
        return
    for piece in pieces:
        _append_note(measure, None, piece, voice, staff)


def _append_clef_attributes(
    measure: ET.Element, changes: list[tuple[int, str, int]]
) -> None:
    attributes = ET.SubElement(measure, "attributes")
    for staff, sign, line in changes:
        clef = ET.SubElement(attributes, "clef", {"number": str(staff)})
        ET.SubElement(clef, "sign").text = sign
        ET.SubElement(clef, "line").text = str(line)


def _event_pieces(event: dict, duration: Fraction) -> list[tuple[dict, Fraction]]:
    if event.get("tuplet") or _duration_notation(duration):
        return [(event, duration)]
    try:
        durations = _split_notatable_duration(duration)
    except ValueError:
        tuplet = _inferred_tuplet(duration)
        if tuplet is None:
            raise
        cloned = copy.deepcopy(event)
        cloned["tuplet"] = tuplet
        cloned["_standalone_tuplet"] = True
        return [(cloned, duration)]
    result: list[tuple[dict, Fraction]] = []
    original_ties = set(event.get("ties", []))
    for index, piece in enumerate(durations):
        cloned = copy.deepcopy(event)
        ties = set(original_ties)
        if index > 0:
            ties.add("stop")
            cloned["articulations"] = []
            cloned["lyrics"] = []
        if index < len(durations) - 1:
            ties.add("start")
        cloned["ties"] = sorted(ties)
        cloned["tuplet"] = None
        result.append((cloned, piece))
    return result


def _emit_voice(
    measure: ET.Element,
    events: list[dict],
    measure_duration: Fraction,
    voice: str,
    staff: str,
    clef_changes: list[tuple[Fraction, int, str, int]] | None = None,
) -> None:
    groups: dict[tuple[Fraction, Fraction], list[dict]] = defaultdict(list)
    for event in events:
        onset = Fraction(event["onset"])
        duration = Fraction(event["duration"])
        if onset >= measure_duration or duration <= 0:
            continue
        duration = min(duration, measure_duration - onset)
        groups[(onset, duration)].append(event)

    cursor = Fraction(0)
    ordered = sorted(groups.items())
    pending_clefs = sorted(clef_changes or [], key=lambda item: item[0])

    def emit_clefs_through(target: Fraction) -> None:
        nonlocal cursor
        while pending_clefs and pending_clefs[0][0] <= target:
            onset = pending_clefs[0][0]
            if onset > cursor:
                _append_rest_duration(measure, onset - cursor, voice, staff)
                cursor = onset
            simultaneous: list[tuple[int, str, int]] = []
            while pending_clefs and pending_clefs[0][0] == onset:
                _, clef_staff, sign, line = pending_clefs.pop(0)
                simultaneous.append((clef_staff, sign, line))
            _append_clef_attributes(measure, simultaneous)

    tuplet_groups: dict[str, list[tuple[Fraction, Fraction]]] = defaultdict(list)
    for event_key, grouped_events in ordered:
        if grouped_events[0].get("tuplet"):
            group_key = grouped_events[0].get("tuplet_group", "default")
            tuplet_groups[group_key].append(event_key)
    for (onset, duration), chord_events in ordered:
        if onset < cursor:
            continue
        emit_clefs_through(onset)
        if onset > cursor:
            _append_rest_duration(measure, onset - cursor, voice, staff)
        ordered_chord = sorted(
            chord_events, key=lambda item: _pitch_number(item.get("pitch"))
        )
        duration_pieces = _event_pieces(ordered_chord[0], duration)
        for piece_index, (_, piece_duration) in enumerate(duration_pieces):
            for chord_index, event in enumerate(ordered_chord):
                piece_event = _event_pieces(event, duration)[piece_index][0]
                marker = None
                group_key = piece_event.get("tuplet_group", "default")
                boundaries = tuplet_groups.get(group_key, [])
                if (
                    chord_index == 0
                    and piece_index == 0
                    and boundaries
                    and (onset, duration) == boundaries[0]
                ):
                    marker = "start"
                if (
                    chord_index == 0
                    and piece_index == len(duration_pieces) - 1
                    and boundaries
                    and (onset, duration) == boundaries[-1]
                ):
                    marker = ("start", "stop") if marker == "start" else "stop"
                if piece_event.get("_standalone_tuplet") and chord_index == 0:
                    marker = ("start", "stop")
                _append_note(
                    measure,
                    piece_event,
                    piece_duration,
                    voice,
                    staff,
                    chord=chord_index > 0,
                    tuplet_marker=marker,
                )
        cursor = onset + duration
    emit_clefs_through(measure_duration)
    if cursor < measure_duration:
        _append_rest_duration(measure, measure_duration - cursor, voice, staff)


def validate_meter_score(score: dict, duration_for, require_full=None) -> dict:
    """Reject voice overruns and require each staff/measure to reach its exact boundary."""
    require_full = require_full or (lambda _part, _measure: True)
    grouped: dict[tuple[str, int, str, str], list[dict]] = defaultdict(list)
    for event in score["events"]:
        grouped[
            (
                event["part_id"],
                int(event["measure_index"]),
                event.get("staff", "1"),
                event.get("voice", "1"),
            )
        ].append(event)

    violations: list[dict] = []
    staff_ends: dict[tuple[str, int, str], list[Fraction]] = defaultdict(list)
    for (part_id, measure_index, staff, voice), events in sorted(grouped.items()):
        expected = duration_for(part_id, measure_index)
        ends = [Fraction(event["onset"]) + Fraction(event["duration"]) for event in events]
        actual = max(ends, default=Fraction(0))
        staff_ends[(part_id, measure_index, staff)].append(actual)
        if actual > expected:
            violations.append(
                {
                    "part_id": part_id,
                    "measure": measure_index,
                    "staff": staff,
                    "voice": voice,
                    "expected_quarters": str(expected),
                    "actual_quarters": str(actual),
                    "kind": "overrun",
                }
            )
    for (part_id, measure_index, staff), ends in sorted(staff_ends.items()):
        expected = duration_for(part_id, measure_index)
        actual = max(ends, default=Fraction(0))
        if actual < expected and require_full(part_id, measure_index):
            violations.append(
                {
                    "part_id": part_id,
                    "measure": measure_index,
                    "staff": staff,
                    "voice": "all",
                    "expected_quarters": str(expected),
                    "actual_quarters": str(actual),
                    "kind": "underfill",
                }
            )
    return {
        "valid": not violations,
        "checked_streams": len(grouped),
        "checked_staff_measures": len(staff_ends),
        "overruns": sum(item["kind"] == "overrun" for item in violations),
        "underfills": sum(item["kind"] == "underfill" for item in violations),
        "violations": violations,
    }


def _write_and_validate(
    tree: ET.ElementTree, output: Path, duration_for, require_full=None
) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(output, encoding="utf-8", xml_declaration=True)
    validation = validate_meter_score(
        parse_musicxml(output, include_rests=True), duration_for, require_full=require_full
    )
    if not validation["valid"]:
        raise ValueError(f"validação métrica falhou: {validation['violations'][:3]}")
    return validation


def _parse_meter(meter: str) -> tuple[int, int, Fraction]:
    match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", meter)
    if not match:
        raise ValueError(f"compasso inválido: {meter!r}")
    beats, beat_type = (int(value) for value in match.groups())
    if beats <= 0 or beat_type <= 0:
        raise ValueError(f"compasso inválido: {meter!r}")
    return beats, beat_type, Fraction(beats * 4, beat_type)


def _apply_movement1_profile(candidate: dict, root: ET.Element) -> tuple[dict[str, str], bool]:
    """Merge page-8 abbreviations into the full instrument names found on page 7."""
    names = {item["id"]: item["name"] for item in candidate["parts"]}
    if candidate.get("parts_count") != 44 or names.get("P1") != "Picc.":
        return {}, False
    for credit in root.findall("credit"):
        root.remove(credit)
    work = root.find("work")
    if work is None:
        work = ET.Element("work")
        root.insert(0, work)
    work_title = work.find("work-title")
    if work_title is None:
        work_title = ET.SubElement(work, "work-title")
    work_title.text = "I. Allegro"
    movement_title = root.find("movement-title")
    if movement_title is None:
        movement_title = ET.Element("movement-title")
        root.insert(1, movement_title)
    movement_title.text = "I. Allegro"
    movement_number = root.find("movement-number")
    if movement_number is not None:
        root.remove(movement_number)
    aliases = {
        "P1": "P15",
        "P2": "P16",
        "P3": "P17",
        "P4": "P19",
        "P5": "P20",
        "P6": "P21",
        "P7": "P23",
        "P8": "P24",
        "P10": "P25",
        "P11": "P26",
        "P12": "P27",
        "P13": "P28",
        "P14": "P29",
        "P40": "P33",
        "P41": "P35",
        "P42": "P36",
        "P43": "P37",
        "P44": "P38",
    }
    full_names = {
        "P15": "Piccolo I, II",
        "P16": "Flauta I, II",
        "P17": "Oboé I, II",
        "P18": "Corne Inglês",
        "P19": "Clarinete I, II, III em B♭",
        "P20": "Clarinete Baixo em B♭",
        "P21": "Fagote I, II",
        "P22": "Contrafagote",
        "P23": "Trompa em F I, II",
        "P24": "Trompa em F III, IV",
        "P9": "Trompete I, II em B♭",
        "P25": "Trompete III, IV em B♭",
        "P26": "Trombone I, II",
        "P27": "Trombone III, IV",
        "P28": "Tuba",
        "P29": "Tímpano",
        "P30": "Tam-tam",
        "P31": "Bombo",
        "P32": "Harpa",
        "P39": "Celesta",
        "P33": "Piano",
        "P34": "Violino I",
        "P35": "Violino II",
        "P36": "Viola",
        "P37": "Violoncelo",
        "P38": "Contrabaixo",
    }
    order = list(full_names)
    part_list = root.find("part-list")
    if part_list is None:
        return {}, False
    score_parts = {item.get("id", ""): item for item in part_list.findall("score-part")}
    score_part_nodes = []
    for part_id in order:
        item = score_parts[part_id]
        name = item.find("part-name")
        if name is None:
            name = ET.SubElement(item, "part-name")
        name.text = full_names[part_id]
        abbreviation = item.find("part-abbreviation")
        if abbreviation is not None:
            abbreviation.text = full_names[part_id]
        score_part_nodes.append(item)
    for child in list(part_list):
        part_list.remove(child)
    for item in score_part_nodes:
        part_list.append(item)

    xml_parts = {item.get("id", ""): item for item in root.findall("part")}
    for item in root.findall("part"):
        root.remove(item)
    for part_id in order:
        root.append(xml_parts[part_id])
    return aliases, True


def _set_score_instrument(score_part: ET.Element, name: str, sound: str, midi: int) -> None:
    score_instrument = score_part.find("score-instrument")
    if score_instrument is None:
        score_instrument = ET.SubElement(
            score_part, "score-instrument", {"id": f"{score_part.get('id')}-I1"}
        )
    instrument_name = score_instrument.find("instrument-name")
    if instrument_name is None:
        instrument_name = ET.SubElement(score_instrument, "instrument-name")
    instrument_name.text = name
    instrument_sound = score_instrument.find("instrument-sound")
    if instrument_sound is None:
        instrument_sound = ET.SubElement(score_instrument, "instrument-sound")
    instrument_sound.text = sound
    midi_instrument = score_part.find("midi-instrument")
    if midi_instrument is None:
        midi_instrument = ET.SubElement(
            score_part, "midi-instrument", {"id": score_instrument.get("id", "")}
        )
    midi_program = midi_instrument.find("midi-program")
    if midi_program is None:
        midi_program = ET.SubElement(midi_instrument, "midi-program")
    midi_program.text = str(midi)


def _apply_page109_profile(candidate: dict, root: ET.Element) -> tuple[dict[str, str], bool]:
    """Join the two editorial systems on PDF page 109 into one 16-bar score."""
    names = {item["id"]: item["name"] for item in candidate["parts"]}
    if (
        candidate.get("parts_count") != 21
        or names.get("P2", "").rstrip(".") != "Tpa"
        or names.get("P12", "").rstrip(".") != "Tpa"
        or names.get("P21") != "Cb."
    ):
        return {}, False

    # Audiveris assigns P11-P21 to the upper system and P1-P10 to the lower
    # one. P21 (double bass) is the only staff it already joined correctly.
    aliases = {f"P{index}": f"P{index + 10}" for index in range(1, 11)}
    xml_parts = {part.get("id", ""): part for part in root.findall("part")}
    for lower_id, target_id in aliases.items():
        lower_measures = xml_parts[lower_id].findall("measure")
        target_part = xml_parts[target_id]
        target_measures = target_part.findall("measure")
        for index in range(8, min(len(lower_measures), len(target_measures))):
            replacement = copy.deepcopy(lower_measures[index])
            child_index = list(target_part).index(target_measures[index])
            target_part.remove(target_measures[index])
            target_part.insert(child_index, replacement)

    part_specs = {
        "P11": ("Trompa I, III em F", "Tpa. I, III", "brass.french-horn", 61),
        "P12": ("Trompa II, IV em F", "Tpa. II, IV", "brass.french-horn", 61),
        "P13": ("Ameríndia", "Amer.", "voice.baritone", 54),
        "P14": ("Voz da Terra", "V. da T.", "voice.baritone", 54),
        "P15": ("Sopranos", "S.", "voice.soprano", 54),
        "P16": ("Contraltos", "C.", "voice.alto", 54),
        "P17": ("Violino I", "Vl. I", "strings.violin", 41),
        "P18": ("Violino II", "Vl. II", "strings.violin", 41),
        "P19": ("Viola", "Vla.", "strings.viola", 42),
        "P20": ("Violoncelo", "Vc.", "strings.cello", 43),
        "P21": ("Contrabaixo", "Cb.", "strings.contrabass", 44),
    }
    kept_ids = set(part_specs)
    part_list = root.find("part-list")
    if part_list is None:
        return {}, False
    for score_part in list(part_list.findall("score-part")):
        part_id = score_part.get("id", "")
        if part_id not in kept_ids:
            part_list.remove(score_part)
            continue
        full_name, abbreviation, sound, midi = part_specs[part_id]
        name_node = score_part.find("part-name")
        if name_node is None:
            name_node = ET.SubElement(score_part, "part-name")
        name_node.text = full_name
        abbreviation_node = score_part.find("part-abbreviation")
        if abbreviation_node is None:
            abbreviation_node = ET.SubElement(score_part, "part-abbreviation")
        abbreviation_node.text = abbreviation
        _set_score_instrument(score_part, full_name, sound, midi)

    for part in list(root.findall("part")):
        if part.get("id", "") not in kept_ids:
            root.remove(part)
    for part_id in part_specs:
        part = xml_parts[part_id]
        for measure_index, measure in enumerate(part.findall("measure"), 52):
            measure.set("number", str(measure_index))
            # The printed 3./4. horn indications and lyric extenders must not
            # become volta endings or repeat barlines.
            for barline in list(measure.findall("barline")):
                measure.remove(barline)
        if part_id in {"P11", "P12"}:
            attributes = part.find("./measure/attributes")
            if attributes is not None:
                transpose = attributes.find("transpose")
                if transpose is None:
                    transpose = ET.SubElement(attributes, "transpose")
                for child in list(transpose):
                    transpose.remove(child)
                ET.SubElement(transpose, "diatonic").text = "-4"
                ET.SubElement(transpose, "chromatic").text = "-7"

    for credit in root.findall("credit"):
        root.remove(credit)
    work = root.find("work")
    if work is None:
        work = ET.Element("work")
        root.insert(0, work)
    title = work.find("work-title")
    if title is None:
        title = ET.SubElement(work, "work-title")
    title.text = "Sinfonia nº 10 - página 109"
    return aliases, True


def _apply_choros9_opening_profile(
    candidate: dict, root: ET.Element
) -> tuple[dict[str, str], bool]:
    """Resolve the 24 retained staves on the first printed page.

    Audiveris drops the isolated one-line percussion staff on this page and
    exports the two Celesta and two harp staves separately. Keeping those
    staves separate is safer than guessing a grand-staff merge, but their
    musical identities and opening clefs are deterministic.
    """
    if candidate.get("parts_count") != 24 or candidate.get("measures") != 3:
        return {}, False
    specs = (
        ("Piccolo", "Picc.", "G", 2, "wind.flutes.piccolo", 73),
        ("2 Flûtes", "Fl.", "G", 2, "wind.flutes.flute", 73),
        ("2 Hautbois", "Htb.", "G", 2, "wind.reed.oboe", 69),
        ("Cor anglais", "C. Ang.", "G", 2, "wind.reed.english-horn", 70),
        ("2 Clarinettes (Si♭)", "Clar.", "G", 2, "wind.reed.clarinet", 72),
        ("Clarinette basse (Si♭)", "Cl. B.", "G", 2, "wind.reed.bass-clarinet", 72),
        ("2 Bassons", "Bon.", "F", 4, "wind.reed.bassoon", 71),
        ("Contrebasson", "C. Bon.", "F", 4, "wind.reed.contrabassoon", 71),
        ("Cors 1–2 (Fa)", "Cors 1–2", "G", 2, "brass.french-horn", 61),
        ("Cors 3–4 (Fa)", "Cors 3–4", "G", 2, "brass.french-horn", 61),
        ("4 Pistons (Si♭)", "Pist.", "G", 2, "brass.trumpet", 57),
        ("Trombones 1–2", "Trb. 1–2", "C", 4, "brass.trombone", 58),
        ("Trombones 3–4", "Trb. 3–4", "F", 4, "brass.trombone", 58),
        ("Tuba", "Tuba", "F", 4, "brass.tuba", 59),
        ("Timbales", "Timb.", "F", 4, "drum.timpani", 48),
        ("Célesta — portée supérieure", "Cél. sup.", "G", 2, "keyboard.celesta", 9),
        ("Célesta — portée inférieure", "Cél. inf.", "F", 4, "keyboard.celesta", 9),
        ("Harpes 1–2 — portée supérieure", "Hpes sup.", "G", 2, "pluck.harp", 47),
        ("Harpes 1–2 — portée inférieure", "Hpes inf.", "F", 4, "pluck.harp", 47),
        ("Violons I", "Viol. I", "G", 2, "strings.violin", 41),
        ("Violons II", "Viol. II", "G", 2, "strings.violin", 41),
        ("Altos", "Alt.", "C", 3, "strings.viola", 42),
        ("Violoncelles", "Vcl.", "F", 4, "strings.cello", 43),
        ("Contrebasses", "C.B.", "F", 4, "strings.contrabass", 44),
    )
    score_parts = root.findall("./part-list/score-part")
    xml_parts = root.findall("part")
    if len(score_parts) != len(specs) or len(xml_parts) != len(specs):
        return {}, False
    # The scan's title OCR is commonly reduced to fragments such as "CH(".
    # Keep reliable metadata and remove only unreliable positioned credits.
    for credit in root.findall("credit"):
        root.remove(credit)
    work = root.find("work")
    if work is None:
        work = ET.Element("work")
        root.insert(0, work)
    title = work.find("work-title")
    if title is None:
        title = ET.SubElement(work, "work-title")
    title.text = "Chôros Nº 9"
    identification = root.find("identification")
    if identification is None:
        identification = ET.SubElement(root, "identification")
    composer = next(
        (creator for creator in identification.findall("creator") if creator.get("type") == "composer"),
        None,
    )
    if composer is None:
        composer = ET.SubElement(identification, "creator", {"type": "composer"})
    composer.text = "Heitor Villa-Lobos"
    for score_part, part, (name, abbreviation, clef_sign, clef_line, sound, midi) in zip(
        score_parts, xml_parts, specs
    ):
        name_node = score_part.find("part-name")
        if name_node is None:
            name_node = ET.SubElement(score_part, "part-name")
        name_node.text = name
        abbreviation_node = score_part.find("part-abbreviation")
        if abbreviation_node is None:
            abbreviation_node = ET.SubElement(score_part, "part-abbreviation")
        abbreviation_node.text = abbreviation
        _set_score_instrument(score_part, name, sound, midi)

        measures = part.findall("measure")
        for measure in measures:
            for attributes in measure.findall("attributes"):
                for clef in list(attributes.findall("clef")):
                    attributes.remove(clef)
        if measures:
            attributes = measures[0].find("attributes")
            if attributes is None:
                attributes = ET.Element("attributes")
                measures[0].insert(0, attributes)
            clef = ET.SubElement(attributes, "clef")
            ET.SubElement(clef, "sign").text = clef_sign
            ET.SubElement(clef, "line").text = str(clef_line)
    return {}, True


def _apply_page109_lyrics(events_by_part: dict[str, list[dict]]) -> int:
    """Attach only lyrics whose note positions were visually verified at 350 dpi."""
    plan = {
        ("P13", 1, "0"): ("xi", "single"),
        ("P13", 2, "0"): ("ma,", "single"),
        ("P13", 2, "1/2"): ("i", "begin"),
        ("P13", 2, "1"): ("lu", "middle"),
        ("P13", 2, "3/2"): ("mi", "end"),
        ("P13", 3, "0"): ("na", "begin"),
        ("P13", 3, "1/2"): ("da,", "end"),
        ("P13", 3, "1"): ("au", "begin"),
        ("P13", 3, "3/2"): ("reo", "end"),
        ("P13", 4, "0"): ("la", "single"),
        ("P13", 5, "0"): ("da...", "single"),
        ("P13", 6, "0"): ("I", "begin"),
        ("P13", 6, "1"): ("lu", "middle"),
        ("P13", 6, "3/2"): ("mi", "end"),
        ("P13", 7, "0"): ("na", "single"),
        ("P13", 8, "0"): ("da...", "single"),
        ("P13", 8, "1/2"): ("Au", "begin"),
        ("P13", 8, "1"): ("re", "middle"),
        ("P13", 8, "3/2"): ("o", "middle"),
        ("P13", 9, "0"): ("la", "single"),
        ("P13", 9, "1"): ("da...", "single"),
        ("P13", 9, "7/4"): ("Um!", "single"),
        ("P13", 12, "3/2"): ("Um!", "single"),
        ("P15", 9, "7/4"): ("Um!", "single"),
        ("P15", 12, "3/2"): ("Um!", "single"),
        ("P16", 9, "7/4"): ("Um!", "single"),
        ("P16", 12, "3/2"): ("Um!", "single"),
    }
    inserted = 0
    for part_id, events in events_by_part.items():
        for event in events:
            lyric = plan.get((part_id, event["measure_index"], event["onset"]))
            if lyric and not event.get("chord"):
                event["lyrics"] = [{"text": lyric[0], "syllabic": lyric[1]}]
                inserted += 1
    if inserted != len(plan):
        missing = len(plan) - inserted
        raise ValueError(f"não foi possível associar {missing} sílabas verificadas da página 109")
    return inserted


def build_meter_locked_musicxml(
    candidate_path: Path,
    output: Path,
    meter: str,
    score_profile: str | None = None,
) -> dict:
    """Rebuild an OMR result with every stream clamped and filled to a fixed meter."""
    beats, beat_type, duration = _parse_meter(meter)
    candidate = parse_musicxml(candidate_path)
    root = ET.fromstring(_read_musicxml(candidate_path))
    tree = ET.ElementTree(root)
    if score_profile == "choros9-opening":
        aliases, profile_applied = _apply_choros9_opening_profile(candidate, root)
        profile_name = "choros9-opening" if profile_applied else None
    else:
        aliases, profile_applied = _apply_movement1_profile(candidate, root)
        profile_name = "movement1-pages-7-8" if profile_applied else None
        if not profile_applied:
            aliases, profile_applied = _apply_page109_profile(candidate, root)
            if profile_applied:
                profile_name = "page-109-split-systems"
    events_by_part: dict[str, list[dict]] = defaultdict(list)
    for event in candidate["events"]:
        if event.get("pitch"):
            target = aliases.get(event["part_id"], event["part_id"])
            events_by_part[target].append(_clone_event(event, target))
    grouped_tuplet_notes = sum(
        _assign_imported_tuplet_groups(events) for events in events_by_part.values()
    )
    simplified_tuplets = 0
    dropped_boundary_events = 0
    if score_profile in {"choros9", "choros9-opening"}:
        for part_id, events in list(events_by_part.items()):
            safe_events: list[dict] = []
            for event in events:
                event_duration = Fraction(event["duration"])
                if event.get("_standalone_tuplet") and event.get("tuplet"):
                    ratio = event["tuplet"]
                    event_duration *= Fraction(
                        int(ratio["actual"]), int(ratio["normal"])
                    )
                    event["duration"] = str(event_duration)
                    event["tuplet"] = None
                    event.pop("tuplet_group", None)
                    event.pop("_standalone_tuplet", None)
                    simplified_tuplets += 1
                onset = Fraction(event["onset"])
                if onset >= duration:
                    dropped_boundary_events += 1
                    continue
                clipped = min(event_duration, duration - onset)
                if clipped != event_duration:
                    if _duration_notation(clipped, event.get("tuplet")) is None:
                        dropped_boundary_events += 1
                        continue
                    event["duration"] = str(clipped)
                safe_events.append(event)
            events_by_part[part_id] = safe_events
    verified_lyrics = _apply_page109_lyrics(events_by_part) if profile_name == "page-109-split-systems" else 0

    for part in root.findall("part"):
        part_id = part.get("id", "")
        part_events = events_by_part.get(part_id, [])
        part_measures = part.findall("measure")
        staves = max(
            [int(event.get("staff", "1")) for event in part_events]
            + [int(part.findtext("./measure/attributes/staves", "1"))]
        )
        for measure_index, measure in enumerate(part_measures, 1):
            retained = [
                copy.deepcopy(child)
                for child in measure
                if child.tag in {"print", "attributes", "direction", "barline"}
            ]
            for child in list(measure):
                measure.remove(child)
            for child in retained:
                if child.tag != "barline":
                    measure.append(child)
            attributes = measure.find("attributes")
            if measure_index == 1 or attributes is not None:
                if attributes is None:
                    attributes = ET.Element("attributes")
                    measure.insert(0, attributes)
                divisions = attributes.find("divisions")
                if divisions is None:
                    divisions = ET.Element("divisions")
                    attributes.insert(0, divisions)
                divisions.text = str(DIVISIONS)
                time = attributes.find("time")
                if time is None and measure_index == 1:
                    time = ET.SubElement(attributes, "time")
                if time is not None:
                    for child in list(time):
                        time.remove(child)
                    ET.SubElement(time, "beats").text = str(beats)
                    ET.SubElement(time, "beat-type").text = str(beat_type)

            current = [event for event in part_events if event["measure_index"] == measure_index]
            streams: list[tuple[str, str, list[dict]]] = []
            for staff_number in range(1, staves + 1):
                staff = str(staff_number)
                staff_events = [event for event in current if event.get("staff", "1") == staff]
                voices = sorted({event.get("voice", "1") for event in staff_events}) or ["1"]
                for voice in voices:
                    streams.append(
                        (staff, voice, [event for event in staff_events if event.get("voice", "1") == voice])
                    )
            for stream_index, (staff, voice, stream_events) in enumerate(streams):
                if stream_index:
                    backup = ET.SubElement(measure, "backup")
                    ET.SubElement(backup, "duration").text = str(duration * DIVISIONS)
                _emit_voice(measure, stream_events, duration, voice, staff)
            for child in retained:
                if child.tag == "barline":
                    measure.append(child)
            if (
                measure_index == len(part_measures)
                and measure.find("barline") is None
                and profile_name != "page-109-split-systems"
            ):
                barline = ET.SubElement(measure, "barline", {"location": "right"})
                ET.SubElement(barline, "bar-style").text = "light-heavy"

    validation = _write_and_validate(tree, output, lambda _part, _measure: duration)
    return {
        "output": str(output.resolve()),
        "meter": f"{beats}/{beat_type}",
        "parts": len(root.findall("part")),
        "measures": candidate["measures"],
        "instrument_profile": profile_name,
        "verified_lyrics": verified_lyrics,
        "grouped_tuplet_notes": grouped_tuplet_notes,
        "simplified_incomplete_tuplets": simplified_tuplets,
        "dropped_boundary_events": dropped_boundary_events,
        "meter_validation": validation,
    }


def build_normalized_musicxml(
    candidate_path: Path,
    template_path: Path,
    output: Path,
    page69_candidate_path: Path | None = None,
) -> dict:
    candidate = parse_musicxml(candidate_path)
    mapped = map_sinfonia10_scherzo(candidate)
    target_measure_count = candidate["measures"]
    page_starts = {9}
    if page69_candidate_path:
        page69 = parse_musicxml(page69_candidate_path)
        page69_mapped = map_sinfonia10_page69(page69)
        for part_id, events in page69_mapped.items():
            mapped[part_id].extend(events)
        target_measure_count = 17 + page69["measures"]
        page_starts.add(18)
    tree = ET.parse(template_path)
    root = tree.getroot()

    names = {
        item.get("id", ""): _unescape(item.findtext("part-name", item.get("id", "")))
        for item in root.findall("./part-list/score-part")
    }
    for part in root.findall("part"):
        part_id = part.get("id", "")
        part_events = mapped.get(part_id, [])
        staves = max(
            [int(event.get("staff", "1")) for event in part_events]
            + [int(part.findtext("./measure/attributes/staves", "1"))]
        )
        measures = part.findall("measure")
        template_measure_count = len(measures)
        while len(measures) < target_measure_count:
            number = len(measures) + 1
            measure = ET.Element("measure", {"number": str(number)})
            if number in page_starts and part_id == "P1":
                measure.append(ET.Element("print", {"new-page": "yes"}))
            part.append(measure)
            measures.append(measure)
        for measure_index, measure in enumerate(measures, 1):
            # The user's MuseScore transcription is authoritative for page 67.
            # Preserve its time signatures, local 3/4, tuplets and engraving exactly.
            if measure_index <= template_measure_count:
                continue
            duration = _measure_duration(part_id, measure_index)
            retained = [
                copy.deepcopy(child)
                for child in measure
                if child.tag in {"print", "attributes", "direction", "barline"}
            ]
            for child in list(measure):
                measure.remove(child)
            for child in retained:
                if child.tag != "barline":
                    measure.append(child)
            if measure_index in page_starts:
                attributes = measure.find("attributes")
                if attributes is None:
                    attributes = ET.Element("attributes")
                    insert_at = 1 if measure.find("print") is not None else 0
                    measure.insert(insert_at, attributes)
                divisions = ET.SubElement(attributes, "divisions")
                divisions.text = str(DIVISIONS)
                time = ET.SubElement(attributes, "time")
                ET.SubElement(time, "beats").text = "9"
                ET.SubElement(time, "beat-type").text = "8"

            current = [
                event for event in part_events if event["measure_index"] == measure_index
            ]
            streams: list[tuple[str, str, list[dict]]] = []
            for staff_number in range(1, staves + 1):
                staff = str(staff_number)
                staff_events = [event for event in current if event.get("staff", "1") == staff]
                voices = sorted({event.get("voice", "1") for event in staff_events}) or ["1"]
                for voice in voices:
                    streams.append(
                        (staff, voice, [event for event in staff_events if event.get("voice", "1") == voice])
                    )
            for stream_index, (staff, voice, stream_events) in enumerate(streams):
                if stream_index:
                    backup = ET.SubElement(measure, "backup")
                    ET.SubElement(backup, "duration").text = str(duration * DIVISIONS)
                _emit_voice(measure, stream_events, duration, voice, staff)
            for child in retained:
                if child.tag == "barline":
                    measure.append(child)

    validation = _write_and_validate(
        tree,
        output,
        _measure_duration,
        require_full=lambda _part, measure_index: measure_index > template_measure_count,
    )
    return {
        "output": str(output.resolve()),
        "parts": len(names),
        "mapped_events": sum(len(events) for events in mapped.values()),
        "unmapped_target_parts": [names.get(f"P{i}", f"P{i}") for i in range(1, 31) if not mapped.get(f"P{i}")],
        "measures": target_measure_count,
        "page_starts": sorted(page_starts),
        "meter_validation": validation,
    }


MOVEMENT1_METER_CHANGES = {
    1: (4, 4),
    12: (3, 4),
    23: (2, 4),
    26: (3, 4),
    28: (4, 4),
    29: (3, 4),
    30: (2, 4),
    31: (4, 4),
    37: (5, 8),
    61: (4, 4),
    84: (2, 4),
    85: (4, 4),
    150: (3, 4),
    177: (2, 4),
    180: (4, 4),
}

# Clefs verified against the engraved score on PDF pages 7-12.  Each entry is
# (measure, quarter-note onset, staff, sign, line).  The two harp parts share
# the same writing.  Courtesy clefs printed at the end of a preceding bar are
# stored at the first sounding bar except where the change is genuinely
# mid-measure (m.22 and m.32).
MOVEMENT1_CLEF_CHANGES = {
    "P32": [
        (1, Fraction(0), 1, "F", 4),
        (1, Fraction(0), 2, "F", 4),
        (6, Fraction(0), 1, "G", 2),
        (6, Fraction(0), 2, "G", 2),
        (18, Fraction(0), 1, "G", 2),
        (18, Fraction(0), 2, "F", 4),
        (21, Fraction(0), 2, "G", 2),
        (22, Fraction(3), 2, "F", 4),
        (34, Fraction(0), 1, "F", 4),
    ],
    "P47": [
        (1, Fraction(0), 1, "F", 4),
        (1, Fraction(0), 2, "F", 4),
        (6, Fraction(0), 1, "G", 2),
        (6, Fraction(0), 2, "G", 2),
        (18, Fraction(0), 1, "G", 2),
        (18, Fraction(0), 2, "F", 4),
        (21, Fraction(0), 2, "G", 2),
        (22, Fraction(3), 2, "F", 4),
        (34, Fraction(0), 1, "F", 4),
    ],
    "P39": [
        (1, Fraction(0), 1, "G", 2),
        (1, Fraction(0), 2, "F", 4),
        (16, Fraction(0), 2, "G", 2),
    ],
    "P33": [
        (1, Fraction(0), 1, "G", 2),
        (1, Fraction(0), 2, "F", 4),
        (4, Fraction(0), 1, "F", 4),
        (16, Fraction(0), 1, "G", 2),
        (16, Fraction(0), 2, "G", 2),
        (18, Fraction(0), 2, "F", 4),
        (21, Fraction(0), 1, "G", 2),
        (21, Fraction(0), 2, "G", 2),
        (22, Fraction(3), 2, "F", 4),
        (32, Fraction(7, 2), 1, "F", 4),
        (34, Fraction(0), 1, "G", 2),
        (34, Fraction(0), 2, "G", 2),
    ],
    "P26": [
        (1, Fraction(0), 1, "F", 4),
        (31, Fraction(0), 1, "C", 4),
    ],
    "P36": [
        (44, Fraction(0), 1, "G", 2),
    ],
    "P37": [
        (41, Fraction(0), 1, "C", 4),
    ],
}


# Page-level staff order verified against the engraved PDF. A ``split`` entry
# means a condensed melodic staff must become two monophonic player parts. A
# plain tuple duplicates a genuinely shared staff (for example Harpa + Piano).
SPLIT_PICC = ("split", "P15", "P45")
SPLIT_FLUTE = ("split", "P16", "P46")
SPLIT_HORNS = ("split", "P23", "P24")
SPLIT_TRUMPETS = ("split", "P9", "P25")
SPLIT_TROMBONES = ("split", "P26", "P27")
SHARED_HARPS = ("P32", "P47")
SHARED_HARPS_PIANO = ("P32", "P47", "P33")

MOVEMENT1_PAGE_LAYOUTS: dict[int, list[str | tuple[str, ...]]] = {
    14: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P29", "P34", "P35", "P36", "P37", "P38"],
    15: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P29", "P34", "P35", "P36", "P37", "P38"],
    16: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P29", "P34", "P35", "P36", "P37", "P38"],
    17: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P29", "P34", "P35", "P36", "P37", "P38"],
    18: ["P16", "P46", "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", SPLIT_TRUMPETS, SPLIT_TROMBONES, "P28", "P29", "P39", "P33", "P34", "P35", "P36", "P37", "P38"],
    19: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", SPLIT_TRUMPETS, SPLIT_TROMBONES, "P28", "P29", SHARED_HARPS, "P39", "P34", "P35", "P36", "P37", "P38"],
    20: [SPLIT_FLUTE, "P18", "P20", "P21", "P22", "P23", "P24", SPLIT_TRUMPETS, "P26", "P27", "P29", "P32", "P47", "P39", "P34", "P35", "P36", "P37", "P38"],
    21: ["P16", "P46", "P20", "P21", "P22", "P23", "P24", SPLIT_TRUMPETS, "P26", "P27", "P29", "P32", "P47", "P39", "P34", "P35", "P36", "P37", "P38"],
    22: ["P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", SHARED_HARPS, "P33", "P34", "P35", "P36", "P37", "P38"],
    23: ["P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", SHARED_HARPS, "P33", "P34", "P35", "P36", "P37", "P38"],
    24: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P29", "P48", "P30", "P32", "P47", "P33", "P34", "P35", "P36", "P37", "P38"],
    25: ["P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P29", "P48", "P30", "P32", "P47", "P33", "P34", "P35", "P36", "P37", "P38"],
    26: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P29", SHARED_HARPS_PIANO, "P39", "P34", "P35", "P36", "P37", "P38"],
    27: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P29", "P49", "P31", SHARED_HARPS_PIANO, "P39", "P34", "P35", "P36", "P37", "P38"],
    28: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P19", "P20", "P21", "P22", "P23", "P24", "P29", "P49", SHARED_HARPS, "P39", "P33", "P34", "P35", "P36", "P37", "P38"],
    29: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P19", "P20", "P21", "P22", "P23", "P24", "P9", "P25", SPLIT_TROMBONES, "P28", "P29", SHARED_HARPS, "P33", "P34", "P35", "P36", "P37", "P38"],
    30: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P21", "P22", "P23", "P24", SPLIT_TRUMPETS, "P26", "P27", "P29", "P32", "P47", "P33", "P34", "P35", "P36", "P37", "P38"],
    31: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", SPLIT_TRUMPETS, "P26", "P27", "P28", "P29", "P48", "P50", "P33", "P34", "P35", "P36", "P37", "P38"],
    32: [SPLIT_FLUTE, "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", SPLIT_TROMBONES, "P28", "P48", "P50", "P34", "P35", "P36", "P37", "P38"],
    33: ["P16", "P46", "P18", "P19", "P20", "P21", "P22", "P23", "P24", SPLIT_TRUMPETS, "P33", "P34", "P35", "P36", "P37", "P38"],
    34: ["P16", "P46", "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P29", "P33", "P34", "P35", "P36", "P37", "P38"],
    35: ["P16", "P46", "P17", "P18", "P19", "P19", "P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P29", "P33", "P34", "P35", "P36", "P37", "P38"],
    36: ["P16", "P46", "P17", "P18", "P19", "P19", "P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P29", "P33", "P34", "P35", "P36", "P37", "P38"],
    37: ["P16", "P46", "P17", "P18", "P19", "P19", "P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P29", "P33", "P34", "P35", "P36", "P37", "P38"],
    38: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P29", "P48", SHARED_HARPS, "P39", "P33", "P34", "P35", "P36", "P37", "P38"],
    39: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P48", SHARED_HARPS, "P39", "P33", "P34", "P35", "P36", "P37", "P38"],
    40: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P30", SHARED_HARPS, "P39", "P33", "P34", "P35", "P36", "P37", "P38"],
    41: [SPLIT_PICC, SPLIT_FLUTE, "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", "P9", "P25", "P26", "P27", "P28", "P29", "P30", "P39", "P33", "P34", "P35", "P36", "P37", "P38"],
}


def movement1_meter(measure_index: int) -> tuple[int, int, Fraction]:
    active_measure = max(index for index in MOVEMENT1_METER_CHANGES if index <= measure_index)
    beats, beat_type = MOVEMENT1_METER_CHANGES[active_measure]
    return beats, beat_type, Fraction(beats * 4, beat_type)


def _rename_score_part(root: ET.Element, part_id: str, name: str) -> None:
    score_part = root.find(f"./part-list/score-part[@id='{part_id}']")
    if score_part is None:
        raise ValueError(f"instrumento ausente no modelo: {part_id}")
    for tag in ("part-name", "part-abbreviation"):
        node = score_part.find(tag)
        if node is None:
            node = ET.SubElement(score_part, tag)
        node.text = name
    instrument_name = score_part.find("./score-instrument/instrument-name")
    if instrument_name is not None:
        instrument_name.text = name


def _clone_score_part_after(
    root: ET.Element, source_id: str, target_id: str, name: str
) -> None:
    """Clone a complete MusicXML part and keep it adjacent to its source."""
    part_list = root.find("part-list")
    source_score_part = root.find(f"./part-list/score-part[@id='{source_id}']")
    source_part = root.find(f"./part[@id='{source_id}']")
    if part_list is None or source_score_part is None or source_part is None:
        raise ValueError(f"não foi possível duplicar o instrumento {source_id}")

    score_part = copy.deepcopy(source_score_part)
    score_part.set("id", target_id)
    for node in score_part.iter():
        for attribute, value in list(node.attrib.items()):
            if value.startswith(source_id):
                node.set(attribute, target_id + value[len(source_id) :])
    score_index = list(part_list).index(source_score_part)
    part_list.insert(score_index + 1, score_part)

    part = copy.deepcopy(source_part)
    part.set("id", target_id)
    part_index = list(root).index(source_part)
    root.insert(part_index + 1, part)
    _rename_score_part(root, target_id, name)


def _pitch_height(pitch: str | None) -> int:
    if not pitch:
        return -999
    match = re.fullmatch(r"([A-G])([#b]*)(-?\d+)", pitch)
    if not match:
        return 0
    step, accidental, octave = match.groups()
    semitone = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[step]
    semitone += accidental.count("#") - accidental.count("b")
    return (int(octave) + 1) * 12 + semitone


def _split_paired_melodic_part(
    events: list[dict], source_id: str, second_id: str
) -> list[dict]:
    """Split a condensed two-player staff into monophonic player parts.

    Two-note chords become upper/lower player lines. A lone note is duplicated,
    which is conventional unison notation on a paired orchestral staff.
    """
    retained = [event for event in events if event["part_id"] != source_id]
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for event in events:
        if event["part_id"] != source_id:
            continue
        groups[
            (
                event["measure_index"],
                event["onset"],
                event.get("staff", "1"),
                event.get("voice", "1"),
            )
        ].append(event)
    for group in groups.values():
        notes = sorted(group, key=lambda event: _pitch_height(event["pitch"]), reverse=True)
        if len(notes) == 1:
            assignments = ((source_id, notes[0]), (second_id, notes[0]))
        else:
            assignments = ((source_id, notes[0]), (second_id, notes[-1]))
        for target_id, event in assignments:
            cloned = _clone_event(event, target_id)
            cloned["chord"] = False
            retained.append(cloned)
    return retained


def _restore_missed_quintuplets(events: list[dict]) -> int:
    """Restore obvious 5:4 sixteenth groups that Audiveris expanded to five beats."""
    grouped: dict[tuple[str, int, str, str], list[dict]] = defaultdict(list)
    for event in events:
        grouped[
            (
                event["part_id"],
                event["measure_index"],
                event.get("staff", "1"),
                event.get("voice", "1"),
            )
        ].append(event)
    restored = 0
    for (part_id, measure_index, _staff, _voice), stream in grouped.items():
        _beats, _beat_type, expected = movement1_meter(measure_index)
        if expected != 4 or any(event.get("tuplet") for event in stream):
            continue
        if not stream or any(Fraction(event["duration"]) != Fraction(1, 4) for event in stream):
            continue
        unique_onsets = sorted({Fraction(event["onset"]) for event in stream})
        if len(unique_onsets) < 17 or max(unique_onsets) < 4:
            continue
        for event in stream:
            original_onset = Fraction(event["onset"])
            event["onset"] = str(original_onset * Fraction(4, 5))
            event["duration"] = "1/5"
            event["type"] = "16th"
            event["dots"] = 0
            event["tuplet"] = {"actual": "5", "normal": "4"}
            group_index = int(original_onset * 4) // 5
            event["tuplet_group"] = f"{part_id}-{measure_index}-quint-{group_index}"
            restored += 1
        last_end = max(
            Fraction(event["onset"]) + Fraction(event["duration"]) for event in stream
        )
        while last_end < expected:
            rest = copy.deepcopy(stream[-1])
            rest["onset"] = str(last_end)
            rest["duration"] = "1/5"
            rest["pitch"] = None
            rest["rest"] = True
            rest["chord"] = False
            rest["ties"] = []
            rest["articulations"] = []
            rest["lyrics"] = []
            rest["tuplet"] = {"actual": "5", "normal": "4"}
            group_index = int(last_end * 5) // 5
            rest["tuplet_group"] = f"{part_id}-{measure_index}-quint-{group_index}"
            events.append(rest)
            last_end += Fraction(1, 5)
    return restored


def _assign_imported_tuplet_groups(events: list[dict]) -> int:
    """Recover tuplet boundaries lost by the canonical MusicXML parser."""
    streams: dict[tuple[str, int, str, str], list[dict]] = defaultdict(list)
    for event in events:
        if event.get("tuplet"):
            streams[
                (
                    event["part_id"],
                    event["measure_index"],
                    event.get("staff", "1"),
                    event.get("voice", "1"),
                )
            ].append(event)
    assigned = 0
    for stream_key, stream in streams.items():
        by_ratio: list[list[dict]] = []
        current: list[dict] = []
        current_ratio = None
        for event in sorted(stream, key=lambda item: Fraction(item["onset"])):
            ratio = (
                event["tuplet"].get("actual"),
                event["tuplet"].get("normal"),
            )
            if current and ratio != current_ratio:
                by_ratio.append(current)
                current = []
            current.append(event)
            current_ratio = ratio
        if current:
            by_ratio.append(current)

        for run_index, run in enumerate(by_ratio):
            actual = max(1, int(run[0]["tuplet"].get("actual") or 1))
            normal = max(1, int(run[0]["tuplet"].get("normal") or 1))
            onset_groups: dict[Fraction, list[dict]] = defaultdict(list)
            for event in run:
                onset_groups[Fraction(event["onset"])].append(event)
            onsets = sorted(onset_groups)
            chunk_index = 0
            group_index = 0
            while chunk_index < len(onsets):
                chunk: list[Fraction] = []
                nominal_total = Fraction(0)
                nominal_base: Fraction | None = None
                complete = False
                for onset in onsets[chunk_index:]:
                    representative = onset_groups[onset][0]
                    nominal = Fraction(representative["duration"]) * Fraction(actual, normal)
                    nominal_total += nominal
                    nominal_base = nominal if nominal_base is None else min(nominal_base, nominal)
                    chunk.append(onset)
                    # A tuplet may contain fewer noteheads than ``actual``
                    # when one member has a longer nominal value (for example
                    # half + quarter inside a three-in-the-time-of-two group).
                    if nominal_total == actual * nominal_base:
                        complete = True
                        break
                for local_index, onset in enumerate(chunk):
                    group = (
                        f"imported-{stream_key}-{run_index}-{group_index}"
                        if complete
                        else f"imported-standalone-{stream_key}-{run_index}-{chunk_index}-{local_index}"
                    )
                    for event in onset_groups[onset]:
                        event["tuplet_group"] = group
                        if not complete:
                            event["_standalone_tuplet"] = True
                        else:
                            event.pop("_standalone_tuplet", None)
                        assigned += 1
                chunk_index += len(chunk)
                group_index += 1
    return assigned


def _verified_tuplet_event(
    template: dict,
    *,
    part_id: str,
    measure_index: int,
    onset: Fraction,
    duration: Fraction,
    pitch: str,
    voice: str,
    staff: str,
    actual: int,
    normal: int,
    group: str,
) -> dict:
    """Create one visually verified tuplet member without OCR cursor debris."""
    event = copy.deepcopy(template)
    event.update(
        {
            "part_id": part_id,
            "measure_index": measure_index,
            "measure_number": str(measure_index),
            "onset": str(onset),
            "duration": str(duration),
            "pitch": pitch,
            "rest": False,
            "grace": False,
            "chord": False,
            "voice": voice,
            "staff": staff,
            "type": "16th" if duration == Fraction(1, 5) else event.get("type"),
            "dots": 0,
            "tuplet": {"actual": str(actual), "normal": str(normal)},
            "tuplet_group": group,
            "ties": [],
            "articulations": [],
            "lyrics": [],
        }
    )
    event.pop("_standalone_tuplet", None)
    return event


def _restore_movement1_review_tuplets(events: list[dict]) -> int:
    """Restore tuplets visually checked in printed measures 26-34.

    Audiveris omitted structural rests in several triplets and read each 5:4
    passage in measures 33-34 as ordinary sixteenths.  The latter makes a
    nominal five-quarter stream inside a 4/4 bar.  Rebuilding the verified
    voices here retains the printed notes while keeping every bar exact.
    """
    restored = 0

    # Measure 28: the second member/group was dropped on several sustained
    # triplet staves.  Replace its OCR rest with the printed repeated pitch or
    # chord, preserving the original staff and voice.
    for part_id in ("P17", "P18", "P20", "P21", "P22", "P32", "P47"):
        streams: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for event in events:
            if event["part_id"] == part_id and event["measure_index"] == 28:
                streams[(event.get("staff", "1"), event.get("voice", "1"))].append(event)
        for (staff, voice), stream in streams.items():
            by_onset: dict[Fraction, list[dict]] = defaultdict(list)
            for event in stream:
                by_onset[Fraction(event["onset"])].append(event)
            final_events = by_onset.get(Fraction(8, 3), [])
            if any(event.get("pitch") for event in final_events):
                continue
            source_onset = Fraction(2) if Fraction(2) in by_onset else Fraction(4, 3)
            source = [event for event in by_onset.get(source_onset, []) if event.get("pitch")]
            if not source:
                continue
            if final_events:
                events[:] = [event for event in events if event not in final_events]
            group = f"{part_id}-28-reviewed-triplet-{staff}-{voice}"
            for original in source:
                cloned = copy.deepcopy(original)
                cloned.update(
                    {
                        "onset": "8/3",
                        "duration": "4/3",
                        "type": "half",
                        "tuplet": {"actual": "3", "normal": "2"},
                        "tuplet_group": group,
                    }
                )
                cloned.pop("_standalone_tuplet", None)
                events.append(cloned)
                restored += 1

    # Measure 28 strings contain two adjacent quarter+half triplet groups.
    # OMR retained only the first one in each string staff.
    for part_id in ("P34", "P35", "P36", "P37"):
        stream = [
            event
            for event in events
            if event["part_id"] == part_id
            and event["measure_index"] == 28
            and event.get("pitch")
        ]
        if not stream or any(Fraction(event["onset"]) >= 2 for event in stream):
            continue
        first = min(stream, key=lambda event: Fraction(event["onset"]))
        second = max(stream, key=lambda event: Fraction(event["onset"]))
        for event in stream:
            event["tuplet"] = {"actual": "3", "normal": "2"}
            event["tuplet_group"] = f"{part_id}-28-reviewed-triplet-0"
            event.pop("_standalone_tuplet", None)
        for original, onset, duration, note_type in (
            (second, Fraction(2), Fraction(4, 3), "half"),
            (first, Fraction(10, 3), Fraction(2, 3), "quarter"),
        ):
            cloned = copy.deepcopy(original)
            cloned.update(
                {
                    "onset": str(onset),
                    "duration": str(duration),
                    "type": note_type,
                    "tuplet": {"actual": "3", "normal": "2"},
                    "tuplet_group": f"{part_id}-28-reviewed-triplet-1",
                }
            )
            cloned.pop("_standalone_tuplet", None)
            events.append(cloned)
            restored += 1

    # Measures 33 and 34: two repeated ascending/descending 5:4 figures on
    # the paired oboe and clarinet staves.  They are two independent voices,
    # so their quintuplets alternate at quarter-beat boundaries.
    wind_patterns = {
        "P17": (
            ("C4", "Db4", "E4", "F4", "D#5"),
            ("E5", "D#5", "F4", "E4", "Db4"),
        ),
        "P19": (
            ("D4", "Eb4", "F#4", "G4", "E#5"),
            ("F#5", "E#5", "G4", "F#4", "Eb4"),
        ),
    }
    for measure_index in (33, 34):
        for part_id, (ascending, descending) in wind_patterns.items():
            removed = _replace_measure_events(events, part_id, measure_index)
            template = next((event for event in removed if event.get("pitch")), None)
            if template is None:
                continue
            for group_index, (start, voice, pitches) in enumerate(
                (
                    (Fraction(0), "1", ascending),
                    (Fraction(1), "2", descending),
                    (Fraction(2), "1", ascending),
                    (Fraction(3), "2", descending),
                )
            ):
                for note_index, pitch in enumerate(pitches):
                    events.append(
                        _verified_tuplet_event(
                            template,
                            part_id=part_id,
                            measure_index=measure_index,
                            onset=start + Fraction(note_index, 5),
                            duration=Fraction(1, 5),
                            pitch=pitch,
                            voice=voice,
                            staff="1",
                            actual=5,
                            normal=4,
                            group=f"{part_id}-{measure_index}-reviewed-quint-{group_index}",
                        )
                    )
                    restored += 1

    # Measure 34 violins: the upper violin has two ascending quintuplets;
    # Violin II answers with the two descending figures printed one beat later.
    violin_patterns = {
        "P34": ((Fraction(0), Fraction(2)), ("C4", "Db4", "E4", "F4", "D#5")),
        "P35": ((Fraction(1), Fraction(3)), ("D#5", "F4", "E4", "Db4", "C4")),
    }
    for part_id, (starts, pitches) in violin_patterns.items():
        removed = _replace_measure_events(events, part_id, 34)
        template = next((event for event in removed if event.get("pitch")), None)
        if template is None:
            continue
        for group_index, start in enumerate(starts):
            for note_index, pitch in enumerate(pitches):
                events.append(
                    _verified_tuplet_event(
                        template,
                        part_id=part_id,
                        measure_index=34,
                        onset=start + Fraction(note_index, 5),
                        duration=Fraction(1, 5),
                        pitch=pitch,
                        voice="1",
                        staff="1",
                        actual=5,
                        normal=4,
                        group=f"{part_id}-34-reviewed-quint-{group_index}",
                    )
                )
                restored += 1

    return restored


def _replace_measure_events(
    events: list[dict], part_id: str, measure_index: int, staff: str | None = None
) -> list[dict]:
    """Remove and return pitched source events for one manually verified stream."""
    removed = []
    retained = []
    for event in events:
        matches = (
            event["part_id"] == part_id
            and event["measure_index"] == measure_index
            and (staff is None or event.get("staff", "1") == staff)
        )
        if matches:
            removed.append(event)
        else:
            retained.append(event)
    events[:] = retained
    return removed


def _verified_quintuplet_event(
    template: dict,
    *,
    part_id: str,
    measure_index: int,
    onset: Fraction,
    pitch: str,
    voice: str,
    staff: str,
    group: int,
) -> dict:
    event = copy.deepcopy(template)
    event.update(
        {
            "part_id": part_id,
            "measure_index": measure_index,
            "measure_number": str(measure_index),
            "onset": str(onset),
            "duration": "1/5",
            "pitch": pitch,
            "rest": False,
            "grace": False,
            "chord": False,
            "voice": voice,
            "staff": staff,
            "type": "16th",
            "dots": 0,
            "tuplet": {"actual": "5", "normal": "4"},
            "tuplet_group": f"{part_id}-{measure_index}-verified-quint-{group}",
            "ties": [],
            "articulations": [],
            "lyrics": [],
        }
    )
    return event


def _restore_verified_violin2_quintuplets(events: list[dict]) -> int:
    """Restore the two alternating voices visible in Violin II, bars 4-10."""
    ascending = ("G4", "A4", "B4", "C#5", "D5")
    descending = tuple(reversed(ascending))
    restored = 0
    fallback = next((item for item in events if item["part_id"] == "P35"), None)
    if fallback is None:
        return 0
    for measure_index in range(4, 11):
        source = _replace_measure_events(events, "P35", measure_index, "1")
        template = source[0] if source else fallback
        for beat in range(4):
            pitches = ascending if beat % 2 == 0 else descending
            voice = "2" if beat % 2 == 0 else "1"
            for note_index, pitch in enumerate(pitches):
                events.append(
                    _verified_quintuplet_event(
                        template,
                        part_id="P35",
                        measure_index=measure_index,
                        onset=Fraction(beat) + Fraction(note_index, 5),
                        pitch=pitch,
                        voice=voice,
                        staff="1",
                        group=beat,
                    )
                )
                restored += 1
    return restored


def _restore_verified_harp_quintuplets(events: list[dict]) -> int:
    """Normalize the four 5:4 groups on the upper staff of both harps."""
    restored = 0
    for part_id in ("P32", "P47"):
        fallback = next((item for item in events if item["part_id"] == part_id), None)
        if fallback is None:
            continue
        for measure_index in range(6, 11):
            source = _replace_measure_events(events, part_id, measure_index, "1")
            if not source:
                continue
            source.sort(
                key=lambda item: (
                    int(item.get("voice", "1")),
                    Fraction(item["onset"]),
                    _pitch_height(item["pitch"]),
                )
            )
            pitches = [item["pitch"] for item in source]
            # Audiveris omitted the final two notes in bar 10. The printed
            # ostinato is a repeating three-note cell, so complete that cell.
            while len(pitches) < 20:
                pitches.append(pitches[len(pitches) % min(3, len(pitches))])
            for note_index, pitch in enumerate(pitches[:20]):
                events.append(
                    _verified_quintuplet_event(
                        source[0],
                        part_id=part_id,
                        measure_index=measure_index,
                        onset=Fraction(note_index, 5),
                        pitch=pitch,
                        voice="1",
                        staff="1",
                        group=note_index // 5,
                    )
                )
                restored += 1
    return restored


def _restore_verified_celesta_quintuplets(events: list[dict]) -> int:
    """Normalize Celesta's four 5:4 groups in bars 7-10.

    MusicXML tuplets cannot safely cross a backup between grand-staff streams:
    MuseScore otherwise lengthens the imported bar. Keep the exact notes and
    rhythm on the upper staff; cross-staff engraving is a later visual edit.
    """
    restored = 0
    fallback = next((item for item in events if item["part_id"] == "P39"), None)
    if fallback is None:
        return 0
    for measure_index in range(7, 11):
        source = _replace_measure_events(events, "P39", measure_index)
        if not source:
            continue
        source.sort(key=lambda item: (Fraction(item["onset"]), item.get("staff", "1")))
        for note_index, original in enumerate(source[:20]):
            events.append(
                _verified_quintuplet_event(
                    original,
                    part_id="P39",
                    measure_index=measure_index,
                    onset=Fraction(note_index, 5),
                    pitch=original["pitch"],
                    voice="1",
                    staff="1",
                    group=note_index // 5,
                )
            )
            restored += 1
    return restored


def _normalize_verified_harp_triplet_bars(events: list[dict]) -> int:
    """Repair the visually confirmed full-bar Harp I ostinati in m.127/130."""
    normalized = 0
    for measure_index in (127, 130):
        for staff, count, duration in (
            ("1", 12, Fraction(1, 3)),
            ("2", 6, Fraction(2, 3)),
        ):
            source = _replace_measure_events(events, "P32", measure_index, staff)
            notes = [event for event in source if event.get("pitch")]
            notes.sort(
                key=lambda event: (
                    int(event.get("voice", "1")),
                    Fraction(event["onset"]),
                    _pitch_height(event.get("pitch")),
                )
            )
            if len(notes) < count:
                events.extend(source)
                continue
            for index, original in enumerate(notes[:count]):
                cloned = copy.deepcopy(original)
                cloned.update(
                    {
                        "onset": str(index * duration),
                        "duration": str(duration),
                        "voice": "1",
                        "staff": staff,
                        "chord": False,
                        "tuplet": {"actual": "3", "normal": "2"},
                        "tuplet_group": f"P32-{measure_index}-verified-triplet-{staff}-{index // 3}",
                    }
                )
                cloned.pop("_standalone_tuplet", None)
                events.append(cloned)
                normalized += 1
    return normalized


def _normalize_final_two_note_tremolos(events: list[dict]) -> int:
    """Restore the measured two-note tremolos printed on PDF page 41."""
    normalized = 0
    target_parts = ("P15", "P45", "P16", "P46", "P19", "P39", "P34", "P35")
    for part_id in target_parts:
        for measure_index in (234, 235, 236):
            staves = sorted(
                {
                    event.get("staff", "1")
                    for event in events
                    if event["part_id"] == part_id
                    and event["measure_index"] == measure_index
                    and event.get("pitch")
                }
            )
            for staff in staves:
                source = _replace_measure_events(events, part_id, measure_index, staff)
                pitched = [event for event in source if event.get("pitch")]
                onset_groups: dict[Fraction, list[dict]] = defaultdict(list)
                for event in pitched:
                    onset_groups[Fraction(event["onset"])].append(event)
                groups = [onset_groups[onset] for onset in sorted(onset_groups)]
                if len(groups) < 2:
                    events.extend(source)
                    continue

                # Clarinet m.236 ends with a sustained half-note chord after
                # one tremolo pair. Other verified streams contain two pairs.
                sustained = None
                if part_id == "P19" and measure_index == 236 and len(groups) >= 3:
                    sustained = groups[-1]
                    groups = groups[:2]
                else:
                    groups = groups[:4]
                if len(groups) % 2:
                    events.extend(source)
                    continue

                onset = Fraction(0)
                for group_index, group in enumerate(groups):
                    duration = Fraction(1)
                    ordered = sorted(group, key=lambda event: _pitch_height(event.get("pitch")))
                    for chord_index, original in enumerate(ordered):
                        cloned = copy.deepcopy(original)
                        cloned.update(
                            {
                                "onset": str(onset),
                                "duration": str(duration),
                                "voice": "1",
                                "staff": staff,
                                "chord": chord_index > 0,
                                "tuplet": None,
                                "tuplet_group": None,
                                "tremolo": (
                                    {
                                        "type": "start" if group_index % 2 == 0 else "stop",
                                        "marks": 3,
                                    }
                                    if chord_index == 0
                                    else None
                                ),
                            }
                        )
                        cloned.pop("_standalone_tuplet", None)
                        events.append(cloned)
                        normalized += 1
                    onset += duration
                if sustained:
                    ordered = sorted(sustained, key=lambda event: _pitch_height(event.get("pitch")))
                    for chord_index, original in enumerate(ordered):
                        cloned = copy.deepcopy(original)
                        cloned.update(
                            {
                                "onset": "2",
                                "duration": "2",
                                "voice": "1",
                                "staff": staff,
                                "chord": chord_index > 0,
                                "tuplet": None,
                                "tuplet_group": None,
                                "tremolo": None,
                            }
                        )
                        cloned.pop("_standalone_tuplet", None)
                        events.append(cloned)
                        normalized += 1
    return normalized


def build_movement1_block_7_12(
    candidate_7_8_path: Path,
    candidate_9_12_path: Path,
    output: Path,
    candidate_13_path: Path | None = None,
) -> dict:
    """Build the reviewed opening block with one stable orchestral layout."""
    first = parse_musicxml(candidate_7_8_path)
    root = ET.fromstring(_read_musicxml(candidate_7_8_path))
    tree = ET.ElementTree(root)
    aliases, applied = _apply_movement1_profile(first, root)
    if not applied:
        raise ValueError("o OMR das páginas 7-8 não corresponde ao perfil do I movimento")

    # Preserve the real performer identities instead of leaving paired flute
    # staves and one generic harp in the review score.
    _rename_score_part(root, "P15", "Flauta III / Piccolo I")
    _clone_score_part_after(root, "P15", "P45", "Flauta IV / Piccolo II")
    _rename_score_part(root, "P16", "Flauta I")
    _clone_score_part_after(root, "P16", "P46", "Flauta II")
    _rename_score_part(root, "P32", "Harpa I")
    _clone_score_part_after(root, "P32", "P47", "Harpa II")

    mapped_events: list[dict] = []
    for event in first["events"]:
        if not event.get("pitch"):
            continue
        target = aliases.get(event["part_id"], event["part_id"])
        mapped_events.append(_clone_event(event, target))

    # Tupletted rests are members of the printed rhythm, not disposable empty
    # space.  Keeping them lets complete 3:2 groups survive MusicXML import.
    later = parse_musicxml(candidate_9_12_path, include_rests=True)
    page_maps: list[tuple[range, dict[str, str]]] = [
        (
            range(1, 6),
            {
                "P39": "P15", "P40": "P16", "P41": "P17", "P42": "P18",
                "P43": "P19", "P44": "P20", "P45": "P21", "P46": "P22",
                "P47": "P23", "P48": "P24", "P49": "P9", "P50": "P25",
                "P51": "P26", "P52": "P27", "P53": "P28", "P54": "P29",
                "P55": "P32", "P56": "P39", "P57": "P33", "P58": "P34",
                "P59": "P35", "P60": "P36", "P61": "P37", "P62": "P38",
            },
        ),
        (
            range(6, 13),
            {
                "P24": "P15", "P25": "P16", "P26": "P17", "P27": "P18",
                "P28": "P19", "P29": "P20", "P30": "P21", "P31": "P22",
                "P32": "P23", "P33": "P24", "P34": "P9", "P35": "P25",
                "P36": "P26", "P37": "P27", "P38": "P28", "P54": "P29",
                "P55": "P32", "P63": "P39", "P64": "P33", "P65": "P34",
                "P66": "P35", "P67": "P36", "P68": "P37", "P69": "P38",
            },
        ),
        (
            range(13, 23),
            {
                "P11": "P15", "P12": "P16", "P13": "P17", "P14": "P18",
                "P15": "P19", "P16": "P20", "P17": "P21", "P18": "P22",
                "P19": "P23", "P20": "P24", "P21": "P9", "P22": "P25",
                "P23": "P26", "P37": "P27", "P38": "P28", "P54": "P29",
                "P55": "P32", "P56": "P39", "P64": "P33", "P70": "P34",
                "P71": "P35", "P72": "P36", "P73": "P37", "P74": "P38",
            },
        ),
        (
            range(23, 30),
            {
                "P1": "P16", "P2": "P17", "P3": "P18", "P4": "P19",
                "P5": "P20", "P6": "P21", "P7": "P22", "P8": "P23",
                "P9": "P24", "P10": "P9", "P23": "P26", "P37": "P27",
                "P38": "P28", "P54": "P29", "P55": "P32", "P64": "P33",
                "P65": "P34", "P75": "P35", "P76": "P36", "P77": "P37",
                "P78": "P38",
            },
        ),
    ]
    for event in later["events"]:
        keep_structural_rest = (
            18 <= event["measure_index"] <= 26
            and event.get("tuplet")
            and _duration_notation(Fraction(event["duration"]), event["tuplet"])
            is not None
        )
        if not event.get("pitch") and not keep_structural_rest:
            continue
        target = None
        for measures, mapping in page_maps:
            if event["measure_index"] in measures:
                target = mapping.get(event["part_id"])
                break
        if not target:
            continue
        cloned = _clone_event(event, target)
        cloned["measure_index"] += 8
        cloned["measure_number"] = str(cloned["measure_index"])
        mapped_events.append(cloned)

    end_measure = 37
    source_pages = list(range(7, 13))
    if candidate_13_path is not None:
        page_13 = parse_musicxml(candidate_13_path)
        page_13_map = {
            "P1": "P16", "P2": "P17", "P3": "P18", "P4": "P19",
            "P5": "P20", "P6": "P21", "P7": "P22", "P8": "P23",
            "P9": "P24", "P10": "P9", "P11": "P26", "P12": "P27",
            "P13": "P28", "P14": "P29", "P15": "P32", "P16": "P33",
            "P17": "P34", "P18": "P35", "P19": "P36", "P20": "P37",
            "P21": "P38",
        }
        for event in page_13["events"]:
            if not event.get("pitch") or event["part_id"] not in page_13_map:
                continue
            target = page_13_map[event["part_id"]]
            cloned = _clone_event(event, target)
            cloned["measure_index"] += 37
            cloned["measure_number"] = str(cloned["measure_index"])
            mapped_events.append(cloned)
            # The one trumpet staff here is marked as an orchestral unison.
            if event["part_id"] == "P10":
                mapped_events.append(_clone_event(cloned, "P25"))
        end_measure = 44
        source_pages.append(13)

    mapped_events = _split_paired_melodic_part(mapped_events, "P15", "P45")
    mapped_events = _split_paired_melodic_part(mapped_events, "P16", "P46")
    mapped_events.extend(
        _clone_event(event, "P47")
        for event in list(mapped_events)
        if event["part_id"] == "P32"
    )
    for event in mapped_events:
        # Audiveris may number grand-staff voices globally (5-8 on the lower
        # staff). MuseScore expects the local 1-4 voice slot on each staff;
        # leaving 5/7 here makes it right-align the voice and extend the bar.
        try:
            event["voice"] = str((int(event.get("voice", "1")) - 1) % 4 + 1)
        except ValueError:
            event["voice"] = "1"
    restored_quintuplet_notes = _restore_missed_quintuplets(mapped_events)
    verified_violin2_notes = _restore_verified_violin2_quintuplets(mapped_events)
    verified_harp_notes = _restore_verified_harp_quintuplets(mapped_events)
    verified_celesta_notes = _restore_verified_celesta_quintuplets(mapped_events)
    reviewed_tuplet_notes = _restore_movement1_review_tuplets(mapped_events)
    grouped_imported_tuplet_notes = _assign_imported_tuplet_groups(mapped_events)
    events_by_part: dict[str, list[dict]] = defaultdict(list)
    for event in mapped_events:
        events_by_part[event["part_id"]].append(event)

    for credit in root.findall("credit"):
        root.remove(credit)
    work = root.find("work")
    if work is None:
        work = ET.Element("work")
        root.insert(0, work)
    title = work.find("work-title")
    if title is None:
        title = ET.SubElement(work, "work-title")
    title.text = f"I. Allegro - páginas 7-{source_pages[-1]}"

    meter_change_measures = {
        measure for measure in MOVEMENT1_METER_CHANGES if measure <= end_measure
    }
    for part in root.findall("part"):
        part_id = part.get("id", "")
        clef_plan = MOVEMENT1_CLEF_CHANGES.get(part_id, [])
        old_measures = part.findall("measure")
        first_attributes = (
            copy.deepcopy(old_measures[0].find("attributes")) if old_measures else None
        )
        for measure in old_measures:
            part.remove(measure)
        part_events = events_by_part.get(part_id, [])
        staves = max(
            [int(event.get("staff", "1")) for event in part_events]
            + [int(first_attributes.findtext("staves", "1")) if first_attributes is not None else 1]
        )
        for measure_index in range(1, end_measure + 1):
            measure = ET.SubElement(part, "measure", {"number": str(measure_index)})
            beats, beat_type, duration = movement1_meter(measure_index)
            if measure_index == 1:
                attributes = copy.deepcopy(first_attributes) if first_attributes is not None else ET.Element("attributes")
                measure.append(attributes)
            elif measure_index in meter_change_measures:
                attributes = ET.SubElement(measure, "attributes")
            else:
                attributes = None
            measure_clefs = [
                (onset, staff, sign, line)
                for change_measure, onset, staff, sign, line in clef_plan
                if change_measure == measure_index
            ]
            starting_clefs = [
                (staff, sign, line)
                for onset, staff, sign, line in measure_clefs
                if onset == 0
            ]
            if starting_clefs:
                if attributes is None:
                    attributes = ET.Element("attributes")
                    measure.insert(0, attributes)
                for clef in list(attributes.findall("clef")):
                    attributes.remove(clef)
                for staff, sign, line in starting_clefs:
                    clef = ET.SubElement(
                        attributes, "clef", {"number": str(staff)}
                    )
                    ET.SubElement(clef, "sign").text = sign
                    ET.SubElement(clef, "line").text = str(line)
            if attributes is not None and (
                measure_index == 1 or measure_index in meter_change_measures
            ):
                divisions = attributes.find("divisions")
                if divisions is None:
                    divisions = ET.Element("divisions")
                    attributes.insert(0, divisions)
                divisions.text = str(DIVISIONS)
                time = attributes.find("time")
                if time is None:
                    time = ET.SubElement(attributes, "time")
                for child in list(time):
                    time.remove(child)
                ET.SubElement(time, "beats").text = str(beats)
                ET.SubElement(time, "beat-type").text = str(beat_type)

            current = [event for event in part_events if event["measure_index"] == measure_index]
            inline_clefs = [
                (onset, staff, sign, line)
                for onset, staff, sign, line in measure_clefs
                if onset > 0
            ]
            streams: list[tuple[str, str, list[dict]]] = []
            for staff_number in range(1, staves + 1):
                staff = str(staff_number)
                staff_events = [event for event in current if event.get("staff", "1") == staff]
                voices = sorted({event.get("voice", "1") for event in staff_events}) or ["1"]
                for voice in voices:
                    streams.append(
                        (staff, voice, [event for event in staff_events if event.get("voice", "1") == voice])
                    )
            clef_staves_emitted: set[str] = set()
            for stream_index, (staff, voice, stream_events) in enumerate(streams):
                if stream_index:
                    backup = ET.SubElement(measure, "backup")
                    ET.SubElement(backup, "duration").text = str(duration * DIVISIONS)
                stream_clefs = []
                if staff not in clef_staves_emitted:
                    stream_clefs = [
                        change for change in inline_clefs if str(change[1]) == staff
                    ]
                    clef_staves_emitted.add(staff)
                _emit_voice(
                    measure,
                    stream_events,
                    duration,
                    voice,
                    staff,
                    stream_clefs,
                )

    validation = _write_and_validate(
        tree,
        output,
        lambda _part, measure: movement1_meter(measure)[2],
    )
    return {
        "output": str(output.resolve()),
        "pages": source_pages,
        "measures": end_measure,
        "parts": len(root.findall("part")),
        "mapped_events": len(mapped_events),
        "restored_quintuplet_notes": restored_quintuplet_notes,
        "verified_violin2_quintuplet_notes": verified_violin2_notes,
        "verified_harp_quintuplet_notes": verified_harp_notes,
        "verified_celesta_quintuplet_notes": verified_celesta_notes,
        "reviewed_tuplet_notes": reviewed_tuplet_notes,
        "grouped_imported_tuplet_notes": grouped_imported_tuplet_notes,
        "verified_clef_changes": sum(
            len(MOVEMENT1_CLEF_CHANGES.get(part_id, []))
            for part_id in {item.get("id", "") for item in root.findall("part")}
        ),
        "meter_changes": {
            str(measure): f"{beats}/{beat_type}"
            for measure, (beats, beat_type) in MOVEMENT1_METER_CHANGES.items()
            if measure <= end_measure
        },
        "meter_validation": validation,
    }


def _layout_targets(entry: str | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(entry, str):
        return (entry,)
    if entry and entry[0] == "split":
        return tuple(entry[1:])
    return tuple(entry)


def _candidate_clef_changes(
    path: Path,
    layout: list[str | tuple[str, ...]],
    first_measure: int,
) -> dict[str, list[tuple[int, Fraction, int, str, int]]]:
    """Read clef positions directly from one page's MusicXML event stream."""
    root = ET.fromstring(_read_musicxml(path))
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    parts = root.findall("part")
    if len(parts) != len(layout):
        raise ValueError(
            f"layout de claves incompatível em {path}: {len(parts)} != {len(layout)}"
        )
    result: dict[str, list[tuple[int, Fraction, int, str, int]]] = defaultdict(list)
    for source_part, entry in zip(parts, layout):
        divisions = 1
        for local_measure, measure in enumerate(source_part.findall("measure"), 1):
            cursor = Fraction(0)
            previous_onset = Fraction(0)
            for child in measure:
                if child.tag == "attributes":
                    divisions_text = child.findtext("divisions")
                    if divisions_text:
                        divisions = int(divisions_text)
                    for clef in child.findall("clef"):
                        sign = clef.findtext("sign")
                        line = clef.findtext("line")
                        if not sign or not line or sign in {"percussion", "TAB"}:
                            continue
                        staff = int(clef.get("number", "1"))
                        for target in _layout_targets(entry):
                            result[target].append(
                                (
                                    first_measure + local_measure - 1,
                                    max(Fraction(0), cursor),
                                    staff,
                                    sign,
                                    int(line),
                                )
                            )
                    continue
                if child.tag in {"backup", "forward"}:
                    movement = Fraction(int(child.findtext("duration", "0")), divisions)
                    cursor += movement if child.tag == "forward" else -movement
                    continue
                if child.tag != "note":
                    continue
                duration_text = child.findtext("duration")
                duration = Fraction(int(duration_text), divisions) if duration_text else Fraction(0)
                chord = child.find("chord") is not None
                grace = child.find("grace") is not None
                onset = previous_onset if chord else cursor
                if not chord:
                    previous_onset = onset
                    if not grace:
                        cursor += duration
    return result


def build_movement1_complete(
    base_musicxml: Path,
    page_candidates: dict[int, Path],
    output: Path,
) -> dict:
    """Assemble PDF pages 7-41 into one meter-locked 239-measure score."""
    base = parse_musicxml(base_musicxml)
    if base["measures"] != 44:
        raise ValueError("a base validada precisa terminar no compasso 44")
    root = ET.fromstring(_read_musicxml(base_musicxml))
    tree = ET.ElementTree(root)

    existing_ids = {part.get("id", "") for part in root.findall("part")}
    if "P48" not in existing_ids:
        # Xylophone belongs to the percussion block, immediately after timpani.
        _clone_score_part_after(root, "P29", "P48", "Xilofone")
    if "P49" not in existing_ids:
        _clone_score_part_after(root, "P30", "P49", "Pratos")
    if "P50" not in existing_ids:
        _clone_score_part_after(root, "P31", "P50", "Maracas")

    base_event_count = len([event for event in base["events"] if event.get("pitch")])
    mapped_events: list[dict] = []
    clef_changes = {
        part_id: list(changes) for part_id, changes in MOVEMENT1_CLEF_CHANGES.items()
    }
    first_measure = 45
    page_audit = []
    for page in range(14, 42):
        candidate_path = page_candidates.get(page)
        if candidate_path is None or not candidate_path.is_file():
            raise FileNotFoundError(f"OMR individual ausente para a página {page}")
        # Tuplet rests are structural members of the group. Keeping them is
        # essential: omitting one makes MuseScore stretch the remaining notes
        # when it reconstructs the native tuplet container.
        score = parse_musicxml(candidate_path, include_rests=True)
        layout = MOVEMENT1_PAGE_LAYOUTS[page]
        if len(layout) != len(score["parts"]):
            raise ValueError(
                f"layout da página {page}: {len(layout)} destinos para "
                f"{len(score['parts'])} partes"
            )

        source_ids = [part["id"] for part in score["parts"]]
        direct_counts: dict[str, int] = defaultdict(int)
        for entry in layout:
            if isinstance(entry, str):
                direct_counts[entry] += 1
        direct_seen: dict[str, int] = defaultdict(int)
        page_events: list[dict] = []
        mapped_counts: dict[str, int] = defaultdict(int)
        for source_id, entry in zip(source_ids, layout):
            source_events = [
                event
                for event in score["events"]
                if event["part_id"] == source_id and not event.get("grace")
            ]
            shifted = []
            for event in source_events:
                cloned = copy.deepcopy(event)
                cloned["measure_index"] = first_measure + event["measure_index"] - 1
                cloned["measure_number"] = str(cloned["measure_index"])
                shifted.append(cloned)

            if isinstance(entry, tuple) and entry and entry[0] == "split":
                first_target, second_target = entry[1], entry[2]
                temporary = [_clone_event(event, first_target) for event in shifted]
                split = _split_paired_melodic_part(
                    temporary, first_target, second_target
                )
                page_events.extend(split)
                for event in split:
                    mapped_counts[event["part_id"]] += 1
                continue

            targets = _layout_targets(entry)
            occurrence = 0
            if isinstance(entry, str) and direct_counts[entry] > 1:
                occurrence = direct_seen[entry]
                direct_seen[entry] += 1
            for target in targets:
                for event in shifted:
                    cloned = _clone_event(event, target)
                    if occurrence:
                        try:
                            voice = int(cloned.get("voice", "1"))
                        except ValueError:
                            voice = 1
                        cloned["voice"] = str((voice - 1 + occurrence) % 4 + 1)
                    page_events.append(cloned)
                    mapped_counts[target] += 1

        imported_tuplet_notes = _assign_imported_tuplet_groups(page_events)
        mapped_events.extend(page_events)
        detected_clefs = _candidate_clef_changes(
            candidate_path, layout, first_measure
        )
        for part_id, changes in detected_clefs.items():
            clef_changes.setdefault(part_id, []).extend(changes)
        last_measure = first_measure + score["measures"] - 1
        page_audit.append(
            {
                "page": page,
                "first_measure": first_measure,
                "last_measure": last_measure,
                "measures": score["measures"],
                "source_parts": len(score["parts"]),
                "source_events": len(score["events"]),
                "mapped_events": len(page_events),
                "grouped_tuplet_notes": imported_tuplet_notes,
                "mapped_parts": dict(sorted(mapped_counts.items())),
            }
        )
        first_measure = last_measure + 1

    end_measure = first_measure - 1
    if end_measure != 239:
        raise ValueError(f"o movimento deveria terminar no compasso 239, não {end_measure}")

    for event in mapped_events:
        try:
            event["voice"] = str((int(event.get("voice", "1")) - 1) % 4 + 1)
        except ValueError:
            event["voice"] = "1"
    normalized_harp_triplets = _normalize_verified_harp_triplet_bars(mapped_events)
    normalized_two_note_tremolos = _normalize_final_two_note_tremolos(mapped_events)
    restored_quintuplets = _restore_missed_quintuplets(mapped_events)
    events_by_part: dict[str, list[dict]] = defaultdict(list)
    for event in mapped_events:
        events_by_part[event["part_id"]].append(event)

    work = root.find("work")
    if work is None:
        work = ET.Element("work")
        root.insert(0, work)
    title = work.find("work-title")
    if title is None:
        title = ET.SubElement(work, "work-title")
    title.text = "I. Allegro - movimento completo"

    meter_change_measures = {
        measure for measure in MOVEMENT1_METER_CHANGES if measure <= end_measure
    }
    for part in root.findall("part"):
        part_id = part.get("id", "")
        clef_plan = sorted(set(clef_changes.get(part_id, [])))
        old_measures = part.findall("measure")
        first_attributes = (
            copy.deepcopy(old_measures[0].find("attributes")) if old_measures else None
        )
        preserve_validated_opening = part_id not in {"P48", "P49", "P50"}
        if not preserve_validated_opening:
            for measure in old_measures:
                part.remove(measure)
        part_events = events_by_part.get(part_id, [])
        staves = max(
            [int(event.get("staff", "1")) for event in part_events]
            + [int(first_attributes.findtext("staves", "1")) if first_attributes is not None else 1]
        )
        first_generated_measure = 45 if preserve_validated_opening else 1
        for measure_index in range(first_generated_measure, end_measure + 1):
            measure = ET.SubElement(part, "measure", {"number": str(measure_index)})
            beats, beat_type, duration = movement1_meter(measure_index)
            if measure_index == 1:
                attributes = copy.deepcopy(first_attributes) if first_attributes is not None else ET.Element("attributes")
                measure.append(attributes)
            elif measure_index in meter_change_measures:
                attributes = ET.SubElement(measure, "attributes")
            else:
                attributes = None
            measure_clefs = [
                (onset, staff, sign, line)
                for change_measure, onset, staff, sign, line in clef_plan
                if change_measure == measure_index
            ]
            starting_clefs = [
                (staff, sign, line)
                for onset, staff, sign, line in measure_clefs
                if onset == 0
            ]
            if starting_clefs:
                if attributes is None:
                    attributes = ET.Element("attributes")
                    measure.insert(0, attributes)
                for clef in list(attributes.findall("clef")):
                    attributes.remove(clef)
                for staff, sign, line in starting_clefs:
                    clef = ET.SubElement(attributes, "clef", {"number": str(staff)})
                    ET.SubElement(clef, "sign").text = sign
                    ET.SubElement(clef, "line").text = str(line)
            if attributes is not None and (
                measure_index == 1 or measure_index in meter_change_measures
            ):
                divisions = attributes.find("divisions")
                if divisions is None:
                    divisions = ET.Element("divisions")
                    attributes.insert(0, divisions)
                divisions.text = str(DIVISIONS)
                time = attributes.find("time")
                if time is None:
                    time = ET.SubElement(attributes, "time")
                for child in list(time):
                    time.remove(child)
                ET.SubElement(time, "beats").text = str(beats)
                ET.SubElement(time, "beat-type").text = str(beat_type)

            current = [event for event in part_events if event["measure_index"] == measure_index]
            inline_clefs = [
                (onset, staff, sign, line)
                for onset, staff, sign, line in measure_clefs
                if onset > 0
            ]
            streams: list[tuple[str, str, list[dict]]] = []
            for staff_number in range(1, staves + 1):
                staff = str(staff_number)
                staff_events = [event for event in current if event.get("staff", "1") == staff]
                voices = sorted({event.get("voice", "1") for event in staff_events}) or ["1"]
                for voice in voices:
                    streams.append(
                        (staff, voice, [event for event in staff_events if event.get("voice", "1") == voice])
                    )
            clef_staves_emitted: set[str] = set()
            for stream_index, (staff, voice, stream_events) in enumerate(streams):
                if stream_index:
                    backup = ET.SubElement(measure, "backup")
                    ET.SubElement(backup, "duration").text = str(duration * DIVISIONS)
                stream_clefs = []
                if staff not in clef_staves_emitted:
                    stream_clefs = [change for change in inline_clefs if str(change[1]) == staff]
                    clef_staves_emitted.add(staff)
                _emit_voice(measure, stream_events, duration, voice, staff, stream_clefs)

    validation = _write_and_validate(
        tree,
        output,
        lambda _part, measure: movement1_meter(measure)[2],
    )
    return {
        "output": str(output.resolve()),
        "pages": list(range(7, 42)),
        "measures": end_measure,
        "parts": len(root.findall("part")),
        "base_events_preserved": base_event_count,
        "mapped_events": len(mapped_events),
        "restored_quintuplet_notes": restored_quintuplets,
        "normalized_harp_triplet_notes": normalized_harp_triplets,
        "normalized_two_note_tremolo_notes": normalized_two_note_tremolos,
        "detected_clef_changes": sum(len(changes) for changes in clef_changes.values()),
        "page_audit": page_audit,
        "meter_changes": {
            str(measure): f"{beats}/{beat_type}"
            for measure, (beats, beat_type) in MOVEMENT1_METER_CHANGES.items()
            if measure <= end_measure
        },
        "meter_validation": validation,
    }


# The validated pages 67-69 end at printed measure 25.  The rest of the
# Scherzo stays in 9/8 through measure 171 and changes to 4/4 at rehearsal 10.
SCHERZO_METER_CHANGES: dict[int, tuple[int, int]] = {
    1: (9, 8),
    74: (6, 8),
    119: (9, 8),
    172: (4, 4),
    187: (6, 8),
}

SCHERZO_VOCAL_PARTS = {"P37", "P38", "P39", "P40", "P41", "P42"}


def scherzo_meter(measure_index: int) -> tuple[int, int, Fraction]:
    active = max(index for index in SCHERZO_METER_CHANGES if index <= measure_index)
    beats, beat_type = SCHERZO_METER_CHANGES[active]
    return beats, beat_type, Fraction(beats * 4, beat_type)


def _scherzo_measure_duration(part_id: str, measure_index: int) -> Fraction:
    # The opening model intentionally uses local 3/4 for the three lower
    # string staves while the rest of the score is in 9/8.
    if part_id in {"P28", "P29", "P30"} and measure_index <= 3:
        return Fraction(3)
    return scherzo_meter(measure_index)[2]


def _set_part_midi_program(root: ET.Element, part_id: str, program: int) -> None:
    score_part = root.find(f"./part-list/score-part[@id='{part_id}']")
    if score_part is None:
        return
    midi = score_part.find("midi-instrument")
    if midi is None:
        midi = ET.SubElement(midi if midi is not None else score_part, "midi-instrument")
        midi.set("id", f"{part_id}-I1")
    program_node = midi.find("midi-program")
    if program_node is None:
        program_node = ET.SubElement(midi, "midi-program")
    program_node.text = str(program)


def _set_initial_transpose(
    root: ET.Element,
    part_id: str,
    *,
    diatonic: int | None = None,
    chromatic: int | None = None,
    octave_change: int | None = None,
) -> None:
    part = root.find(f"./part[@id='{part_id}']")
    if part is None:
        return
    measure = part.find("measure")
    if measure is None:
        return
    attributes = measure.find("attributes")
    if attributes is None:
        attributes = ET.Element("attributes")
        measure.insert(0, attributes)
    old = attributes.find("transpose")
    if old is not None:
        attributes.remove(old)
    transpose = ET.SubElement(attributes, "transpose")
    if diatonic is not None:
        ET.SubElement(transpose, "diatonic").text = str(diatonic)
    if chromatic is not None:
        ET.SubElement(transpose, "chromatic").text = str(chromatic)
    if octave_change is not None:
        ET.SubElement(transpose, "octave-change").text = str(octave_change)


def _ensure_scherzo_complete_parts(root: ET.Element) -> set[str]:
    """Add instruments and vocal staves absent from the short opening model."""
    specs = [
        ("P5", "P31", "Corne Inglês", 69),
        ("P7", "P32", "Clarinete Baixo em Si♭", 72),
        ("P9", "P33", "Contrafagote", 71),
        ("P26", "P34", "Xilofone", 14),
        ("P20", "P35", "Tam-tam", 48),
        ("P21", "P36", "Percussão auxiliar", 49),
        ("P29", "P37", "Ameríndia", 54),
        ("P29", "P38", "Voz da Terra", 54),
        ("P26", "P39", "Sopranos", 54),
        ("P26", "P40", "Contraltos", 54),
        ("P26", "P41", "Tenores", 54),
        ("P29", "P42", "Baixos", 54),
    ]
    existing = {part.get("id", "") for part in root.findall("part")}
    created: set[str] = set()
    for source_id, target_id, name, midi in specs:
        if target_id not in existing:
            _clone_score_part_after(root, source_id, target_id, name)
            existing.add(target_id)
            created.add(target_id)
        _set_part_midi_program(root, target_id, midi)
    _set_initial_transpose(root, "P31", diatonic=-4, chromatic=-7)
    _set_initial_transpose(root, "P32", diatonic=-8, chromatic=-14)
    _set_initial_transpose(root, "P33", chromatic=0, octave_change=-1)
    return created


def _reorder_scherzo_parts(root: ET.Element) -> None:
    """Keep added percussion/voices out of the string block in MuseScore."""
    order = [
        "P1", "P2", "P3", "P4", "P5", "P6", "P31", "P7", "P8", "P32",
        "P9", "P10", "P33", "P11", "P12", "P13", "P14", "P15", "P16",
        "P17", "P18", "P19", "P20", "P34", "P35", "P21", "P36", "P22",
        "P23", "P24", "P25", "P37", "P38", "P39", "P40", "P41", "P42",
        "P26", "P27", "P28", "P29", "P30",
    ]
    part_list = root.find("part-list")
    if part_list is None:
        raise ValueError("modelo do Scherzo sem part-list")
    score_parts = {
        item.get("id", ""): item for item in part_list.findall("score-part")
    }
    if set(order) != set(score_parts):
        missing = sorted(set(order) - set(score_parts))
        extra = sorted(set(score_parts) - set(order))
        raise ValueError(f"ordem instrumental incompleta: faltam={missing}, extras={extra}")
    # The original nested groups no longer describe the score after adding
    # twelve parts. Recreate a flat, deterministic list; grand-staff braces are
    # still carried by each part's own <staves> declaration.
    for child in list(part_list):
        part_list.remove(child)
    for part_id in order:
        part_list.append(score_parts[part_id])

    parts = {part.get("id", ""): part for part in root.findall("part")}
    for part in list(parts.values()):
        root.remove(part)
    for part_id in order:
        root.append(parts[part_id])


def _scherzo_source_category(name: str) -> str | None:
    value = normalize_part_name(name)
    compact = value.replace(" ", "")
    if not value or value == "voice":
        return None
    if "amer" in value:
        return "amerindia"
    if "v da t" in value or "vozdaterra" in compact:
        return "voz_terra"
    if compact in {"s", "sop", "sopr"}:
        return "soprano"
    if compact in {"c", "contr", "alto"}:
        return "contralto"
    if compact in {"t", "ten", "tenor"}:
        return "tenor"
    if compact in {"b", "basso", "baixo"}:
        return "baixo"
    if "pic" in value:
        return "piccolo"
    if compact.startswith(("fl", "fi")):
        return "flute"
    if compact.startswith("ob"):
        return "oboe"
    if value == "c i" or compact in {"corningles", "coranglais"}:
        return "cor_anglais"
    if (compact.startswith(("cl", "ci"))) and "b" in compact:
        return "bass_clarinet"
    if compact.startswith(("cl", "ci")):
        return "clarinet"
    if compact.startswith(("cfg", "cig")):
        return "contrabassoon"
    if compact.startswith("fg"):
        return "bassoon"
    if compact.startswith(("tpa", "corno", "horn")):
        return "horn"
    if compact.startswith("trp"):
        return "trumpet"
    if compact.startswith("trb"):
        return "trombone"
    if compact in {"tb", "tuba"}:
        return "tuba"
    if "timp" in value or compact.startswith(("tlmp", "timp")):
        return "timpani"
    if compact.startswith(("xil", "xyl", "xii")):
        return "xylophone"
    if "ttam" in compact or "tam tam" in value:
        return "tam_tam"
    if any(token in value for token in ("cocos", "choc", "pand", "guizos", "pratos")):
        return "aux_percussion"
    if compact.startswith(("caix", "snare")):
        return "snare"
    if compact.startswith(("bombo", "bassdrum")):
        return "bass_drum"
    if compact.startswith(("prat", "cym")):
        return "cymbals"
    has_harp = compact.startswith("hp") or "harp" in value
    has_piano = compact.startswith("pno") or "piano" in value
    if has_harp and has_piano:
        return "harp_piano"
    if has_harp:
        return "harp"
    if has_piano:
        return "piano"
    if compact.startswith("cel"):
        return "celesta"
    if value.startswith("vi ii") or "viii" in compact or compact.startswith(("vlii", "v2")):
        return "violin2"
    if value.startswith("vi i") or compact.startswith(("vli", "v1")):
        return "violin1"
    if compact.startswith(("vla", "via")):
        return "viola"
    if compact.startswith(("vc", "v0")):
        return "cello"
    if compact.startswith("cb"):
        return "bass"
    return None


def _scherzo_vocal_slots(page: int) -> list[tuple[str, str | tuple[str, ...]]]:
    ids = {
        "amerindia": "P37",
        "voz_terra": "P38",
        "soprano": "P39",
        "contralto": "P40",
        "tenor": "P41",
        "baixo": "P42",
    }
    if 80 <= page <= 86:
        names = ("soprano", "contralto")
    elif 87 <= page <= 88:
        names = ("tenor", "baixo")
    elif page == 89:
        names = ("soprano", "contralto", "tenor", "baixo")
    elif 90 <= page <= 92:
        names = ("voz_terra", "soprano", "contralto", "tenor", "baixo")
    elif 93 <= page <= 94 or page == 96:
        names = ("amerindia", "voz_terra", "soprano", "contralto", "tenor", "baixo")
    elif page == 95:
        names = ("amerindia", "voz_terra", "soprano", "contralto")
    elif 97 <= page <= 98:
        names = ("soprano", "contralto", "tenor", "baixo")
    else:
        names = ()
    return [(name, ids[name]) for name in names]


def _scherzo_expected_slots(
    page: int, source_categories: list[str | None]
) -> list[tuple[str, str | tuple[str, ...]]]:
    combined_keyboard = "harp_piano" in source_categories
    slots: list[tuple[str, str | tuple[str, ...]]] = [
        ("piccolo", ("split", "P1", "P2")),
        ("flute", ("split", "P3", "P4")),
        ("oboe", ("split", "P5", "P6")),
        ("cor_anglais", "P31"),
        ("clarinet", ("split", "P7", "P8")),
        ("bass_clarinet", "P32"),
        ("bassoon", ("split", "P9", "P10")),
        ("contrabassoon", "P33"),
        ("horn", "P11"),
        ("horn", "P12"),
        ("trumpet", "P13"),
        ("trumpet", "P14"),
        ("trombone", "P15"),
        ("trombone", "P16"),
        ("tuba", "P17"),
        ("timpani", "P18"),
        ("xylophone", "P34"),
        ("snare", "P19"),
        ("bass_drum", "P20"),
        ("cymbals", "P21"),
        ("tam_tam", "P35"),
        ("aux_percussion", "P36"),
    ]
    if combined_keyboard:
        slots.append(("harp_piano", ("P24", "P25", "P23")))
    else:
        slots.extend((("harp", ("P24", "P25")), ("piano", "P23")))
    slots.append(("celesta", "P22"))
    slots.extend(_scherzo_vocal_slots(page))
    slots.extend(
        (
            ("violin1", "P26"),
            ("violin2", "P27"),
            ("viola", "P28"),
            ("cello", "P29"),
            ("bass", "P30"),
        )
    )
    return slots


def _scherzo_layout_for_page(
    page: int, parts: list[dict]
) -> tuple[list[str | tuple[str, ...]], list[dict]]:
    """Align imperfect OCR labels to the verified orchestral staff order."""
    all_categories = [_scherzo_source_category(part["name"]) for part in parts]
    vocal_slots = _scherzo_vocal_slots(page)
    string_slots: list[tuple[str, str | tuple[str, ...]]] = [
        ("violin1", "P26"),
        ("violin2", "P27"),
        ("viola", "P28"),
        ("cello", "P29"),
        ("bass", "P30"),
    ]
    suffix_count = len(vocal_slots) + len(string_slots)
    if len(parts) < suffix_count:
        raise ValueError(
            f"página {page}: faltam pautas para vozes e cordas ({len(parts)} < {suffix_count})"
        )
    instrument_parts = parts[:-suffix_count]
    instrument_categories = all_categories[:-suffix_count]
    expected = _scherzo_expected_slots(page, instrument_categories)
    excluded = {category for category, _target in vocal_slots + string_slots}
    slots = [slot for slot in expected if slot[0] not in excluded]
    source_count = len(instrument_parts)
    slot_count = len(slots)
    if source_count > slot_count:
        raise ValueError(
            f"página {page}: {source_count} pautas reconhecidas para {slot_count} destinos"
        )

    infinity = 10_000.0
    costs = [[infinity] * (slot_count + 1) for _ in range(source_count + 1)]
    previous: list[list[tuple[int, int, bool] | None]] = [
        [None] * (slot_count + 1) for _ in range(source_count + 1)
    ]
    costs[0][0] = 0.0
    for j in range(1, slot_count + 1):
        costs[0][j] = costs[0][j - 1] + 0.02
        previous[0][j] = (0, j - 1, False)
    for i in range(1, source_count + 1):
        for j in range(1, slot_count + 1):
            skipped = costs[i][j - 1] + 0.02
            if skipped < costs[i][j]:
                costs[i][j] = skipped
                previous[i][j] = (i, j - 1, False)
            category = instrument_categories[i - 1]
            expected = slots[j - 1][0]
            match_cost = 1.0 if category is None else (0.0 if category == expected else 8.0)
            assigned = costs[i - 1][j - 1] + match_cost
            if assigned < costs[i][j]:
                costs[i][j] = assigned
                previous[i][j] = (i - 1, j - 1, True)

    assignments: list[int] = []
    i, j = source_count, slot_count
    while i or j:
        step = previous[i][j]
        if step is None:
            raise ValueError(f"página {page}: não foi possível alinhar as pautas")
        previous_i, previous_j, assigned = step
        if assigned:
            assignments.append(j - 1)
        i, j = previous_i, previous_j
    assignments.reverse()
    instrument_layout = [slots[index][1] for index in assignments]
    # These pages engrave a shared Harpa + Piano grand staff under the label
    # that Audiveris usually shortens to just ``Pno.``.
    if page in {80, 97, 98, 99}:
        for index in range(len(instrument_parts) - 1, -1, -1):
            if instrument_categories[index] == "piano":
                instrument_layout[index] = ("P23", "P24", "P25")
                break
    # Page 93 has two separate grand staves. Their OCR labels are reversed:
    # ``Piano`` is the harp and ``TAV.`` is the actual piano.
    if page == 93 and len(instrument_layout) >= 2:
        instrument_layout[-2] = ("P24", "P25")
        instrument_layout[-1] = "P23"

    layout = instrument_layout + [target for _category, target in vocal_slots + string_slots]
    audit = []
    for part, category, slot_index, target in zip(
        instrument_parts, instrument_categories, assignments, instrument_layout
    ):
        expected = slots[slot_index][0]
        audit.append(
            {
                "source_id": part["id"],
                "source_name": part["name"],
                "recognized_category": category,
                "expected_category": expected,
                "target": list(target) if isinstance(target, tuple) else target,
                "label_match": category == expected if category else None,
            }
        )
    for part, category, (expected, target) in zip(
        parts[-suffix_count:], all_categories[-suffix_count:], vocal_slots + string_slots
    ):
        audit.append(
            {
                "source_id": part["id"],
                "source_name": part["name"],
                "recognized_category": category,
                "expected_category": expected,
                "target": list(target) if isinstance(target, tuple) else target,
                "label_match": category == expected if category else None,
            }
        )
    return layout, audit


_NON_LYRIC_TOKENS = {
    "f", "ff", "fff", "p", "pp", "ppp", "mf", "mp", "sf", "sfz",
    "a2", "a3", "div", "div.", "unis", "unis.", "arco", "pizz", "pizz.",
    "sord", "sord.", "heitor", "villa", "lobos", "sinfonia",
}


def _clean_imported_lyrics(event: dict, vocal: bool) -> None:
    if not vocal or event.get("rest") or not event.get("pitch"):
        event["lyrics"] = []
        return
    cleaned = []
    for lyric in event.get("lyrics", []):
        text = lyric.get("text")
        if text is not None and normalize_part_name(text) in _NON_LYRIC_TOKENS:
            continue
        cleaned.append(lyric)
    event["lyrics"] = cleaned


def _normalize_scherzo_tuplet_artifacts(events: list[dict]) -> dict[str, int]:
    """Turn misread string tremolos into native notation without losing notes."""
    converted_tremolo_tuplets = 0
    for event in events:
        tuplet = event.get("tuplet")
        if (
            event.get("part_id") in {"P26", "P27", "P28", "P29"}
            and 172 <= event.get("measure_index", 0) <= 186
            and tuplet == {"actual": "3", "normal": "2"}
        ):
            # The printed mark is a three-stroke single-note tremolo. Audiveris
            # reads its subdivision digit as a 3:2 time modification, which
            # shortens every quarter to 2/3 and corrupts the bar. Keep every
            # recognized chord, restore its quarter duration, and emit native
            # tremolo notation instead of silently deleting the visual mark.
            if Fraction(event["duration"]) == Fraction(2, 3):
                event["duration"] = "1"
                event["type"] = "quarter"
            event["tremolo"] = {"type": "single", "marks": 3}
            event["tuplet"] = None
            event.pop("tuplet_group", None)
            event.pop("_standalone_tuplet", None)
            converted_tremolo_tuplets += 1

    # Page 89, measure 198: the second triplet contains its first note but the
    # two structural rests were omitted. Add them so MuseScore receives a
    # complete native triplet rather than a standalone tuplet that lengthens
    # every staff's measure.
    seed = next(
        (
            event
            for event in events
            if event.get("part_id") == "P27"
            and event.get("measure_index") == 198
            and Fraction(event.get("onset", "0")) == 1
            and event.get("tuplet") == {"actual": "3", "normal": "2"}
        ),
        None,
    )
    added_triplet_rests = 0
    if seed is not None:
        for onset in (Fraction(4, 3), Fraction(5, 3)):
            rest = copy.deepcopy(seed)
            rest.update(
                {
                    "onset": str(onset),
                    "duration": "1/3",
                    "pitch": None,
                    "rest": True,
                    "chord": False,
                    "ties": [],
                    "articulations": [],
                    "lyrics": [],
                }
            )
            events.append(rest)
            added_triplet_rests += 1

    merged_oboe_voice_notes = 0
    for part_id in ("P5", "P6"):
        secondary = sorted(
            (
                event
                for event in events
                if event.get("part_id") == part_id
                and event.get("measure_index") == 192
                and event.get("voice") == "3"
            ),
            key=lambda event: Fraction(event["onset"]),
        )
        for index, event in enumerate(secondary):
            # Audiveris created a third voice beginning inside the sustained
            # second voice. MuseScore offsets that voice after import and makes
            # it overrun the 6/8 bar. The two printed notes follow the sustain,
            # so place them consecutively in voice 2.
            event["voice"] = "2"
            event["onset"] = str(Fraction(3, 2) + Fraction(index, 2))
            merged_oboe_voice_notes += 1
    return {
        "converted_tremolo_tuplets": converted_tremolo_tuplets,
        "added_triplet_rests": added_triplet_rests,
        "merged_oboe_voice_notes": merged_oboe_voice_notes,
    }


def build_scherzo_complete(
    base_musicxml: Path,
    page_candidates: dict[int, Path],
    output: Path,
) -> dict:
    """Assemble PDF pages 67-99 into one meter-locked Scherzo score."""
    base = parse_musicxml(base_musicxml, include_rests=True)
    if base["measures"] != 25:
        raise ValueError("a base validada do Scherzo precisa terminar no compasso 25")
    root = ET.fromstring(_read_musicxml(base_musicxml))
    tree = ET.ElementTree(root)
    created_parts = _ensure_scherzo_complete_parts(root)
    _reorder_scherzo_parts(root)

    mapped_events: list[dict] = []
    clef_changes: dict[str, list[tuple[int, Fraction, int, str, int]]] = defaultdict(list)
    first_measure = 26
    page_audit = []
    lyric_syllables = 0
    for page in range(70, 100):
        candidate_path = page_candidates.get(page)
        if candidate_path is None or not candidate_path.is_file():
            raise FileNotFoundError(f"OMR individual ausente para a página {page}")
        score = parse_musicxml(candidate_path, include_rests=True)
        # Audiveris creates an eighth, empty measure after the final barline on
        # page 88. The engraved page contains measures 180-186 only; retaining
        # that artifact would shift rehearsal 11 and every later lyric by one.
        effective_measures = score["measures"] - 1 if page == 88 else score["measures"]
        layout, mapping_audit = _reviewed_scherzo_layout(page, score["parts"])
        source_ids = [part["id"] for part in score["parts"]]
        page_events: list[dict] = []
        mapped_counts: dict[str, int] = defaultdict(int)
        for source_id, entry in zip(source_ids, layout):
            shifted = []
            for event in score["events"]:
                if (
                    event["part_id"] != source_id
                    or event.get("grace")
                    or event["measure_index"] > effective_measures
                ):
                    continue
                cloned = copy.deepcopy(event)
                cloned["measure_index"] = first_measure + event["measure_index"] - 1
                cloned["measure_number"] = str(cloned["measure_index"])
                shifted.append(cloned)

            if isinstance(entry, tuple) and entry and entry[0] == "split":
                first_target, second_target = entry[1], entry[2]
                temporary = [_clone_event(event, first_target) for event in shifted]
                assigned_events = _split_paired_melodic_part(
                    temporary, first_target, second_target
                )
            else:
                assigned_events = []
                for target in _layout_targets(entry):
                    assigned_events.extend(_clone_event(event, target) for event in shifted)
            for event in assigned_events:
                target = event["part_id"]
                _clean_imported_lyrics(event, target in SCHERZO_VOCAL_PARTS)
                lyric_syllables += sum(
                    bool(lyric.get("text")) for lyric in event.get("lyrics", [])
                )
                mapped_counts[target] += 1
            page_events.extend(assigned_events)

        grouped_tuplet_notes = _assign_imported_tuplet_groups(page_events)
        mapped_events.extend(page_events)
        detected_clefs = _candidate_clef_changes(candidate_path, layout, first_measure)
        for part_id, changes in detected_clefs.items():
            clef_changes[part_id].extend(changes)
        last_measure = first_measure + effective_measures - 1
        page_audit.append(
            {
                "page": page,
                "first_measure": first_measure,
                "last_measure": last_measure,
                "measures": effective_measures,
                "source_measures": score["measures"],
                "discarded_empty_measures": score["measures"] - effective_measures,
                "source_parts": len(score["parts"]),
                "source_events": len(score["events"]),
                "mapped_events": len(page_events),
                "grouped_tuplet_notes": grouped_tuplet_notes,
                "mapped_parts": dict(sorted(mapped_counts.items())),
                "staff_mapping": mapping_audit,
            }
        )
        first_measure = last_measure + 1

    end_measure = first_measure - 1
    if end_measure != 310:
        raise ValueError(f"o Scherzo deveria terminar no compasso 310, não {end_measure}")

    integrity_before_repairs = {
        "events": len(mapped_events),
        "pitched_events": sum(bool(event.get("pitch")) for event in mapped_events),
        "tuplet_events": sum(bool(event.get("tuplet")) for event in mapped_events),
    }
    tuplet_repairs = _normalize_scherzo_tuplet_artifacts(mapped_events)
    # Group tuplets only after page-level repairs have added all structural
    # members and converted tremolo marks misread as time modifications.
    _assign_imported_tuplet_groups(mapped_events)
    integrity_after_repairs = {
        "events": len(mapped_events),
        "pitched_events": sum(bool(event.get("pitch")) for event in mapped_events),
        "tuplet_events": sum(bool(event.get("tuplet")) for event in mapped_events),
        "tremolo_events": sum(bool(event.get("tremolo")) for event in mapped_events),
    }
    if integrity_after_repairs["pitched_events"] != integrity_before_repairs["pitched_events"]:
        raise ValueError("a normalização do Scherzo alterou a quantidade de notas reconhecidas")
    for event in mapped_events:
        try:
            event["voice"] = str((int(event.get("voice", "1")) - 1) % 4 + 1)
        except ValueError:
            event["voice"] = "1"
    events_by_part: dict[str, list[dict]] = defaultdict(list)
    for event in mapped_events:
        events_by_part[event["part_id"]].append(event)

    work = root.find("work")
    if work is None:
        work = ET.Element("work")
        root.insert(0, work)
    title = work.find("work-title")
    if title is None:
        title = ET.SubElement(work, "work-title")
    title.text = "III. Scherzo - movimento completo"

    meter_changes = set(SCHERZO_METER_CHANGES)
    for part in root.findall("part"):
        part_id = part.get("id", "")
        old_measures = part.findall("measure")
        first_attributes = (
            copy.deepcopy(old_measures[0].find("attributes")) if old_measures else None
        )
        if part_id in created_parts:
            for measure in old_measures:
                part.remove(measure)
        first_generated_measure = 1 if part_id in created_parts else 26
        part_events = events_by_part.get(part_id, [])
        staves = max(
            [int(event.get("staff", "1")) for event in part_events]
            + [
                int(first_attributes.findtext("staves", "1"))
                if first_attributes is not None
                else 1
            ]
        )
        clef_plan = sorted(set(clef_changes.get(part_id, [])))
        for measure_index in range(first_generated_measure, end_measure + 1):
            measure = ET.SubElement(part, "measure", {"number": str(measure_index)})
            beats, beat_type, duration = scherzo_meter(measure_index)
            if measure_index == 1:
                attributes = (
                    copy.deepcopy(first_attributes)
                    if first_attributes is not None
                    else ET.Element("attributes")
                )
                measure.append(attributes)
            elif measure_index == first_generated_measure or measure_index in meter_changes:
                attributes = ET.SubElement(measure, "attributes")
            else:
                attributes = None
            if attributes is not None:
                divisions = attributes.find("divisions")
                if divisions is None:
                    divisions = ET.Element("divisions")
                    attributes.insert(0, divisions)
                divisions.text = str(DIVISIONS)
            if attributes is not None and measure_index in meter_changes:
                time = attributes.find("time")
                if time is None:
                    time = ET.SubElement(attributes, "time")
                for child in list(time):
                    time.remove(child)
                ET.SubElement(time, "beats").text = str(beats)
                ET.SubElement(time, "beat-type").text = str(beat_type)

            measure_clefs = [
                (onset, staff, sign, line)
                for change_measure, onset, staff, sign, line in clef_plan
                if change_measure == measure_index
            ]
            starting_clefs = [
                (staff, sign, line)
                for onset, staff, sign, line in measure_clefs
                if onset == 0
            ]
            if starting_clefs:
                if attributes is None:
                    attributes = ET.Element("attributes")
                    measure.insert(0, attributes)
                for clef in list(attributes.findall("clef")):
                    attributes.remove(clef)
                for staff, sign, line in starting_clefs:
                    clef = ET.SubElement(attributes, "clef", {"number": str(staff)})
                    ET.SubElement(clef, "sign").text = sign
                    ET.SubElement(clef, "line").text = str(line)

            current = [
                event for event in part_events if event["measure_index"] == measure_index
            ]
            inline_clefs = [change for change in measure_clefs if change[0] > 0]
            streams: list[tuple[str, str, list[dict]]] = []
            for staff_number in range(1, staves + 1):
                staff = str(staff_number)
                staff_events = [
                    event for event in current if event.get("staff", "1") == staff
                ]
                voices = sorted({event.get("voice", "1") for event in staff_events}) or ["1"]
                for voice in voices:
                    streams.append(
                        (
                            staff,
                            voice,
                            [
                                event
                                for event in staff_events
                                if event.get("voice", "1") == voice
                            ],
                        )
                    )
            clef_staves_emitted: set[str] = set()
            for stream_index, (staff, voice, stream_events) in enumerate(streams):
                if stream_index:
                    backup = ET.SubElement(measure, "backup")
                    ET.SubElement(backup, "duration").text = str(duration * DIVISIONS)
                stream_clefs = []
                if staff not in clef_staves_emitted:
                    stream_clefs = [
                        change for change in inline_clefs if str(change[1]) == staff
                    ]
                    clef_staves_emitted.add(staff)
                _emit_voice(
                    measure,
                    stream_events,
                    _scherzo_measure_duration(part_id, measure_index),
                    voice,
                    staff,
                    stream_clefs,
                )

    validation = _write_and_validate(
        tree,
        output,
        _scherzo_measure_duration,
        require_full=lambda _part, measure: measure >= 26,
    )
    validation["opening_measures_preserved"] = 25
    return {
        "output": str(output.resolve()),
        "pages": list(range(67, 100)),
        "measures": end_measure,
        "parts": len(root.findall("part")),
        "base_events_preserved": len(base["events"]),
        "mapped_events": len(mapped_events),
        "lyric_syllables": lyric_syllables,
        "tuplet_repairs": tuplet_repairs,
        "event_integrity": {
            "before_repairs": integrity_before_repairs,
            "after_repairs": integrity_after_repairs,
            "pitched_events_preserved": True,
        },
        "created_parts": sorted(created_parts),
        "page_audit": page_audit,
        "meter_changes": {
            str(measure): f"{beats}/{beat_type}"
            for measure, (beats, beat_type) in SCHERZO_METER_CHANGES.items()
        },
        "meter_validation": validation,
    }


# The Scherzo template supplied by the user contains the thirty instruments
# used in the reviewed opening. Later pages add auxiliary winds, percussion and
# voices. IDs are deliberately stable so page maps and revision reports remain
# readable between runs.
SCHERZO_ADDITIONAL_PARTS: tuple[tuple[str, str, str], ...] = (
    ("P31", "P6", "Corne Inglês"),
    ("P32", "P8", "Clarinete Baixo"),
    ("P33", "P10", "Contrafagote"),
    ("P39", "P18", "Güiros"),
    ("P38", "P18", "Pandeiro"),
    ("P37", "P18", "Chocalhos"),
    ("P36", "P18", "Cocos"),
    ("P35", "P18", "Tam-tam"),
    ("P34", "P18", "Xilofone"),
    ("P45", "P25", "Baixo"),
    ("P44", "P25", "Tenor"),
    ("P43", "P25", "Contralto"),
    ("P42", "P25", "Soprano"),
    ("P41", "P25", "Voz da Terra"),
    ("P40", "P25", "Ameríndia"),
)

_LEGACY_SCHERZO_VOCAL_PARTS = {"P40", "P41", "P42", "P43", "P44", "P45"}
_LEGACY_SCHERZO_METER_CHANGES: dict[int, tuple[int, int]] = {
    26: (9, 8),
    74: (6, 8),
    119: (9, 8),
    172: (4, 4),
    187: (6, 8),
}

SCHERZO_SPLIT_PICC = ("split", "P1", "P2")
SCHERZO_SPLIT_FLUTE = ("split", "P3", "P4")
SCHERZO_SPLIT_OBOE = ("split", "P5", "P6")
SCHERZO_SPLIT_CLARINET = ("split", "P7", "P8")
SCHERZO_SPLIT_BASSOON = ("split", "P9", "P10")
SCHERZO_SPLIT_HORNS = ("split", "P11", "P12")
SCHERZO_SPLIT_TRUMPETS = ("split", "P13", "P14")
SCHERZO_SPLIT_TROMBONES = ("split", "P15", "P16")
SCHERZO_SHARED_HARPS = ("P24", "P25")
SCHERZO_SHARED_HARPS_PIANO = ("P23", "P24", "P25")
SCHERZO_SHARED_HARPS_CELESTA = ("P22", "P24", "P25")

# Filled from a page-by-page visual audit. Each item corresponds to one
# Audiveris source part, in the order engraved at the left edge of that page.
SCHERZO_PAGE_LAYOUTS: dict[int, list[str | tuple[str, ...]]] = {
    70: [SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", "P13", "P14", "P15", "P16", "P18", "P23", "P26", "P27", "P28", "P29", "P30"],
    71: [SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", "P13", "P14", "P15", "P16", "P18", "P23", "P26", "P27", "P28", "P29", "P30"],
    72: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", SCHERZO_SPLIT_TRUMPETS, SCHERZO_SPLIT_TROMBONES, "P17", "P18", "P34", SCHERZO_SHARED_HARPS, "P23", "P26", "P27", "P28", "P29", "P30"],
    73: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", SCHERZO_SPLIT_TRUMPETS, "P15", "P16", "P17", "P18", "P34", SCHERZO_SHARED_HARPS, "P23", "P26", "P27", "P28", "P29", "P30"],
    74: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", "P13", "P14", "P15", "P16", SCHERZO_SHARED_HARPS, "P23", "P26", "P27", "P28", "P29", "P30"],
    75: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", "P13", "P14", "P15", "P16", "P18", "P35", SCHERZO_SHARED_HARPS_PIANO, "P26", "P27", "P28", "P29", "P30"],
    76: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", "P13", "P14", "P15", "P16", "P17", "P18", "P35", SCHERZO_SHARED_HARPS, "P26", "P27", "P28", "P29", "P30"],
    77: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", "P13", "P14", "P15", "P16", "P17", "P18", "P35", SCHERZO_SHARED_HARPS, "P26", "P27", "P28", "P29", "P30"],
    78: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", "P13", "P14", "P15", "P16", "P17", "P18", "P26", "P27", "P28", "P29", "P30"],
    79: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", "P13", "P14", "P15", "P16", "P17", "P18", "P26", "P27", "P28", "P29", "P30"],
    80: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", "P13", "P14", "P15", "P16", "P17", "P18", SCHERZO_SHARED_HARPS_PIANO, "P42", "P43", "P26", "P27", "P28", "P29", "P30"],
    81: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", SCHERZO_SPLIT_HORNS, SCHERZO_SPLIT_TRUMPETS, SCHERZO_SPLIT_TROMBONES, "P17", "P36", SCHERZO_SHARED_HARPS, "P23", "P42", "P43", "P26", "P27", "P28", "P29", "P30"],
    82: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P11", "P12", SCHERZO_SPLIT_TRUMPETS, SCHERZO_SPLIT_TROMBONES, "P18", "P36", SCHERZO_SHARED_HARPS, "P23", "P42", "P43", "P26", "P27", "P28", "P29", "P30"],
    83: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", SCHERZO_SPLIT_TRUMPETS, SCHERZO_SPLIT_TROMBONES, "P18", "P36", SCHERZO_SHARED_HARPS, "P23", "P42", "P43", "P26", "P27", "P28", "P29", "P30"],
    84: [SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", SCHERZO_SPLIT_TRUMPETS, "P15", "P16", "P17", "P18", "P35", "P36", SCHERZO_SHARED_HARPS, "P23", "P42", "P43", "P26", "P27", "P28", "P29", "P30"],
    85: [SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", SCHERZO_SPLIT_TRUMPETS, "P15", "P16", "P17", "P18", "P35", "P36", SCHERZO_SHARED_HARPS, "P23", "P42", "P43", "P26", "P27", "P28", "P29", "P30"],
    86: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P18", "P35", "P42", "P43", "P26", "P27", "P28", "P29", "P30"],
    87: [SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P15", "P16", "P17", "P18", "P35", "P44", "P45", "P26", "P27", "P28", "P29", "P30"],
    88: [SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", SCHERZO_SPLIT_HORNS, "P15", "P16", "P17", "P18", SCHERZO_SHARED_HARPS, "P44", "P45", "P26", "P27", "P28", "P29", "P30"],
    89: [SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P11", "P12", SCHERZO_SPLIT_TRUMPETS, "P15", "P16", "P42", "P43", "P44", "P45", "P26", "P27", "P28", "P29", "P30"],
    90: [SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", SCHERZO_SPLIT_TRUMPETS, "P15", "P16", "P17", "P41", "P42", "P43", "P44", "P45", "P26", "P27", "P28", "P29", "P30"],
    91: [SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", SCHERZO_SPLIT_HORNS, SCHERZO_SPLIT_TRUMPETS, SCHERZO_SPLIT_TROMBONES, "P17", SCHERZO_SHARED_HARPS, "P41", "P42", "P43", "P44", "P45", "P26", "P27", "P28", "P29", "P30"],
    92: [SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", "P33", SCHERZO_SPLIT_HORNS, SCHERZO_SPLIT_TRUMPETS, "P17", "P35", SCHERZO_SHARED_HARPS, "P23", "P41", "P42", "P43", "P44", "P45", "P26", "P27", "P28", "P29", "P30"],
    93: [SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", "P33", SCHERZO_SPLIT_HORNS, SCHERZO_SPLIT_TRUMPETS, "P35", SCHERZO_SHARED_HARPS_CELESTA, "P23", "P40", "P41", "P42", "P43", "P44", "P45", "P26", "P27", "P28", "P29", "P30"],
    94: [SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", SCHERZO_SPLIT_HORNS, SCHERZO_SPLIT_TRUMPETS, SCHERZO_SPLIT_TROMBONES, "P17", "P35", "P23", "P40", "P41", "P42", "P43", "P44", "P45", "P26", "P27", "P28", "P29", "P30"],
    95: [SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", "P13", "P14", "P15", "P16", "P17", "P35", "P23", "P40", "P41", "P42", "P43", "P26", "P27", "P28", "P29", "P30"],
    96: [SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", SCHERZO_SPLIT_TRUMPETS, SCHERZO_SPLIT_TROMBONES, "P17", "P22", "P40", "P41", "P42", "P43", "P44", "P45", "P26", "P27", "P28", "P29", "P30"],
    97: [SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P11", "P12", "P13", "P14", "P15", "P16", "P17", "P18", SCHERZO_SHARED_HARPS_PIANO, "P22", "P42", "P43", "P44", "P45", "P26", "P27", "P28", "P29", "P30"],
    98: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", "P13", "P14", "P15", "P16", "P17", "P18", ("P37", "P38", "P39", "P21"), SCHERZO_SHARED_HARPS_PIANO, "P22", "P42", "P43", "P44", "P45", "P26", "P27", "P28", "P29", "P30"],
    99: [SCHERZO_SPLIT_PICC, SCHERZO_SPLIT_FLUTE, SCHERZO_SPLIT_OBOE, "P31", SCHERZO_SPLIT_CLARINET, "P32", SCHERZO_SPLIT_BASSOON, "P33", "P11", "P12", "P13", "P14", "P15", "P16", "P17", "P18", ("P37", "P38", "P39", "P21"), SCHERZO_SHARED_HARPS_PIANO, "P22", "P26", "P27", "P28", "P29", "P30"],
}

# Page 88 ends at measure 186. Audiveris creates an eighth, empty measure from
# the 6/8 signature printed at the far-right system boundary; it is not a bar.
SCHERZO_PAGE_MEASURE_COUNTS = {88: 7}


_SCHERZO_REVIEWED_ID_TRANSLATION = {
    # The explicit page map was reviewed using a six-voice suffix after the
    # auxiliary-percussion block. The complete-score model uses P37-P42 for
    # those same six vocal lines.
    "P40": "P37",  # Ameríndia
    "P41": "P38",  # Voz da Terra
    "P42": "P39",  # Soprano
    "P43": "P40",  # Contralto
    "P44": "P41",  # Tenor
    "P45": "P42",  # Baixo
    # Pages 98-99 show four auxiliary labels on one OMR percussion part.
    "P37": "P36",
    "P38": "P36",
    "P39": "P36",
}


def _reviewed_scherzo_layout(
    page: int, parts: list[dict]
) -> tuple[list[str | tuple[str, ...]], list[dict]]:
    """Return the visually checked left-to-right staff map for one page."""
    raw = SCHERZO_PAGE_LAYOUTS.get(page)
    if raw is None or len(raw) != len(parts):
        raise ValueError(
            f"página {page}: mapa revisado incompatível "
            f"({len(raw or [])} != {len(parts)})"
        )

    def translate(entry: str | tuple[str, ...]) -> str | tuple[str, ...]:
        if isinstance(entry, str):
            return _SCHERZO_REVIEWED_ID_TRANSLATION.get(entry, entry)
        if entry and entry[0] == "split":
            return (
                "split",
                _SCHERZO_REVIEWED_ID_TRANSLATION.get(entry[1], entry[1]),
                _SCHERZO_REVIEWED_ID_TRANSLATION.get(entry[2], entry[2]),
            )
        translated = []
        for target in entry:
            resolved = _SCHERZO_REVIEWED_ID_TRANSLATION.get(target, target)
            if resolved not in translated:
                translated.append(resolved)
        return translated[0] if len(translated) == 1 else tuple(translated)

    layout = [translate(entry) for entry in raw]
    audit = [
        {
            "source_id": part["id"],
            "source_name": part["name"],
            "recognized_category": _scherzo_source_category(part["name"]),
            "target": list(target) if isinstance(target, tuple) else target,
            "mapping_basis": "visual_page_audit",
        }
        for part, target in zip(parts, layout)
    ]
    return layout, audit


def _legacy_scherzo_meter(measure_index: int) -> tuple[int, int, Fraction]:
    if measure_index < 26:
        raise ValueError("a abertura validada usa fórmulas locais por pauta")
    active = max(index for index in SCHERZO_METER_CHANGES if index <= measure_index)
    beats, beat_type = SCHERZO_METER_CHANGES[active]
    return beats, beat_type, Fraction(beats * 4, beat_type)


def _clean_vocal_lyrics(events: list[dict]) -> int:
    """Keep note-linked sung text while removing OMR dynamics/page furniture."""
    rejected = {
        "f", "ff", "fff", "mf", "mp", "p", "pp", "ppp", "sf", "sfz", "sffz",
        "div", "div.", "arco", "sord", "sord.", "copo", "(copo)", "a2", "a3",
        "heitor", "sinfonia", "n9", "nº", "l",
    }
    retained = 0
    for event in events:
        if event.get("part_id") not in SCHERZO_VOCAL_PARTS:
            event["lyrics"] = []
            continue
        cleaned = []
        for lyric in event.get("lyrics", []):
            text = lyric.get("text")
            if text is None:
                cleaned.append(lyric)
                continue
            normalized = normalize_part_name(text)
            if normalized in rejected or re.fullmatch(r"\d+", normalized):
                continue
            cleaned.append(lyric)
        event["lyrics"] = cleaned
        retained += len(cleaned)
    return retained


def _legacy_build_scherzo_complete(
    base_musicxml: Path,
    page_candidates: dict[int, Path],
    output: Path,
) -> dict:
    """Assemble PDF pages 67-99, preserving the approved first 25 measures."""
    base = parse_musicxml(base_musicxml, include_rests=True)
    if base["measures"] != 25:
        raise ValueError("a base validada do Scherzo precisa terminar no compasso 25")
    root = ET.fromstring(_read_musicxml(base_musicxml))
    tree = ET.ElementTree(root)
    original_ids = {part.get("id", "") for part in root.findall("part")}
    for target_id, source_id, name in SCHERZO_ADDITIONAL_PARTS:
        if root.find(f"./part[@id='{target_id}']") is None:
            _clone_score_part_after(root, source_id, target_id, name)

    mapped_events: list[dict] = []
    clef_changes: dict[str, list[tuple[int, Fraction, int, str, int]]] = defaultdict(list)
    first_measure = 26
    page_audit = []
    for page in range(70, 100):
        candidate_path = page_candidates.get(page)
        if candidate_path is None or not candidate_path.is_file():
            raise FileNotFoundError(f"OMR individual ausente para a página {page}")
        score = parse_musicxml(candidate_path, include_rests=True)
        page_measures = SCHERZO_PAGE_MEASURE_COUNTS.get(page, score["measures"])
        layout = SCHERZO_PAGE_LAYOUTS.get(page)
        if layout is None:
            raise ValueError(f"layout instrumental não auditado para a página {page}")
        if len(layout) != len(score["parts"]):
            raise ValueError(
                f"layout da página {page}: {len(layout)} destinos para "
                f"{len(score['parts'])} partes"
            )

        source_ids = [part["id"] for part in score["parts"]]
        direct_counts: dict[str, int] = defaultdict(int)
        for entry in layout:
            if isinstance(entry, str):
                direct_counts[entry] += 1
        direct_seen: dict[str, int] = defaultdict(int)
        page_events: list[dict] = []
        mapped_counts: dict[str, int] = defaultdict(int)
        for source_id, entry in zip(source_ids, layout):
            shifted = []
            for event in score["events"]:
                if (
                    event["part_id"] != source_id
                    or event.get("grace")
                    or event["measure_index"] > page_measures
                ):
                    continue
                cloned = copy.deepcopy(event)
                cloned["measure_index"] = first_measure + event["measure_index"] - 1
                cloned["measure_number"] = str(cloned["measure_index"])
                shifted.append(cloned)

            if isinstance(entry, tuple) and entry and entry[0] == "split":
                first_target, second_target = entry[1], entry[2]
                temporary = [_clone_event(event, first_target) for event in shifted]
                split = _split_paired_melodic_part(temporary, first_target, second_target)
                page_events.extend(split)
                for event in split:
                    mapped_counts[event["part_id"]] += 1
                continue

            targets = _layout_targets(entry)
            occurrence = 0
            if isinstance(entry, str) and direct_counts[entry] > 1:
                occurrence = direct_seen[entry]
                direct_seen[entry] += 1
            for target in targets:
                for event in shifted:
                    cloned = _clone_event(event, target)
                    if occurrence:
                        try:
                            voice = int(cloned.get("voice", "1"))
                        except ValueError:
                            voice = 1
                        cloned["voice"] = str((voice - 1 + occurrence) % 4 + 1)
                    page_events.append(cloned)
                    mapped_counts[target] += 1

        grouped_tuplets = _assign_imported_tuplet_groups(page_events)
        mapped_events.extend(page_events)
        detected_clefs = _candidate_clef_changes(candidate_path, layout, first_measure)
        for part_id, changes in detected_clefs.items():
            clef_changes[part_id].extend(
                change
                for change in changes
                if change[0] < first_measure + page_measures
            )
        last_measure = first_measure + page_measures - 1
        page_audit.append(
            {
                "page": page,
                "first_measure": first_measure,
                "last_measure": last_measure,
                "measures": page_measures,
                "source_measures": score["measures"],
                "source_parts": len(score["parts"]),
                "source_events": len(score["events"]),
                "mapped_events": len(page_events),
                "grouped_tuplet_notes": grouped_tuplets,
                "mapped_parts": dict(sorted(mapped_counts.items())),
            }
        )
        first_measure = last_measure + 1

    end_measure = first_measure - 1
    if end_measure != 310:
        raise ValueError(f"o Scherzo deveria terminar no compasso 310, não {end_measure}")
    for event in mapped_events:
        try:
            event["voice"] = str((int(event.get("voice", "1")) - 1) % 4 + 1)
        except ValueError:
            event["voice"] = "1"
    retained_lyrics = _clean_vocal_lyrics(mapped_events)
    events_by_part: dict[str, list[dict]] = defaultdict(list)
    for event in mapped_events:
        events_by_part[event["part_id"]].append(event)

    work = root.find("work")
    if work is None:
        work = ET.Element("work")
        root.insert(0, work)
    title = work.find("work-title")
    if title is None:
        title = ET.SubElement(work, "work-title")
    title.text = "III. Scherzo - movimento completo"

    for part in root.findall("part"):
        part_id = part.get("id", "")
        old_measures = part.findall("measure")
        first_attributes = (
            copy.deepcopy(old_measures[0].find("attributes")) if old_measures else None
        )
        preserve_opening = part_id in original_ids
        if not preserve_opening:
            for measure in old_measures:
                part.remove(measure)
        part_events = events_by_part.get(part_id, [])
        staves = max(
            [int(event.get("staff", "1")) for event in part_events]
            + [
                int(first_attributes.findtext("staves", "1"))
                if first_attributes is not None
                else 1
            ]
        )
        clef_plan = sorted(set(clef_changes.get(part_id, [])))
        first_generated = 26 if preserve_opening else 1
        for measure_index in range(first_generated, end_measure + 1):
            measure = ET.SubElement(part, "measure", {"number": str(measure_index)})
            if measure_index < 26:
                beats, beat_type, duration = 9, 8, Fraction(9, 2)
            else:
                beats, beat_type, duration = scherzo_meter(measure_index)
            attributes = None
            if measure_index == 1:
                attributes = (
                    copy.deepcopy(first_attributes)
                    if first_attributes is not None
                    else ET.Element("attributes")
                )
                measure.append(attributes)
                divisions = attributes.find("divisions")
                if divisions is None:
                    divisions = ET.Element("divisions")
                    attributes.insert(0, divisions)
                divisions.text = str(DIVISIONS)
                time = attributes.find("time")
                if time is None:
                    time = ET.SubElement(attributes, "time")
                for child in list(time):
                    time.remove(child)
                ET.SubElement(time, "beats").text = str(beats)
                ET.SubElement(time, "beat-type").text = str(beat_type)

            measure_clefs = [
                (onset, staff, sign, line)
                for change_measure, onset, staff, sign, line in clef_plan
                if change_measure == measure_index
            ]
            starting_clefs = [
                (staff, sign, line)
                for onset, staff, sign, line in measure_clefs
                if onset == 0
            ]
            if starting_clefs:
                if attributes is None:
                    attributes = ET.Element("attributes")
                    measure.insert(0, attributes)
                for clef in list(attributes.findall("clef")):
                    attributes.remove(clef)
                for staff, sign, line in starting_clefs:
                    clef = ET.SubElement(attributes, "clef", {"number": str(staff)})
                    ET.SubElement(clef, "sign").text = sign
                    ET.SubElement(clef, "line").text = str(line)
            if measure_index in SCHERZO_METER_CHANGES and measure_index != 26:
                if attributes is None:
                    attributes = ET.Element("attributes")
                    measure.insert(0, attributes)
                time = attributes.find("time")
                if time is None:
                    time = ET.SubElement(attributes, "time")
                for child in list(time):
                    time.remove(child)
                ET.SubElement(time, "beats").text = str(beats)
                ET.SubElement(time, "beat-type").text = str(beat_type)

            current = [
                event for event in part_events if event["measure_index"] == measure_index
            ]
            inline_clefs = [
                (onset, staff, sign, line)
                for onset, staff, sign, line in measure_clefs
                if onset > 0
            ]
            streams: list[tuple[str, str, list[dict]]] = []
            for staff_number in range(1, staves + 1):
                staff = str(staff_number)
                staff_events = [
                    event for event in current if event.get("staff", "1") == staff
                ]
                voices = sorted({event.get("voice", "1") for event in staff_events}) or ["1"]
                for voice in voices:
                    streams.append(
                        (
                            staff,
                            voice,
                            [
                                event
                                for event in staff_events
                                if event.get("voice", "1") == voice
                            ],
                        )
                    )
            clef_staves_emitted: set[str] = set()
            for stream_index, (staff, voice, stream_events) in enumerate(streams):
                if stream_index:
                    backup = ET.SubElement(measure, "backup")
                    ET.SubElement(backup, "duration").text = str(duration * DIVISIONS)
                stream_clefs = []
                if staff not in clef_staves_emitted:
                    stream_clefs = [
                        change for change in inline_clefs if str(change[1]) == staff
                    ]
                    clef_staves_emitted.add(staff)
                _emit_voice(measure, stream_events, duration, voice, staff, stream_clefs)

    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(output, encoding="utf-8", xml_declaration=True)
    assembled = parse_musicxml(output, include_rests=True)
    validation = validate_meter_score(
        assembled,
        lambda _part, measure: scherzo_meter(measure)[2]
        if measure >= 26
        else Fraction(1000),
        require_full=lambda _part, measure: measure >= 26,
    )
    # The approved opening is intentionally excluded from the uniform-meter
    # validator because its first three measures use local 3/4 and 9/8 meters.
    validation["opening_measures_preserved"] = 25
    if not validation["valid"]:
        raise ValueError(f"validação métrica do Scherzo falhou: {validation['violations'][:3]}")
    return {
        "output": str(output.resolve()),
        "pages": list(range(67, 100)),
        "measures": end_measure,
        "parts": len(root.findall("part")),
        "base_events_preserved": base["events_count"],
        "mapped_events": len(mapped_events),
        "retained_lyrics": retained_lyrics,
        "detected_clef_changes": sum(len(changes) for changes in clef_changes.values()),
        "page_audit": page_audit,
        "meter_changes": {
            str(measure): f"{beats}/{beat_type}"
            for measure, (beats, beat_type) in SCHERZO_METER_CHANGES.items()
        },
        "meter_validation": validation,
    }
