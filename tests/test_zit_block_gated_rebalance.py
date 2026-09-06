"""Regression test for the double_block_patch closure state tracking.

comfy/ldm/lumina/model.py captures `img_input` once, before the block loop
starts, and passes that same (pre-block-0) tensor to every block's patch call
- it is not "this block's own input". Using it directly as `block_in` for a
weight of 0 ("skip the block") would revert all the way back to the original
pre-DiT embedding, discarding every prior block's work instead of passing
through the previous block's actual output. See ZitBlockGatedRebalance's
docstring for the full explanation.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodes.model.zit_block_gated_rebalance import ZitBlockGatedRebalance


class FakeModel:
    """Just enough of ModelPatcher's interface for run() to capture the patch."""

    def clone(self):
        return self

    def set_model_double_block_patch(self, patch):
        self.patch = patch


def run_sequence(node, early, mid, late, multiplier=1.0):
    model = FakeModel()
    node.run(model, early, mid, late, multiplier, crossover=0.0, overlap=0.0)

    img_input = 0  # comfy's fixed, pre-block-0 reference value
    effective = []
    for i in range(30):
        raw_out = i + 1  # this block's own (unpatched) layer output
        out = model.patch({"block_index": i, "img": raw_out, "img_input": img_input})
        effective.append(out.get("img", raw_out))
    return effective


class DoubleBlockPatchStateTests(unittest.TestCase):
    def test_all_weights_one_is_a_true_no_op(self):
        node = ZitBlockGatedRebalance()
        ones = "1,1,1,1,1,1,1,1,1,1"
        effective = run_sequence(node, ones, ones, ones)
        self.assertEqual(effective, [i + 1 for i in range(30)])

    def test_skipping_a_block_passes_through_the_previous_block_not_img_input(self):
        node = ZitBlockGatedRebalance()
        mid = "0,1,1,1,1,1,1,1,1,1"  # block 10 (first "mid" block) weight = 0
        effective = run_sequence(node, "1,1,1,1,1,1,1,1,1,1", mid, "1,1,1,1,1,1,1,1,1,1")

        # Block 9 is untouched (weight 1), so its effective output is its raw output.
        self.assertEqual(effective[9], 10)
        # Skipping block 10 must reproduce block 9's real output, not img_input (0).
        self.assertEqual(effective[10], effective[9])
        self.assertNotEqual(effective[10], 0)


if __name__ == "__main__":
    unittest.main()
