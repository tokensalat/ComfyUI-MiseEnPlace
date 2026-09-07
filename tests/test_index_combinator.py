import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodes.combinators.index_combinator import IndexCombinator


class IndexCombinatorTests(unittest.TestCase):
    def setUp(self):
        self.node = IndexCombinator()

    def test_walks_b_fastest_like_a_nested_loop(self):
        # total_a=2, total_b=3 -> (0,0)(0,1)(0,2)(1,0)(1,1)(1,2)
        expected = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]
        got = [self.node.run(2, 3, k)[:2] for k in range(6)]
        self.assertEqual(got, expected)

    def test_total_is_the_product(self):
        _, _, total, _ = self.node.run(2, 3, 0)
        self.assertEqual(total, 6)

    def test_index_past_the_end_is_clamped_to_the_last_step(self):
        last = self.node.run(2, 3, 5)[:2]
        clamped = self.node.run(2, 3, 999)[:2]
        self.assertEqual(last, clamped)


if __name__ == "__main__":
    unittest.main()
