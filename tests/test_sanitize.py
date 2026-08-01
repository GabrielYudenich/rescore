from rescore.musicxml import parse_musicxml
from rescore.sanitize import sanitize_musicxml


def test_sanitize_musicxml_removes_names_credits_lyrics_and_words(tmp_path) -> None:
    source = tmp_path / "secret.xml"
    source.write_text(
        """<?xml version="1.0"?><score-partwise version="4.0">
<work><work-title>Secret Work</work-title></work><movement-title>Secret Movement</movement-title>
<identification><creator>Secret Person</creator></identification><credit><credit-words>Secret</credit-words></credit>
<part-list><score-part id="P1"><part-name>Named Instrument</part-name><score-instrument id="I1"><instrument-name>Named Instrument</instrument-name></score-instrument></score-part></part-list>
<part id="P1"><measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
<direction><direction-type><words>private note</words><dynamics><f/></dynamics></direction-type></direction>
<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><lyric><text>secret lyric</text></lyric></note>
</measure></part></score-partwise>""",
        encoding="utf-8",
    )
    output = tmp_path / "public.musicxml"
    result = sanitize_musicxml(source, output)
    text = output.read_text()
    assert "Secret" not in text and "private note" not in text and "secret lyric" not in text
    assert "part-0001" in text and "<f" in text
    assert parse_musicxml(output)["parts_count"] == 1
    assert result["removed_text_nodes"] >= 6
