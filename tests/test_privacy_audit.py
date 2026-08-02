import tempfile
import unittest
from pathlib import Path

from rescore.privacy_audit import audit_public_json


class PrivacyAuditTests(unittest.TestCase):
    def test_rejects_paths_keys_and_terms_recursively(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "public.json"
            path.write_text(
                '{"safe": [{"path": "C:\\\\Users\\\\person\\\\score.pdf"}], "text": "Secret Work"}',
                encoding="utf-8",
            )
            report = audit_public_json(path, ["secret work"])
            self.assertFalse(report["valid"])
            reasons = {item["reason"] for item in report["violations"]}
            self.assertIn("forbidden-key", reasons)
            self.assertIn("absolute-path", reasons)
            self.assertIn("forbidden-term:secret work", reasons)


if __name__ == "__main__":
    unittest.main()
