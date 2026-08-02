"""Structural privacy checks for artifacts intended to be committed publicly."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

FORBIDDEN_KEYS = {
    "path",
    "source_path",
    "thumbnail",
    "filename",
    "file_name",
    "composer",
    "work",
    "title",
    "creator",
    "author",
}
ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:home|Users|mnt|tmp)/)")


def audit_public_json(path: Path, forbidden_terms: list[str] | None = None) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    violations: list[dict[str, str]] = []
    terms = [term.casefold() for term in (forbidden_terms or []) if len(term.strip()) >= 3]

    def visit(value: Any, location: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_location = f"{location}.{key}"
                if key.casefold() in FORBIDDEN_KEYS:
                    violations.append({"location": child_location, "reason": "forbidden-key"})
                visit(child, child_location)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{location}[{index}]")
        elif isinstance(value, str):
            if ABSOLUTE_PATH.search(value):
                violations.append({"location": location, "reason": "absolute-path"})
            folded = value.casefold()
            for term in terms:
                if term in folded:
                    violations.append(
                        {"location": location, "reason": f"forbidden-term:{term}"}
                    )

    visit(payload, "$")
    return {
        "valid": not violations,
        "path": str(path.resolve()),
        "violations": violations,
    }
