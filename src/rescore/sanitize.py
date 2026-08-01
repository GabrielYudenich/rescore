"""Remove identifying and free-text metadata from public MusicXML training targets."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from pathlib import Path

from .musicxml import _read_musicxml, _strip_namespaces


def sanitize_musicxml(source: Path, output: Path) -> dict[str, int | str]:
    root = _strip_namespaces(ET.fromstring(_read_musicxml(source)))
    removed = 0
    for tag in ("work", "movement-number", "movement-title", "identification", "credit"):
        for node in list(root.findall(tag)):
            root.remove(node)
            removed += 1
    score_parts = root.findall("./part-list/score-part")
    for index, score_part in enumerate(score_parts, 1):
        for tag in ("part-name", "part-abbreviation"):
            nodes = score_part.findall(tag)
            if nodes:
                nodes[0].text = f"part-{index:04d}"
                for extra in nodes[1:]:
                    score_part.remove(extra)
            else:
                ET.SubElement(score_part, tag).text = f"part-{index:04d}"
        for tag in ("score-instrument", "midi-device", "midi-instrument"):
            for node in list(score_part.findall(tag)):
                score_part.remove(node)
                removed += 1
    for parent in root.iter():
        for child in list(parent):
            if child.tag == "lyric":
                parent.remove(child)
                removed += 1
            elif child.tag in {"words", "rehearsal"}:
                parent.remove(child)
                removed += 1
            elif child.tag == "instrument":
                parent.remove(child)
                removed += 1
    output.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(copy.deepcopy(root))
    ET.indent(tree, space="  ")
    tree.write(output, encoding="utf-8", xml_declaration=True)
    return {"output": str(output.resolve()), "parts": len(score_parts), "removed_text_nodes": removed}
