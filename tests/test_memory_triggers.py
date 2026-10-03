"""`scripts/check_memory_triggers.py` — ADR 0002's four revisit triggers (#168).

Hermetic throughout: every test builds its own `memory/` tree and its own
transcript corpus in a `tempfile.TemporaryDirectory()`, and points
`CLAUDE_CONFIG_DIR` at a temp directory so neither the operator's real brain nor
their real `~/.claude` is read or written.

Three groups carry most of the weight:

* **The privacy group** is the reason this file exists at all. The repo is
  public and the script reads transcripts containing arbitrary user content,
  absolute paths, and operator-configured MCP server names. The headline test
  feeds the scanner a corpus seeded with `mcp__`-named tools and asserts that no
  emitted line — report or JSON — contains one.

* **The matcher group** pins the two false-positive classes the naive
  `"memory/" in cmd` test admitted (a `grep` *pattern* that is the word
  "memory", and a sibling directory ending in it) and the false *negative* that
  naive separator splitting caused (a quoted regex alternation tearing a command
  in half). Each of those was measured against the real corpus, so each gets a
  test rather than a comment.

* **The `unknown` group** pins the ADR 0004 discipline: an absent tally and an
  unscannable corpus must report `unknown`, never a clean verdict, and T4 must
  never be able to fire.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_memory_triggers as cmt  # noqa: E402
import _trail_scope  # noqa: E402
import _unrouted_record as ur  # noqa: E402

sys.path.insert(0, str(ROOT / "hooks"))
import record_stop as rs  # noqa: E402

NOTE = "---\nname: {name}\ndescription: A note.\ntype: feedback\n---\n\nBody.\n"


def _seed_notes(memory: Path, rel_dir: str, count: int) -> None:
    """Create ``count`` indexable notes in ``memory/<rel_dir>``, plus a MEMORY.md.

    The `MEMORY.md` is written deliberately: it must NOT be counted as a note,
    because `_wiki_common.iter_notes` skips it and the whole point of sourcing
    the count from that iterator is that the reported number and the indexed
    number agree.
    """
    target = memory / rel_dir if rel_dir != "." else memory
    target.mkdir(parents=True, exist_ok=True)
    (target / "MEMORY.md").write_text("# index\n", encoding="utf-8", newline="")
    for i in range(count):
        (target / f"note-{i:03d}.md").write_text(
            NOTE.format(name=f"{rel_dir}-{i}"), encoding="utf-8", newline=""
        )


def _tool_use(name: str, inp: dict) -> dict:
    return {"type": "tool_use", "id": "tu_1", "name": name, "input": inp}


def _record(session: str, cwd: str, blocks: list, ts: str | None = "2026-10-03T10:00:00Z") -> dict:
    rec = {
        "sessionId": session,
        "cwd": cwd,
        "type": "assistant",
        "message": {"role": "assistant", "content": blocks},
    }
    if ts is not None:
        rec["timestamp"] = ts
    return rec


def _write_transcript(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        for rec in records:
            handle.write(json.dumps(rec) + "\n")


class _Harness(unittest.TestCase):
    """A temp repo with a `memory/` tree, a temp config dir, and a transcript dir."""

    def setUp(self):
        self._repo_tmp = tempfile.TemporaryDirectory()
        self._cfg_tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._repo_tmp.name) / "brain"
        self.memory = self.repo / "memory"
        self.memory.mkdir(parents=True)
        self.transcripts = Path(self._cfg_tmp.name) / "projects"
        self.transcripts.mkdir(parents=True)
        self._saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = self._cfg_tmp.name

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self._saved
        self._repo_tmp.cleanup()
        self._cfg_tmp.cleanup()

    @property
    def repo_cwd(self) -> str:
        """The repo root the CLI will scope transcripts to, for seeding `cwd`.

        Derived the same way `main()` derives it rather than hardcoded, so a
        test exercising the CLI exercises the real attribution wiring instead of
        a parallel assumption about it.
        """
        return _trail_scope.posix_path(rs.git_roots(str(self.repo))[1])

    def run_cli(self, *extra) -> tuple[int, str]:
        """Invoke `main()` with stdout captured; return (rc, output)."""
        argv = ["--memory-root", str(self.memory), *extra]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmt.main(argv)
        return rc, buf.getvalue()


# ── T1 / T2: the computable triggers ───────────────────────────────────────


class NoteCountingTest(_Harness):
    def test_counts_what_a_memory_index_indexes_not_every_md_file(self):
        _seed_notes(self.memory, "repo/x", 3)
        total, per_dir = cmt.count_notes(self.memory)
        self.assertEqual(total, 3, "MEMORY.md must not be counted as a note")
        self.assertEqual(per_dir, {"repo/x": 3})

    def test_directory_counts_sum_to_the_corpus(self):
        _seed_notes(self.memory, "repo/x", 4)
        _seed_notes(self.memory, "repo/x/adr", 2)
        _seed_notes(self.memory, "feedback", 5)
        total, per_dir = cmt.count_notes(self.memory)
        self.assertEqual(sum(per_dir.values()), total)
        self.assertEqual(total, 11)

    def test_a_subdirectory_is_its_own_unit_because_it_has_its_own_index(self):
        _seed_notes(self.memory, "repo/x", 4)
        _seed_notes(self.memory, "repo/x/adr", 2)
        _, per_dir = cmt.count_notes(self.memory)
        self.assertEqual(per_dir["repo/x"], 4, "adr/ must not roll up into repo/x")
        self.assertEqual(per_dir["repo/x/adr"], 2)

    def test_dot_directories_are_skipped(self):
        _seed_notes(self.memory, "repo/x", 2)
        _seed_notes(self.memory, ".obsidian", 9)
        total, _ = cmt.count_notes(self.memory)
        self.assertEqual(total, 2)


class DirectoryTriggerTest(unittest.TestCase):
    def test_fires_at_the_limit_not_one_past_it(self):
        self.assertEqual(
            cmt.check_directory_size({"repo/x": 100}, limit=100).verdict,
            cmt.VERDICT_FIRED,
        )
        self.assertEqual(
            cmt.check_directory_size({"repo/x": 99}, limit=100).verdict,
            cmt.VERDICT_CLEAR,
        )

    def test_a_clear_verdict_still_reports_the_margin(self):
        result = cmt.check_directory_size({"repo/x": 80}, limit=100)
        self.assertEqual(result.verdict, cmt.VERDICT_CLEAR)
        self.assertIn("80 notes", " ".join(result.detail))
        self.assertIn("80%", " ".join(result.detail))

    def test_names_the_largest_directory(self):
        result = cmt.check_directory_size({"a": 5, "b": 40, "c": 12}, limit=100)
        self.assertIn("memory/b — 40 notes", " ".join(result.detail))

    def test_an_empty_corpus_is_unknown_not_clear(self):
        result = cmt.check_directory_size({}, limit=100)
        self.assertEqual(result.verdict, cmt.VERDICT_UNKNOWN)


class CorpusTriggerTest(unittest.TestCase):
    def test_fires_at_the_limit(self):
        self.assertEqual(
            cmt.check_corpus_size(500, limit=500).verdict, cmt.VERDICT_FIRED
        )
        self.assertEqual(
            cmt.check_corpus_size(499, limit=500).verdict, cmt.VERDICT_CLEAR
        )

    def test_a_fired_trigger_sets_rc_one(self):
        self.assertTrue(cmt.check_corpus_size(500, limit=500).fired)


class ExitCodeTest(_Harness):
    def test_clear_corpus_exits_zero(self):
        _seed_notes(self.memory, "repo/x", 3)
        rc, out = self.run_cli("--skip-transcripts")
        self.assertEqual(rc, cmt.EXIT_PASS, out)

    def test_a_fired_trigger_exits_one(self):
        _seed_notes(self.memory, "repo/big", cmt.DIR_NOTE_LIMIT)
        rc, out = self.run_cli("--skip-transcripts")
        self.assertEqual(rc, cmt.EXIT_FIRED, out)
        self.assertIn("FIRED", out)

    def test_an_unreadable_memory_root_exits_two(self):
        """A mistyped --memory-root must not report a clean corpus of 0.

        `Path.rglob` on a missing directory yields nothing rather than raising,
        so without the explicit check this exits 0 with `t2 clear`.

        stderr is captured as well as stdout: exit 2 names its reason there by
        design, and a diagnostic printed into the suite's own stderr would undo
        #163's pristine-output work.
        """
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmt.main(
                ["--memory-root", str(self.repo / "nope"), "--skip-transcripts"]
            )
        self.assertEqual(rc, cmt.EXIT_ERROR)
        self.assertIn("could not check", err.getvalue())

    def test_unknown_verdicts_alone_never_exit_one(self):
        """T3 and T4 both read `unknown` here; rc must stay 0."""
        _seed_notes(self.memory, "repo/x", 1)
        rc, out = self.run_cli("--skip-transcripts")
        self.assertEqual(rc, cmt.EXIT_PASS, out)
        self.assertIn("unknown t3-unrouted-harvest", out)
        self.assertIn("unknown t4-index-bypass", out)
        self.assertIn("not clean bills", out)


# ── T3: the unrouted tally ─────────────────────────────────────────────────


class UnroutedTriggerTest(_Harness):
    def test_an_absent_tally_is_unknown_not_clear(self):
        result = cmt.check_unrouted(self.repo / "nothing-here.json")
        self.assertEqual(result.verdict, cmt.VERDICT_UNKNOWN)
        self.assertEqual(result.reason, "no-record")
        self.assertNotEqual(result.verdict, cmt.VERDICT_CLEAR)

    def test_a_recorded_count_fires(self):
        path = Path(self._cfg_tmp.name) / "t.unrouted.json"
        ur.append_unrouted(path, reason="no owner", name="n", date="2026-10-03")
        result = cmt.check_unrouted(path)
        self.assertEqual(result.verdict, cmt.VERDICT_FIRED)
        self.assertTrue(result.fired)
        self.assertIn("1 unrouted learning(s)", " ".join(result.detail))

    def test_the_cli_reads_the_tally_for_the_memory_roots_repo(self):
        _seed_notes(self.memory, "repo/x", 1)
        ur.append_unrouted(
            ur.record_path(self.repo), reason="no owner", name="n", date="2026-10-03"
        )
        rc, out = self.run_cli("--skip-transcripts")
        self.assertEqual(rc, cmt.EXIT_FIRED, out)
        self.assertIn("FIRED   t3-unrouted-harvest", out)


# ── T4: the matchers ───────────────────────────────────────────────────────


class MemoryPathMatcherTest(unittest.TestCase):
    def test_structured_values_accept_a_bare_memory_directory(self):
        self.assertTrue(cmt.is_memory_path("memory"))
        self.assertTrue(cmt.is_memory_path("memory/repo/x"))
        self.assertTrue(cmt.is_memory_path("C:/p/brain/memory/repo"))
        self.assertTrue(cmt.is_memory_path(r"C:\p\brain\memory\repo"))

    def test_structured_values_reject_a_lookalike_directory(self):
        self.assertFalse(cmt.is_memory_path("skills/harvest-memory"))
        self.assertFalse(cmt.is_memory_path("memory-bank/x"))
        self.assertFalse(cmt.is_memory_path(""))
        self.assertFalse(cmt.is_memory_path(None))


class ShellSearchMatcherTest(unittest.TestCase):
    def test_a_search_against_memory_is_a_hit(self):
        for cmd in (
            "grep -rn 'x' memory/repo/foo.md",
            "rg pattern memory/",
            r"findstr /s x memory\repo",
            "find C:/p/brain/memory -name '*.md'",
            "cd /p/brain && grep -n x memory/notes.md",
        ):
            self.assertTrue(cmt.shell_searches_memory(cmd), cmd)

    def test_a_grep_pattern_that_is_the_word_memory_is_not_a_hit(self):
        """Measured false positive: `grep -n "memory" install.py`."""
        self.assertFalse(cmt.shell_searches_memory('grep -n "memory" install.py'))

    def test_a_sibling_directory_ending_in_memory_is_not_a_hit(self):
        """Measured false positive: `find .../skills/harvest-memory`."""
        self.assertFalse(
            cmt.shell_searches_memory("find /p/skills/harvest-memory -type f")
        )

    def test_a_search_in_a_different_segment_is_not_a_hit(self):
        """Measured false positive, and ~70% of the naive count on the real
        corpus: a compound command where the search never touched memory/."""
        for cmd in (
            "git diff -- memory/repo/x.md && echo done | grep -v warning",
            'git add -A 2>&1 | grep -v "^warning:"\ncat memory/x.md',
            "cat memory/x.md && ls tests/ | grep py",
        ):
            self.assertFalse(cmt.shell_searches_memory(cmd), cmd)

    def test_a_quoted_alternation_does_not_tear_the_command_apart(self):
        """Measured false NEGATIVE: naive `|` splitting separated `grep` from its
        own memory operand, dropping a genuine search."""
        self.assertTrue(
            cmt.shell_searches_memory(
                r'grep -n "24\|forfeit" memory/projects/rules.md'
            )
        )

    def test_a_quoted_memory_path_still_matches(self):
        self.assertTrue(cmt.shell_searches_memory('grep -n x "memory/notes.md"'))

    def test_a_piped_search_over_an_already_located_note_is_not_a_hit(self):
        """`cat memory/x | grep y` searches a note's *contents*; the agent had
        already routed to the path, so the index did not fail."""
        self.assertFalse(cmt.shell_searches_memory("cat memory/x.md | grep y"))

    def test_non_search_commands_are_never_hits(self):
        for cmd in (
            "cat memory/repo/x.md",
            "git log -- memory/",
            "ls memory/repo",
            "",
        ):
            self.assertFalse(cmt.shell_searches_memory(cmd), cmd)


class BlockClassificationTest(unittest.TestCase):
    def test_grep_pattern_is_not_treated_as_a_path(self):
        """`Grep.pattern` is content to match; `Glob.pattern` is a path glob."""
        tier, _ = cmt.classify_block(
            _tool_use("Grep", {"pattern": "memory/x", "path": "scripts"})
        )
        self.assertIsNone(tier)

    def test_grep_path_is_a_structured_hit(self):
        tier, _ = cmt.classify_block(_tool_use("Grep", {"pattern": "x", "path": "memory"}))
        self.assertEqual(tier, "structured")

    def test_glob_pattern_is_a_structured_hit(self):
        tier, _ = cmt.classify_block(_tool_use("Glob", {"pattern": "memory/**/*.md"}))
        self.assertEqual(tier, "structured")

    def test_a_bash_search_is_a_shell_hit(self):
        tier, _ = cmt.classify_block(
            _tool_use("Bash", {"command": "rg x memory/repo"})
        )
        self.assertEqual(tier, "shell")

    def test_reading_an_index_is_not_a_search(self):
        tier, reads_index = cmt.classify_block(
            _tool_use("Read", {"file_path": "/p/brain/memory/repo/x/MEMORY.md"})
        )
        self.assertIsNone(tier)
        self.assertTrue(reads_index)

    def test_grepping_the_index_is_a_search_not_an_index_read(self):
        """Letting a bypass count as its own justification would make the
        post-index refinement self-fulfilling."""
        tier, reads_index = cmt.classify_block(
            _tool_use("Grep", {"pattern": "x", "path": "memory/repo/x/MEMORY.md"})
        )
        self.assertEqual(tier, "structured")
        self.assertFalse(reads_index)

    def test_reading_a_plain_note_is_neither(self):
        tier, reads_index = cmt.classify_block(
            _tool_use("Read", {"file_path": "/p/brain/memory/repo/x/note.md"})
        )
        self.assertIsNone(tier)
        self.assertFalse(reads_index)


# ── T4: the scan ───────────────────────────────────────────────────────────


class ScanTest(_Harness):
    CWD = "C:/p/brain"

    def _scan(self) -> cmt.Scan:
        return cmt.scan_transcripts(self.transcripts, self.CWD)

    def test_a_session_spanning_many_files_is_counted_once(self):
        """Subagent transcripts carry the PARENT's sessionId."""
        _write_transcript(
            self.transcripts / "proj" / "s1.jsonl",
            [_record("s1", self.CWD, [_tool_use("Grep", {"path": "memory"})])],
        )
        _write_transcript(
            self.transcripts / "proj" / "s1" / "subagents" / "agent-a.jsonl",
            [_record("s1", self.CWD, [_tool_use("Grep", {"path": "memory"})])],
        )
        _write_transcript(
            self.transcripts / "proj" / "s1" / "subagents" / "agent-b.jsonl",
            [_record("s1", self.CWD, [_tool_use("Grep", {"path": "memory"})])],
        )
        scan = self._scan()
        self.assertEqual(scan.files, 3)
        self.assertEqual(scan.sessions, 1, "three files, one session")
        self.assertEqual(scan.memory_sessions, 1)
        self.assertEqual(scan.structured_calls, 3)

    def test_the_denominator_is_not_the_memory_session_count(self):
        """The bug this test exists for: deriving the denominator from sessions
        that touched memory/ makes the broad rate 100% by construction."""
        _write_transcript(
            self.transcripts / "p" / "s1.jsonl",
            [_record("s1", self.CWD, [_tool_use("Grep", {"path": "memory"})])],
        )
        for i in range(4):
            _write_transcript(
                self.transcripts / "p" / f"s{i + 2}.jsonl",
                [_record(f"s{i + 2}", self.CWD, [_tool_use("Read", {"file_path": "x.py"})])],
            )
        scan = self._scan()
        self.assertEqual(scan.sessions, 5)
        self.assertEqual(scan.memory_sessions, 1)
        self.assertLess(scan.memory_sessions, scan.sessions)

    def test_sessions_outside_the_repo_are_not_counted(self):
        _write_transcript(
            self.transcripts / "other" / "s9.jsonl",
            [_record("s9", "C:/p/unrelated", [_tool_use("Grep", {"path": "memory"})])],
        )
        scan = self._scan()
        self.assertEqual(scan.sessions, 0)
        self.assertEqual(scan.memory_sessions, 0)

    def test_a_worktree_cwd_attributes_to_the_repository(self):
        _write_transcript(
            self.transcripts / "wt" / "s1.jsonl",
            [
                _record(
                    "s1",
                    f"{self.CWD}/.claude/worktrees/feature-x",
                    [_tool_use("Grep", {"path": "memory"})],
                )
            ],
        )
        self.assertEqual(self._scan().memory_sessions, 1)

    def test_a_subdirectory_cwd_attributes_to_the_repository(self):
        _write_transcript(
            self.transcripts / "sub" / "s1.jsonl",
            [_record("s1", f"{self.CWD}/scripts", [_tool_use("Grep", {"path": "memory"})])],
        )
        self.assertEqual(self._scan().memory_sessions, 1)

    def test_a_search_after_an_index_read_is_post_index(self):
        _write_transcript(
            self.transcripts / "p" / "s1.jsonl",
            [
                _record(
                    "s1",
                    self.CWD,
                    [_tool_use("Read", {"file_path": "memory/repo/x/MEMORY.md"})],
                    ts="2026-10-03T10:00:00Z",
                ),
                _record(
                    "s1",
                    self.CWD,
                    [_tool_use("Grep", {"path": "memory"})],
                    ts="2026-10-03T10:05:00Z",
                ),
            ],
        )
        scan = self._scan()
        self.assertEqual(scan.search_sessions, 1)
        self.assertEqual(scan.post_index_sessions, 1)

    def test_a_cold_search_is_counted_broadly_but_not_post_index(self):
        """The distinction the trigger's causal clause demands."""
        _write_transcript(
            self.transcripts / "p" / "s1.jsonl",
            [_record("s1", self.CWD, [_tool_use("Grep", {"path": "memory"})])],
        )
        scan = self._scan()
        self.assertEqual(scan.search_sessions, 1)
        self.assertEqual(scan.post_index_sessions, 0)

    def test_an_untimed_search_never_establishes_ordering(self):
        _write_transcript(
            self.transcripts / "p" / "s1.jsonl",
            [
                _record(
                    "s1",
                    self.CWD,
                    [_tool_use("Read", {"file_path": "memory/repo/x/MEMORY.md"})],
                ),
                _record("s1", self.CWD, [_tool_use("Grep", {"path": "memory"})], ts=None),
            ],
        )
        scan = self._scan()
        self.assertEqual(scan.search_sessions, 1)
        self.assertEqual(scan.post_index_sessions, 0, "under-report, never guess")

    def test_structured_and_shell_tiers_are_reported_separately(self):
        _write_transcript(
            self.transcripts / "p" / "s1.jsonl",
            [
                _record("s1", self.CWD, [_tool_use("Grep", {"path": "memory"})]),
                _record("s1", self.CWD, [_tool_use("Bash", {"command": "rg x memory/"})]),
            ],
        )
        scan = self._scan()
        self.assertEqual(scan.structured_calls, 1)
        self.assertEqual(scan.shell_calls, 1)
        self.assertEqual(scan.search_calls, 2)

    def test_malformed_lines_and_records_do_not_derail_the_scan(self):
        path = self.transcripts / "p" / "s1.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write("not json at all\n")
            handle.write('["a list, not an object with memory/ tool_use"]\n')
            handle.write("\n")
            handle.write(
                json.dumps(
                    _record("s1", self.CWD, [_tool_use("Grep", {"path": "memory"})])
                )
                + "\n"
            )
        scan = self._scan()
        self.assertEqual(scan.memory_sessions, 1)
        self.assertEqual(scan.structured_calls, 1)

    def test_a_missing_transcript_dir_is_unknown_not_zero(self):
        scan = cmt.scan_transcripts(self.transcripts / "gone", self.CWD)
        self.assertFalse(scan.scanned)
        self.assertEqual(scan.reason, "no-transcripts")
        self.assertEqual(cmt.check_index_bypass(scan).verdict, cmt.VERDICT_UNKNOWN)

    def test_any_repo_widens_the_scope(self):
        _write_transcript(
            self.transcripts / "other" / "s9.jsonl",
            [_record("s9", "C:/p/unrelated", [_tool_use("Grep", {"path": "memory"})])],
        )
        self.assertEqual(cmt.scan_transcripts(self.transcripts, "").memory_sessions, 1)


class BypassTriggerNeverFiresTest(unittest.TestCase):
    def test_t4_cannot_fire_however_high_the_rate(self):
        scan = cmt.Scan(
            files=1,
            sessions=10,
            memory_sessions=10,
            search_sessions=10,
            post_index_sessions=10,
            structured_calls=10,
        )
        result = cmt.check_index_bypass(scan)
        self.assertEqual(result.verdict, cmt.VERDICT_UNKNOWN)
        self.assertEqual(result.reason, "uncalibrated")
        self.assertFalse(result.can_fire)
        self.assertFalse(result.fired)
        self.assertIn("NOT CALIBRATED", " ".join(result.detail))

    def test_both_rates_are_reported(self):
        scan = cmt.Scan(
            files=1,
            sessions=100,
            memory_sessions=50,
            search_sessions=20,
            post_index_sessions=5,
            structured_calls=20,
        )
        detail = " ".join(cmt.check_index_bypass(scan).detail)
        self.assertIn("20 searched memory/ (40%)", detail)
        self.assertIn("5 searched AFTER reading an index (10%)", detail)


# ── privacy ────────────────────────────────────────────────────────────────


class ToolLabelTest(unittest.TestCase):
    def test_an_mcp_name_is_bucketed(self):
        self.assertEqual(
            cmt.tool_label("mcp__acme_internal__query_secrets"), cmt.MCP_BUCKET
        )
        self.assertEqual(cmt.tool_label("mcp__x__y"), cmt.MCP_BUCKET)

    def test_an_unrecognised_name_is_bucketed(self):
        self.assertEqual(cmt.tool_label("SomeClientPluginTool"), cmt.OTHER_BUCKET)
        self.assertEqual(cmt.tool_label(None), cmt.OTHER_BUCKET)
        self.assertEqual(cmt.tool_label(42), cmt.OTHER_BUCKET)

    def test_allowlisted_builtins_pass_through(self):
        for name in ("Bash", "Grep", "Glob", "Read", "PowerShell"):
            self.assertEqual(cmt.tool_label(name), name)

    def test_the_allowlist_contains_no_mcp_names(self):
        """A single `mcp__` entry would defeat the bucket it exists to feed."""
        leaky = [n for n in cmt.EMITTABLE_TOOLS if n.startswith("mcp__")]
        self.assertEqual(leaky, [])


class PrivacyTest(_Harness):
    """The headline privacy assertion: the repo is public, so no emitted line may
    carry an operator-configured MCP server name, nor transcript text."""

    SECRET_SERVER = "mcp__acme_internal_crm__search_customer_records"
    SECRET_TEXT = "ACME-CONFIDENTIAL-CUSTOMER-PAYLOAD"

    def _seed_leaky_corpus(self) -> None:
        _seed_notes(self.memory, "repo/x", 3)
        cwd = self.repo_cwd
        _write_transcript(
            self.transcripts / "p" / "s1.jsonl",
            [
                # An operator-configured MCP tool reaching into memory/: the
                # name must be bucketed, the call must still be counted.
                _record(
                    "s1",
                    cwd,
                    [_tool_use(self.SECRET_SERVER, {"path": "memory", "pattern": "x"})],
                ),
                # A shell search whose command string carries user content.
                _record(
                    "s1",
                    cwd,
                    [
                        _tool_use(
                            "Bash",
                            {"command": f"rg '{self.SECRET_TEXT}' memory/repo/x"},
                        )
                    ],
                ),
                _record(
                    "s1",
                    cwd,
                    [_tool_use("AnotherUnknownPluginTool", {"path": "memory"})],
                ),
            ],
        )

    def test_no_emitted_line_contains_an_unrecognised_mcp_name(self):
        self._seed_leaky_corpus()
        rc, out = self.run_cli("--transcripts", str(self.transcripts))
        self.assertEqual(rc, cmt.EXIT_PASS, out)
        for line in out.splitlines():
            self.assertNotIn("mcp__", line, f"MCP name leaked: {line!r}")
            self.assertNotIn("acme_internal", line.lower(), f"server leaked: {line!r}")

    def test_the_json_output_leaks_no_mcp_name_either(self):
        self._seed_leaky_corpus()
        rc, out = self.run_cli("--transcripts", str(self.transcripts), "--json")
        self.assertEqual(rc, cmt.EXIT_PASS, out)
        self.assertNotIn("mcp__", out)
        payload = json.loads(out)
        self.assertNotIn(self.SECRET_SERVER, json.dumps(payload["scan"]["by_tool"]))
        self.assertIn(cmt.MCP_BUCKET, payload["scan"]["by_tool"])

    def test_no_transcript_text_is_emitted(self):
        self._seed_leaky_corpus()
        for extra in ((), ("--json",)):
            _, out = self.run_cli("--transcripts", str(self.transcripts), *extra)
            self.assertNotIn(self.SECRET_TEXT, out)

    def test_an_mcp_search_is_still_counted_even_though_it_is_not_named(self):
        """Bucketing must redact the label, not discard the signal."""
        self._seed_leaky_corpus()
        _, out = self.run_cli("--transcripts", str(self.transcripts), "--json")
        by_tool = json.loads(out)["scan"]["by_tool"]
        self.assertEqual(by_tool.get(cmt.MCP_BUCKET), 1)
        self.assertEqual(by_tool.get(cmt.OTHER_BUCKET), 1)
        self.assertEqual(by_tool.get("Bash"), 1)

    def test_emitted_memory_paths_are_relative_to_the_memory_root(self):
        """Paths under memory/ are permitted; absolute host paths are not."""
        _seed_notes(self.memory, "repo/x", 3)
        _, out = self.run_cli("--skip-transcripts", "--json")
        payload = json.loads(out)
        self.assertEqual(list(payload["directory_notes"]), ["repo/x"])


class ReadOnlyTest(_Harness):
    def test_the_script_writes_nothing(self):
        _seed_notes(self.memory, "repo/x", 2)
        _write_transcript(
            self.transcripts / "p" / "s1.jsonl",
            [_record("s1", self.repo_cwd, [_tool_use("Grep", {"path": "memory"})])],
        )
        before = {
            p: p.stat().st_mtime_ns
            for p in list(self.memory.rglob("*")) + list(self.transcripts.rglob("*"))
        }
        self.run_cli("--transcripts", str(self.transcripts))
        after = {
            p: p.stat().st_mtime_ns
            for p in list(self.memory.rglob("*")) + list(self.transcripts.rglob("*"))
        }
        self.assertEqual(before, after)
        self.assertFalse(ur.record_path(self.repo).exists())


if __name__ == "__main__":
    unittest.main()
