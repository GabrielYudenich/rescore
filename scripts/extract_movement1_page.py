from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rescore.pipeline import extract_omr_candidate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("page", type=int)
    parser.add_argument("--dpi", type=int, default=450)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    pdf = next(ROOT.glob("HVL*.pdf"))
    output = ROOT / "output" / "movement1-omr-pages" / f"page-{args.page:04d}"
    candidate = extract_omr_candidate(
        ROOT,
        pdf,
        str(args.page),
        output,
        force=args.force,
        omr_dpi=args.dpi,
    )
    print(candidate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
