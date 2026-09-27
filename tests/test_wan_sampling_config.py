import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodes.sampling.wan_sampling_config import WanSamplingConfig


class WanSamplingConfigTests(unittest.TestCase):
    def setUp(self):
        self.node = WanSamplingConfig()
        self.image = torch.zeros((1, 480, 832, 3))

    def test_reports_image_dimensions(self):
        width, height, _total_steps, _boundary_step = self.node.run(self.image, 20, 0.2)
        self.assertEqual((width, height), (832, 480))

    def test_boundary_step_splits_by_ratio(self):
        _w, _h, total_steps, boundary_step = self.node.run(self.image, 20, 0.2)
        self.assertEqual(total_steps, 20)
        self.assertEqual(boundary_step, 4)

    def test_boundary_step_rounds_to_nearest_int(self):
        _w, _h, _total_steps, boundary_step = self.node.run(self.image, 10, 0.25)
        self.assertEqual(boundary_step, round(10 * 0.25))

    def test_ratio_zero_is_all_low_noise(self):
        _w, _h, _total_steps, boundary_step = self.node.run(self.image, 20, 0.0)
        self.assertEqual(boundary_step, 0)

    def test_ratio_one_is_all_high_noise(self):
        _w, _h, total_steps, boundary_step = self.node.run(self.image, 20, 1.0)
        self.assertEqual(boundary_step, total_steps)


if __name__ == "__main__":
    unittest.main()
