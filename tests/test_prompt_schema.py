"""Pure-logic regression tests for nodes/prompting/_prompt_schema.py.

No ComfyUI/torch dependency - merge() and parse_document() only touch json.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodes.prompting._prompt_schema import merge, parse_document


class MergeSequentialRunsTests(unittest.TestCase):
    """A document parsed and merged in one call, then a second document
    merged against the first call's output - the shape of two separate
    queue runs threading state through PromptBuilder.execute().
    """

    def test_modify_after_add_in_separate_merge_calls(self):
        ops1, errors1 = parse_document(json.dumps([
            {"section": "subject", "op": "add", "position": 0, "content": "a lighthouse keeper"},
        ]))
        self.assertEqual(errors1, [])
        sections, changes1, errors2 = merge([], ops1)
        self.assertEqual(errors2, [])
        self.assertEqual(changes1["added"], ["subject"])

        ops2, errors3 = parse_document(json.dumps([
            {"section": "subject", "op": "modify", "content": "a lighthouse keeper reading by lamplight"},
        ]))
        self.assertEqual(errors3, [])
        sections2, changes2, errors4 = merge(sections, ops2)
        self.assertEqual(errors4, [])
        self.assertEqual(changes2["modified"], ["subject"])
        self.assertEqual(sections2[0]["content"], "a lighthouse keeper reading by lamplight")

    def test_modify_is_case_and_whitespace_insensitive(self):
        sections, _, errors1 = merge([], [
            {"op": "add", "name": "Subject", "content": "x", "position": 0},
        ])
        self.assertEqual(errors1, [])
        sections2, changes, errors2 = merge(sections, [
            {"op": "modify", "name": "  subject ", "content": "y", "position": None},
        ])
        self.assertEqual(errors2, [])
        self.assertEqual(changes["modified"], ["Subject"])
        self.assertEqual(sections2[0]["content"], "y")

    def test_modify_against_a_genuinely_empty_prompt_reports_error(self):
        # The correct behaviour when the section really isn't there - kept as
        # a control alongside the "it should succeed" cases above, so a
        # regression that makes modify silently no-op would also be caught.
        _, _, errors = merge([], [
            {"op": "modify", "name": "subject", "content": "y", "position": None},
        ])
        self.assertEqual(errors, ["no section named 'subject' to modify"])

    def test_seven_section_add_then_modify_one(self):
        """The exact shape of a reported bug: add several sections, then
        modify one of them in a later call. All others must survive untouched.
        """
        names = ["style", "subject", "action", "environment", "lighting", "palette_mood", "finish"]
        add_ops, errors = parse_document(json.dumps([
            {"section": name, "op": "add", "position": i, "content": f"{name} content"}
            for i, name in enumerate(names)
        ]))
        self.assertEqual(errors, [])
        sections, _, errors = merge([], add_ops)
        self.assertEqual(errors, [])
        self.assertEqual([s["name"] for s in sections], names)

        modify_ops, errors = parse_document(json.dumps([
            {"section": "subject", "op": "modify", "content": "a young woman in a crimson cloak"},
        ]))
        self.assertEqual(errors, [])
        sections2, changes, errors = merge(sections, modify_ops)
        self.assertEqual(errors, [])
        self.assertEqual(changes["modified"], ["subject"])
        by_name = {s["name"]: s["content"] for s in sections2}
        self.assertEqual(by_name["subject"], "a young woman in a crimson cloak")
        for name in names:
            if name != "subject":
                self.assertEqual(by_name[name], f"{name} content")


if __name__ == "__main__":
    unittest.main()
