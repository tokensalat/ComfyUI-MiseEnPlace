"""Regression test for _blend_weights' generalized identity: the same
crossover/overlap smooth-step blend must relax toward 1.0 for 'multiply' mode
and toward 0.0 for 'add' mode, since each mode has a different no-op value.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodes.conditioning.zit_conditioning_rebalance import ZitConditioningRebalance


class BlendIdentityTests(unittest.TestCase):
    def setUp(self):
        self.node = ZitConditioningRebalance()

    def test_crossover_zero_applies_weights_in_full_regardless_of_mode(self):
        weights = [0.2, 5.0, -1.0]
        for identity in (1.0, 0.0):
            blended = self.node._blend_weights(weights, crossover=0.0, overlap=0.0, identity=identity)
            for got, want in zip(blended, weights):
                self.assertAlmostEqual(got, want)

    def test_unreachable_crossover_relaxes_every_band_to_each_modes_own_identity(self):
        # crossover past 1.0 means no position (which ranges 0..1) ever reaches it,
        # so every band falls into the overlap<=0 "not yet crossed" branch: blend=0.
        weights = [0.2, 5.0, -1.0]
        multiply_blended = self.node._blend_weights(weights, crossover=2.0, overlap=0.0, identity=1.0)
        add_blended = self.node._blend_weights(weights, crossover=2.0, overlap=0.0, identity=0.0)

        self.assertEqual(multiply_blended, [1.0, 1.0, 1.0])
        self.assertEqual(add_blended, [0.0, 0.0, 0.0])

    def test_empty_weights_pass_through_for_either_identity(self):
        self.assertEqual(self.node._blend_weights([], crossover=0.5, overlap=0.5, identity=1.0), [])
        self.assertEqual(self.node._blend_weights([], crossover=0.5, overlap=0.5, identity=0.0), [])


if __name__ == "__main__":
    unittest.main()
