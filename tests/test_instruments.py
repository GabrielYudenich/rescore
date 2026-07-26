from rescore.instruments import (
    canonical_instrument_label,
    identify_instrument,
    identify_instruments,
)


def test_multilingual_instrument_names_are_canonicalized() -> None:
    cases = {
        "Célesta — portée inférieure": ("celesta", "Celesta — pauta inferior"),
        "2 Flûtes": ("flute", "Flauta"),
        "Hautbois": ("oboe", "Oboé"),
        "4 Pistons (Si♭)": ("trumpet", "Trompete"),
        "Altos": ("viola", "Viola"),
        "Vcl.": ("cello", "Violoncelo"),
    }
    for source, (instrument_id, canonical) in cases.items():
        identity = identify_instrument(source)
        assert identity is not None
        assert identity["id"] == instrument_id
        assert canonical_instrument_label(source) == canonical


def test_player_numbers_are_preserved_after_tonality_qualifier() -> None:
    identity = identify_instrument("Cors 1-2 (Fa)")
    assert identity is not None
    assert identity["id"] == "horn"
    assert identity["players"] == "1-2"
    assert canonical_instrument_label("Cors 1-2 (Fa)") == "Trompa 1-2"


def test_ambiguous_cor_abbreviation_defaults_to_french_horn() -> None:
    identity = identify_instrument("Cor. 3")
    assert identity is not None
    assert identity["id"] == "horn"
    assert identity["players"] == "3"


def test_doubling_label_preserves_both_instruments_and_players() -> None:
    source = "Flauta III / Piccolo I"
    assert [item["id"] for item in identify_instruments(source)] == ["flute", "piccolo"]
    assert canonical_instrument_label(source) == "Flauta III / Flautim I"


def test_portuguese_plurals_and_score_percussion_are_recognized() -> None:
    cases = {
        "Tímpano": "timpani",
        "Bombo": "bass_drum",
        "Maracas": "maracas",
        "Violinos 1": "violin",
        "Violoncelos": "cello",
        "Contrabaixos": "double_bass",
    }
    for source, instrument_id in cases.items():
        identity = identify_instrument(source)
        assert identity is not None
        assert identity["id"] == instrument_id
