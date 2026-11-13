"""Agent reports recovered from subagent transcripts when the parent transcript has none.

Split from test_dream_inputs.py (module tripwire); reuses its fixtures.
"""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))
import _dream_inputs as di  # noqa: E402
import dream  # noqa: E402
from test_dream import FAKE_TOKEN, dispatch, human, verdict_text  # noqa: E402
from test_dream_async import async_launch, hand_back  # noqa: E402
from test_dream_inputs import SubTestBase  # noqa: E402


def final_text(text):
    """A subagent transcript entry: an assistant text block."""
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


class MergeTestBase(SubTestBase):
    def launch(self, uid, agent, agent_id):
        return [dispatch(uid, agent), async_launch(uid, agent_id)]

    def sub_report(self, agent_id, text, agent="builder-standard", parent="a"):
        self.write_sub(parent, agent_id, [final_text("working"), final_text(text)], meta=json.dumps({"agentType": agent}))

    def merged(self, name="a"):
        """Parse parent ``name`` with its subagents and merge; returns the session."""
        parent = self.transcripts / f"{name}.jsonl"
        s = dream.parse_session(parent)
        s["sub"] = di.parse_subagents(parent, 25)
        s["sub"]["merged"] = di.merge_subagent_reports(s, s["sub"])
        return s


class ParseSubagentReportTest(MergeTestBase):
    def test_last_verdict_block_wins_and_no_raw_text_kept(self):
        path = self.write_sub("a", "1", [
            final_text(verdict_text("BLOCKED")),
            final_text(verdict_text("COMPLETE", oos="- Split big_file.py")),
            final_text("thanks, done"),
        ])
        rep = di.parse_subagent(path, "builder")["report"]
        self.assertEqual((rep["verdict"], rep["out_of_scope"]), ("COMPLETE", ["Split big_file.py"]))
        self.assertEqual(set(rep), {"verdict", "flags", "out_of_scope"})

    def test_no_verdict_means_no_report(self):
        path = self.write_sub("a", "1", [final_text("all done, no contract"), human("ok")])
        self.assertIsNone(di.parse_subagent(path, "builder")["report"])

    def test_agent_id_comes_from_the_filename(self):
        self.parent()
        self.sub_report("abc123", verdict_text("COMPLETE"))
        out = di.parse_subagents(self.transcripts / "a.jsonl", 5)
        self.assertEqual([(i, a, r["verdict"]) for i, a, r in out["reports"]], [("abc123", "builder-standard", "COMPLETE")])


class MergeTest(MergeTestBase):
    def test_unreported_background_agent_is_merged_and_escalates(self):
        self.write("a", [
            human("go"), *self.launch("d1", "builder-standard", "ag1"),
            dispatch("d2", "builder"),  # the retry one tier up
        ])
        self.sub_report("ag1", verdict_text("PARTIAL"))
        s = self.merged()
        self.assertEqual(s["sub"]["merged"], 1)
        self.assertEqual([(r["agent"], r["verdict"], r["ts"], r["source"]) for r in s["reports"]],
                         [("builder-standard", "PARTIAL", None, "subagent")])
        # report lands right after its own dispatch, before the retry
        self.assertEqual(s["events"], [
            ("dispatch", "builder-standard"), ("report", "builder-standard", "PARTIAL"), ("dispatch", "builder"),
        ])
        self.assertEqual(s["escalations"], [("builder", 1, 2)])
        agg = dream.aggregate([s])
        self.assertEqual(agg["verdicts"], {"builder-standard": {"PARTIAL": 1}})
        self.assertEqual((agg["agent_reports"], agg["reports_from_subagents"]), (1, 1))
        self.assertEqual([r["kind"] for r in agg["recurring"] if r["kind"] == "escalation"], [])  # one session only
        both = dream.aggregate([s, {**s, "id": "other"}], min_sessions=2)
        self.assertEqual([r["summary"] for r in both["recurring"] if r["kind"] == "escalation"], ["builder: standard→complex"])

    def test_agent_already_reported_by_parent_is_not_merged(self):
        self.write("a", [*self.launch("d1", "builder-standard", "ag1"), hand_back("ag1", verdict_text("COMPLETE"))])
        self.sub_report("ag1", verdict_text("PARTIAL"))
        s = self.merged()
        self.assertEqual(s["sub"]["merged"], 0)
        self.assertEqual([(r["verdict"], "source" in r) for r in s["reports"]], [("COMPLETE", False)])
        self.assertEqual(dream.aggregate([s])["verdicts"], {"builder-standard": {"COMPLETE": 1}})

    def test_subagent_without_verdict_merges_nothing(self):
        self.write("a", [*self.launch("d1", "builder", "ag1")])
        self.write_sub("a", "ag1", [final_text("I got lost")], meta='{"agentType": "builder"}')
        s = self.merged()
        self.assertEqual((s["sub"]["merged"], s["reports"]), (0, []))
        self.assertEqual(s["events"], [("dispatch", "builder")])

    def test_unknown_dispatch_appends_at_end_in_merge_order(self):
        self.write("a", [dispatch("d1", "builder")])
        self.sub_report("zz1", verdict_text("BLOCKED"), agent="scout")
        self.sub_report("zz2", verdict_text("COMPLETE"), agent="scout")
        s = self.merged()
        self.assertEqual(s["sub"]["merged"], 2)
        self.assertEqual(s["events"][0], ("dispatch", "builder"))
        self.assertEqual({e[2] for e in s["events"][1:]}, {"BLOCKED", "COMPLETE"})
        self.assertEqual([r["verdict"] for r in s["reports"]], [e[2] for e in s["events"][1:]])

    def test_two_known_dispatches_insert_in_descending_order(self):
        self.write("a", [
            *self.launch("d1", "builder-simple", "ag1"), *self.launch("d2", "scout", "ag2"), dispatch("d3", "builder"),
        ])
        self.sub_report("ag1", verdict_text("BLOCKED"), agent="builder-simple")
        self.sub_report("ag2", verdict_text("COMPLETE"), agent="scout")
        s = self.merged()
        self.assertEqual(s["events"], [
            ("dispatch", "builder-simple"), ("report", "builder-simple", "BLOCKED"),
            ("dispatch", "scout"), ("report", "scout", "COMPLETE"), ("dispatch", "builder"),
        ])
        self.assertEqual(s["escalations"], [("builder", 0, 2)])

    def test_summary_exposes_reported_ids_and_dispatch_index_but_no_private_keys(self):
        s = dream.parse_session(self.write("a", [
            *self.launch("d1", "builder", "ag1"), hand_back("ag1", verdict_text("COMPLETE")), human("x"),
        ]))
        self.assertEqual((s["reported_ids"], s["agent_dispatch"]), (["ag1"], {"ag1": 0}))
        self.assertEqual([k for k in s if k.startswith("_")], [])

    def test_inverted_pin_in_subagent_report_reaches_to_confirm(self):
        self.write("a", [*self.launch("d1", "builder", "ag1")])
        self.sub_report("ag1", verdict_text("PARTIAL", deviations="- Inverted pin: test_x state S via path P"), agent="builder")
        agg = dream.aggregate([self.merged()])
        self.assertEqual([(f["agent"], f["text"]) for f in agg["to_confirm"]], [("builder", "Inverted pin: test_x state S via path P")])

    def test_secret_in_out_of_scope_line_is_redacted(self):
        self.write("a", [*self.launch("d1", "builder", "ag1")])
        self.sub_report("ag1", verdict_text("COMPLETE", oos=f"- rotate {FAKE_TOKEN} soon"), agent="builder")
        s = self.merged()
        self.assertEqual(len(s["reports"]), 1)
        self.assertNotIn("a1B2c3D4", json.dumps(s))
        self.assertNotIn("a1B2c3D4", json.dumps(dream.aggregate([s])))


class MergeCliTest(MergeTestBase):
    def setUp(self):
        super().setUp()
        self.write("a", [human("go"), *self.launch("d1", "builder-standard", "ag1"), dispatch("d2", "builder")])
        self.sub_report("ag1", verdict_text("PARTIAL"))
        self.out_path = self.tmp / "p.md"

    def proposal(self, *extra):
        rc, out = self.run_main("--no-stamp", "--out", str(self.out_path), "--json", *extra)
        self.assertEqual(rc, 0)
        return self.out_path.read_text(encoding="utf-8"), json.loads(out)

    def test_header_and_verdict_table_count_the_merged_report(self):
        text, data = self.proposal()
        self.assertIn("Agent reports parsed: 1, of which 1 from subagent transcripts (dispatches seen: 2)", text)
        self.assertIn("| builder-standard | 0 | 1 | 0 | 0 |", text)
        self.assertEqual(data["reports_from_subagents"], 1)
        # drift stays parent-based: a recovered report must not hide "no parent reports parsed"
        self.assertIn("Agent dispatches seen but no agent reports parsed", text)

    def test_no_subagents_flag_merges_nothing(self):
        text, data = self.proposal("--no-subagents")
        self.assertIn("Agent reports parsed: 0, of which 0 from subagent transcripts", text)
        self.assertEqual((data["reports_from_subagents"], data["verdicts"]), (0, {}))


if __name__ == "__main__":
    unittest.main()
