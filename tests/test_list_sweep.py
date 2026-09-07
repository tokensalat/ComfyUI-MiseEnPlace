import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodes.loopers.list_sweep import ListSweep


class ListSweepTests(unittest.TestCase):
    def setUp(self):
        self.node = ListSweep()

    def test_picks_the_item_at_index(self):
        item, total, status = self.node.run("a,b,c", ",", 1)
        self.assertEqual(item, "b")
        self.assertEqual(total, 3)

    def test_strips_whitespace_and_drops_empty_tokens(self):
        item, total, _ = self.node.run(" a , , b ", ",", 1)
        self.assertEqual(item, "b")
        self.assertEqual(total, 2)

    def test_custom_delimiter_is_unescaped(self):
        item, total, _ = self.node.run("a\nb\nc", "\\n", 2)
        self.assertEqual(item, "c")
        self.assertEqual(total, 3)

    def test_index_past_the_end_is_clamped(self):
        last = self.node.run("a,b,c", ",", 2)[0]
        clamped = self.node.run("a,b,c", ",", 999)[0]
        self.assertEqual(last, clamped)

    def test_empty_list_does_not_crash(self):
        item, total, status = self.node.run("", ",", 0)
        self.assertEqual((item, total), ("", 0))


if __name__ == "__main__":
    unittest.main()
