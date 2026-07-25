from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from .musicxml import parse_musicxml

DIVISIONS = 24
RHYTHMIC_GRID = Fraction(1, 8)
NOTATED_DURATIONS = (
    Fraction(4),
    Fraction(3),
    Fraction(2),
    Fraction(3, 2),
    Fraction(1),
    Fraction(3, 4),
    Fraction(1, 2),
    Fraction(3, 8),
    Fraction(1, 4),
    Fraction(1, 8),
)


@dataclass(frozen=True)
class PartSpec:
    id: str
    name: str
    abbreviation: str
    clefs: tuple[tuple[str, int], ...]
    low_midi: int | None
    high_midi: int | None

    @property
    def staves(self) -> int:
        return len(self.clefs)


@dataclass(frozen=True)
class SourceMap:
    source: str
    part_id: str
    source_staff: str
    target_part: str
    target_staff: str = "1"


MENINA_PARTS = (
    PartSpec("P01", "Flautim / 2ª Flauta", "Flm./2ª Fl.", (("G", 2),), 60, 98),
    PartSpec("P02", "1ª Flauta", "1ª Fl.", (("G", 2),), 60, 96),
    PartSpec("P03", "Oboé / Corne inglês", "Ob./C. I.", (("G", 2),), 55, 93),
    PartSpec("P04", "Clarinete 1 / Saxofone", "Cl. 1/Sax.", (("G", 2),), 52, 96),
    PartSpec("P05", "Clarinete 2", "Cl. 2", (("G", 2),), 52, 96),
    PartSpec("P06", "Fagote", "Fg.", (("F", 4),), 34, 72),
    PartSpec("P07", "Trompas 1–2", "Tpa. 1–2", (("G", 2),), 45, 81),
    PartSpec("P08", "Trompa 3", "Tpa. 3", (("G", 2),), 45, 81),
    PartSpec("P09", "Pistão / Corneta", "Pist./Cor.", (("G", 2),), 54, 86),
    PartSpec("P10", "Trombone", "Trb.", (("F", 4),), 36, 70),
    PartSpec("P11", "Tuba", "Tba.", (("F", 4),), 24, 64),
    PartSpec("P12", "Tímpano", "Tmp.", (("F", 4),), 38, 57),
    PartSpec("P13", "Harpa", "Hp.", (("G", 2), ("F", 4)), 24, 103),
    PartSpec("P14", "Celesta / Xilofone", "Cel./Xil.", (("G", 2),), 48, 108),
    PartSpec("P15", "Bateria", "Bat.", (("percussion", 2),), None, None),
    PartSpec("P16", "Piano", "Pno.", (("G", 2), ("F", 4)), 21, 108),
    PartSpec("P17", "Menina", "Menina", (("G", 2),), 55, 84),
    PartSpec("P18", "Coro", "Coro", (("G", 2),), 48, 84),
    PartSpec("P19", "Violino I", "Vln. I", (("G", 2),), 55, 103),
    PartSpec("P20", "Violino II", "Vln. II", (("G", 2),), 55, 100),
    PartSpec("P21", "Viola", "Vla.", (("C", 3),), 48, 88),
    PartSpec("P22", "Violoncelo", "Vc.", (("F", 4),), 36, 84),
    PartSpec("P23", "Contrabaixo", "Cb.", (("F", 4),), 28, 67),
)


MENINA_PAGE_MAPS: dict[int, tuple[SourceMap, ...]] = {
    1: (
        SourceMap("page1_upper", "P1", "1", "P01"),
        SourceMap("page1_upper", "P1", "2", "P02"),
        SourceMap("page1_upper", "P2", "1", "P03"),
        SourceMap("page1_upper", "P3", "1", "P04"),
        SourceMap("page1_upper", "P4", "1", "P06"),
        SourceMap("page1_upper", "P4", "2", "P07"),
        SourceMap("page1_upper", "P5", "1", "P09"),
        SourceMap("page1_upper", "P5", "2", "P11"),
        SourceMap("page1_upper", "P6", "1", "P10"),
        SourceMap("page1_upper", "P7", "1", "P12"),
        SourceMap("page1_lower", "P1", "1", "P13", "1"),
        SourceMap("page1_lower", "P2", "1", "P14"),
        SourceMap("page1_lower", "P3", "1", "P15"),
        SourceMap("page1_lower", "P4", "1", "P16", "1"),
        SourceMap("page1_lower", "P4", "2", "P16", "2"),
        SourceMap("page1_lower", "P5", "2", "P19"),
        SourceMap("page1_lower", "P6", "1", "P20"),
        SourceMap("page1_lower", "P7", "1", "P21"),
        SourceMap("page1_lower", "P8", "1", "P22"),
        SourceMap("page1_lower", "P8", "2", "P23"),
    ),
    2: (
        SourceMap("page2_upper", "P1", "1", "P01"),
        SourceMap("page2_upper", "P2", "1", "P03"),
        SourceMap("page2_upper", "P2", "2", "P04"),
        SourceMap("page2_upper", "P3", "1", "P06"),
        SourceMap("page2_upper", "P4", "1", "P07"),
        SourceMap("page2_upper", "P4", "2", "P08"),
        SourceMap("page2_upper", "P5", "1", "P09"),
        SourceMap("page2_upper", "P6", "1", "P10"),
        SourceMap("page2_upper", "P7", "1", "P11"),
        SourceMap("page2_upper", "P8", "1", "P12"),
        SourceMap("page2_lower", "P3", "1", "P19"),
        SourceMap("page2_lower", "P4", "1", "P20"),
        SourceMap("page2_lower", "P5", "1", "P21"),
        SourceMap("page2_lower", "P6", "1", "P22"),
        SourceMap("page2_lower", "P7", "1", "P23"),
    ),
    3: (
        SourceMap("page3_upper", "P1", "1", "P01"),
        SourceMap("page3_upper", "P1", "2", "P02"),
        SourceMap("page3_upper", "P2", "1", "P03"),
        SourceMap("page3_upper", "P2", "2", "P04"),
        SourceMap("page3_upper", "P3", "1", "P06"),
        SourceMap("page3_upper", "P4", "1", "P07"),
        SourceMap("page3_upper", "P5", "1", "P09"),
        SourceMap("page3_upper", "P6", "1", "P10"),
        SourceMap("page3_upper", "P7", "1", "P11"),
        SourceMap("page3_upper", "P8", "1", "P12"),
        SourceMap("page3_upper", "P9", "1", "P15"),
        SourceMap("page3_upper", "P10", "1", "P14"),
        SourceMap("page3_upper", "P11", "1", "P13", "1"),
        SourceMap("page3_upper", "P12", "1", "P16", "1"),
        SourceMap("page3_lower", "P2", "1", "P16", "2"),
        SourceMap("page3_lower", "P7", "1", "P19"),
        SourceMap("page3_lower", "P8", "1", "P20"),
        SourceMap("page3_lower", "P9", "1", "P21"),
        SourceMap("page3_lower", "P10", "1", "P22"),
        SourceMap("page3_lower", "P11", "1", "P23"),
    ),
    4: (
        SourceMap("page4_upper", "P1", "1", "P01"),
        SourceMap("page4_upper", "P1", "2", "P03"),
        SourceMap("page4_upper", "P2", "1", "P04"),
        SourceMap("page4_upper", "P2", "2", "P05"),
        SourceMap("page4_upper", "P3", "1", "P06"),
        SourceMap("page4_upper", "P4", "1", "P07"),
        SourceMap("page4_upper", "P4", "2", "P08"),
        SourceMap("page4_lower", "P1", "1", "P15"),
        SourceMap("page4_lower", "P2", "1", "P13", "1"),
        SourceMap("page4_lower", "P2", "2", "P13", "2"),
        SourceMap("page4_lower", "P3", "1", "P16", "1"),
        SourceMap("page4_lower", "P3", "2", "P16", "2"),
        SourceMap("page4_lower", "P4", "1", "P17"),
        SourceMap("page4_lower", "P5", "1", "P18"),
        SourceMap("page4_lower", "P7", "2", "P19"),
        SourceMap("page4_lower", "P8", "1", "P20"),
        SourceMap("page4_lower", "P9", "1", "P21"),
        SourceMap("page4_lower", "P10", "1", "P22"),
        SourceMap("page4_lower", "P11", "1", "P23"),
    ),
}


PAGE_MEASURE_COUNTS = {1: 8, 2: 8, 3: 5, 4: 5}
PAGE_FIRST_MEASURE = {1: 1, 2: 9, 3: 17, 4: 22}

MENINA_CROP_BOXES: dict[str, tuple[int, int, int, int]] = {
    "page1_upper": (100, 1040, 3420, 2860),
    "page1_lower": (100, 2880, 3420, 4810),
    "page2_upper": (120, 600, 3430, 2550),
    "page2_lower": (120, 3550, 3430, 4860),
    "page3_upper": (120, 550, 3430, 3100),
    "page3_lower": (120, 2900, 3430, 4750),
    "page4_upper": (120, 600, 3430, 2550),
    "page4_lower": (120, 2350, 3430, 4890),
}


def _meter(measure: int) -> tuple[int, int, Fraction]:
    if 19 <= measure <= 21:
        return 3, 4, Fraction(3)
    return 2, 4, Fraction(2)


def _pitch_to_midi(pitch: str | None) -> int | None:
    if not pitch or pitch.startswith("unpitched:"):
        return None
    step_value = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    step = pitch[0]
    index = 1
    accidental = 0
    while index < len(pitch) and pitch[index] in "#b":
        accidental += 1 if pitch[index] == "#" else -1
        index += 1
    try:
        octave = int(pitch[index:])
    except ValueError:
        return None
    return (octave + 1) * 12 + step_value[step] + accidental


def _measure_groups(events: list[dict]) -> list[list[dict]]:
    pitched = [event for event in events if event.get("pitch") and not event.get("grace")]
    by_onset: dict[Fraction, list[dict]] = defaultdict(list)
    for event in pitched:
        by_onset[Fraction(event["onset"])].append(copy.deepcopy(event))
    return [by_onset[onset] for onset in sorted(by_onset)]


def _source_measure_buckets(
    score: dict,
    part_id: str,
    staff: str,
    expected: int,
) -> list[list[dict]]:
    count = int(score.get("measure_counts", {}).get(part_id, score.get("measures", 0)))
    buckets = [
        [
            copy.deepcopy(event)
            for event in score["events"]
            if event["part_id"] == part_id
            and event.get("staff", "1") == staff
            and int(event["measure_index"]) == measure
            and event.get("voice", "1") == "1"
        ]
        for measure in range(1, count + 1)
    ]
    if not buckets:
        return [[] for _ in range(expected)]
    if len(buckets) <= expected:
        return buckets + [[] for _ in range(expected - len(buckets))]

    # TrOMR sometimes treats a stem, lyric stroke, or courtesy bar as a new
    # barline. Preserve the real leading measures and fold surplus material
    # into the final expected measure. The vocal line on page 4 has one known
    # false split in the middle; handle that without shifting its four lyric bars.
    if part_id in {"P11", "P4"} and expected == 5 and len(buckets) == 6:
        plan = ((0,), (1,), (2,), (3, 4), (5,))
    else:
        plan = tuple((index,) for index in range(expected - 1)) + (
            tuple(range(expected - 1, len(buckets))),
        )
    result: list[list[dict]] = []
    for source_indices in plan:
        merged: list[dict] = []
        offset = Fraction(0)
        for source_index in source_indices:
            source = buckets[source_index]
            for event in source:
                cloned = copy.deepcopy(event)
                cloned["onset"] = str(Fraction(cloned["onset"]) + offset)
                merged.append(cloned)
            end = max(
                (
                    Fraction(event["onset"]) + Fraction(event["duration"])
                    for event in source
                    if not event.get("chord") and not event.get("grace")
                ),
                default=Fraction(0),
            )
            offset += max(end, Fraction(1))
        result.append(merged)
    return result


def _quantize(value: Fraction) -> Fraction:
    """Snap uncertain OMR timing to the smallest safely notated value.

    homr can return proportional positions that are metrically exact in
    MusicXML but have no corresponding written duration. MuseScore then
    approximates those values with 128th-note fractions and reports incomplete
    measures. A 32nd-note grid retains the useful horizontal order while every
    emitted note and rest has an unambiguous native spelling.
    """
    return round(value / RHYTHMIC_GRID) * RHYTHMIC_GRID


def _sanitize_groups(
    events: list[dict],
    part: PartSpec,
    duration: Fraction,
    *,
    page: int,
    global_measure: int,
    report: dict,
) -> list[tuple[Fraction, Fraction, list[dict]]]:
    groups = _measure_groups(events)
    if not groups:
        return []

    # The first bar of page 4 contains clearly marked groups of twelve in
    # these instruments. TrOMR recognizes fragments of them, but does not
    # preserve a trustworthy 12-note tuplet ratio. A sparse review bar is
    # preferable to a metrically valid but fabricated cadenza.
    if global_measure == 22 and part.id in {"P03", "P04", "P05", "P13", "P16"}:
        report["withheld_tuplet_measures"].append(
            {
                "page": page,
                "measure": global_measure,
                "part": part.name,
                "reason": "grupo manuscrito de 12 sem razão rítmica comprovada",
            }
        )
        return []

    maximum_groups = 12 if duration == 3 else 8
    if len(groups) > maximum_groups:
        report["dropped_dense_measures"].append(
            {
                "page": page,
                "measure": global_measure,
                "part": part.name,
                "recognized_groups": len(groups),
            }
        )
        return []

    raw_end = max(
        Fraction(group[0]["onset"]) + max(Fraction(event["duration"]) for event in group)
        for group in groups
    )
    if raw_end <= 0:
        return []
    scale = Fraction(1)
    if raw_end > duration or raw_end < duration / 2:
        scale = duration / raw_end

    sanitized: list[tuple[Fraction, Fraction, list[dict]]] = []
    range_drops = 0
    total_pitches = 0
    for group in groups:
        onset = _quantize(Fraction(group[0]["onset"]) * scale)
        raw_duration = min(Fraction(event["duration"]) for event in group)
        note_duration = _quantize(raw_duration * scale)
        if len(groups) == 1 and raw_duration >= duration:
            onset = Fraction(0)
            note_duration = duration
        if note_duration <= 0:
            note_duration = Fraction(1, 2)
        if onset >= duration:
            continue
        note_duration = min(note_duration, duration - onset)
        kept: list[dict] = []
        for event in group:
            total_pitches += 1
            midi = _pitch_to_midi(event.get("pitch"))
            if (
                midi is not None
                and part.low_midi is not None
                and not (part.low_midi <= midi <= part.high_midi)
            ):
                range_drops += 1
                continue
            kept.append(event)
        if kept:
            sanitized.append((onset, note_duration, kept))

    if total_pitches and range_drops / total_pitches > 0.4:
        report["dropped_range_measures"].append(
            {
                "page": page,
                "measure": global_measure,
                "part": part.name,
                "recognized_notes": total_pitches,
                "out_of_range": range_drops,
            }
        )
        report["dropped_out_of_range_notes"] += range_drops
        return []
    report["dropped_out_of_range_notes"] += range_drops

    result: list[tuple[Fraction, Fraction, list[dict]]] = []
    cursor = Fraction(0)
    for onset, note_duration, group in sorted(sanitized, key=lambda item: item[0]):
        onset = max(onset, cursor)
        if onset >= duration:
            continue
        note_duration = min(note_duration, duration - onset)
        if note_duration <= 0:
            continue
        result.append((onset, note_duration, group))
        cursor = onset + note_duration
    return result


def _duration_type(duration: Fraction) -> tuple[str | None, int]:
    values = {
        Fraction(4): ("whole", 0),
        Fraction(3): ("half", 1),
        Fraction(2): ("half", 0),
        Fraction(3, 2): ("quarter", 1),
        Fraction(1): ("quarter", 0),
        Fraction(3, 4): ("eighth", 1),
        Fraction(1, 2): ("eighth", 0),
        Fraction(3, 8): ("16th", 1),
        Fraction(1, 4): ("16th", 0),
        Fraction(3, 16): ("32nd", 1),
        Fraction(1, 8): ("32nd", 0),
    }
    return values.get(duration, (None, 0))


def _emit_rest(measure: ET.Element, duration: Fraction, voice: str, staff: str) -> None:
    for piece in _duration_pieces(duration):
        note = ET.SubElement(measure, "note")
        ET.SubElement(note, "rest")
        ET.SubElement(note, "duration").text = str(int(piece * DIVISIONS))
        ET.SubElement(note, "voice").text = voice
        note_type, dots = _duration_type(piece)
        if note_type:
            ET.SubElement(note, "type").text = note_type
            for _ in range(dots):
                ET.SubElement(note, "dot")
        ET.SubElement(note, "staff").text = staff


def _duration_pieces(duration: Fraction) -> list[Fraction]:
    """Spell a duration as tied/rest pieces MuseScore represents exactly."""
    remaining = duration
    pieces: list[Fraction] = []
    while remaining > 0:
        piece = next(
            (candidate for candidate in NOTATED_DURATIONS if candidate <= remaining),
            None,
        )
        if piece is None:
            raise ValueError(f"duração fora da grade notacional: {remaining}")
        pieces.append(piece)
        remaining -= piece
    return pieces


def _pitch_components(pitch: str) -> tuple[str, int, int]:
    step = pitch[0]
    index = 1
    alter = 0
    while index < len(pitch) and pitch[index] in "#b":
        alter += 1 if pitch[index] == "#" else -1
        index += 1
    return step, alter, int(pitch[index:])


def _emit_note(
    measure: ET.Element,
    event: dict,
    duration: Fraction,
    voice: str,
    staff: str,
    *,
    chord: bool,
    lyric: str | None,
    tie_start: bool = False,
    tie_stop: bool = False,
) -> None:
    note = ET.SubElement(measure, "note")
    if chord:
        ET.SubElement(note, "chord")
    pitch_text = event.get("pitch")
    if pitch_text and pitch_text.startswith("unpitched:"):
        unpitched = ET.SubElement(note, "unpitched")
        ET.SubElement(unpitched, "display-step").text = pitch_text[-2]
        ET.SubElement(unpitched, "display-octave").text = pitch_text[-1]
    elif pitch_text:
        step, alter, octave = _pitch_components(pitch_text)
        pitch = ET.SubElement(note, "pitch")
        ET.SubElement(pitch, "step").text = step
        if alter:
            ET.SubElement(pitch, "alter").text = str(alter)
        ET.SubElement(pitch, "octave").text = str(octave)
    else:
        ET.SubElement(note, "rest")
    ET.SubElement(note, "duration").text = str(int(duration * DIVISIONS))
    if tie_stop:
        ET.SubElement(note, "tie", {"type": "stop"})
    if tie_start:
        ET.SubElement(note, "tie", {"type": "start"})
    ET.SubElement(note, "voice").text = voice
    note_type, dots = _duration_type(duration)
    if note_type:
        ET.SubElement(note, "type").text = note_type
        for _ in range(dots):
            ET.SubElement(note, "dot")
    ET.SubElement(note, "staff").text = staff
    if tie_start or tie_stop:
        notations = ET.SubElement(note, "notations")
        if tie_stop:
            ET.SubElement(notations, "tied", {"type": "stop"})
        if tie_start:
            ET.SubElement(notations, "tied", {"type": "start"})
    if lyric and not chord:
        lyric_node = ET.SubElement(note, "lyric", {"number": "1"})
        ET.SubElement(lyric_node, "syllabic").text = "single"
        ET.SubElement(lyric_node, "text").text = lyric


def _attributes(
    measure: ET.Element,
    part: PartSpec,
    global_measure: int,
) -> None:
    beats, beat_type, _ = _meter(global_measure)
    attributes = ET.SubElement(measure, "attributes")
    ET.SubElement(attributes, "divisions").text = str(DIVISIONS)
    if part.staves > 1:
        ET.SubElement(attributes, "staves").text = str(part.staves)
    if global_measure in {1, 19, 22}:
        time = ET.SubElement(attributes, "time")
        ET.SubElement(time, "beats").text = str(beats)
        ET.SubElement(time, "beat-type").text = str(beat_type)
    for staff_number, (sign, line) in enumerate(part.clefs, 1):
        clef = ET.SubElement(
            attributes,
            "clef",
            {"number": str(staff_number)} if part.staves > 1 else {},
        )
        ET.SubElement(clef, "sign").text = sign
        ET.SubElement(clef, "line").text = str(line)


def _add_part_list(root: ET.Element) -> None:
    part_list = ET.SubElement(root, "part-list")
    for index, part in enumerate(MENINA_PARTS, 1):
        score_part = ET.SubElement(part_list, "score-part", {"id": part.id})
        ET.SubElement(score_part, "part-name").text = part.name
        ET.SubElement(score_part, "part-abbreviation").text = part.abbreviation
        score_instrument = ET.SubElement(score_part, "score-instrument", {"id": f"{part.id}-I1"})
        ET.SubElement(score_instrument, "instrument-name").text = part.name
        midi = ET.SubElement(score_part, "midi-instrument", {"id": f"{part.id}-I1"})
        ET.SubElement(midi, "midi-channel").text = str(((index - 1) % 16) + 1)
        ET.SubElement(midi, "midi-program").text = "1"


def _lyric_plan(global_measure: int) -> list[str]:
    return {
        23: ["E", "le", "ga", "ran"],
        24: ["tiu", "que", "com"],
        25: ["is", "so", "vo"],
        26: ["cê", "vi", "ra", "va"],
    }.get(global_measure, [])


def build_menina_das_nuvens_draft(
    sources: dict[str, Path],
    output: Path,
    report_path: Path | None = None,
) -> dict:
    """Build a meter-safe, continuous draft from the four manuscript photos.

    The function deliberately accepts only the fixed vertical mappings verified
    against these source pages. It is conservative: implausible ranges and
    overly dense readings become rests instead of fabricated notation.
    """
    missing = sorted(name for name, path in sources.items() if not path.is_file())
    if missing:
        raise FileNotFoundError(f"fontes OMR ausentes: {', '.join(missing)}")
    parsed = {name: parse_musicxml(path, include_rests=True) for name, path in sources.items()}
    part_by_id = {part.id: part for part in MENINA_PARTS}
    streams: dict[tuple[str, int, str], list[tuple[Fraction, Fraction, list[dict]]]] = {}
    report: dict = {
        "title": "A Menina das Nuvens — 1º Ato",
        "policy": "conservative-meter-safe",
        "source_pages": 4,
        "measures": 26,
        "meter_changes": {"1": "2/4", "19": "3/4", "22": "2/4"},
        "parts": [part.name for part in MENINA_PARTS],
        "dropped_dense_measures": [],
        "dropped_range_measures": [],
        "withheld_tuplet_measures": [],
        "dropped_out_of_range_notes": 0,
        "accepted_pitched_notes": 0,
        "known_manual_review": [
            "compasso 22: grupos manuscritos de 12 na harpa/piano/clarinetes",
            "articulações, dinâmicas e ligaduras ainda não são consideradas verificadas",
            "transpositores são mantidos em altura escrita reconhecida; conferir afinação final",
        ],
    }

    for page, mappings in MENINA_PAGE_MAPS.items():
        expected = PAGE_MEASURE_COUNTS[page]
        first = PAGE_FIRST_MEASURE[page]
        for mapping in mappings:
            score = parsed[mapping.source]
            buckets = _source_measure_buckets(
                score, mapping.part_id, mapping.source_staff, expected
            )
            part = part_by_id[mapping.target_part]
            for local_index, events in enumerate(buckets):
                global_measure = first + local_index
                _, _, duration = _meter(global_measure)
                groups = _sanitize_groups(
                    events,
                    part,
                    duration,
                    page=page,
                    global_measure=global_measure,
                    report=report,
                )
                key = (mapping.target_part, global_measure, mapping.target_staff)
                streams[key] = groups
                report["accepted_pitched_notes"] += sum(
                    len(group) for _onset, _duration, group in groups
                )

    root = ET.Element("score-partwise", {"version": "4.0"})
    work = ET.SubElement(root, "work")
    ET.SubElement(work, "work-title").text = "A Menina das Nuvens — 1º Ato"
    identification = ET.SubElement(root, "identification")
    ET.SubElement(identification, "creator", {"type": "composer"}).text = "Heitor Villa-Lobos"
    encoding = ET.SubElement(identification, "encoding")
    ET.SubElement(encoding, "software").text = "ReScore manuscript conservative draft"
    _add_part_list(root)

    for part in MENINA_PARTS:
        part_node = ET.SubElement(root, "part", {"id": part.id})
        for global_measure in range(1, 27):
            _, _, duration = _meter(global_measure)
            measure = ET.SubElement(part_node, "measure", {"number": str(global_measure)})
            if global_measure in {1, 9, 17, 22}:
                ET.SubElement(
                    measure,
                    "print",
                    {"new-system": "yes"} if global_measure != 1 else {},
                )
            if global_measure == 1 or global_measure in {19, 22}:
                _attributes(measure, part, global_measure)
            lyrics = _lyric_plan(global_measure) if part.id == "P17" else []
            lyric_index = 0
            for staff_number in range(1, part.staves + 1):
                staff = str(staff_number)
                if staff_number > 1:
                    backup = ET.SubElement(measure, "backup")
                    ET.SubElement(backup, "duration").text = str(int(duration * DIVISIONS))
                groups = streams.get((part.id, global_measure, staff), [])
                cursor = Fraction(0)
                for onset, note_duration, group in groups:
                    if onset > cursor:
                        _emit_rest(measure, onset - cursor, "1", staff)
                    pieces = _duration_pieces(note_duration)
                    for piece_index, piece in enumerate(pieces):
                        for chord_index, event in enumerate(group):
                            lyric = (
                                lyrics[lyric_index]
                                if piece_index == 0
                                and chord_index == 0
                                and lyric_index < len(lyrics)
                                else None
                            )
                            _emit_note(
                                measure,
                                event,
                                piece,
                                "1",
                                staff,
                                chord=chord_index > 0,
                                lyric=lyric,
                                tie_start=piece_index < len(pieces) - 1,
                                tie_stop=piece_index > 0,
                            )
                    if lyric_index < len(lyrics):
                        lyric_index += 1
                    cursor = onset + note_duration
                if cursor < duration:
                    _emit_rest(measure, duration - cursor, "1", staff)
            if global_measure == 26:
                barline = ET.SubElement(measure, "barline", {"location": "right"})
                ET.SubElement(barline, "bar-style").text = "light-heavy"

    ET.indent(root, space="  ")
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    report["output"] = str(output.resolve())
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def find_homr(project_root: Path, supplied: Path | None = None) -> Path | None:
    if supplied:
        resolved = supplied.resolve()
        return resolved if resolved.is_file() else None
    executable = shutil.which("homr")
    if executable:
        return Path(executable).resolve()
    local = project_root / "tools" / "homr-env" / "Scripts" / "homr.exe"
    return local.resolve() if local.is_file() else None


def prepare_menina_crops(image_dir: Path, output_dir: Path) -> dict[str, Path]:
    images = sorted(
        path
        for path in image_dir.iterdir()
        if path.is_file() and path.suffix.casefold() in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    )
    if len(images) != 4:
        raise ValueError(
            f"eram esperadas exatamente 4 imagens do manuscrito; encontradas: {len(images)}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    crops: dict[str, Path] = {}
    for key, box in MENINA_CROP_BOXES.items():
        page = int(key[4])
        source = images[page - 1]
        with Image.open(source) as image:
            if image.width < box[2] or image.height < box[3]:
                raise ValueError(
                    f"{source.name} tem {image.width}x{image.height}; "
                    f"o perfil requer pelo menos {box[2]}x{box[3]}"
                )
            crop = image.crop(box).convert("L")
            crop = ImageOps.autocontrast(crop, cutoff=0.35)
            crop = ImageEnhance.Contrast(crop).enhance(1.2)
            destination = output_dir / f"{key}.png"
            crop.save(destination, dpi=(300, 300))
            crops[key] = destination
    return crops


def run_homr_on_crops(
    homr: Path,
    crops: dict[str, Path],
    output_dir: Path,
    *,
    force: bool = False,
) -> dict[str, Path]:
    homr = homr.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Path] = {}
    for key, crop in crops.items():
        crop = crop.resolve()
        candidates = [crop]
        for retry_index, brightness in enumerate((0.995, 1.005), start=1):
            retry = output_dir / f"{crop.stem}-retry-{retry_index}.png"
            if force or not retry.is_file():
                with Image.open(crop) as image:
                    adjusted = ImageEnhance.Brightness(image).enhance(brightness)
                    adjusted.save(retry, dpi=(300, 300))
            candidates.append(retry)

        selected: Path | None = None
        logs: list[str] = []
        for candidate in candidates:
            result = candidate.with_suffix(".musicxml")
            if result.is_file() and not force:
                selected = result
                break
            if force and result.is_file():
                result.unlink()
            process = subprocess.run(
                [str(homr), "--write-staff-positions", "--cache", str(candidate)],
                cwd=output_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            logs.append(
                f"=== {candidate.name} (exit {process.returncode}) ===\n"
                f"{process.stdout}\n{process.stderr}"
            )
            if process.returncode == 0 and result.is_file():
                selected = result
                break
            if "inv_scale_x > 0" in process.stderr:
                python = homr.parent / "python.exe"
                source_dir = Path(__file__).resolve().parents[1]
                environment = os.environ.copy()
                existing_pythonpath = environment.get("PYTHONPATH")
                environment["PYTHONPATH"] = (
                    str(source_dir)
                    if not existing_pythonpath
                    else str(source_dir) + os.pathsep + existing_pythonpath
                )
                safe_process = subprocess.run(
                    [
                        str(python),
                        "-m",
                        "rescore.homr_safe_runner",
                        "--write-staff-positions",
                        "--cache",
                        str(candidate),
                    ],
                    cwd=output_dir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    env=environment,
                )
                logs.append(
                    f"=== {candidate.name} safe runner "
                    f"(exit {safe_process.returncode}) ===\n"
                    f"{safe_process.stdout}\n{safe_process.stderr}"
                )
                if safe_process.returncode == 0 and result.is_file():
                    selected = result
                    break
        log_path = output_dir / f"{key}-homr.log"
        log_path.write_text("\n".join(logs), encoding="utf-8")
        if selected is None:
            raise RuntimeError(f"homr falhou em {key}; consulte {log_path.resolve()}")
        results[key] = selected
    return results


def recognize_menina_image_directory(
    project_root: Path,
    image_dir: Path,
    output_dir: Path,
    *,
    homr_path: Path | None = None,
    force: bool = False,
) -> dict:
    """Run the fixed four-photo manuscript profile and build one MusicXML draft."""
    image_dir = image_dir.resolve()
    if not image_dir.is_dir():
        raise FileNotFoundError(f"pasta de imagens não encontrada: {image_dir}")
    homr = find_homr(project_root, homr_path)
    if homr is None:
        raise FileNotFoundError(
            "homr não encontrado; instale `homr==0.7.0` em um ambiente virtual "
            "ou informe o executável com --homr"
        )
    crop_dir = output_dir / "crops"
    crops = prepare_menina_crops(image_dir, crop_dir)
    sources = run_homr_on_crops(homr, crops, crop_dir, force=force)
    musicxml = output_dir / "menina-das-nuvens-draft.musicxml"
    report_path = output_dir / "recognition-report.json"
    report = build_menina_das_nuvens_draft(sources, musicxml, report_path)
    return {
        "musicxml": musicxml,
        "report": report_path,
        "crops": crops,
        "omr": sources,
        "summary": report,
    }
