from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rescore.musicxml import parse_musicxml  # noqa: E402


def candidate_for(page: int) -> Path:
    if page == 13:
        return ROOT / "output/movement1-omr-13/audiveris/page-0013.mxl"
    folder = ROOT / "output/movement1-omr-pages" / f"page-{page:04d}" / "audiveris"
    return next(folder.glob("*.mxl"))


def main() -> int:
    first_measure = 38
    inventory = []
    for page in range(13, 42):
        path = candidate_for(page)
        score = parse_musicxml(path)
        measure_count = max(
            [event["measure_index"] for event in score["events"]]
            + [int(part.get("measures", 0)) for part in score["parts"]]
        )
        parts = []
        for part in score["parts"]:
            parts.append(
                {
                    "id": part["id"],
                    "name": part["name"],
                    "events": sum(
                        event["part_id"] == part["id"] for event in score["events"]
                    ),
                }
            )
        inventory.append(
            {
                "page": page,
                "first_measure": first_measure,
                "last_measure": first_measure + measure_count - 1,
                "measure_count": measure_count,
                "parts": parts,
                "candidate": str(path.resolve()),
            }
        )
        first_measure += measure_count
    output = ROOT / "output/movement1-page-inventory.json"
    output.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    print("final measure", first_measure - 1)
    for item in inventory:
        names = ", ".join(part["name"] for part in item["parts"])
        print(
            f"p{item['page']}: m{item['first_measure']}-{item['last_measure']} "
            f"({item['measure_count']}), {names}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
