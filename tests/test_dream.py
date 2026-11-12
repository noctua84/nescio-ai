import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
sys.path.insert(0, str(ROOT / "scripts"))
import dream  # noqa: E402

FAKE_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3"


def assistant(*uses):
    """An assistant entry; each use is (id, name, input)."""
    blocks = [{"type": "tool_use", "id": i, "name": n, "input": inp} for i, n, inp in uses]
    return {"type": "assistant", "message": {"id": "m", "content": blocks}}


def dispatch(uid, agent):
    return assistant((uid, "Agent", {"subagent_type": agent}))


def report(agent, text, ts="2026-07-01T10:00:00Z"):
    return {
        "type": "user",
        "timestamp": ts,
        "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "content": "done"}]},
        "toolUseResult": {"agentType": agent, "content": [{"type": "text", "text": text}]},
    }


def verdict_text(verdict, deviations="None", oos="None"):
    return (
        f"<result><verdict>{verdict}</verdict><deviations>\n{deviations}\n</deviations>"
        f"<out-of-scope>\n{oos}\n</out-of-scope></result>"
    )


def human(text, **extra):
    return {"type": "user", "message": {"content": text}, **extra}


def tool_error(uid, text):
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": uid, "is_error": True, "content": text}]},
    }


class DreamTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.transcripts = self.tmp / "transcripts"
        self.transcripts.mkdir()
        self.config = self.tmp / "config"
        env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.config)})
        env.start()
        self.addCleanup(env.stop)

    def write(self, name, entries, raw=()):
        path = self.transcripts / f"{name}.jsonl"
        lines = [json.dumps(e) for e in entries] + list(raw)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def parse(self, name, entries, raw=()):
        return dream.parse_session(self.write(name, entries, raw))

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = dream.main([*argv, "--repo", str(self.tmp), "--transcripts", str(self.transcripts)])
        return rc, out.getvalue()


class ParseTest(DreamTestBase):
    def test_verdict_tally(self):
        a = self.parse("a", [report("builder", verdict_text("COMPLETE")), report("builder", verdict_text("BLOCKED"))])
        b = self.parse("b", [report("builder", verdict_text("COMPLETE")), report("scout", "no contract here")])
        agg = dream.aggregate([a, b])
        self.assertEqual(agg["verdicts"]["builder"], {"COMPLETE": 2, "BLOCKED": 1})
        self.assertEqual(agg["verdicts"]["scout"], {"none": 1})

    def test_inverted_pin_and_deferred_red_extracted(self):
        dev = "- Inverted pin: test_x state S via path P\n- Deferred red: test_y asserts Z\n- unrelated note"
        s = self.parse("a", [report("builder", verdict_text("PARTIAL", deviations=dev))])
        self.assertEqual(
            s["reports"][0]["flags"], ["Inverted pin: test_x state S via path P", "Deferred red: test_y asserts Z"]
        )

    def test_out_of_scope_skips_none_and_dedupes(self):
        s1 = self.parse("a", [report("builder", verdict_text("COMPLETE", oos="- Split big_file.py"))])
        s2 = self.parse("b", [report("builder", verdict_text("COMPLETE", oos="- split  big_file.py\nNone"))])
        agg = dream.aggregate([s1, s2])
        self.assertEqual(len(agg["follow_ups"]), 1)
        self.assertEqual(agg["follow_ups"][0]["sessions"], 2)

    def test_string_content_report_tolerated(self):
        entry = report("builder", "")
        entry["toolUseResult"]["content"] = verdict_text("COMPLETE")
        self.assertEqual(self.parse("a", [entry])["reports"][0]["verdict"], "COMPLETE")

    def test_malformed_line_skipped_and_counted(self):
        s = self.parse("a", [report("builder", verdict_text("COMPLETE"))], raw=["{not json", "[1, 2]"])
        self.assertEqual(s["malformed"], 2)
        self.assertEqual(len(s["reports"]), 1)

    def test_corrections_exclude_meta_tool_result_and_wrappers(self):
        s = self.parse("a", [
            human("No, use the other file"),
            human("Actually, revert that"),
            human("no way this was meta", isMeta=True),
            human("<command-name>/no</command-name>"),
            human("Nothing to correct here"),
            tool_error("t1", "boom"),
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "content": "No such file"}]}},
            human("[Request interrupted by user]"),
            human([{"type": "text", "text": "Stop doing that"}]),
        ])
        self.assertEqual(s["corrections"], 3)
        self.assertEqual(s["interrupts"], 1)

    def test_excerpts_capped_at_three_per_run(self):
        sessions = [self.parse(f"s{i}", [human(f"no {i}"), human(f"no again {i}")]) for i in range(3)]
        agg = dream.aggregate(sessions)
        self.assertEqual(agg["corrections"]["count"], 6)
        self.assertEqual(len(agg["corrections"]["excerpts"]), 3)

    def test_reverts_counted_once_per_tool_use(self):
        use = ("r1", "Bash", {"command": "git reset --hard HEAD~1"})
        s = self.parse("a", [
            assistant(use), assistant(use),  # re-emitted message
            assistant(("r2", "Bash", {"command": "git checkout -- file.py"})),
            assistant(("r3", "Bash", {"command": "git status"})),
        ])
        self.assertEqual(s["reverts"], 2)


class EscalationTest(DreamTestBase):
    def test_simple_to_standard_within_session(self):
        s = self.parse("a", [
            dispatch("d1", "builder-simple"),
            report("builder-simple", verdict_text("BLOCKED")),
            dispatch("d2", "builder-standard"),
        ])
        self.assertEqual(s["escalations"], [("builder", 0, 1)])

    def test_not_counted_across_sessions(self):
        a = self.parse("a", [dispatch("d1", "builder-simple"), report("builder-simple", verdict_text("BLOCKED"))])
        b = self.parse("b", [dispatch("d2", "builder-standard")])
        self.assertEqual(a["escalations"] + b["escalations"], [])

    def test_other_family_or_complete_is_not_escalation(self):
        s = self.parse("a", [
            report("builder-simple", verdict_text("COMPLETE")),
            dispatch("d1", "builder-standard"),
            report("scout-simple", verdict_text("BLOCKED")),
            dispatch("d2", "builder"),
        ])
        self.assertEqual(s["escalations"], [])

    def test_recurring_requires_min_sessions(self):
        def sess(name):
            return self.parse(name, [report("b-simple", verdict_text("PARTIAL")), dispatch(name, "b")])

        one = dream.aggregate([sess("a")], min_sessions=2)
        two = dream.aggregate([sess("a"), sess("b")], min_sessions=2)
        self.assertEqual([r for r in one["recurring"] if r["kind"] == "escalation"], [])
        esc = [r for r in two["recurring"] if r["kind"] == "escalation"]
        self.assertEqual(esc[0]["summary"], "b: simple→complex")
        self.assertEqual(esc[0]["sessions"], 2)


class ToolErrorTest(DreamTestBase):
    def _session(self, name, path):
        return self.parse(name, [
            assistant(("t1", "Read", {})),
            tool_error("t1", f"File does not exist: {path} (line 42)"),
        ])

    def test_signature_normalises_paths_and_numbers(self):
        a, b = dream.error_signature("File not found: /a/b/c.py at 123"), dream.error_signature("File not found: /x/y.py at 9")
        self.assertEqual(a, b)
        self.assertIn("<path>", a)

    def test_recurrence_across_two_sessions_meets_threshold(self):
        agg = dream.aggregate([self._session("a", "/p/one.py"), self._session("b", "/q/two.py")])
        errs = [r for r in agg["recurring"] if r["kind"] == "tool-error"]
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["sessions"], 2)
        self.assertTrue(errs[0]["summary"].startswith("Read:"))

    def test_single_session_does_not_meet_threshold(self):
        agg = dream.aggregate([self._session("a", "/p/one.py")])
        self.assertEqual([r for r in agg["recurring"] if r["kind"] == "tool-error"], [])
        self.assertEqual(len(agg["tool_errors"]), 1)


class PrivacyTest(DreamTestBase):
    def test_token_excerpt_is_redacted(self):
        s = self.parse("a", [human(f"No, the key is {FAKE_TOKEN}")])
        self.assertEqual(s["excerpts"], ["[redacted]"])

    def test_home_path_replaced_with_tilde(self):
        fake_home = self.tmp / "fakehome" / "someone"
        with mock.patch.object(Path, "home", return_value=fake_home):
            s = self.parse("a", [human(f"No, look at {fake_home}/proj and {str(fake_home).replace(os.sep, '/')}/x")])
        text = s["excerpts"][0]
        self.assertNotIn("someone", text)
        self.assertEqual(text.count("~"), 2)

    def test_excerpt_truncated(self):
        s = self.parse("a", [human("No " + "x" * 500)])
        self.assertLessEqual(len(s["excerpts"][0]), dream.EXCERPT_MAX)


class CliTest(DreamTestBase):
    def _state(self):
        files = list((self.config / "dreams").glob("*/last-dream.json"))
        return files[0] if files else None

    def test_no_stamp_leaves_no_watermark(self):
        self.write("a", [human("hi")])
        rc, _ = self.run_main("--no-stamp")
        self.assertEqual(rc, 0)
        self.assertIsNone(self._state())

    def test_stamp_writes_watermark_after_proposal(self):
        self.write("a", [human("hi")])
        rc, _ = self.run_main()
        self.assertEqual(rc, 0)
        state = self._state()
        self.assertIsNotNone(state)
        self.assertIn("since", json.loads(state.read_text(encoding="utf-8")))
        self.assertEqual(len(list(state.parent.glob("*.md"))), 1)

    def test_watermark_is_used_as_default_since(self):
        self.write("a", [human("hi")])
        self.run_main()
        # second run: the transcript predates the watermark, so nothing is read
        old = time.time() - 3600
        os.utime(self.transcripts / "a.jsonl", (old, old))
        _, out = self.run_main("--no-stamp", "--json")
        self.assertEqual(json.loads(out)["sessions_read"], 0)

    def test_max_sessions_cap_reports_skipped(self):
        for i in range(4):
            p = self.write(f"s{i}", [human("hi")])
            os.utime(p, (time.time() - i * 10, time.time() - i * 10))
        _, out = self.run_main("--no-stamp", "--json", "--max-sessions", "2")
        data = json.loads(out)
        self.assertEqual((data["sessions_read"], data["sessions_skipped"]), (2, 2))

    def test_empty_dir_exits_zero_and_says_so(self):
        out_path = self.tmp / "p.md"
        rc, _ = self.run_main("--no-stamp", "--out", str(out_path))
        self.assertEqual(rc, 0)
        self.assertIn("No transcripts found", out_path.read_text(encoding="utf-8"))

    def test_proposal_sections_present(self):
        self.write("a", [report("builder", verdict_text("COMPLETE"))])
        out_path = self.tmp / "p.md"
        self.run_main("--no-stamp", "--out", str(out_path))
        text = out_path.read_text(encoding="utf-8")
        for heading in ("## Recurring patterns", "## Agent verdicts", "## To confirm",
                        "## Candidate follow-ups", "## Suggested next steps"):
            self.assertIn(heading, text)
        self.assertIn("/harvest-memory", text)


class DiscoveryTest(DreamTestBase):
    def test_slug_matches_claude_code_scheme(self):
        self.assertEqual(dream.slug("D:\\work\\my.repo"), "D--work-my-repo")

    def test_transcript_dirs_select_main_and_worktree_slugs(self):
        projects = self.tmp / "projects"
        root = Path("/work/app")
        base = dream.slug(str(root))
        for name in (base, base + "--claude-worktrees-feat", base + "-other", "unrelated"):
            (projects / name).mkdir(parents=True)
        got = {d.name for d in dream.transcript_dirs(projects, root)}
        self.assertEqual(got, {base, base + "--claude-worktrees-feat"})

    def test_missing_projects_dir_yields_nothing(self):
        self.assertEqual(dream.transcript_dirs(self.tmp / "nope", Path("/x")), [])


if __name__ == "__main__":
    unittest.main()
