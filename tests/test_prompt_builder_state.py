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


class ResetRebuildStabilityTests(unittest.TestCase):
    """Regression test for a report that the version number (and a new history
    entry) kept incrementing on every run even though the upstream LLM's
    prompt_json was confirmed byte-identical run to run.

    Root cause: with reset=True, `standing` is forced to [] before merge()
    runs, so every section in the rebuilt document shows up in changes["added"]
    regardless of whether the end result matches what was already standing -
    `any(changes.values())` can never be False in that case, so the old gate
    (`reset or any(changes.values())`) always recorded a new version whenever
    reset was on, no matter what the document actually said.
    """

    NODE_ID = "test-node-prompt-builder-reset-rebuild"

    def setUp(self):
        self.PB = prompt_builder.PromptBuilder
        self.PB.hidden = SimpleNamespace(unique_id=self.NODE_ID)
        prompt_builder._STATE.pop(f"__node_{self.NODE_ID}", None)

    def test_resending_the_same_full_document_via_reset_does_not_bump_version(self):
        doc = json.dumps([
            {"section": "subject", "op": "add", "position": 0, "content": "a lighthouse keeper"},
            {"section": "style", "op": "add", "position": 1, "content": "35mm film"},
        ])

        first = self.PB.execute(prompt_json=doc, prompt_id="", max_history=50, reset=True, strict=True)
        _, _, _, first_version, _ = first.args

        # Same document, same reset=True - simulating an LLM re-emitting the
        # identical full prompt state on the next queue run.
        second = self.PB.execute(prompt_json=doc, prompt_id="", max_history=50, reset=True, strict=True)
        text2, _, _, second_version, sections_json2 = second.args

        self.assertEqual(first_version, second_version, "an identical resend must not bump the version")
        self.assertEqual(len(json.loads(sections_json2)), 2, "the sections must still be there, not wiped")
        self.assertIn("lighthouse keeper", text2)

    def test_resending_via_reset_with_genuinely_different_content_still_records(self):
        first_doc = json.dumps([{"section": "subject", "op": "add", "position": 0, "content": "a fox"}])
        second_doc = json.dumps([{"section": "subject", "op": "add", "position": 0, "content": "a wolf"}])

        self.PB.execute(prompt_json=first_doc, prompt_id="", max_history=50, reset=True, strict=True)
        # Each genuine reset restarts its own version numbering at 1, so two
        # separate resets both landing on version 1 is expected - the thing
        # that must hold is that the second, different document actually took
        # effect rather than being wrongly treated as "no change".
        second = self.PB.execute(prompt_json=second_doc, prompt_id="", max_history=50, reset=True, strict=True)
        text2, _, _, second_version, sections_json2 = second.args

        self.assertEqual(second_version, 1, "a genuine reset+change must record (not carry_forward)")
        self.assertIn("a wolf", text2)
        self.assertNotIn("a fox", text2)


class DeleteThenReaddStabilityTests(unittest.TestCase):
    """Regression test for the reset=False case of the same underlying bug:
    an LLM that always represents its (possibly unchanged) desired prompt as
    delete-then-re-add per section - since `modify` can never reposition a
    section, delete+add is the only way to express "this section belongs
    here" without assuming it wasn't already there. A plain re-`add` on an
    untouched section is caught by merge()'s identical-content check, but
    delete-then-add isn't: by the time the `add` runs, the section was just
    deleted, so there's nothing to compare its content against - each
    individual op is seen as a real change even when the net result is not.
    """

    NODE_ID = "test-node-prompt-builder-delete-readd"

    def setUp(self):
        self.PB = prompt_builder.PromptBuilder
        self.PB.hidden = SimpleNamespace(unique_id=self.NODE_ID)
        prompt_builder._STATE.pop(f"__node_{self.NODE_ID}", None)

    def test_delete_then_readd_to_the_same_content_does_not_bump_version(self):
        add_doc = json.dumps([{"section": "subject", "op": "add", "position": 0, "content": "a fox"}])
        first = self.PB.execute(prompt_json=add_doc, prompt_id="", max_history=50, reset=False, strict=True)
        _, _, _, first_version, _ = first.args

        rebuild_doc = json.dumps([
            {"section": "subject", "op": "delete"},
            {"section": "subject", "op": "add", "position": 0, "content": "a fox"},
        ])
        second = self.PB.execute(prompt_json=rebuild_doc, prompt_id="", max_history=50, reset=False, strict=True)
        text2, _, _, second_version, sections_json2 = second.args

        self.assertEqual(first_version, second_version, "net-unchanged delete+readd must not bump the version")
        self.assertIn("a fox", text2)
        self.assertEqual(len(json.loads(sections_json2)), 1)


class FingerprintStabilityTests(unittest.TestCase):
    """Regression test for a report that a PromptBuilder feeding a Bundler/
    Unbundler chain kept re-executing (and retriggering everything downstream,
    e.g. CLIP Text Encode) on a requeue with a completely unchanged prompt_json.

    Root cause: fingerprint_inputs() used to key on the general `revision`
    counter, which execute()'s own _record() call bumps as a side effect of
    running. The cache key for run N is computed (and stored) against
    revision-before-N, but the very next queue's cache-check reads
    revision-after-N (already bumped) - guaranteeing a mismatch, and therefore
    a spurious re-execution, exactly one queue after any real edit even with
    byte-identical inputs both times.
    """

    NODE_ID = "test-node-prompt-builder-fingerprint"

    def setUp(self):
        self.PB = prompt_builder.PromptBuilder
        self.PB.hidden = SimpleNamespace(unique_id=self.NODE_ID)
        self.pid = f"__node_{self.NODE_ID}"
        prompt_builder._STATE.pop(self.pid, None)

    def _fingerprint(self, prompt_json):
        return self.PB.fingerprint_inputs(
            prompt_json=prompt_json, prompt_id="", max_history=50, reset=False, strict=True
        )

    def test_fingerprint_unchanged_by_a_real_execute_in_between(self):
        doc = json.dumps([{"section": "subject", "op": "add", "position": 0, "content": "x"}])

        before = self._fingerprint(doc)
        self.PB.execute(prompt_json=doc, prompt_id="", max_history=50, reset=False, strict=True)
        after = self._fingerprint(doc)

        self.assertEqual(before, after, "a normal execute() must not change its own next fingerprint")

    def test_fingerprint_changes_after_an_out_of_band_restore(self):
        first_doc = json.dumps([{"section": "subject", "op": "add", "position": 0, "content": "x"}])
        second_doc = json.dumps([{"section": "subject", "op": "modify", "content": "y"}])

        self.PB.execute(prompt_json=first_doc, prompt_id="", max_history=50, reset=False, strict=True)
        self.PB.execute(prompt_json=second_doc, prompt_id="", max_history=50, reset=False, strict=True)

        fp_before_restore = self._fingerprint(first_doc)
        payload, status = prompt_builder.restore(self.pid, 1)
        self.assertEqual(status, 200)
        fp_after_restore = self._fingerprint(first_doc)

        self.assertNotEqual(
            fp_before_restore, fp_after_restore,
            "restoring an old version must invalidate the cache even though prompt_json didn't change",
        )

    def test_fingerprint_stable_across_differently_worded_no_op_resends(self):
        """A resend that nets to no change must fingerprint the same even when its
        raw text differs, or ComfyUI's cache treats it as a change anyway - and
        since a downstream node's cache key is built from its ancestors'
        fingerprints, not their actual output values, that cascades a spurious
        re-execution to everything reading this node's output.
        """
        add_doc = json.dumps([{"section": "subject", "op": "add", "position": 0, "content": "a fox"}])
        self.PB.execute(prompt_json=add_doc, prompt_id="", max_history=50, reset=False, strict=True)

        # Same net result, worded as delete-then-readd instead of a plain resend.
        delete_readd_doc = json.dumps([
            {"section": "subject", "op": "delete"},
            {"section": "subject", "op": "add", "position": 0, "content": "a fox"},
        ])

        self.assertEqual(
            self._fingerprint(add_doc), self._fingerprint(delete_readd_doc),
            "two documents that both leave the prompt unchanged must fingerprint the same",
        )


if __name__ == "__main__":
    unittest.main()
