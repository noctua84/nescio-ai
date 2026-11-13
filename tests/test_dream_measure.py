"""Sidecar, ``--link`` and ``--compare`` for dream.py. Synthetic fixtures only."""

import contextlib
import io
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import _dream_measure as dm  # noqa: E402
import dream  # noqa: E402
from test_dream import DreamTestBase, assistant, dispatch, human, report, tool_error, verdict_text  # noqa: E402

H1, H2 = "a" * 12, "b" * 12
SIG = "0123abcd"


def ts(day):
    return datetime(2026, 7, day, tzinfo=timezone.utc)


def run(since, until, sessions, hits=None, sig=SIG, key="tool-error:Bash:boom", file=None):
    """A loaded run (as ``load_runs`` returns it); ``hits`` is the signal's session count."""
    signals = {sig: {"key": key, "sessions": hits, "count": hits}} if hits is not None else {}
    return {"file": file or f"{since}-{until}.json", "since": ts(since), "until": ts(until),
            "sessions_read": sessions, "signals": signals}


def sidecar(path, since, until, sessions, hits, sig=SIG, schema=1):
    data = {"schema": schema, "repo_key": "r", "since": f"2026-07-{since:02d}T00:00:00Z",
            "until": f"2026-07-{until:02d}T00:00:00Z", "sessions_read": sessions, "agent_dispatches": 0,
            "signals": {sig: {"key": "tool-error:Bash:boom", "sessions": hits, "count": hits}}}
    path.write_text(json.dumps(data), encoding="utf-8")


class SignalIdTest(unittest.TestCase):
    def test_stable_short_hex_and_distinct(self):
        a = dream.signal_id("tool-error:Bash:boom")
        self.assertEqual(a, dream.signal_id("tool-error:Bash:boom"))
        self.assertRegex(a, r"^[0-9a-f]{8}$")
        self.assertNotEqual(a, dream.signal_id("tool-error:Bash:bang"))


class SidecarTest(DreamTestBase):
    def _error_sessions(self, kinds):
        """One session whose Bash call fails with ``kinds`` distinct signatures."""
        uses = [(f"t{i}", "Bash", {}) for i in range(len(kinds))]
        return [assistant(*uses)] + [tool_error(f"t{i}", f"{k} failure") for i, k in enumerate(kinds)]

    def _sidecar(self, *argv):
        out = self.tmp / "p.md"
        self.run_main("--no-stamp", "--out", str(out), *argv)
        return json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))

    def test_json_out_is_refused_before_anything_is_written(self):
        out = self.tmp / "p.JSON"
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            self.run_main("--no-stamp", "--out", str(out))
        self.assertEqual(cm.exception.code, 2)
        self.assertFalse(out.exists())

    def test_sidecar_lists_every_signal_not_only_top_five(self):
        kinds = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"]
        self.write("a", self._error_sessions(kinds))
        data = self._sidecar()
        self.assertEqual(len(dream.aggregate([self.parse("a", self._error_sessions(kinds))])["tool_errors"]), 5)
        keys = {v["key"] for v in data["signals"].values()}
        self.assertEqual(keys, {f"tool-error:Bash:{k} failure" for k in kinds})
        for sid, v in data["signals"].items():
            self.assertEqual(sid, dream.signal_id(v["key"]))
            self.assertEqual((v["sessions"], v["count"]), (1, 1))

    def test_schema_fields_and_counts(self):
        self.write("a", [dispatch("d1", "builder"), report("builder", verdict_text("COMPLETE"))])
        data = self._sidecar()
        self.assertEqual(data["schema"], 1)
        self.assertEqual((data["sessions_read"], data["agent_dispatches"]), (1, 1))
        for field in ("repo_key", "since", "until"):
            self.assertIn(field, data)

    def test_every_signal_kind_has_a_stable_key(self):
        pins = "- Inverted pin: test_x state S via path P"
        self.write("a", [
            # The opening message is never a correction (signal-quality rule).
            human("Please fix the parser"),
            dispatch("d1", "b-simple"),
            report("b-simple", verdict_text("BLOCKED", deviations=pins)),
            dispatch("d2", "b"),
            report("b", verdict_text("PARTIAL")),
            human("Please tidy the build script"),  # the opening message is never a correction
            human("No, use the other file"),
            human("[Request interrupted by user]"),
            assistant(("r1", "Bash", {"command": "git reset --hard"})),
        ])
        keys = {v["key"]: v for v in self._sidecar()["signals"].values()}
        self.assertEqual(
            set(keys),
            {"escalation:b:simple->complex", "blocked:b-simple", "partial:b", "inverted-pins",
             "corrections", "reverts", "interrupts"},
        )
        self.assertEqual(keys["corrections"]["sessions"], 1)

    def test_verdict_and_error_keys_count_distinct_sessions(self):
        for name in ("a", "b"):
            first, second = report("b", verdict_text("BLOCKED")), report("b", verdict_text("BLOCKED"))
            second["toolUseResult"]["agentId"] = "agent-2"  # a second dispatch; an identical (id, text) pair counts once
            self.write(name, [first, second])
        table = dream.signal_table([dream.parse_session(self.transcripts / f"{n}.jsonl") for n in "ab"])
        entry = table[dream.signal_id("blocked:b")]
        self.assertEqual((entry["sessions"], entry["count"]), (2, 4))

    def test_sidecar_written_with_proposal_and_watermark(self):
        self.write("a", [human("hi")])
        self.run_main()
        state = next((self.config / "dreams").glob("*/last-dream.json")).parent
        self.assertEqual(len(list(state.glob("2*.json"))), 1)
        self.assertEqual(len(list(state.glob("*.md"))), 1)

    def test_no_raw_text_in_sidecar(self):
        self.write("a", [human("No, the secret plan is zebra")])
        self.assertNotIn("zebra", json.dumps(self._sidecar()))

    def test_render_shows_sig_ids_matching_sidecar(self):
        for name in ("a", "b"):
            self.write(name, self._error_sessions(["alpha"]))
        out = self.tmp / "p.md"
        self.run_main("--no-stamp", "--out", str(out))
        sid = dream.signal_id("tool-error:Bash:alpha failure")
        line = next(ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.startswith("- [tool-error]"))
        self.assertTrue(line.endswith(f"(2 sessions) [sig {sid}]"), line)
        self.assertIn(sid, json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["signals"])

    def test_aggregate_recurring_entries_carry_ids(self):
        sessions = [self.parse(n, [human("No, x"), human("No, y")]) for n in ("a", "b")]
        rec = dream.aggregate(sessions)["recurring"]
        self.assertEqual([r["id"] for r in rec], [dream.signal_id("corrections")])


class LinkTest(DreamTestBase):
    def _links(self):
        files = list((self.config / "dreams").glob("*/links.json"))
        return json.loads(files[0].read_text(encoding="utf-8")) if files else None

    def test_link_appends_and_is_idempotent(self):
        rc, out = self.run_main("--link", H1, SIG)
        self.assertEqual(rc, 0)
        self.assertIn("linked", out)
        self.run_main("--link", H1, SIG)
        self.run_main("--link", H2, SIG)
        links = self._links()
        self.assertEqual([(x["hash"], x["sig"]) for x in links], [(H1, SIG), (H2, SIG)])
        self.assertRegex(links[0]["linked_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_bad_arguments_rejected_with_rc_2(self):
        for h, s in (("A" * 12, SIG), ("a" * 11, SIG), (H1, "0123ABCD"), (H1, "0123abc"), ("g" * 12, SIG)):
            rc, out = self.run_main("--link", h, s)
            self.assertEqual(rc, 2, (h, s))
            self.assertIn("error", out)
        self.assertIsNone(self._links())

    def test_link_does_not_run_extractor(self):
        self.write("a", [human("hi")])
        self.run_main("--link", H1, SIG)
        state = next((self.config / "dreams").glob("*"))
        self.assertEqual([p.name for p in state.iterdir()], ["links.json"])

    def test_corrupt_links_file_is_refused_not_overwritten(self):
        self.run_main("--link", H1, SIG)
        path = next((self.config / "dreams").glob("*/links.json"))
        path.write_text("{not json", encoding="utf-8")
        rc, out = self.run_main("--link", H2, SIG)
        self.assertEqual(rc, 2)
        self.assertEqual(path.read_text(encoding="utf-8"), "{not json")


class SelectRunsTest(unittest.TestCase):
    def test_sorted_by_until_and_adjacent_windows_kept(self):
        got = dm.select_runs([run(10, 15, 5), run(1, 5, 5), run(5, 10, 5)])
        self.assertEqual([(r["since"].day, r["until"].day) for r in got], [(1, 5), (5, 10), (10, 15)])

    def test_overlapping_rerun_dropped(self):
        got = dm.select_runs([run(1, 5, 5), run(1, 6, 5, file="rerun"), run(6, 9, 5)])
        self.assertEqual([r["until"].day for r in got], [5, 9])

    def test_load_runs_skips_bad_files_and_state_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            sidecar(state / "ok.json", 1, 5, 4, 2)
            sidecar(state / "old.json", 1, 5, 4, 2, schema=2)
            (state / "bad.json").write_text("{nope", encoding="utf-8")
            (state / "list.json").write_text("[]", encoding="utf-8")
            (state / "last-dream.json").write_text('{"since": "2026-07-05T00:00:00Z"}', encoding="utf-8")
            (state / "links.json").write_text("[]", encoding="utf-8")
            runs, skipped = dm.load_runs(state)
        self.assertEqual([r["file"] for r in runs], ["ok.json"])
        self.assertEqual(skipped, 3)
        self.assertEqual(dm.load_runs(Path(d))[0], [])  # directory is gone: nothing, no crash


class CompareTest(unittest.TestCase):
    LEDGER = {H1: "2026-07-10"}
    LINK = [{"hash": H1, "sig": SIG, "linked_at": "2026-07-20T00:00:00Z"}]

    def one(self, runs, ledger=None, links=None, min_after=10):
        got = dm.compare(runs, links or self.LINK, self.LEDGER if ledger is None else ledger, min_after)
        self.assertEqual(len(got), 1)
        return got[0]

    def test_working_when_rate_halves(self):
        r = self.one([run(1, 10, 20, hits=10), run(10, 20, 20, hits=5)])
        self.assertEqual(r["verdict"], "working")
        self.assertEqual((r["before"]["rate"], r["after"]["rate"]), (0.5, 0.25))
        self.assertEqual(r["key"], "tool-error:Bash:boom")

    def test_ineffective_when_rate_does_not_drop(self):
        self.assertEqual(self.one([run(1, 10, 20, hits=4), run(10, 20, 20, hits=4)])["verdict"], "ineffective")
        self.assertEqual(self.one([run(1, 10, 20, hits=4), run(10, 20, 20, hits=9)])["verdict"], "ineffective")

    def test_unclear_between_half_and_unchanged(self):
        self.assertEqual(self.one([run(1, 10, 20, hits=10), run(10, 20, 20, hits=7)])["verdict"], "unclear")

    def test_too_early_when_few_after_sessions(self):
        r = self.one([run(1, 10, 20, hits=10), run(10, 20, 9, hits=0)])
        self.assertEqual(r["verdict"], "too early")
        self.assertEqual(self.one([run(1, 10, 20, hits=10), run(10, 20, 9, hits=0)], min_after=9)["verdict"], "working")

    def test_no_baseline_without_before_runs_or_signal(self):
        self.assertEqual(self.one([run(10, 20, 30, hits=1)])["verdict"], "no baseline")
        # baseline sessions exist but the signal never occurred: not "ineffective"
        self.assertEqual(self.one([run(1, 10, 20, hits=None), run(10, 20, 20, hits=0)])["verdict"], "no baseline")

    def test_straddling_run_counts_for_neither_side(self):
        r = self.one([run(1, 10, 20, hits=10), run(8, 14, 100, hits=100, file="x"), run(10, 20, 20, hits=2)])
        self.assertEqual((r["before"]["sessions"], r["after"]["sessions"]), (20, 20))
        straddle = dm.compare([run(1, 6, 20, hits=10), run(6, 14, 50, hits=50), run(14, 20, 20, hits=1)],
                              self.LINK, self.LEDGER, 10)[0]
        self.assertEqual(straddle["before"]["sessions"], 20)
        self.assertEqual(straddle["after"]["sessions"], 20)

    def test_runs_ending_or_starting_on_the_date_belong_to_a_side(self):
        r = self.one([run(5, 10, 10, hits=5), run(10, 15, 10, hits=1)])
        self.assertEqual((r["before"]["sessions"], r["after"]["sessions"]), (10, 10))

    def test_ledger_date_wins_over_linked_at(self):
        r = self.one([run(1, 10, 20, hits=10), run(10, 20, 20, hits=1)])
        self.assertEqual((r["date"], r["date_source"]), ("2026-07-10", "ledger"))

    def test_falls_back_to_linked_at_when_hash_not_in_ledger(self):
        runs = [run(1, 20, 20, hits=10), run(20, 30, 20, hits=1)]
        r = self.one(runs, ledger={})
        self.assertEqual((r["date"], r["date_source"], r["verdict"]), ("2026-07-20", "linked_at", "working"))
        self.assertIn("not in the ledger", dm.render([r]))
        self.assertNotIn("not in the ledger", dm.render([self.one(runs)]))

    def test_unparseable_ledger_date_falls_back(self):
        self.assertEqual(self.one([run(1, 5, 5, hits=1)], ledger={H1: "sometime"})["date_source"], "linked_at")

    def test_unseen_signal_and_render_truncates_key(self):
        r = self.one([run(1, 10, 20, hits=None)])
        self.assertIsNone(r["key"])
        long = self.one([run(1, 10, 20, hits=10, key="k" * 200), run(10, 20, 20, hits=1, key="k" * 200)])
        table = dm.render([long])
        self.assertIn("k" * 59 + "…", table)
        self.assertNotIn("k" * 61, table)
        self.assertIn("| working |", table)

    def test_render_empty(self):
        self.assertIn("No links recorded", dm.render([]))


class CompareCliTest(DreamTestBase):
    def _state(self):
        self.run_main("--link", H1, SIG)
        return next((self.config / "dreams").glob("*"))

    def _ledger(self, date="2026-07-10"):
        path = self.tmp / "learning-log.md"
        path.write_text(f"- {date} | feedback/x.md | {H1} | promoted: x\n", encoding="utf-8")
        return path

    def test_compare_end_to_end_json_and_table(self):
        state = self._state()
        sidecar(state / "1.json", 1, 10, 20, 10)
        sidecar(state / "2.json", 10, 20, 20, 2)
        sidecar(state / "3.json", 10, 18, 20, 2)  # overlapping rerun: dropped
        (state / "junk.json").write_text("{", encoding="utf-8")
        ledger = self._ledger()
        rc, out = self.run_main("--compare", "--ledger", str(ledger), "--json")
        self.assertEqual(rc, 0)
        self.assertEqual([(r["hash"], r["verdict"]) for r in json.loads(out)], [(H1, "working")])
        rc, out = self.run_main("--compare", "--ledger", str(ledger))
        self.assertIn(f"| {H1} | tool-error:Bash:boom | 50% (20 sessions) | 10% (20 sessions) | working |", out)
        self.assertIn("dropped as overlapping: 1; unreadable or other schema: 1", out)

    def test_compare_does_not_run_extractor_or_move_watermark(self):
        state = self._state()
        self.write("a", [human("hi")])
        self.run_main("--compare", "--ledger", str(self._ledger()))
        self.assertEqual([p.name for p in state.iterdir()], ["links.json"])

    def test_compare_with_no_links_or_missing_ledger_is_rc_0(self):
        rc, out = self.run_main("--compare", "--ledger", str(self.tmp / "nope.md"))
        self.assertEqual(rc, 0)
        self.assertIn("No links recorded", out)
        self._state()
        rc, out = self.run_main("--compare", "--ledger", str(self.tmp / "nope.md"), "--json")
        self.assertEqual(json.loads(out)[0]["date_source"], "linked_at")


if __name__ == "__main__":
    unittest.main()
