"""Signed, atomic model update manifests with rollback."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def create_signed_manifest(
    artifact: Path, *, version: str, private_key: Ed25519PrivateKey
) -> dict[str, Any]:
    artifact = artifact.resolve()
    payload = {
        "schema_version": "1.0",
        "version": version,
        "artifact": {
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "bytes": artifact.stat().st_size,
            "filename": artifact.name,
        },
    }
    return {**payload, "signature": base64.b64encode(private_key.sign(_canonical(payload))).decode()}


def verify_signed_manifest(manifest: dict[str, Any], public_key: Ed25519PublicKey) -> None:
    signature = manifest.get("signature")
    if not isinstance(signature, str):
        raise ValueError("manifesto sem assinatura")
    payload = {key: value for key, value in manifest.items() if key != "signature"}
    public_key.verify(base64.b64decode(signature, validate=True), _canonical(payload))


def install_update(
    artifact: Path, manifest: dict[str, Any], destination: Path, public_key: Ed25519PublicKey
) -> dict[str, str | None]:
    verify_signed_manifest(manifest, public_key)
    artifact = artifact.resolve()
    expected = manifest["artifact"]
    if artifact.stat().st_size != expected["bytes"]:
        raise ValueError("tamanho do modelo não corresponde ao manifesto")
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != expected["sha256"]:
        raise ValueError("hash do modelo não corresponde ao manifesto")
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    previous = destination.with_suffix(destination.suffix + ".previous")
    temporary = destination.with_suffix(destination.suffix + ".new")
    shutil.copy2(artifact, temporary)
    if destination.exists():
        os.replace(destination, previous)
    os.replace(temporary, destination)
    return {
        "version": manifest["version"],
        "installed": str(destination),
        "rollback": str(previous) if previous.exists() else None,
    }


def rollback_update(destination: Path) -> bool:
    destination = destination.resolve()
    previous = destination.with_suffix(destination.suffix + ".previous")
    if not previous.is_file():
        return False
    failed = destination.with_suffix(destination.suffix + ".failed")
    if destination.exists():
        os.replace(destination, failed)
    os.replace(previous, destination)
    return True
