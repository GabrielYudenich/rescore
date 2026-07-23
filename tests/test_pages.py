import unittest

from rescore.pages import compact_page_spec, parse_page_spec


class PageSpecTests(unittest.TestCase):
    def test_parse_and_compact(self):
        pages = parse_page_spec("67,70-72,68")
        self.assertEqual(pages, [67, 68, 70, 71, 72])
        self.assertEqual(compact_page_spec(pages), "67-68,70-72")

    def test_rejects_invalid_range(self):
        with self.assertRaises(ValueError):
            parse_page_spec("4-2")


if __name__ == "__main__":
    unittest.main()
