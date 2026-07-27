from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from rescore.community import validate_contribution


def create_app(root: Path | None = None) -> FastAPI:
    storage = (root or Path(os.environ.get("RESCORE_HUB_DATA", "data/community-hub"))).resolve()
    blobs = storage / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    database = storage / "hub.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS contributions (id TEXT PRIMARY KEY, status TEXT NOT NULL, "
            "created_at TEXT NOT NULL, manifest TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS blob_refs (sha256 TEXT NOT NULL, contribution_id TEXT NOT NULL, "
            "bytes INTEGER NOT NULL, PRIMARY KEY (sha256, contribution_id))"
        )
    app = FastAPI(title="ReScore Community Learning Hub", version="1.0.0")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "protocol_version": "1.0"}

    @app.post("/v1/contributions", status_code=202)
    async def contribution(request: Request) -> dict:
        manifest = await request.json()
        errors = validate_contribution(manifest)
        if errors:
            raise HTTPException(422, {"invalid_fields": errors})
        contribution_id = manifest["contribution_id"]
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(database) as connection:
            existing = connection.execute(
                "SELECT manifest FROM contributions WHERE id = ?", (contribution_id,)
            ).fetchone()
            serialized = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
            if existing and existing[0] != serialized:
                raise HTTPException(409, "contribution_id already has different content")
            connection.execute(
                "INSERT OR IGNORE INTO contributions VALUES (?, 'quarantined', ?, ?)",
                (contribution_id, now, serialized),
            )
            for record in manifest["blobs"]:
                connection.execute(
                    "INSERT OR IGNORE INTO blob_refs VALUES (?, ?, ?)",
                    (record["sha256"], contribution_id, int(record.get("bytes", 0))),
                )
        missing = [r["sha256"] for r in manifest["blobs"] if not (blobs / r["sha256"]).is_file()]
        return {"contribution_id": contribution_id, "status": "quarantined", "missing_blobs": missing}

    @app.post("/v1/blobs/{expected_sha256}", status_code=201)
    async def upload_blob(expected_sha256: str, request: Request) -> dict:
        if len(expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_sha256):
            raise HTTPException(400, "invalid sha256")
        with sqlite3.connect(database) as connection:
            reference = connection.execute(
                "SELECT MAX(bytes) FROM blob_refs WHERE sha256 = ?", (expected_sha256,)
            ).fetchone()
        if not reference or reference[0] is None:
            raise HTTPException(404, "blob was not requested by an accepted contribution")
        declared_size = int(reference[0])
        if declared_size < 1 or declared_size > 25 * 1024 * 1024:
            raise HTTPException(413, "blob size is outside the accepted range")
        data = await request.body()
        if len(data) != declared_size:
            raise HTTPException(422, "blob size differs from contribution metadata")
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected_sha256:
            raise HTTPException(422, "sha256 mismatch")
        destination = blobs / actual
        if not destination.exists():
            temporary = blobs / f".{actual}.tmp"
            temporary.write_bytes(data)
            os.replace(temporary, destination)
        return {"sha256": actual, "bytes": len(data)}

    @app.get("/v1/contributions/{contribution_id}")
    def status(contribution_id: str) -> dict:
        with sqlite3.connect(database) as connection:
            row = connection.execute(
                "SELECT status, created_at FROM contributions WHERE id = ?", (contribution_id,)
            ).fetchone()
        if not row:
            raise HTTPException(404, "contribution not found")
        return {"contribution_id": contribution_id, "status": row[0], "created_at": row[1]}

    @app.post("/v1/admin/contributions/{contribution_id}/decision")
    async def decide(contribution_id: str, request: Request) -> dict:
        configured = os.environ.get("RESCORE_HUB_ADMIN_TOKEN", "")
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not configured or not secrets.compare_digest(configured, supplied):
            raise HTTPException(403, "administrative promotion is disabled or unauthorized")
        body = await request.json()
        decision = body.get("decision")
        if decision not in {"accepted", "rejected", "withdrawn"}:
            raise HTTPException(422, "invalid decision")
        with sqlite3.connect(database) as connection:
            row = connection.execute(
                "SELECT manifest FROM contributions WHERE id = ?", (contribution_id,)
            ).fetchone()
            if not row:
                raise HTTPException(404, "contribution not found")
            manifest = json.loads(row[0])
            missing = [r["sha256"] for r in manifest["blobs"] if not (blobs / r["sha256"]).is_file()]
            if decision == "accepted" and missing:
                raise HTTPException(409, {"missing_blobs": missing})
            connection.execute(
                "UPDATE contributions SET status = ? WHERE id = ?", (decision, contribution_id)
            )
        return {"contribution_id": contribution_id, "status": decision}

    return app


app = create_app()
