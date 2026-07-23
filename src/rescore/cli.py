from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .mscz import inspect_mscz
from .musicxml import compare_scores, parse_musicxml, write_canonical
from .normalize import build_normalized_musicxml
from .pdf import pdf_info, render_pages
from .pipeline import convert
from .tooling import doctor


def _json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rescore",
        description="Converte partituras PDF em MusicXML/MuseScore e compara com um gabarito.",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="verifica as ferramentas externas")

    inspect_parser = subparsers.add_parser("inspect-mscz", help="inspeciona um arquivo .mscz")
    inspect_parser.add_argument("path", type=Path)

    render_parser = subparsers.add_parser("render", help="renderiza páginas do PDF")
    render_parser.add_argument("pdf", type=Path)
    render_parser.add_argument("--pages", required=True)
    render_parser.add_argument("--output", type=Path, default=Path("output/pages"))
    render_parser.add_argument("--dpi", type=int, default=300)

    canonical_parser = subparsers.add_parser(
        "canonicalize", help="converte MusicXML/MXL em JSON semântico"
    )
    canonical_parser.add_argument("path", type=Path)
    canonical_parser.add_argument("--output", type=Path)
    canonical_parser.add_argument("--include-rests", action="store_true")

    compare_parser = subparsers.add_parser("compare", help="compara dois MusicXML/MXL")
    compare_parser.add_argument("reference", type=Path)
    compare_parser.add_argument("candidate", type=Path)
    compare_parser.add_argument("--output", type=Path)

    normalize_parser = subparsers.add_parser(
        "normalize-scherzo", help="expande o OMR condensado para o modelo orquestral"
    )
    normalize_parser.add_argument("candidate", type=Path)
    normalize_parser.add_argument("template", type=Path)
    normalize_parser.add_argument("--output", type=Path, default=Path("output/normalized.musicxml"))

    convert_parser = subparsers.add_parser("convert", help="executa o pipeline completo")
    convert_parser.add_argument("pdf", type=Path)
    convert_parser.add_argument("--pages", required=True)
    convert_parser.add_argument("--output", type=Path, default=Path("output/conversion"))
    convert_parser.add_argument("--reference", type=Path)
    convert_parser.add_argument("--reference-mscz", type=Path)
    convert_parser.add_argument(
        "--meter",
        help="trava todos os compassos, por exemplo 4/4 ou 9/8 (usado sem --reference)",
    )
    convert_parser.add_argument(
        "--omr-dpi", type=int, default=450, help="resolução da imagem enviada ao OMR"
    )
    convert_parser.add_argument(
        "--force", action="store_true", help="refaz o OMR mesmo quando já existe um .mxl"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = args.project_root.resolve()
    try:
        if args.command == "doctor":
            result = doctor(project_root)
        elif args.command == "inspect-mscz":
            result = inspect_mscz(args.path)
        elif args.command == "render":
            result = {
                "pdf": pdf_info(args.pdf),
                "rendered": [
                    str(path.resolve())
                    for path in render_pages(args.pdf, args.pages, args.output, args.dpi)
                ],
            }
        elif args.command == "canonicalize":
            result = parse_musicxml(args.path, include_rests=args.include_rests)
            if args.output:
                write_canonical(result, args.output)
        elif args.command == "compare":
            result = compare_scores(parse_musicxml(args.reference), parse_musicxml(args.candidate))
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
        elif args.command == "normalize-scherzo":
            result = build_normalized_musicxml(args.candidate, args.template, args.output)
        elif args.command == "convert":
            result = convert(
                project_root,
                args.pdf,
                args.pages,
                args.output,
                args.reference,
                args.force,
                args.reference_mscz,
                args.omr_dpi,
                args.meter,
            )
        else:
            parser.error(f"comando desconhecido: {args.command}")
            return 2
    except Exception as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    _json(result)
    return 0
