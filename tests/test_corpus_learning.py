import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from rescore.corpus_learning import (
    build_visual_curriculum,
    rebalance_visual_curriculum,
    validate_visual_curriculum,
)


class CorpusLearningTests(unittest.TestCase):
    def test_builds_anonymous_group_safe_curriculum(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            for index in range(6):
                group, slope = f"secret-{index}", index * 5
                folder = source / group
                folder.mkdir(parents=True)
                image = Image.new("RGB", (800, 1000), "white")
                draw = ImageDraw.Draw(image)
                for y in range(100, 900, 80):
                    draw.line((50, y, 750, y + slope), fill="black", width=2)
                image.save(folder / "named-score.jpg")
            output = root / "output"
            result = build_visual_curriculum(source, output, clusters=2)
            public = json.loads((output / "visual-curriculum.json").read_text())
            serialized = json.dumps(public)
            self.assertNotIn("secret-0", serialized)
            self.assertNotIn("named-score", serialized)
            self.assertEqual(result["summary"]["samples"], 6)
            self.assertEqual(len({item["style_cluster"] for item in public["samples"]}), 2)
            for group_id in {item["group_id"] for item in public["samples"]}:
                self.assertEqual(
                    len({item["split"] for item in public["samples"] if item["group_id"] == group_id}),
                    1,
                )
            self.assertTrue(validate_visual_curriculum(output / "visual-curriculum.json")["valid"])
            self.assertTrue(rebalance_visual_curriculum(output / "visual-curriculum.json")["valid"])
            cached = build_visual_curriculum(source, output, clusters=2)
            self.assertEqual(cached["summary"]["cached_documents"], 6)


if __name__ == "__main__":
    unittest.main()
