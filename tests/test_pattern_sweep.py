import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodes.loopers.pattern_sweep import PatternSweep
from nodes.loopers.pattern_sweep_config import PatternSweepConfig


class PatternSweepTests(unittest.TestCase):
    def setUp(self):
        self.node = PatternSweep()

    def test_matches_the_worked_example_step_by_step(self):
        expected = ["1,1,1", "2,1,1", "3,2,1", "1,3,2", "1,1,3"]
        got = [
            self.node.run(pattern="2,3", length=3, identity=1.0, index_in=i, mirror=False)[0]
            for i in range(5)
        ]
        self.assertEqual(got, expected)

    def test_index_past_the_end_is_clamped_to_the_last_step(self):
        last = self.node.run(pattern="2,3", length=3, identity=1.0, index_in=4, mirror=False)[0]
        clamped = self.node.run(pattern="2,3", length=3, identity=1.0, index_in=999, mirror=False)[0]
        self.assertEqual(last, clamped)

    def test_mirror_reverses_entry_order(self):
        weights, _ = self.node.run(pattern="2,3", length=3, identity=1.0, index_in=1, mirror=True)
        self.assertEqual(weights, "3,1,1")


class PatternSweepConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = PatternSweepConfig()
        self.sweep = PatternSweep()

    def test_total_matches_the_sweep_nodes_own_last_step(self):
        pattern, length, identity, mirror, total = self.config.run(
            pattern="2,3", length=3, identity=1.0, mirror=False
        )
        self.assertEqual(total, 5)

        last_via_total = self.sweep.run(pattern, length, identity, total - 1, mirror)[0]
        one_past_total = self.sweep.run(pattern, length, identity, total, mirror)[0]
        self.assertEqual(last_via_total, one_past_total, "total - 1 must already be the final step")
        self.assertEqual(last_via_total, "1,1,3")

    def test_passthrough_values_feed_straight_into_sweep(self):
        pattern, length, identity, mirror, _ = self.config.run(
            pattern="5,7", length=4, identity=0.0, mirror=True
        )
        weights = self.sweep.run(pattern, length, identity, 0, mirror)[0]
        self.assertEqual(weights, "0,0,0,0")


if __name__ == "__main__":
    unittest.main()
