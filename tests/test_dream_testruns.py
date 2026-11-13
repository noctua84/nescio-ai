"""Subagent test-run classification for the dream extractor (``_dream_testruns``).

Fixtures are synthetic; reuses the subagent-transcript helpers of the neighbouring dream tests.
"""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))
import _dream_inputs as di  # noqa: E402
import _dream_testruns as tr  # noqa: E402
import dream  # noqa: E402
from test_dream import human, verdict_text  # noqa: E402
from test_dream_inputs import BASH, SubTestBase  # noqa: E402
from test_dream_subagent_reports import final_text  # noqa: E402

UNITTEST_OK = "Ran 3 tests in 0.1s\n\nOK\n"
UNITTEST_FAIL = "Ran 3 tests in 0.1s\n\nFAILED (failures=1)\n"
PYTEST_OK = "===== 4 passed in 0.2s ====="
PYTEST_FAIL = "===== 1 failed, 3 passed in 0.2s ====="
RUN = "python -m unittest discover -s tests"
REJECTED = "The user doesn't want to proceed with this tool use."


def result(uid, text, is_error=False):
    block = {"type": "tool_result", "tool_use_id": uid, "content": text}
    if is_error:
        block["is_error"] = True
    return {"type": "user", "message": {"content": [block]}}


def assistant_use(*uses):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": i, "name": n, "input": inp} for i, n, inp in uses]}}


def run(uid, text, cmd=RUN, is_error=False):
    """A test command and its result, as two transcript entries."""
    return [assistant_use(BASH(uid, cmd)), result(uid, text, is_error)]


def edit(uid, name="Edit", **inp):
    return [assistant_use((uid, name, inp)), result(uid, "ok")]


class OutcomeTest(unittest.TestCase):
    def test_unittest_and_pytest_summaries(self):
        self.assertIs(tr.outcome(UNITTEST_OK, False), True)
        self.assertIs(tr.outcome(UNITTEST_FAIL, False), False)
        self.assertIs(tr.outcome("ERROR: x\nERRORS!\n", False), False)
        self.assertIs(tr.outcome(PYTEST_OK, False), True)
        self.assertIs(tr.outcome(PYTEST_FAIL, False), False)
        self.assertIs(tr.outcome("== 2 errors in 0.1s ==", False), False)

    def test_summary_beats_is_error_and_unknown_is_none(self):
        self.assertIs(tr.outcome(UNITTEST_OK, True), True)
        self.assertIs(tr.outcome("no summary here", True), False)
        self.assertIsNone(tr.outcome("no summary here", False))
        self.assertIsNone(tr.outcome("", False))

    def test_only_the_tail_is_read(self):
        self.assertIs(tr.outcome("FAILED (failures=1)\n" + "x" * 4000 + "\nOK\n", False), True)
        self.assertIsNone(tr.outcome("1 failed\n" + "x" * 4000, False))

    def test_ok_must_start_a_line(self):
        self.assertIsNone(tr.outcome("it is OK to skip", False))


class IsEditTest(unittest.TestCase):
    def test_edit_tools(self):
        for name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            self.assertTrue(tr.is_edit(name, {}))
        self.assertFalse(tr.is_edit("Read", {"command": "sed -i x"}))

    def test_shell_writes(self):
        for cmd in ("sed -i 's/a/b/' f.py", "sed -n -i 's/a/b/' f", "echo hi > out.txt", "echo hi >> out.txt",
                    "printf x | tee f.txt", "Set-Content f.txt hi", "x | Out-File f.txt", "Add-Content f hi"):
            self.assertTrue(tr.is_edit("Bash", {"command": cmd}), cmd)
        self.assertTrue(tr.is_edit("PowerShell", {"command": "Set-Content f.txt hi"}))

    def test_redirects_that_write_nothing_are_not_edits(self):
        for cmd in ("make 2>&1", "make 2>&1 | tail -3", "make >/dev/null", "make > /dev/null 2>&1", "echo x >&2",
                    "sed -n 's/a/b/p' f.py", "grep -r pattern .", "echo a -> b"):
            self.assertFalse(tr.is_edit("Bash", {"command": cmd}), cmd)

    def test_bad_inputs(self):
        self.assertFalse(tr.is_edit("Bash", None))
        self.assertFalse(tr.is_edit("Bash", {"command": 5}))


class TrackerTest(unittest.TestCase):
    def feed(self, steps):
        """steps: ("use", id, name, input) / ("res", id, text, is_error) / ("run", id, text[, is_error[, cmd]])."""
        t = tr.TestTracker()
        for st in steps:
            if st[0] == "run":
                _, uid, text, *rest = st
                t.on_tool_use(uid, "Bash", {"command": rest[1] if len(rest) > 1 else RUN})
                t.on_tool_result(uid, text, rest[0] if rest else False)
            elif st[0] == "use":
                t.on_tool_use(*st[1:])
            else:
                t.on_tool_result(*st[1:])
        return t.summary()

    def after(self, steps):
        return {k: v for k, v in self.feed(steps)["after_fail"].items() if v}

    def test_counts_and_masked_failure(self):
        s = self.feed([("run", "a", UNITTEST_FAIL), ("run", "b", UNITTEST_FAIL, True), ("run", "c", "nothing"),
                       ("run", "d", UNITTEST_OK)])
        self.assertEqual((s["runs"], s["known"], s["failed"], s["masked"], s["last_ok"]), (4, 3, 2, 1, True))

    def test_piped_failure_with_exit_zero_is_failing_and_masked(self):
        s = self.feed([("run", "a", PYTEST_FAIL, False, "pytest -q | tail -3")])
        self.assertEqual((s["failed"], s["masked"], s["last_ok"]), (1, 1, False))

    def test_unknown_outcome_is_ignored_for_pairing(self):
        s = self.feed([("run", "a", UNITTEST_FAIL), ("run", "b", "who knows"), ("run", "c", UNITTEST_OK)])
        self.assertEqual({k: v for k, v in s["after_fail"].items() if v}, {"passed_no_edit_seen": 1})
        self.assertEqual((s["runs"], s["known"]), (3, 2))

    def test_non_test_commands_are_not_runs(self):
        s = self.feed([("use", "x", "Bash", {"command": "ls -la"}), ("res", "x", UNITTEST_FAIL, True)])
        self.assertEqual((s["runs"], s["known"], s["last_ok"]), (0, 0, None))

    def test_rejected_run_has_no_outcome(self):
        s = self.feed([("run", "a", REJECTED, True)])
        self.assertEqual((s["runs"], s["known"], s["failed"], s["last_ok"]), (1, 0, 0, None))

    def test_fixed_after_edit(self):
        self.assertEqual(self.after([("run", "a", UNITTEST_FAIL), ("use", "e", "Edit", {}), ("run", "b", UNITTEST_OK)]),
                         {"fixed_after_edit": 1})

    def test_fixed_after_sed_inplace(self):
        steps = [("run", "a", UNITTEST_FAIL), ("use", "e", "Bash", {"command": "sed -i s/a/b/ f.py"}), ("run", "b", PYTEST_OK)]
        self.assertEqual(self.after(steps), {"fixed_after_edit": 1})

    def test_passed_with_no_edit_seen(self):
        self.assertEqual(self.after([("run", "a", UNITTEST_FAIL), ("run", "b", UNITTEST_OK)]), {"passed_no_edit_seen": 1})

    def test_stderr_redirects_do_not_count_as_edits(self):
        for cmd in ("make 2>&1", "make >/dev/null"):
            steps = [("run", "a", UNITTEST_FAIL), ("use", "e", "Bash", {"command": cmd}), ("run", "b", UNITTEST_OK)]
            self.assertEqual(self.after(steps), {"passed_no_edit_seen": 1}, cmd)

    def test_refailed_after_edit_and_retried_no_edit(self):
        self.assertEqual(self.after([("run", "a", UNITTEST_FAIL), ("use", "e", "Write", {}), ("run", "b", UNITTEST_FAIL)]),
                         {"refailed_after_edit": 1, "not_rerun": 1})
        self.assertEqual(self.after([("run", "a", UNITTEST_FAIL), ("run", "b", UNITTEST_FAIL)]),
                         {"retried_no_edit": 1, "not_rerun": 1})

    def test_not_rerun_and_summary_does_not_mutate(self):
        t = tr.TestTracker()
        t.on_tool_use("a", "Bash", {"command": RUN})
        t.on_tool_result("a", UNITTEST_FAIL, False)
        self.assertEqual(t.summary()["after_fail"]["not_rerun"], 1)
        self.assertEqual(t.summary()["after_fail"]["not_rerun"], 1)

    def test_pairs_with_next_known_run_even_with_a_different_command(self):
        steps = [("run", "a", UNITTEST_FAIL), ("run", "b", PYTEST_OK, False, "pytest tests/test_other.py")]
        self.assertEqual(self.after(steps), {"passed_no_edit_seen": 1})

    def test_edit_before_the_failure_does_not_count(self):
        steps = [("use", "e", "Edit", {}), ("run", "a", UNITTEST_FAIL), ("run", "b", UNITTEST_OK)]
        self.assertEqual(self.after(steps), {"passed_no_edit_seen": 1})

    def test_chain_classifies_each_failure_once(self):
        steps = [("run", "a", UNITTEST_FAIL), ("run", "b", UNITTEST_FAIL), ("use", "e", "Edit", {}), ("run", "c", UNITTEST_OK)]
        self.assertEqual(self.after(steps), {"retried_no_edit": 1, "fixed_after_edit": 1})

    def test_no_command_or_output_text_is_kept(self):
        s = self.feed([("run", "a", "SECRET-OUTPUT FAILED (failures=1)", False, "pytest SECRET-ARG")])
        self.assertNotIn("SECRET", json.dumps(s))


class ParseSubagentTestRunsTest(SubTestBase):
    def sub(self, agent_id, entries, agent="builder", parent="a"):
        return self.write_sub(parent, agent_id, entries, meta=json.dumps({"agentType": agent}))

    def test_parse_subagent_returns_the_summary_and_dedupes_reemitted_tool_use(self):
        use = assistant_use(BASH("r1", RUN))
        path = self.sub("1", [use, use, result("r1", UNITTEST_FAIL)])
        t = di.parse_subagent(path, "builder")["tests"]
        self.assertEqual((t["runs"], t["failed"], t["masked"], t["after_fail"]["not_rerun"]), (1, 1, 1, 1))

    def test_failing_output_with_exit_zero_is_not_a_tool_error(self):
        path = self.sub("1", run("r1", UNITTEST_FAIL))
        r = di.parse_subagent(path, "builder")
        self.assertEqual((len(r["errors"]), r["tests"]["masked"]), (0, 1))

    def test_complete_on_red_is_counted_per_file_and_per_agent(self):
        self.parent()
        self.sub("1", [*run("r1", UNITTEST_FAIL), final_text(verdict_text("COMPLETE"))])
        self.sub("2", [*run("r1", UNITTEST_FAIL), *run("r2", UNITTEST_OK), final_text(verdict_text("COMPLETE"))])
        self.sub("3", [*run("r1", UNITTEST_FAIL), final_text(verdict_text("PARTIAL"))])
        self.sub("4", [*run("r1", UNITTEST_FAIL), final_text(verdict_text("COMPLETE"))], agent="scout")
        self.sub("5", [final_text(verdict_text("COMPLETE"))])  # no test run: last_ok is None
        out = di.parse_subagents(self.transcripts / "a.jsonl", 25)
        self.assertEqual(out["complete_on_red"], 2)
        self.assertEqual(out["complete_on_red_agents"], {"builder": 1, "scout": 1})
        builder = out["tests_by_agent"]["builder"]
        self.assertEqual(builder["runs"], 4)
        self.assertEqual(builder["after_fail"]["fixed_after_edit"], 0)
        self.assertEqual(builder["after_fail"]["passed_no_edit_seen"], 1)
        self.assertEqual(sorted(out["tests_by_agent"]), ["builder", "scout"])


class AggregateTestRunsTest(SubTestBase):
    def sessions(self, names=("a", "b")):
        out = []
        for name in names:
            parent = self.parent(name)
            entries = [*run("r1", UNITTEST_FAIL), *run("r2", UNITTEST_FAIL), *run("r3", PYTEST_FAIL, "pytest | tail"),
                       final_text(verdict_text("COMPLETE"))]
            self.write_sub(name, "1", entries, meta='{"agentType": "builder"}')
            s = dream.parse_session(parent)
            s["sub"] = di.parse_subagents(parent, 25)
            out.append(s)
        return out

    def test_recurring_kinds_with_ids_and_sidecar_entries(self):
        sessions = self.sessions()
        agg = dream.aggregate(sessions)
        by_kind = {r["kind"]: r for r in agg["recurring"]}
        table = dream.signal_table(sessions)
        expected = {"test-retry-no-edit": 4, "test-not-rerun": 2, "test-failure-masked": 6, "complete-on-red": 2}
        for kind, count in expected.items():
            self.assertEqual(by_kind[kind]["sessions"], 2, kind)
            self.assertEqual(by_kind[kind]["id"], dream.signal_id(kind))
            self.assertEqual(table[by_kind[kind]["id"]], {"key": kind, "sessions": 2, "count": count}, kind)
        self.assertIn("2 COMPLETE", by_kind["complete-on-red"]["summary"])

    def test_aggregate_totals_by_agent_and_complete_on_red(self):
        st = dream.aggregate(self.sessions())["subagent_tests"]
        self.assertEqual((st["totals"]["runs"], st["totals"]["failed"], st["totals"]["masked"]), (6, 6, 6))
        self.assertEqual(st["by_agent"]["builder"]["after_fail"], {
            "fixed_after_edit": 0, "passed_no_edit_seen": 0, "refailed_after_edit": 0, "retried_no_edit": 4, "not_rerun": 2})
        self.assertEqual(st["complete_on_red"], {"count": 2, "sessions": 2, "by_agent": {"builder": 2}})
        json.dumps(st)  # plain data only

    def test_one_session_is_below_the_threshold_but_still_in_the_sidecar(self):
        sessions = self.sessions(("a",))
        agg = dream.aggregate(sessions)
        self.assertEqual([r for r in agg["recurring"] if r["kind"].startswith(("test-", "complete-"))], [])
        self.assertIn(dream.signal_id("complete-on-red"), dream.signal_table(sessions))
        low = dream.aggregate(sessions, min_sessions=1)
        self.assertEqual(sum(1 for r in low["recurring"] if r["kind"].startswith(("test-", "complete-"))), 4)

    def test_sessions_without_tests_yield_empty_totals_and_no_signals(self):
        agg = dream.aggregate([dream.parse_session(self.parent())])
        self.assertEqual(agg["subagent_tests"]["totals"]["runs"], 0)
        self.assertEqual(agg["subagent_tests"]["by_agent"], {})
        self.assertEqual(agg["subagent_tests"]["complete_on_red"]["count"], 0)


class RenderTestRunsTest(SubTestBase):
    def proposal(self):
        out_path = self.tmp / "p.md"
        rc, _ = self.run_main("--no-stamp", "--out", str(out_path))
        self.assertEqual(rc, 0)
        return out_path.read_text(encoding="utf-8")

    def test_section_lists_agents_and_complete_on_red(self):
        self.write("a", [human("go")])
        self.write_sub("a", "1", [*run("r1", UNITTEST_FAIL), *edit("e1"), *run("r2", UNITTEST_OK), *run("r3", UNITTEST_FAIL),
                                  final_text(verdict_text("COMPLETE"))], meta='{"agentType": "builder"}')
        text = self.proposal()
        self.assertIn("## Test runs in subagents", text)
        self.assertIn("| builder | 3 | 3 | 2 | 2 | 1 | 0 | 0 | 0 | 1 |", text)
        self.assertIn("COMPLETE reports whose last test run failed: 1 (by agent: builder 1)", text)
        self.assertTrue(text.startswith("# Dream proposal:"))

    def test_empty_message_without_subagent_test_runs(self):
        self.write("a", [human("go")])
        text = self.proposal()
        self.assertIn("## Test runs in subagents", text)
        self.assertIn("No test runs found in subagent transcripts", text)


if __name__ == "__main__":
    unittest.main()
