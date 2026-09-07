import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodes.formatting.json_array_to_lines import JsonArrayToLines


class JsonArrayToLinesTests(unittest.TestCase):
    def setUp(self):
        self.node = JsonArrayToLines()

    def test_joins_string_elements_with_newline(self):
        lines, count = self.node.run('["a", "b", "c"]', 0)
        self.assertEqual(lines, "a\nb\nc")
        self.assertEqual(count, 3)

    def test_skip_drops_leading_elements(self):
        lines, count = self.node.run('["a", "b", "c"]', 2)
        self.assertEqual(lines, "c")
        self.assertEqual(count, 1)

    def test_skip_past_the_end_yields_empty(self):
        lines, count = self.node.run('["a", "b"]', 5)
        self.assertEqual(lines, "")
        self.assertEqual(count, 0)

    def test_non_string_elements_are_json_serialized(self):
        lines, count = self.node.run('[1, true, {"k": 1}, null]', 0)
        self.assertEqual(lines, "1\ntrue\n{\"k\": 1}\nnull")
        self.assertEqual(count, 4)

    def test_invalid_json_returns_empty_instead_of_raising(self):
        lines, count = self.node.run("not json", 0)
        self.assertEqual((lines, count), ("", 0))

    def test_non_array_json_returns_empty_instead_of_raising(self):
        lines, count = self.node.run('{"a": 1}', 0)
        self.assertEqual((lines, count), ("", 0))


if __name__ == "__main__":
    unittest.main()
