"""Regression test for a report that an Unbundler inside a subgraph produced
None for every output (surfacing several nodes downstream as "missing CLIP").

Root cause: the Unbundler's 'keys' input was exposed through the subgraph
boundary and left unconnected outside, so the frontend's widget-promotion
defaulted it to the bare number 0 instead of "". parse_keys()'s `if not keys`
check treated 0 as empty (0 is falsy in Python) and silently returned no keys
at all, discarding every value in the bundle.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests._stub_comfy_api import install

install()

from nodes.bundling._bundle_type import parse_keys


class ParseKeysFalsyValueTests(unittest.TestCase):
    def test_numeric_zero_is_not_treated_as_a_key(self):
        # Must not raise, and must not silently become key "0" or key "".
        self.assertEqual(parse_keys(0), [])

    def test_none_is_empty(self):
        self.assertEqual(parse_keys(None), [])

    def test_empty_string_is_empty(self):
        self.assertEqual(parse_keys(""), [])

    def test_normal_string_still_parses(self):
        self.assertEqual(parse_keys("MODEL, CLIP, VAE"), ["MODEL", "CLIP", "VAE"])


if __name__ == "__main__":
    unittest.main()
