from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from rescore.community import prepare_contribution, validate_contribution
from rescore.dataset import DatasetError
from rescore_hub.app import create_app


def test_prepare_contribution_contains_no_local_paths(tmp_path) -> None:
    image = tmp_path / "private-name.png"
    target = tmp_path / "private-score.musicxml"
    image.write_bytes(b"image")
    target.write_bytes(b"score")
    package = tmp_path / "package"
    manifest = prepare_contribution(
        package,
        files=[("image", image), ("target", target)],
        source_license="CC0-1.0",
        annotation_license="CC-BY-4.0",
        verification="human-reviewed",
    )
    serialized = json.dumps(manifest)
    assert str(tmp_path) not in serialized
    assert "private-name" not in serialized
    assert validate_contribution(manifest) == []
    assert len(list((package / "blobs").iterdir())) == 2


def test_prepare_refuses_machine_generated_truth(tmp_path) -> None:
    source = tmp_path / "score.xml"
    source.write_text("x")
    with pytest.raises(DatasetError):
        prepare_contribution(
            tmp_path / "package",
            files=[("target", source)],
            source_license="CC0-1.0",
            annotation_license="CC-BY-4.0",
            verification="machine-generated",
        )


def test_hub_quarantines_metadata_and_verifies_blob(tmp_path, monkeypatch) -> None:
    data = b"verified sample"
    digest = hashlib.sha256(data).hexdigest()
    manifest = {
        "protocol_version": "1.0",
        "contribution_id": "12345678-1234-1234-1234-123456789abc",
        "verification": "human-reviewed",
        "rights": {
            "redistributable": True,
            "source_license": "CC0-1.0",
            "annotation_license": "CC-BY-4.0",
        },
        "consent": {"share_for_training": True, "confirmed_at": "2026-01-01T00:00:00Z"},
        "blobs": [{"role": "target", "sha256": digest, "bytes": len(data)}],
    }
    client = TestClient(create_app(tmp_path / "hub"))
    response = client.post("/v1/contributions", json=manifest)
    assert response.status_code == 202
    assert response.json()["missing_blobs"] == [digest]
    assert client.post(f"/v1/blobs/{digest}", content=b"tampered").status_code == 422
    assert client.post(f"/v1/blobs/{digest}", content=data).status_code == 201
    repeated = client.post("/v1/contributions", json=manifest)
    assert repeated.json()["missing_blobs"] == []
    status = client.get(f"/v1/contributions/{manifest['contribution_id']}").json()
    assert status["status"] == "quarantined"
    assert client.post(
        f"/v1/admin/contributions/{manifest['contribution_id']}/decision",
        json={"decision": "accepted"},
    ).status_code == 403
    monkeypatch.setenv("RESCORE_HUB_ADMIN_TOKEN", "secret")
    promoted = client.post(
        f"/v1/admin/contributions/{manifest['contribution_id']}/decision",
        json={"decision": "accepted"},
        headers={"Authorization": "Bearer secret"},
    )
    assert promoted.json()["status"] == "accepted"


def test_hub_rejects_non_redistributable_contribution(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "hub"))
    response = client.post(
        "/v1/contributions",
        json={"protocol_version": "1.0", "rights": {"redistributable": False}},
    )
    assert response.status_code == 422
