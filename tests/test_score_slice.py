from rescore.musicxml import parse_musicxml
from rescore.score_slice import slice_musicxml


def test_slice_carries_inherited_divisions_and_time(tmp_path) -> None:
    source = tmp_path / "source.xml"
    source.write_text(
        """<score-partwise><part-list><score-part id="P1"><part-name>P</part-name></score-part></part-list>
<part id="P1"><measure number="1"><attributes><divisions>60</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes><note><rest/><duration>240</duration></note></measure>
<measure number="2"><note><pitch><step>C</step><octave>4</octave></pitch><duration>60</duration></note></measure></part></score-partwise>"""
    )
    output = tmp_path / "slice.xml"
    slice_musicxml(source, output, 2, 2)
    score = parse_musicxml(output)
    assert score["events"][0]["duration"] == "1"
    assert score["time_signatures"][0]["beats"] == "4"
