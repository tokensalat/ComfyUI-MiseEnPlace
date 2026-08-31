"""Regression test for a report that wiring Buffer Read straight into an
IMAGE-typed node (Preview Image) crashed deep inside ComfyUI's own
save_images with a cryptic "'NoneType' object is not subscriptable" instead
of a clear error, because Buffer Read silently returns None when nothing has
been stored yet and no 'default' is wired in.

Uses _stub_comfy_api so this runs without the real ComfyUI/torch stack. A
plain string stands in for an "image" here - the bug isn't about tensors, it's
about a bare None reaching a node that assumes it always gets real data.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests._stub_comfy_api import install

install()

import nodes.feedback._buffer_state as buffer_state
import nodes.feedback.buffer_read as buffer_read

BufferRead = buffer_read.BufferRead


class BufferReadMissingDefaultTests(unittest.TestCase):
    HANDLE = "test-handle-image"

    def setUp(self):
        buffer_state.clear(self.HANDLE)

    def test_raises_instead_of_returning_none_when_unset_and_no_default(self):
        # First run of a feedback loop: nothing has ever been written for this
        # handle, and the user didn't wire a default image - previously this
        # returned None and let a downstream node like Preview Image crash on
        # it far from the real cause.
        with self.assertRaises(ValueError):
            BufferRead.execute(handle=self.HANDLE, default=None, reset=False)

    def test_raises_after_reset_with_no_default(self):
        buffer_state.write(self.HANDLE, "a stored image")
        with self.assertRaises(ValueError):
            BufferRead.execute(handle=self.HANDLE, default=None, reset=True)

    def test_default_is_used_when_unset(self):
        result = BufferRead.execute(handle=self.HANDLE, default="placeholder image", reset=False)
        self.assertEqual(result.args[0], "placeholder image")

    def test_stored_value_wins_over_default_once_written(self):
        buffer_state.write(self.HANDLE, "a stored image")
        result = BufferRead.execute(handle=self.HANDLE, default="placeholder image", reset=False)
        self.assertEqual(result.args[0], "a stored image")


if __name__ == "__main__":
    unittest.main()
