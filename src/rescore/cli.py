from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .alignment import align_dataset_item, validate_alignment
from .dataset import (
    add_pair,
    initialize_dataset,
    validate_dataset,
    write_public_catalog,
)
from .hardware import inspect_hardware
from .mscz import inspect_mscz
from .musicxml import compare_scores, parse_musicxml, write_canonical
from .normalize import build_normalized_musicxml
from .pdf import pdf_info, render_pages
from .pipeline import convert
from .staff_alignment import align_dataset_staffs, validate_staff_alignment
from .tooling import doctor
from .training_export import export_training_samples, validate_training_export


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
    subparsers.add_parser(
        "hardware",
        help="mostra RAM, GPU, VRAM e capacidade aproximada de treinamento",
    )

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

    dataset_init = subparsers.add_parser(
        "dataset-init",
        help="cria um dataset local versionado para treinamento",
    )
    dataset_init.add_argument("path", type=Path)
    dataset_init.add_argument("--id", required=True, dest="dataset_id")
    dataset_init.add_argument("--name", required=True)
    dataset_init.add_argument(
        "--annotation-license",
        default="CC-BY-4.0",
        help="licença padrão das transcrições e correções",
    )

    dataset_add = subparsers.add_parser(
        "dataset-add",
        help="adiciona imagens e um gabarito MSCZ/MusicXML ao dataset",
    )
    dataset_add.add_argument("path", type=Path)
    dataset_add.add_argument("--id", required=True, dest="item_id")
    dataset_add.add_argument("--images", type=Path, nargs="+", required=True)
    dataset_add.add_argument("--score", type=Path, required=True)
    dataset_add.add_argument("--composer", required=True)
    dataset_add.add_argument("--work", required=True)
    dataset_add.add_argument(
        "--source-type",
        choices=("printed", "handwritten", "mixed"),
        required=True,
    )
    dataset_add.add_argument(
        "--visibility",
        choices=("public", "private"),
        required=True,
    )
    dataset_add.add_argument("--rights-status", required=True)
    dataset_add.add_argument("--source-license", required=True)
    dataset_add.add_argument(
        "--redistributable",
        action="store_true",
        help="confirma que a fonte pode ser redistribuída",
    )
    dataset_add.add_argument("--measure-start", type=int, required=True)
    dataset_add.add_argument("--measure-end", type=int, required=True)
    dataset_add.add_argument(
        "--verification",
        choices=(
            "human-transcribed",
            "human-reviewed",
            "partially-reviewed",
            "machine-generated",
        ),
        required=True,
    )
    dataset_add.add_argument(
        "--alignment-status",
        choices=("verified", "inferred", "unassigned"),
        default="unassigned",
    )
    dataset_add.add_argument("--writer", default="")
    dataset_add.add_argument("--notes", default="")

    dataset_validate = subparsers.add_parser(
        "dataset-validate",
        help="valida proveniência, privacidade, arquivos e checksums",
    )
    dataset_validate.add_argument("path", type=Path)
    dataset_validate.add_argument("--skip-hashes", action="store_true")

    dataset_catalog = subparsers.add_parser(
        "dataset-public-catalog",
        help="gera catálogo contendo somente itens públicos",
    )
    dataset_catalog.add_argument("path", type=Path)
    dataset_catalog.add_argument("--output", type=Path, required=True)

    dataset_align = subparsers.add_parser(
        "dataset-align",
        help="propõe regiões de compassos nas imagens de um item",
    )
    dataset_align.add_argument("path", type=Path)
    dataset_align.add_argument("--id", required=True, dest="item_id")
    dataset_align.add_argument(
        "--page-measures",
        help="compassos por imagem, por exemplo 8,8",
    )
    dataset_align.add_argument("--force", action="store_true")

    alignment_validate = subparsers.add_parser(
        "alignment-validate",
        help="valida cobertura e caixas de um measure-regions.json",
    )
    alignment_validate.add_argument("path", type=Path)

    dataset_align_staffs = subparsers.add_parser(
        "dataset-align-staffs",
        help="propõe pautas visuais, instrumentos e células compasso × pauta",
    )
    dataset_align_staffs.add_argument("path", type=Path)
    dataset_align_staffs.add_argument("--id", required=True, dest="item_id")
    dataset_align_staffs.add_argument(
        "--profile",
        choices=("auto", "menina-opening", "choros9-opening"),
        default="auto",
    )
    dataset_align_staffs.add_argument("--force", action="store_true")

    staff_alignment_validate = subparsers.add_parser(
        "staff-alignment-validate",
        help="valida pautas e células de um staff-regions.json",
    )
    staff_alignment_validate.add_argument("path", type=Path)

    dataset_export_training = subparsers.add_parser(
        "dataset-export-training",
        help="exporta recortes compasso × pauta e alvos MusicXML determinísticos",
    )
    dataset_export_training.add_argument("path", type=Path)
    dataset_export_training.add_argument("--id", required=True, dest="item_id")
    dataset_export_training.add_argument("--force", action="store_true")

    training_export_validate = subparsers.add_parser(
        "training-export-validate",
        help="valida imagens, tokens e checksums de um samples.jsonl",
    )
    training_export_validate.add_argument("path", type=Path)
    training_export_validate.add_argument("--skip-hashes", action="store_true")
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
        elif args.command == "hardware":
            result = inspect_hardware(project_root)
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
        elif args.command == "dataset-init":
            result = initialize_dataset(
                args.path,
                dataset_id=args.dataset_id,
                name=args.name,
                default_annotation_license=args.annotation_license,
            )
        elif args.command == "dataset-add":
            result = add_pair(
                project_root,
                args.path,
                item_id=args.item_id,
                images=args.images,
                score=args.score,
                composer=args.composer,
                work=args.work,
                source_type=args.source_type,
                visibility=args.visibility,
                rights_status=args.rights_status,
                source_license=args.source_license,
                redistributable=args.redistributable,
                measure_start=args.measure_start,
                measure_end=args.measure_end,
                verification=args.verification,
                alignment_status=args.alignment_status,
                writer=args.writer,
                notes=args.notes,
            )
        elif args.command == "dataset-validate":
            result = validate_dataset(args.path, verify_hashes=not args.skip_hashes)
        elif args.command == "dataset-public-catalog":
            result = write_public_catalog(args.path, args.output)
        elif args.command == "dataset-align":
            result = align_dataset_item(
                args.path,
                item_id=args.item_id,
                page_measures=args.page_measures,
                force=args.force,
            )
        elif args.command == "alignment-validate":
            result = validate_alignment(args.path)
        elif args.command == "dataset-align-staffs":
            result = align_dataset_staffs(
                args.path,
                item_id=args.item_id,
                profile=args.profile,
                force=args.force,
            )
        elif args.command == "staff-alignment-validate":
            result = validate_staff_alignment(args.path)
        elif args.command == "dataset-export-training":
            result = export_training_samples(
                args.path,
                item_id=args.item_id,
                force=args.force,
            )
        elif args.command == "training-export-validate":
            result = validate_training_export(args.path, verify_hashes=not args.skip_hashes)
        else:
            parser.error(f"comando desconhecido: {args.command}")
            return 2
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports friendly errors.
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    _json(result)
    return 0
