"""Anonymous intake inventory for local score corpora."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fitz
from PIL import Image

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".mxl", ".musicxml", ".mscz"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inspect(path: Path) -> dict[str, Any]:
    suffix = path.suffix.casefold()
    record: dict[str, Any] = {"media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream"}
    if suffix == ".pdf":
        with fitz.open(path) as document:
            record.update(
                pages=document.page_count,
                encrypted=bool(document.needs_pass),
                text_pages=sum(len(page.get_text().strip()) > 30 for page in document),
                image_pages=sum(bool(page.get_images(full=True)) for page in document),
            )
    elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        with Image.open(path) as image:
            record.update(width=image.width, height=image.height, mode=image.mode)
    return record


def build_anonymous_inventory(source: Path, output: Path) -> dict[str, Any]:
    """Write a public name-free inventory and a separate private local mapping."""
    source, output = source.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    groups: dict[str, str] = {}
    public_files, private_files = [], []
    for path in sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.casefold() in SUPPORTED):
        relative = path.relative_to(source)
        group_key = relative.parts[0] if len(relative.parts) > 1 else "_root"
        group_id = groups.setdefault(group_key, f"grp-{uuid.uuid4().hex}")
        digest = _sha256(path)
        public_files.append(
            {
                "content_id": f"sha256:{digest}",
                "group_id": group_id,
                "bytes": path.stat().st_size,
                "inspection": _inspect(path),
                "review_state": "unreviewed",
                "training_eligible": False,
            }
        )
        private_files.append({"content_id": f"sha256:{digest}", "group_id": group_id, "path": str(path)})
    counts = Counter(item["content_id"] for item in public_files)
    manifest = {
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "files": public_files,
        "summary": {
            "files": len(public_files),
            "unique_contents": len(counts),
            "duplicate_files": sum(count - 1 for count in counts.values()),
            "groups": len(groups),
            "training_eligible": 0,
        },
    }
    (output / "public-inventory.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    private = {"schema_version": "1.0", "groups": groups, "files": private_files}
    (output / "private-map.json").write_text(
        json.dumps(private, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "summary": manifest["summary"],
        "public_inventory": str(output / "public-inventory.json"),
        "private_map": str(output / "private-map.json"),
    }
