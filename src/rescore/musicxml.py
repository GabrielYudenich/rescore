from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from fractions import Fraction
from pathlib import Path


def _read_musicxml(path: Path) -> bytes:
    if path.suffix.lower() != ".mxl":
        return path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next(
            element
            for element in container.iter()
            if element.tag.rsplit("}", 1)[-1] == "rootfile"
        )
        return archive.read(rootfile.attrib["full-path"])


def _strip_namespaces(root: ET.Element) -> ET.Element:
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    return root


def _fraction_text(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def normalize_part_name(value: str) -> str:
    for _ in range(3):
        unescaped = html.unescape(value)
        if unescaped == value:
            break
        value = unescaped
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def parse_musicxml(path: Path, include_rests: bool = False) -> dict:
    data = _read_musicxml(path)
    root = _strip_namespaces(ET.fromstring(data))
    if root.tag != "score-partwise":
        raise ValueError(f"somente score-partwise é aceito; recebido: {root.tag}")

    part_names = {
        item.get("id", ""): html.unescape(item.findtext("part-name", item.get("id", "")))
        for item in root.findall("./part-list/score-part")
    }
    events: list[dict] = []
    times: list[dict] = []
    measure_counts: dict[str, int] = {}

    for part in root.findall("part"):
        part_id = part.get("id", "")
        part_name = part_names.get(part_id, part_id)
        divisions = 1
        measures = part.findall("measure")
        measure_counts[part_id] = len(measures)
        for measure_index, measure in enumerate(measures, 1):
            cursor = Fraction(0)
            previous_onset = Fraction(0)
            for child in measure:
                if child.tag == "attributes":
                    divisions_text = child.findtext("divisions")
                    if divisions_text:
                        divisions = int(divisions_text)
                    for time in child.findall("time"):
                        times.append(
                            {
                                "part_id": part_id,
                                "part_name": part_name,
                                "measure_index": measure_index,
                                "measure_number": measure.get("number", str(measure_index)),
                                "beats": time.findtext("beats", ""),
                                "beat_type": time.findtext("beat-type", ""),
                                "symbol": time.get("symbol"),
                            }
                        )
                    continue
                if child.tag in {"backup", "forward"}:
                    duration_text = child.findtext("duration", "0")
                    movement = Fraction(int(duration_text), divisions)
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

                rest = child.find("rest") is not None
                if rest and not include_rests:
                    continue
                pitch_element = child.find("pitch")
                unpitched_element = child.find("unpitched")
                pitch = None
                if pitch_element is not None:
                    step = pitch_element.findtext("step", "")
                    alter = int(pitch_element.findtext("alter", "0"))
                    octave = pitch_element.findtext("octave", "")
                    accidental = "#" * alter if alter > 0 else "b" * (-alter)
                    pitch = f"{step}{accidental}{octave}"
                elif unpitched_element is not None:
                    step = unpitched_element.findtext("display-step", "")
                    octave = unpitched_element.findtext("display-octave", "")
                    pitch = f"unpitched:{step}{octave}"

                time_modification = child.find("time-modification")
                tuplet = None
                if time_modification is not None:
                    tuplet = {
                        "actual": time_modification.findtext("actual-notes"),
                        "normal": time_modification.findtext("normal-notes"),
                    }
                articulations: list[str] = []
                tremolo = None
                notations = child.find("notations")
                if notations is not None:
                    articulation_node = notations.find("articulations")
                    if articulation_node is not None:
                        articulations = [item.tag for item in articulation_node]
                    tremolo_node = notations.find("./ornaments/tremolo")
                    if tremolo_node is not None:
                        tremolo = {
                            "type": tremolo_node.get("type", "single"),
                            "marks": int(tremolo_node.text or "3"),
                        }
                lyrics: list[dict] = []
                for lyric_node in child.findall("lyric"):
                    text = lyric_node.findtext("text")
                    extend_node = lyric_node.find("extend")
                    # A lyric may contain only an extender. Keep it because its
                    # position belongs to the vocal line even when no new
                    # syllable is printed on this note.
                    if text is None and extend_node is None:
                        continue
                    lyric: dict[str, str] = {}
                    if text is not None:
                        lyric["text"] = text
                    syllabic = lyric_node.findtext("syllabic")
                    if syllabic:
                        lyric["syllabic"] = syllabic
                    if extend_node is not None:
                        lyric["extend"] = extend_node.get("type", "continue")
                    if lyric_node.get("number"):
                        lyric["number"] = lyric_node.get("number", "")
                    if lyric_node.get("name"):
                        lyric["name"] = lyric_node.get("name", "")
                    lyrics.append(lyric)

                events.append(
                    {
                        "part_id": part_id,
                        "part_name": part_name,
                        "part_key": normalize_part_name(part_name),
                        "measure_index": measure_index,
                        "measure_number": measure.get("number", str(measure_index)),
                        "measure_width": float(measure.get("width"))
                        if measure.get("width")
                        else None,
                        "default_x": float(child.get("default-x"))
                        if child.get("default-x")
                        else None,
                        "onset": _fraction_text(onset),
                        "duration": _fraction_text(duration),
                        "pitch": pitch,
                        "rest": rest,
                        "grace": grace,
                        "chord": chord,
                        "voice": child.findtext("voice", "1"),
                        "staff": child.findtext("staff", "1"),
                        "type": child.findtext("type"),
                        "dots": len(child.findall("dot")),
                        "tuplet": tuplet,
                        "ties": sorted(tie.get("type", "") for tie in child.findall("tie")),
                        "articulations": sorted(articulations),
                        "tremolo": tremolo,
                        "lyrics": lyrics,
                    }
                )

    return {
        "source": str(path.resolve()),
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": root.get("version"),
        "title": root.findtext("./work/work-title", ""),
        "parts": [{"id": key, "name": value} for key, value in part_names.items()],
        "parts_count": len(part_names),
        "measures": max(measure_counts.values(), default=0),
        "measure_counts": measure_counts,
        "time_signatures": times,
        "events_count": len(events),
        "events": events,
    }


def write_canonical(score: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(score, ensure_ascii=False, indent=2), encoding="utf-8")


def _event_key(event: dict, part_sensitive: bool) -> tuple:
    common = (
        event["measure_index"],
        event["onset"],
        event["duration"],
        event["pitch"],
        event["grace"],
    )
    return (event["part_key"], *common) if part_sensitive else common


def _metric(reference: Counter, candidate: Counter) -> dict:
    matched = sum((reference & candidate).values())
    reference_count = sum(reference.values())
    candidate_count = sum(candidate.values())
    precision = matched / candidate_count if candidate_count else 0.0
    recall = matched / reference_count if reference_count else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "reference": reference_count,
        "candidate": candidate_count,
        "matched": matched,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def compare_scores(reference: dict, candidate: dict, sample_limit: int = 30) -> dict:
    reference_events = [event for event in reference["events"] if event.get("pitch")]
    candidate_events = [event for event in candidate["events"] if event.get("pitch")]
    global_reference = Counter(_event_key(event, False) for event in reference_events)
    global_candidate = Counter(_event_key(event, False) for event in candidate_events)
    part_reference = Counter(_event_key(event, True) for event in reference_events)
    part_candidate = Counter(_event_key(event, True) for event in candidate_events)

    missing = list((global_reference - global_candidate).elements())[:sample_limit]
    extra = list((global_candidate - global_reference).elements())[:sample_limit]
    reference_parts = {item["name"] for item in reference["parts"]}
    candidate_parts = {item["name"] for item in candidate["parts"]}
    return {
        "reference": {
            "source": reference["source"],
            "sha256": reference["sha256"],
            "parts": reference["parts_count"],
            "measures": reference["measures"],
        },
        "candidate": {
            "source": candidate["source"],
            "sha256": candidate["sha256"],
            "parts": candidate["parts_count"],
            "measures": candidate["measures"],
        },
        "global_note_rhythm": _metric(global_reference, global_candidate),
        "instrument_note_rhythm": _metric(part_reference, part_candidate),
        "part_names": {
            "common": sorted(reference_parts & candidate_parts),
            "missing_from_candidate": sorted(reference_parts - candidate_parts),
            "extra_in_candidate": sorted(candidate_parts - reference_parts),
        },
        "missing_global_event_sample": [list(item) for item in missing],
        "extra_global_event_sample": [list(item) for item in extra],
        "interpretation": (
            "A métrica global ignora o instrumento e mede nota+ritmo. "
            "A métrica por instrumento também exige que a parte tenha o mesmo nome normalizado."
        ),
    }
