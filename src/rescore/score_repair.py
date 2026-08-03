from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from fractions import Fraction
from pathlib import Path


def parse_meter_changes(values: list[str]) -> dict[int, tuple[int, int]]:
    changes: dict[int, tuple[int, int]] = {}
    for value in values:
        try:
            measure_text, meter_text = value.split("=", 1)
            beats_text, beat_type_text = meter_text.split("/", 1)
            measure, beats, beat_type = map(int, (measure_text, beats_text, beat_type_text))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"compasso inválido: {value}; use MEDIDA=BATIDAS/DENOMINADOR") from exc
        if min(measure, beats, beat_type) < 1:
            raise ValueError(f"compasso inválido: {value}")
        changes[measure] = (beats, beat_type)
    if not changes:
        raise ValueError("informe ao menos uma mudança com --meter-change")
    return dict(sorted(changes.items()))


def _read_xml(path: Path) -> bytes:
    if path.suffix.lower() != ".mxl":
        return path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next(
            item for item in container.iter() if item.tag.rsplit("}", 1)[-1] == "rootfile"
        )
        return archive.read(rootfile.attrib["full-path"])


def _strip_namespaces(root: ET.Element) -> None:
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]


def _attributes(measure: ET.Element) -> ET.Element:
    attributes = measure.find("attributes")
    if attributes is None:
        attributes = ET.Element("attributes")
        measure.insert(0, attributes)
    return attributes


def _insert_time(attributes: ET.Element, beats: int, beat_type: int) -> None:
    for old in attributes.findall("time"):
        attributes.remove(old)
    time = ET.Element("time")
    ET.SubElement(time, "beats").text = str(beats)
    ET.SubElement(time, "beat-type").text = str(beat_type)
    children = list(attributes)
    position = next(
        (index for index, child in enumerate(children) if child.tag in {"staves", "clef"}),
        len(children),
    )
    attributes.insert(position, time)


def _clef_signature(clef: ET.Element) -> tuple[str, str, str, str]:
    return (
        clef.get("number", "1"),
        clef.findtext("sign", ""),
        clef.findtext("line", ""),
        clef.findtext("clef-octave-change", ""),
    )


def _add_measure_rests(
    measure: ET.Element, divisions: int, meter: tuple[int, int], staves: int
) -> int:
    if measure.findall("note"):
        return 0
    beats, beat_type = meter
    duration = Fraction(divisions * beats * 4, beat_type)
    if duration.denominator != 1:
        return 0
    inserted = 0
    for staff in range(1, staves + 1):
        if staff > 1:
            backup = ET.SubElement(measure, "backup")
            ET.SubElement(backup, "duration").text = str(duration.numerator)
        note = ET.SubElement(measure, "note")
        ET.SubElement(note, "rest", {"measure": "yes"})
        ET.SubElement(note, "duration").text = str(duration.numerator)
        ET.SubElement(note, "voice").text = str(staff)
        if staves > 1:
            ET.SubElement(note, "staff").text = str(staff)
        inserted += 1
    return inserted


def _set_note_type(note: ET.Element, duration: int, divisions: int) -> None:
    value = Fraction(duration, divisions)
    names = {
        Fraction(4): ("whole", 0),
        Fraction(3): ("half", 1),
        Fraction(2): ("half", 0),
        Fraction(3, 2): ("quarter", 1),
        Fraction(1): ("quarter", 0),
        Fraction(3, 4): ("eighth", 1),
        Fraction(1, 2): ("eighth", 0),
        Fraction(3, 8): ("16th", 1),
        Fraction(1, 4): ("16th", 0),
        Fraction(1, 8): ("32nd", 0),
    }
    notation = names.get(value)
    if notation is None:
        return
    duration_type, dots = notation
    type_node = note.find("type")
    if type_node is None:
        type_node = ET.Element("type")
        children = list(note)
        position = next(
            (
                index
                for index, child in enumerate(children)
                if child.tag
                in {
                    "dot",
                    "accidental",
                    "time-modification",
                    "stem",
                    "notehead",
                    "staff",
                    "beam",
                    "notations",
                    "lyric",
                }
            ),
            len(children),
        )
        note.insert(position, type_node)
    type_node.text = duration_type
    for dot in list(note.findall("dot")):
        note.remove(dot)
    position = list(note).index(type_node) + 1
    for offset in range(dots):
        note.insert(position + offset, ET.Element("dot"))


def _clip_measure_overruns(
    measure: ET.Element, divisions: int, meter: tuple[int, int]
) -> tuple[int, int]:
    limit = Fraction(divisions * meter[0] * 4, meter[1])
    if limit.denominator != 1:
        return 0, 0
    cursor = Fraction(0)
    previous_onset = Fraction(0)
    previous_kept = True
    removed = 0
    clipped = 0
    for child in list(measure):
        if child.tag in {"backup", "forward"}:
            movement = Fraction(int(child.findtext("duration", "0")))
            cursor += movement if child.tag == "forward" else -movement
            continue
        if child.tag != "note" or child.find("grace") is not None:
            continue
        chord = child.find("chord") is not None
        onset = previous_onset if chord else cursor
        duration_node = child.find("duration")
        duration = Fraction(int(duration_node.text)) if duration_node is not None else Fraction(0)
        if chord and not previous_kept:
            measure.remove(child)
            removed += 1
            continue
        if onset >= limit:
            measure.remove(child)
            removed += 1
            previous_kept = False
            if not chord:
                previous_onset = onset
                cursor += duration
            continue
        previous_kept = True
        if onset + duration > limit and duration_node is not None:
            duration = limit - onset
            duration_node.text = str(duration.numerator)
            _set_note_type(child, duration.numerator, divisions)
            clipped += 1
        if not chord:
            previous_onset = onset
            cursor = onset + duration
    return removed, clipped


def repair_score_structure(
    source: Path,
    output: Path,
    meter_changes: dict[int, tuple[int, int]],
    *,
    remove_redundant_clefs: bool = True,
    fill_empty_measures: bool = True,
) -> dict:
    root = ET.fromstring(_read_xml(source))
    _strip_namespaces(root)
    if root.tag != "score-partwise":
        raise ValueError(f"somente score-partwise é aceito; recebido: {root.tag}")

    meters = dict(sorted(meter_changes.items()))
    report = {
        "source": str(source.resolve()),
        "output": str(output.resolve()),
        "parts": 0,
        "meter_events_inserted": 0,
        "redundant_clefs_removed": 0,
        "measure_rests_inserted": 0,
        "overrun_notes_removed": 0,
        "overrun_durations_clipped": 0,
        "meter_changes": {str(k): f"{v[0]}/{v[1]}" for k, v in meters.items()},
    }
    for part in root.findall("part"):
        report["parts"] += 1
        divisions, staves = 1, 1
        current_meter: tuple[int, int] | None = None
        active_clefs: dict[str, tuple[str, str, str, str]] = {}
        for index, measure in enumerate(part.findall("measure"), 1):
            attributes = measure.find("attributes")
            if attributes is not None:
                divisions_text = attributes.findtext("divisions")
                staves_text = attributes.findtext("staves")
                if divisions_text:
                    divisions = int(divisions_text)
                if staves_text:
                    staves = int(staves_text)

            if index in meters:
                current_meter = meters[index]
                attributes = _attributes(measure)
                _insert_time(attributes, *current_meter)
                report["meter_events_inserted"] += 1

            if attributes is not None and remove_redundant_clefs:
                for clef in list(attributes.findall("clef")):
                    signature = _clef_signature(clef)
                    staff = signature[0]
                    if active_clefs.get(staff) == signature:
                        attributes.remove(clef)
                        report["redundant_clefs_removed"] += 1
                    else:
                        active_clefs[staff] = signature

            if fill_empty_measures and current_meter is not None:
                report["measure_rests_inserted"] += _add_measure_rests(
                    measure, divisions, current_meter, staves
                )
            if current_meter is not None:
                removed, clipped = _clip_measure_overruns(
                    measure, divisions, current_meter
                )
                report["overrun_notes_removed"] += removed
                report["overrun_durations_clipped"] += clipped

            attributes = measure.find("attributes")
            if attributes is not None and len(attributes) == 0:
                measure.remove(attributes)

    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    output.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    return report
