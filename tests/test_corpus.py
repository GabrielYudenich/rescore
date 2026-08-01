import json

import fitz

from rescore.corpus import build_anonymous_inventory


def test_inventory_separates_private_names_from_public_manifest(tmp_path) -> None:
    source = tmp_path / "Secret Composer" / "Private Work"
    source.mkdir(parents=True)
    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "private title")
    pdf.save(source / "named score.pdf")
    output = tmp_path / "inventory"
    report = build_anonymous_inventory(tmp_path / "Secret Composer", output)
    manifest = json.loads((output / "public-inventory.json").read_text())
    public_text = (output / "public-inventory.json").read_text()
    assert "Secret Composer" not in public_text
    assert "Private Work" not in public_text
    assert "named score" not in public_text
    assert manifest["files"][0]["training_eligible"] is False
    assert report["summary"]["files"] == 1
    private = json.loads((output / "private-map.json").read_text())
    assert "named score.pdf" in private["files"][0]["path"]
