"""User-correction detection and the transcript format check for the dream extractor.

Split from test_dream.py (module tripwire); reuses its fixture builders.
"""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))
import dream  # noqa: E402
from test_dream import DreamTestBase, assistant, dispatch, human, report, tool_error, verdict_text  # noqa: E402, F401


def assistant_text(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


class CorrectionTest(DreamTestBase):
    def corrections(self, *entries):
        """Corrections counted after a leading task prompt."""
        return self.parse("a", [human("task prompt"), *entries])["corrections"]

    def test_first_human_message_never_counts(self):
        self.assertEqual(self.parse("a", [human("No, don't do that")])["corrections"], 0)
        self.assertEqual(self.parse("b", [human("No, don't do that"), human("No, don't do that")])["corrections"], 1)

    def test_no_after_question_is_a_decision(self):
        self.assertEqual(self.corrections(assistant_text("Shall I continue?  \n"), human("no")), 0)

    def test_no_after_statement_counts(self):
        self.assertEqual(self.corrections(assistant_text("I changed the file."), human("no")), 1)

    def test_tool_use_only_entry_keeps_question_state(self):
        entries = [assistant_text("Shall I continue?"), assistant(("t1", "Read", {})), human("no")]
        self.assertEqual(self.corrections(*entries), 0)

    def test_no_with_benign_follow_up_does_not_count(self):
        for text in ("No need, thanks", "no, all done", "nope, nothing else"):
            self.assertEqual(self.corrections(human(text)), 0, text)

    def test_strong_cues_count(self):
        for text in ("I meant the other one", "don't do that", "That is not deployed", "Hm, no. Different approach.",
                     "Wait, that's wrong", "Why did you change it?", "Please don't touch the config"):
            self.assertEqual(self.corrections(assistant_text("Done."), human(text)), 1, text)

    def test_strong_cue_counts_even_after_question(self):
        self.assertEqual(self.corrections(assistant_text("Which file?"), human("I meant the other one")), 1)

    def test_non_cues_do_not_count(self):
        for text in ("I mean, maybe later", "do notify the user", "Stop here", "Actually, can you add a test"):
            self.assertEqual(self.corrections(human(text)), 0, text)

    def test_rejection_with_reason_counts_and_plain_does_not(self):
        plain = "The user doesn't want to proceed with this tool use. The tool use was rejected."
        reasoned = plain + " To tell you how to proceed, the user said:\nuse the other file"
        s = self.parse("a", [
            human("task prompt"),
            assistant(("t1", "Edit", {}), ("t2", "Edit", {})),
            tool_error("t1", plain),
            tool_error("t2", reasoned),
        ])
        self.assertEqual(s["corrections"], 1)
        self.assertEqual(s["excerpts"], [])
        self.assertEqual(len(s["errors"]), 0)


class DriftTest(DreamTestBase):
    def normal(self, name="a"):
        return self.parse(name, [
            human("task"),
            dispatch("d1", "builder"),
            report("builder", verdict_text("COMPLETE")),
            assistant_text("done"),
        ])

    def drift(self, *sessions):
        return dream.aggregate(list(sessions))["drift"]

    def test_normal_fixture_has_no_warnings(self):
        self.assertEqual(self.drift(self.normal()), [])

    def test_empty_window_has_no_warnings(self):
        self.assertEqual(dream.aggregate([])["drift"], [])

    def test_unknown_type_values_warn(self):
        s = self.parse("a", [{"kind": "x", "type": "novel"}, {"type": "other", "n": 1}])
        warnings = self.drift(s)
        self.assertEqual(len(warnings), 1)
        self.assertIn("`type` field", warnings[0])

    def test_renamed_message_warns_and_lists_new_key(self):
        entries = [{"type": "user", "payload": {"content": "hi"}}, {"type": "assistant", "payload": {"content": []}}]
        warnings = self.drift(self.parse("a", entries))
        self.assertTrue(any("lack `message.content`" in w for w in warnings))
        self.assertTrue(any("New top-level keys" in w and "payload" in w for w in warnings))

    def test_missing_tool_use_result_warns(self):
        s = self.parse("a", [human("task"), assistant(("t1", "Read", {})), tool_error("t1", "boom")])
        warnings = self.drift(s)
        self.assertEqual(len(warnings), 1)
        self.assertIn("toolUseResult", warnings[0])

    def test_agent_results_without_dispatches_warn(self):
        s = self.parse("a", [human("task"), report("builder", verdict_text("COMPLETE"))])
        warnings = self.drift(s)
        self.assertEqual(len(warnings), 1)
        self.assertIn("dispatch tool may have been renamed", warnings[0])

    def test_large_sample_without_tool_use_warns(self):
        s = self.parse("a", [human("task")] + [assistant_text(f"t{i}") for i in range(50)])
        self.assertTrue(any("tool_use" in w for w in self.drift(s)))
        small = self.parse("b", [human("task")] + [assistant_text(f"t{i}") for i in range(10)])
        self.assertEqual(self.drift(small), [])

    def test_minority_unknown_key_is_ignored(self):
        entries = [human("hi", uuid="u") for _ in range(3)] + [human("odd", brandNew=1)]
        self.assertEqual(self.drift(self.parse("a", entries)), [])

    def test_shape_counts_sum_across_sessions(self):
        agg = dream.aggregate([self.normal("a"), self.normal("b")])
        self.assertEqual(agg["shape"]["agent_results"], 2)
        self.assertEqual(agg["shape"]["agent_dispatches"], 2)
        self.assertEqual(agg["shape"]["unknown_keys"], [])

    def test_render_shows_format_check_section_and_json_drift(self):
        out_path = self.tmp / "p.md"
        self.write("a", [human("task"), dispatch("d1", "builder"), report("builder", verdict_text("COMPLETE"))])
        self.run_main("--no-stamp", "--out", str(out_path))
        self.assertIn("## Format check\n\nTranscript shapes look as expected.", out_path.read_text(encoding="utf-8"))
        self.write("a", [{"type": "novel"}])
        _, out = self.run_main("--no-stamp", "--out", str(out_path), "--json")
        self.assertIn("`type` field", out_path.read_text(encoding="utf-8"))
        self.assertEqual(len(json.loads(out)["drift"]), 1)


if __name__ == "__main__":
    unittest.main()
