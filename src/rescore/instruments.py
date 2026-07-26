"""Multilingual orchestral instrument names and abbreviations.

The catalog deliberately separates a stable semantic ID from the wording found
in a score.  It is not an OCR model: it normalizes names that the OCR already
read, so French, Portuguese and English labels can be compared safely.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class InstrumentSpec:
    id: str
    name_pt: str
    abbreviation_pt: str
    family: str
    aliases: tuple[str, ...]
    monophonic_player: bool = True


def _spec(
    instrument_id: str,
    name: str,
    abbreviation: str,
    family: str,
    *aliases: str,
    monophonic: bool = True,
) -> InstrumentSpec:
    return InstrumentSpec(
        instrument_id,
        name,
        abbreviation,
        family,
        (name, abbreviation, *aliases),
        monophonic,
    )


INSTRUMENTS = (
    _spec("piccolo", "Flautim", "Flm.", "madeiras", "piccolo", "picc", "petite flute"),
    _spec("flute", "Flauta", "Fl.", "madeiras", "flautas", "flute", "flutes", "flte", "fltes"),
    _spec("oboe", "Oboé", "Ob.", "madeiras", "oboes", "oboe", "hautbois", "htb", "hb"),
    _spec(
        "english_horn",
        "Corne inglês",
        "C. ing.",
        "madeiras",
        "english horn",
        "cor anglais",
        "corno inglese",
        "c ang",
    ),
    _spec(
        "clarinet",
        "Clarinete",
        "Cl.",
        "madeiras",
        "clarinet",
        "clarinets",
        "clarinetes",
        "clarinette",
        "clarinettes",
        "clar",
    ),
    _spec(
        "bass_clarinet",
        "Clarinete baixo",
        "Cl. bx.",
        "madeiras",
        "bass clarinet",
        "clarinette basse",
        "clarone",
        "cl b",
        "clar b",
    ),
    _spec(
        "bassoon",
        "Fagote",
        "Fg.",
        "madeiras",
        "fagotes",
        "bassoon",
        "bassoons",
        "basson",
        "bassons",
        "bn",
    ),
    _spec(
        "contrabassoon",
        "Contrafagote",
        "Cfg.",
        "madeiras",
        "contrabassoon",
        "contrebasson",
        "controfagotto",
        "c bsn",
    ),
    _spec(
        "horn",
        "Trompa",
        "Tpa.",
        "metais",
        "trompas",
        "horn",
        "horns",
        "cor",
        "cors",
        "corno",
        "corni",
        "hn",
    ),
    _spec(
        "trumpet",
        "Trompete",
        "Tpt.",
        "metais",
        "trumpet",
        "trumpets",
        "trompetes",
        "trompette",
        "trompettes",
        "piston",
        "pistons",
        "tromba",
        "trp",
    ),
    _spec("cornet", "Corneta", "Cnt.", "metais", "cornet", "cornets", "corneta", "pistao"),
    _spec("trombone", "Trombone", "Tbn.", "metais", "trombones", "posaune", "posaunen", "trb"),
    _spec(
        "bass_trombone", "Trombone baixo", "Tbn. bx.", "metais", "bass trombone", "trombone basse"
    ),
    _spec("tuba", "Tuba", "Tb.", "metais", "tubas"),
    _spec(
        "timpani",
        "Tímpanos",
        "Timp.",
        "percussão",
        "tímpano",
        "timpano",
        "timpani",
        "timbale",
        "timbales",
        "timp",
        "timb",
    ),
    _spec(
        "percussion", "Percussão", "Perc.", "percussão", "percussion", "bateria", monophonic=False
    ),
    _spec(
        "snare_drum", "Caixa", "Cx.", "percussão", "snare drum", "caisse claire", "tamburo militare"
    ),
    _spec(
        "bass_drum",
        "Bumbo",
        "Bmb.",
        "percussão",
        "bombo",
        "bass drum",
        "grosse caisse",
        "gran cassa",
    ),
    _spec("cymbals", "Pratos", "Pr.", "percussão", "cymbals", "cymbales", "piatti"),
    _spec("tam_tam", "Tam-tam", "T-t.", "percussão", "tam tam", "gong"),
    _spec("maracas", "Maracas", "Mar.", "percussão", "maraca"),
    _spec("triangle", "Triângulo", "Tri.", "percussão", "triangle", "triangolo"),
    _spec("xylophone", "Xilofone", "Xil.", "teclas", "xylophone", "xyl", "xil"),
    _spec("celesta", "Celesta", "Cel.", "teclas", "celeste", "celesta", "cel", monophonic=False),
    _spec("piano", "Piano", "Pno.", "teclas", "pianoforte", "pno", monophonic=False),
    _spec(
        "harp",
        "Harpa",
        "Hpa.",
        "cordas dedilhadas",
        "harp",
        "harps",
        "harpe",
        "harpes",
        "hpe",
        "hp",
        monophonic=False,
    ),
    _spec(
        "violin",
        "Violino",
        "Vln.",
        "cordas",
        "violinos",
        "violin",
        "violins",
        "violon",
        "violons",
        "violini",
        "vl",
        monophonic=False,
    ),
    _spec("viola", "Viola", "Vla.", "cordas", "violas", "alto", "altos", "vla", monophonic=False),
    _spec(
        "cello",
        "Violoncelo",
        "Vlc.",
        "cordas",
        "violoncelos",
        "cello",
        "cellos",
        "violoncelle",
        "violoncelles",
        "violoncello",
        "violoncellos",
        "vcl",
        "vc",
        monophonic=False,
    ),
    _spec(
        "double_bass",
        "Contrabaixo",
        "Cb.",
        "cordas",
        "contrabaixos",
        "double bass",
        "double basses",
        "contrabass",
        "contrabasses",
        "contrebasse",
        "contrebasses",
        "cb",
        monophonic=False,
    ),
    _spec("saxophone", "Saxofone", "Sax.", "madeiras", "saxophone", "saxophones", "sax"),
    _spec("soprano", "Soprano", "S.", "vozes", "sopranos", "soprani", monophonic=False),
    _spec(
        "contralto",
        "Contralto",
        "C.",
        "vozes",
        "contraltos",
        "alto voice",
        "contralti",
        monophonic=False,
    ),
    _spec("tenor", "Tenor", "T.", "vozes", "tenors", "tenori", monophonic=False),
    _spec(
        "baritone",
        "Barítono",
        "Bar.",
        "vozes",
        "baritone",
        "baritones",
        "bariton",
        monophonic=False,
    ),
    _spec("bass_voice", "Baixo", "B.", "vozes", "bass voice", "basses", "bassi", monophonic=False),
    # ``Cor.`` is intentionally not used here: in French orchestral scores it
    # denotes horn (cor), while choir is normally written Coro/Choeur/Choir.
    _spec(
        "choir",
        "Coro",
        "Coro",
        "vozes",
        "choir",
        "chorus",
        "choeur",
        "coro misto",
        monophonic=False,
    ),
)


def normalize_instrument_text(value: str) -> str:
    value = value.replace("♭", "b").replace("♯", " sharp ")
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


_ALIAS_INDEX: dict[str, InstrumentSpec] = {}
for _instrument in INSTRUMENTS:
    for _alias in _instrument.aliases:
        _normalized_alias = normalize_instrument_text(_alias)
        existing = _ALIAS_INDEX.get(_normalized_alias)
        if existing is not None and existing.id != _instrument.id:
            raise RuntimeError(f"alias instrumental ambíguo: {_alias}")
        _ALIAS_INDEX[_normalized_alias] = _instrument


_STAFF_HINTS = {
    "upper": (
        "pauta superior",
        "portee superieure",
        "upper staff",
        "mano destra",
        "main droite",
    ),
    "lower": (
        "pauta inferior",
        "portee inferieure",
        "lower staff",
        "mano sinistra",
        "main gauche",
    ),
}


def _staff_hint(text: str) -> str | None:
    for hint, markers in _STAFF_HINTS.items():
        if any(marker in text for marker in markers):
            return hint
    return None


def _player_suffix(text: str) -> str | None:
    cleaned = _without_qualifiers(text)
    match = re.search(
        r"(?:^|\s)([ivx]+|\d+)(?:\s+(?:(?:a|e|and|et)\s+)?([ivx]+|\d+))?$",
        cleaned,
    )
    if not match:
        return None
    return match.group(1).upper() + (f"-{match.group(2).upper()}" if match.group(2) else "")


def _without_qualifiers(text: str) -> str:
    cleaned = text
    for markers in _STAFF_HINTS.values():
        for marker in markers:
            cleaned = cleaned.replace(marker, " ")
    cleaned = re.sub(r"\b(?:em|in|en)\s+(?:si\s*)?b(?:emol)?\b", " ", cleaned)
    cleaned = re.sub(r"\b(?:em|in|en)\s+f(?:a)?\b", " ", cleaned)
    cleaned = re.sub(r"\((?:si\s*)?b(?:emol)?\)|\(fa\)", " ", cleaned)
    cleaned = re.sub(r"\s+(?:fa|f|si\s+b|bb)\s*$", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _candidate_forms(text: str) -> list[str]:
    forms = [text]
    cleaned = _without_qualifiers(text)
    cleaned = re.sub(r"^\d+\s+", "", cleaned)
    cleaned = re.sub(
        r"(?:\s|^)(?:[ivx]+|\d+)(?:\s*(?:a|e|and|et|-|–)\s*(?:[ivx]+|\d+))?$", "", cleaned
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    forms.append(cleaned)
    return list(dict.fromkeys(form for form in forms if form))


def identify_instrument(label: str) -> dict[str, Any] | None:
    """Return a stable identity for a multilingual score label."""
    segments = [segment.strip() for segment in re.split(r"\s*/\s*", label) if segment.strip()]
    if len(segments) > 1:
        first = identify_instrument(segments[0])
        if first is not None:
            return {**first, "source": label}
    normalized = normalize_instrument_text(label)
    hint = _staff_hint(normalized)
    players = _player_suffix(normalized)
    for form in _candidate_forms(normalized):
        instrument = _ALIAS_INDEX.get(form)
        if instrument is not None:
            result = asdict(instrument)
            result.update(
                {
                    "source": label,
                    "normalized": normalized,
                    "matched_alias": form,
                    "staff_hint": hint,
                    "players": players,
                    "confidence": 1.0,
                }
            )
            return result
    # OCR often leaves a qualifier adjacent to a valid long alias. Restrict
    # fallback matching to aliases with at least three characters/words.
    matches: list[tuple[int, InstrumentSpec, str]] = []
    for alias, instrument in _ALIAS_INDEX.items():
        if len(alias) < 3:
            continue
        if re.search(rf"(?:^|\s){re.escape(alias)}(?:\s|$)", normalized):
            matches.append((len(alias), instrument, alias))
    if not matches:
        return None
    _, instrument, alias = max(matches, key=lambda item: item[0])
    result = asdict(instrument)
    result.update(
        {
            "source": label,
            "normalized": normalized,
            "matched_alias": alias,
            "staff_hint": hint,
            "players": players,
            "confidence": 0.85,
        }
    )
    return result


def identify_instruments(label: str) -> list[dict[str, Any]]:
    """Resolve every instrument in a slash-separated doubling/switch label."""
    segments = [segment.strip() for segment in re.split(r"\s*/\s*", label) if segment.strip()]
    identities = []
    for segment in segments or [label]:
        identity = identify_instrument(segment)
        known_ids = {item["id"] for item in identities}
        if identity is not None and identity["id"] not in known_ids:
            identities.append(identity)
    return identities


def canonical_instrument_label(label: str) -> str:
    segments = [segment.strip() for segment in re.split(r"\s*/\s*", label) if segment.strip()]
    if len(segments) > 1:
        canonical_segments = [canonical_instrument_label(segment) for segment in segments]
        if all(identify_instrument(segment) is not None for segment in segments):
            return " / ".join(canonical_segments)
    identity = identify_instrument(label)
    if identity is None:
        return label.strip()
    canonical = identity["name_pt"]
    if identity.get("players"):
        canonical += f" {identity['players']}"
    if identity.get("staff_hint") == "upper":
        canonical += " — pauta superior"
    elif identity.get("staff_hint") == "lower":
        canonical += " — pauta inferior"
    return canonical


def instrument_catalog() -> list[dict[str, Any]]:
    return [asdict(instrument) for instrument in INSTRUMENTS]
