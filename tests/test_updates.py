import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from rescore.updates import create_signed_manifest, install_update, rollback_update


def test_signed_update_install_and_rollback(tmp_path) -> None:
    key = Ed25519PrivateKey.generate()
    model = tmp_path / "model.onnx"
    model.write_bytes(b"new model")
    manifest = create_signed_manifest(model, version="2026.1", private_key=key)
    current = tmp_path / "current.onnx"
    current.write_bytes(b"old model")
    result = install_update(model, manifest, current, key.public_key())
    assert result["version"] == "2026.1"
    assert current.read_bytes() == b"new model"
    assert rollback_update(current)
    assert current.read_bytes() == b"old model"


def test_signed_update_rejects_tampering(tmp_path) -> None:
    key = Ed25519PrivateKey.generate()
    model = tmp_path / "model.onnx"
    model.write_bytes(b"model")
    manifest = create_signed_manifest(model, version="1", private_key=key)
    model.write_bytes(b"tampered")
    with pytest.raises(ValueError):
        install_update(model, manifest, tmp_path / "current.onnx", key.public_key())
