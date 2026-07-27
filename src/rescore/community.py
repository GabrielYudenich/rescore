"""Safe, opt-in contribution packages for the community learning hub."""

from __future__ import annotations

import hashlib
import json
import shutil
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .dataset import DatasetError

PROTOCOL_VERSION = "1.0"
ALLOWED_VERIFICATION = {"human-reviewed", "human-transcribed"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_contribution(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("protocol_version") != PROTOCOL_VERSION:
        errors.append("protocol_version")
    rights = manifest.get("rights", {})
    if rights.get("redistributable") is not True:
        errors.append("rights.redistributable")
    if not str(rights.get("source_license", "")).strip():
        errors.append("rights.source_license")
    if not str(rights.get("annotation_license", "")).strip():
        errors.append("rights.annotation_license")
    if manifest.get("verification") not in ALLOWED_VERIFICATION:
        errors.append("verification")
    consent = manifest.get("consent", {})
    if consent.get("share_for_training") is not True:
        errors.append("consent.share_for_training")
    if consent.get("confirmed_at") is None:
        errors.append("consent.confirmed_at")
    blobs = manifest.get("blobs")
    if not isinstance(blobs, list) or not blobs:
        errors.append("blobs")
    else:
        for record in blobs:
            if not isinstance(record, dict) or len(str(record.get("sha256", ""))) != 64:
                errors.append("blobs.sha256")
                break
            if record.get("role") not in {"image", "target", "prediction", "metadata"}:
                errors.append("blobs.role")
                break
    return errors


def prepare_contribution(
    output: Path,
    *,
    files: list[tuple[str, Path]],
    source_license: str,
    annotation_license: str,
    verification: str,
    contributor: str = "anonymous",
) -> dict[str, Any]:
    """Create a local-only package after an explicit caller confirmation."""
    if verification not in ALLOWED_VERIFICATION:
        raise DatasetError("somente transcrições conferidas podem ser compartilhadas")
    output = output.resolve()
    if output.exists():
        raise DatasetError(f"pacote já existe: {output}")
    blob_dir = output / "blobs"
    blob_dir.mkdir(parents=True)
    blobs = []
    for role, source in files:
        source = source.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        digest = _sha256(source)
        destination = blob_dir / digest
        if not destination.exists():
            shutil.copy2(source, destination)
        blobs.append({"role": role, "sha256": digest, "bytes": source.stat().st_size})
    now = _now()
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "contribution_id": str(uuid.uuid4()),
        "created_at": now,
        "contributor": contributor.strip() or "anonymous",
        "verification": verification,
        "rights": {
            "redistributable": True,
            "source_license": source_license.strip(),
            "annotation_license": annotation_license.strip(),
        },
        "consent": {"share_for_training": True, "confirmed_at": now},
        "privacy": {"contains_local_paths": False, "contains_personal_data": False},
        "blobs": blobs,
    }
    errors = validate_contribution(manifest)
    if errors:
        raise DatasetError(f"contribuição inválida: {', '.join(errors)}")
    (output / "contribution.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def submit_contribution(package: Path, endpoint: str, *, timeout: float = 30) -> dict[str, Any]:
    """Submit metadata then only the missing content-addressed blobs."""
    package = package.resolve()
    manifest = json.loads((package / "contribution.json").read_text(encoding="utf-8"))
    errors = validate_contribution(manifest)
    if errors:
        raise DatasetError(f"contribuição inválida: {', '.join(errors)}")

    def request(path: str, data: bytes, content_type: str) -> dict[str, Any]:
        req = urllib.request.Request(
            endpoint.rstrip("/") + path,
            data=data,
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise DatasetError(f"hub recusou a contribuição: HTTP {exc.code}") from exc

    accepted = request(
        "/v1/contributions",
        json.dumps(manifest).encode(),
        "application/json",
    )
    for digest in accepted.get("missing_blobs", []):
        blob = package / "blobs" / digest
        result = request(f"/v1/blobs/{digest}", blob.read_bytes(), "application/octet-stream")
        if result.get("sha256") != digest:
            raise DatasetError("hub não confirmou o hash do blob")
    return accepted
