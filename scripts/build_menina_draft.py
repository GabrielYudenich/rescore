from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rescore.manuscript import recognize_menina_image_directory
from rescore.mscz import set_page_layout, validate_meter_map_mscz
from rescore.pipeline import convert_with_musescore
from rescore.tooling import find_musescore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconhece as quatro fotos iniciais de A Menina das Nuvens e gera "
            "uma partitura contínua conservadora em MusicXML, MuseScore e PDF A3."
        )
    )
    parser.add_argument("images", type=Path, help="pasta contendo exatamente quatro imagens")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "output" / "menina-das-nuvens-manuscript",
    )
    parser.add_argument("--homr", type=Path, help="caminho opcional para homr.exe")
    parser.add_argument("--force", action="store_true", help="refaz os recortes e o OMR")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    result = recognize_menina_image_directory(
        PROJECT_ROOT,
        args.images,
        output,
        homr_path=args.homr,
        force=args.force,
    )
    musescore = find_musescore(PROJECT_ROOT)
    if musescore is None:
        raise FileNotFoundError("MuseScore não encontrado; execute `rescore doctor`")
    mscz = output / "menina-das-nuvens-draft.mscz"
    convert_with_musescore(
        musescore,
        result["musicxml"],
        mscz,
        output / "musescore-mscz.log",
    )
    layout = set_page_layout(
        mscz,
        paper="A3",
        landscape=True,
        margin_inches=0.35,
        spatium_mm=0.52,
    )
    validation = validate_meter_map_mscz(
        mscz,
        {1: (2, 4), 19: (3, 4), 22: (2, 4)},
        26,
    )
    validation_path = output / "musescore-validation.json"
    validation_path.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not validation["valid"]:
        raise RuntimeError(
            "o MuseScore alterou a duração de uma ou mais vozes; "
            f"consulte {validation_path}"
        )
    pdf = output / "menina-das-nuvens-draft-A3.pdf"
    convert_with_musescore(
        musescore,
        mscz,
        pdf,
        output / "musescore-pdf.log",
    )
    manifest = {
        "input": str(args.images.resolve()),
        "artifacts": {
            "musicxml": str(result["musicxml"].resolve()),
            "musescore": str(mscz.resolve()),
            "pdf": str(pdf.resolve()),
            "report": str(result["report"].resolve()),
            "validation": str(validation_path.resolve()),
        },
        "layout": layout,
        "summary": result["summary"],
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest["artifacts"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
