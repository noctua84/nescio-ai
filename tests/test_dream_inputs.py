import json
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dream import FAKE_TOKEN, DreamTestBase, assistant, human, tool_error  # noqa: E402

import _dream_inputs as di  # noqa: E402
import dream  # noqa: E402

BASH = lambda uid, cmd: (uid, "Bash", {"command": cmd})  # noqa: E731
SINCE = datetime(2026, 7, 1, tzinfo=timezone.utc)


class SubTestBase(DreamTestBase):
    def write_sub(self, parent, agent_id, entries, meta=None, raw=(), mtime=None):
        """A subagent transcript under ``<parent>/subagents/``; ``meta`` is the meta.json text if given."""
        d = self.transcripts / parent / "subagents"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"agent-{agent_id}.jsonl"
        path.write_text("\n".join([json.dumps(e) for e in entries] + list(raw)) + "\n", encoding="utf-8")
        if meta is not None:
            (d / f"agent-{agent_id}.meta.json").write_text(meta, encoding="utf-8")
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def parent(self, name="a"):
        return self.write(name, [human("hi")])

    def session_with_error(self, name, text="boom: /p/x.py"):
        """A parent session whose one subagent hit a Bash error."""
        parent = self.parent(name)
        self.write_sub(name, "1", [assistant(BASH("t1", "make")), tool_error("t1", text)], meta='{"agentType": "builder"}')
        s = dream.parse_session(parent)
        s["sub"] = di.parse_subagents(parent, 25)
        return s


class SubagentFilesTest(SubTestBase):
    def test_agent_type_from_meta_and_unknown_when_missing_or_bad(self):
        parent = self.parent()
        self.write_sub("a", "1", [], meta='{"agentType": "builder-standard"}')
        self.write_sub("a", "2", [])
        self.write_sub("a", "3", [], meta="{not json")
        self.write_sub("a", "4", [], meta='{"agentType": 7}')
        kept, skipped = di.subagent_files(parent, 10)
        self.assertEqual(skipped, 0)
        self.assertEqual({p.stem: a for p, a in kept}, {
            "agent-1": "builder-standard", "agent-2": "unknown", "agent-3": "unknown", "agent-4": "unknown",
        })

    def test_cap_keeps_newest_and_reports_skipped(self):
        parent = self.parent()
        now = time.time()
        for i in range(4):
            self.write_sub("a", str(i), [], mtime=now - i * 10)
        kept, skipped = di.subagent_files(parent, 2)
        self.assertEqual([p.stem for p, _ in kept], ["agent-0", "agent-1"])
        self.assertEqual(skipped, 2)

    def test_no_subagents_dir(self):
        self.assertEqual(di.subagent_files(self.parent(), 5), ([], 0))


class ParseSubagentTest(SubTestBase):
    def test_errors_keyed_by_agent_tool_signature_and_rejections_excluded(self):
        path = self.write_sub("a", "1", [
            assistant(BASH("t1", "make"), ("t2", "Edit", {}), ("t3", "Read", {})),
            tool_error("t1", "Exit code 2\nmake: failed at /p/one.py"),
            tool_error("t1", "Exit code 2\nmake: failed at /q/two.py"),
            tool_error("t2", "The user doesn't want to proceed with this tool use."),
            tool_error("t3", "[Request interrupted by user for tool use]"),
            tool_error("zz", "mystery"),
        ])
        r = di.parse_subagent(path, "builder")
        self.assertEqual(sorted(r["errors"].values()), [1, 2])
        self.assertEqual(
            r["errors"][("builder", "Bash", di.error_signature("Exit code 2\nmake: failed at /x.py"))], 2
        )
        self.assertIn(("builder", "unknown", "mystery"), r["errors"])
        self.assertEqual(len(r["errors"]), 2)

    def test_malformed_lines_counted_and_skipped(self):
        path = self.write_sub("a", "1", [assistant(BASH("t1", "x")), tool_error("t1", "bad")], raw=["{nope", "[1]"])
        r = di.parse_subagent(path, "a")
        self.assertEqual(r["malformed"], 2)
        self.assertEqual(sum(r["errors"].values()), 1)

    def test_reruns_counted_after_whitespace_normalisation(self):
        reemitted = BASH("r1", "pytest -x")
        path = self.write_sub("a", "1", [
            assistant(reemitted), assistant(reemitted),  # same tool_use id: one command
            assistant(BASH("r2", "pytest   -x")),
            assistant(BASH("r3", "pytest -x\n")),
            assistant(BASH("r4", "ls")),
            assistant(("r5", "Read", {"command": "ls"})),  # not Bash
        ])
        self.assertEqual(di.parse_subagent(path, "a")["reruns"], 2)

    def test_secret_in_error_text_is_redacted(self):
        path = self.write_sub("a", "1", [assistant(BASH("t1", "x")), tool_error("t1", f"auth failed with {FAKE_TOKEN}")])
        sigs = [sig for (_, _, sig) in di.parse_subagent(path, "a")["errors"]]
        self.assertEqual(len(sigs), 1)
        self.assertNotIn(FAKE_TOKEN, sigs[0])
        self.assertNotIn("a1B2c3D4", sigs[0])

    def test_parse_subagents_folds_files(self):
        parent = self.parent()
        for i, agent in enumerate(("builder", "builder", "scout")):
            self.write_sub("a", str(i), [
                assistant(BASH("t1", "go"), BASH("t2", "go")), tool_error("t1", "nope"),
            ], meta=json.dumps({"agentType": agent}), mtime=time.time() - i)
        r = di.parse_subagents(parent, 2)
        self.assertEqual((r["files"], r["skipped"], r["reruns"]), (2, 1, 2))
        self.assertEqual(r["errors"][("builder", "Bash", "nope")], 2)
        self.assertEqual(dict(r["rerun_agents"]), {"builder": 2})


class AggregateTest(SubTestBase):
    def test_recurs_across_two_parent_sessions_only(self):
        a, b = self.session_with_error("a", "boom: /p/x.py"), self.session_with_error("b", "boom: /q/y.py")
        two = dream.aggregate([a, b])
        rec = [r for r in two["recurring"] if r["kind"] == "subagent-tool-error"]
        self.assertEqual([(r["summary"], r["sessions"], r["count"]) for r in rec], [("builder Bash: boom: <path>", 2, 2)])
        self.assertEqual(two["subagent_errors"][0]["agent"], "builder")
        one = dream.aggregate([a])
        self.assertEqual([r for r in one["recurring"] if r["kind"] == "subagent-tool-error"], [])
        self.assertEqual(len(one["subagent_errors"]), 1)

    def test_one_session_repeating_an_error_is_not_recurring(self):
        parent = self.parent()
        self.write_sub("a", "1", [assistant(BASH("t1", "x")), tool_error("t1", "bad"), tool_error("t1", "bad")])
        s = dream.parse_session(parent)
        s["sub"] = di.parse_subagents(parent, 5)
        agg = dream.aggregate([s])
        self.assertEqual(agg["subagent_errors"][0]["count"], 2)
        self.assertEqual([r for r in agg["recurring"] if r["kind"] == "subagent-tool-error"], [])

    def test_reruns_recur_and_malformed_lines_roll_up(self):
        sessions = []
        for name in ("a", "b"):
            parent = self.parent(name)
            self.write_sub(name, "1", [assistant(BASH("r1", "go"), BASH("r2", "go"))], meta='{"agentType": "scout"}', raw=["{x"])
            s = dream.parse_session(parent)
            s["sub"] = di.parse_subagents(parent, 5)
            sessions.append(s)
        agg = dream.aggregate(sessions)
        self.assertEqual(agg["subagent_reruns"], {"count": 2, "sessions": 2, "by_agent": {"scout": 2}})
        self.assertEqual([r["kind"] for r in agg["recurring"] if r["kind"] == "subagent-reruns"], ["subagent-reruns"])
        self.assertEqual((agg["subagents_read"], agg["malformed_lines"]), (2, 2))

    def test_sessions_without_sub_key_are_tolerated(self):
        agg = dream.aggregate([dream.parse_session(self.parent())])
        self.assertEqual((agg["subagents_read"], agg["subagent_errors"], agg["subagent_reruns"]["count"]), (0, [], 0))
        self.assertEqual(agg["qa_reports"], {"reports": [], "totals": dict.fromkeys(di.SEVERITIES, 0)})


class QaReportsTest(DreamTestBase):
    def report(self, name, body):
        d = self.tmp / "docs" / "reports"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body, encoding="utf-8")

    def test_summary_line_parsed_case_insensitive_any_order(self):
        self.report("2026-07-02-a.md", "# R\n**Severity Summary:** 1 Critical | 2 Major | 3 Minor | 4 Info\n")
        self.report("2026-07-03-b.md", "**Severity Summary:** 4 info | 3 MINOR | 0 major | 9 critical\n")
        got = {r["name"]: r for r in di.qa_reports(self.tmp, SINCE, 10)}
        self.assertEqual(got["2026-07-02-a.md"], {
            "name": "2026-07-02-a.md", "date": "2026-07-02", "critical": 1, "major": 2, "minor": 3, "info": 4, "source": "summary",
        })
        b = got["2026-07-03-b.md"]
        self.assertEqual((b["critical"], b["major"], b["minor"], b["info"]), (9, 0, 3, 4))

    def test_heading_fallback_and_titles_never_emitted(self):
        self.report("2026-07-02-a.md", "## Findings\n### [MAJOR] Secret title one\n### [MINOR] Two\n### [MINOR] Three\n"
                                       "### [CRITICAL|MAJOR|MINOR|INFO] Template line\n")
        (r,) = di.qa_reports(self.tmp, SINCE, 10)
        self.assertEqual((r["source"], r["critical"], r["major"], r["minor"], r["info"]), ("headings", 0, 1, 2, 0))
        self.assertNotIn("Secret", json.dumps(r))

    def test_neither_summary_nor_headings_skipped(self):
        self.report("2026-07-02-a.md", "# nothing here\n**Severity Summary:** n/a\n")
        self.assertEqual(di.qa_reports(self.tmp, SINCE, 10), [])

    def test_date_filter_cap_order_and_name_pattern(self):
        body = "**Severity Summary:** 0 Critical | 1 Major | 0 Minor | 0 Info\n"
        for name in ("2026-06-30-old.md", "2026-07-01-edge.md", "2026-07-05-b.md", "2026-07-09-c.md",
                     "notes.md", "2026-13-40-bad.md", "2026-07-07-x.txt"):
            self.report(name, body)
        self.assertEqual([r["name"] for r in di.qa_reports(self.tmp, SINCE, 10)],
                         ["2026-07-09-c.md", "2026-07-05-b.md", "2026-07-01-edge.md"])
        self.assertEqual([r["name"] for r in di.qa_reports(self.tmp, SINCE, 2)], ["2026-07-09-c.md", "2026-07-05-b.md"])

    def test_missing_dir_yields_nothing(self):
        self.assertEqual(di.qa_reports(self.tmp / "nope", SINCE, 5), [])


class CliInputsTest(SubTestBase):
    def setUp(self):
        super().setUp()
        self.out_path = self.tmp / "p.md"
        today = datetime.now(timezone.utc).date()
        d = self.tmp / "docs" / "reports"
        d.mkdir(parents=True)
        (d / f"{today.isoformat()}-audit.md").write_text("**Severity Summary:** 0 Critical | 2 Major | 1 Minor | 5 Info\n", encoding="utf-8")
        (d / f"{(today - timedelta(days=400)).isoformat()}-ancient.md").write_text("### [MAJOR] x\n", encoding="utf-8")
        for name in ("a", "b"):
            self.parent(name)
            self.write_sub(name, "1", [assistant(BASH("t1", "make")), tool_error("t1", "boom")], meta='{"agentType": "builder"}')

    def run_proposal(self, *extra):
        rc, out = self.run_main("--no-stamp", "--out", str(self.out_path), *extra)
        self.assertEqual(rc, 0)
        return self.out_path.read_text(encoding="utf-8"), out

    def test_proposal_contains_new_sections(self):
        text, _ = self.run_proposal()
        self.assertIn("- Subagent transcripts read: 2 (skipped by cap: 0)", text)
        self.assertIn("## Subagent tool errors", text)
        self.assertIn("- builder Bash: boom (2 sessions, 2 errors)", text)
        self.assertIn("[subagent-tool-error] builder Bash: boom (2 sessions)", text)
        self.assertIn("## QA audits", text)
        self.assertIn("| Report | Date | Critical | Major | Minor | Info |", text)
        self.assertIn("-audit.md |", text)
        self.assertNotIn("ancient", text)
        self.assertIn("| **Total** | | **0** | **2** | **1** | **5** |", text)

    def test_no_subagents_flag_disables_reading(self):
        text, _ = self.run_proposal("--no-subagents")
        self.assertIn("Subagent transcripts read: 0", text)
        self.assertNotIn("builder Bash", text)

    def test_max_subagents_caps_per_parent(self):
        self.write_sub("a", "2", [], meta='{"agentType": "scout"}')
        text, _ = self.run_proposal("--max-subagents", "1")
        self.assertIn("Subagent transcripts read: 2 (skipped by cap: 1)", text)

    def test_max_qa_reports_zero_disables(self):
        text, out = self.run_proposal("--max-qa-reports", "0", "--json")
        self.assertIn("No QA reports in the window", text)
        self.assertEqual(json.loads(out)["qa_reports"]["reports"], [])

    def test_empty_sections_have_messages(self):
        for f in (self.tmp / "docs" / "reports").iterdir():
            f.unlink()
        text, _ = self.run_proposal("--no-subagents")
        self.assertIn("No QA reports in the window", text)
        self.assertIn("None found (or subagent transcripts not read).", text)


if __name__ == "__main__":
    unittest.main()
