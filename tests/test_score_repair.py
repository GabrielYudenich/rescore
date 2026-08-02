from __future__ import annotations

import xml.etree.ElementTree as ET

from rescore.score_repair import parse_meter_changes, repair_score_structure


def test_repairs_meter_map_redundant_clefs_and_empty_measures(tmp_path):
    source = tmp_path / "source.musicxml"
    output = tmp_path / "repaired.musicxml"
    source.write_text(
        """<?xml version="1.0"?>
<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>P</part-name></score-part></part-list>
<part id="P1">
  <measure number="1"><attributes><divisions>4</divisions><clef><sign>G</sign><line>2</line></clef></attributes></measure>
  <measure number="2"><attributes><clef><sign>G</sign><line>2</line></clef></attributes></measure>
  <measure number="3"><attributes><clef><sign>F</sign><line>4</line></clef></attributes></measure>
</part></score-partwise>""",
        encoding="utf-8",
    )

    result = repair_score_structure(source, output, {1: (4, 4), 2: (3, 4), 3: (4, 4)})

    root = ET.parse(output).getroot()
    assert [
        (time.findtext("beats"), time.findtext("beat-type")) for time in root.findall(".//time")
    ] == [("4", "4"), ("3", "4"), ("4", "4")]
    assert len(root.findall(".//clef")) == 2
    assert len(root.findall(".//rest[@measure='yes']")) == 3
    assert result["redundant_clefs_removed"] == 1


def test_parse_meter_changes():
    assert parse_meter_changes(["39=4/4", "5=3/4", "1=4/4"]) == {
        1: (4, 4),
        5: (3, 4),
        39: (4, 4),
    }
