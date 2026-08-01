"""Create self-contained MusicXML measure slices with inherited attributes."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from pathlib import Path

from .musicxml import _read_musicxml, _strip_namespaces


def slice_musicxml(source: Path, output: Path, start: int, end: int) -> dict[str, int | str]:
    if start < 1 or end < start:
        raise ValueError("intervalo de compassos inválido")
    root = _strip_namespaces(ET.fromstring(_read_musicxml(source)))
    parts = root.findall("part")
    for part in parts:
        measures = list(part.findall("measure"))
        if end > len(measures):
            raise ValueError(f"partitura possui somente {len(measures)} compassos")
        inherited = ET.Element("attributes")
        for measure in measures[:start]:
            attributes = measure.find("attributes")
            if attributes is not None:
                for child in attributes:
                    identity = (child.tag, child.get("number"))
                    for existing in list(inherited):
                        if (existing.tag, existing.get("number")) == identity:
                            inherited.remove(existing)
                    inherited.append(copy.deepcopy(child))
        selected = measures[start - 1 : end]
        for measure in measures:
            part.remove(measure)
        for measure in selected:
            part.append(measure)
        if len(inherited) and selected:
            selected[0].insert(0, inherited)
    output.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(output, encoding="utf-8", xml_declaration=True)
    return {"output": str(output.resolve()), "parts": len(parts), "start": start, "end": end}
