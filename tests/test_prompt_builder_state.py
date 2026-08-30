"""Regression test for a report that a section added on one queue run could
not be found by 'modify' on a later run ("no section named 'subject' to
modify"), even though it had just been added.

Reproduces the exact pair of documents from the report against the same node
identity across two separate execute() calls, the way two separate queue runs
against the same PromptBuilder node would. Uses _stub_comfy_api so this runs
without the real ComfyUI/torch stack.
"""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests._stub_comfy_api import install

install()

import nodes.prompting.prompt_builder as prompt_builder


class TwoRunPersistenceTests(unittest.TestCase):
    NODE_ID = "test-node-prompt-builder"

    def setUp(self):
        self.PB = prompt_builder.PromptBuilder
        # Simulates what ComfyUI sets before calling execute(): the same node
        # in the graph keeps the same unique_id across separate queue runs.
        self.PB.hidden = SimpleNamespace(unique_id=self.NODE_ID)
        prompt_builder._STATE.pop(f"__node_{self.NODE_ID}", None)

    def test_modify_after_add_across_two_runs_same_node(self):
        add_doc = json.dumps([
            {"section": "style", "op": "add", "position": 0, "content": "Impasto oil painting"},
            {"section": "subject", "op": "add", "position": 1, "content": "A weathered stone gargoyle"},
            {"section": "action", "op": "add", "position": 2, "content": "It crouches forward"},
            {"section": "environment", "op": "add", "position": 3, "content": "A crumbling Gothic cathedral spire"},
            {"section": "lighting", "op": "add", "position": 4, "content": "The dying light of dusk"},
            {"section": "palette_mood", "op": "add", "position": 5, "content": "Charcoal grey and indigo"},
            {"section": "finish", "op": "add", "position": 6, "content": "Rich impasto brushstrokes"},
        ])
        result = self.PB.execute(prompt_json=add_doc, prompt_id="", max_history=50, reset=False, strict=True)
        _, _, _, _, sections_json = result.args
        self.assertIn("subject", json.loads(sections_json))

        modify_doc = json.dumps([
            {"section": "subject", "op": "modify", "content": "A young woman in a crimson traveling cloak"},
        ])
        # strict=True: "no section named 'subject' to modify" would raise
        # instead of just being printed, so the bug (if present) fails this
        # test loudly rather than leaving stale content in place unnoticed.
        result2 = self.PB.execute(prompt_json=modify_doc, prompt_id="", max_history=50, reset=False, strict=True)
        _, _, _, _, sections_json2 = result2.args
        sections = json.loads(sections_json2)

        self.assertEqual(len(sections), 7, "the other six sections must survive untouched")
        self.assertEqual(sections["subject"]["content"], "A young woman in a crimson traveling cloak")

    def test_strict_defaults_on_so_a_bad_operation_halts_instead_of_continuing(self):
        modify_doc = json.dumps([
            {"section": "subject", "op": "modify", "content": "anything"},
        ])
        # No strict= kwarg at all - relies on execute()'s own default, which
        # must be True: an error should stop the run, not print a warning and
        # pass the old (in this case empty) prompt through as if nothing
        # happened.
        with self.assertRaises(ValueError):
            self.PB.execute(prompt_json=modify_doc, prompt_id="")

    def test_non_bool_reset_raises_instead_of_being_treated_as_truthy(self):
        # Reproduces the actual reported incident: a saved node whose
        # widgets_values drifted out of sync with the current schema (a
        # removed field shifted every later value one slot) fed max_history's
        # old value (50) into 'reset'. bool(50) is True, which would have
        # silently wiped the standing prompt on every run - this must raise
        # instead of coercing.
        add_doc = json.dumps([
            {"section": "subject", "op": "add", "position": 0, "content": "x"},
        ])
        with self.assertRaises(TypeError):
            self.PB.execute(prompt_json=add_doc, prompt_id="", max_history=50, reset=50, strict=True)

    def test_non_bool_strict_raises(self):
        add_doc = json.dumps([
            {"section": "subject", "op": "add", "position": 0, "content": "x"},
        ])
        with self.assertRaises(TypeError):
            self.PB.execute(prompt_json=add_doc, prompt_id="", max_history=50, reset=False, strict="false")


if __name__ == "__main__":
    unittest.main()
