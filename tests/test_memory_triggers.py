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


_UNSET = object()


def _write_subagent(
    transcripts: Path,
    session: str,
    agent_id: str,
    records: list[dict],
    agent_type: object = _UNSET,
    meta: object = _UNSET,
) -> Path:
    """Write one subagent invocation: `<s>/subagents/agent-<id>.jsonl` + sidecar.

    The file layout is `scan_by_agent_type`'s `AGENT_FILE_GLOB`
    (`subagents/agent-*.jsonl`) and `_resolve_agent_type`'s sidecar rule
    (`agent-<id>.jsonl` → `agent-<id>.meta.json`), so a test that gets either
    wrong is invisible to the scan rather than failing loudly.

    Three sidecar states, deliberately distinguishable:

    * ``agent_type="x"`` — a normal sidecar, ``{"agentType": "x"}``.
    * neither argument — NO sidecar file at all, which is the routine case the
      `unknown` bucket exists for.
    * ``meta=<any object>`` — a sidecar with arbitrary payload, for the
      malformed-but-present cases.
    """
    path = transcripts / session / "subagents" / f"agent-{agent_id}.jsonl"
    _write_transcript(path, records)
    sidecar = path.with_name(f"agent-{agent_id}.meta.json")
    if meta is not _UNSET:
        sidecar.write_text(json.dumps(meta), encoding="utf-8", newline="")
    elif agent_type is not _UNSET:
        sidecar.write_text(
            json.dumps({"agentType": agent_type}), encoding="utf-8", newline=""
        )
    return path


def _no_cwd_record(blocks: list) -> dict:
    """A record carrying no `cwd` at all — what makes a file `unscopable`.

    `_record` always writes a `cwd`, and a file whose head never yields one is a
    distinct bucket from one whose `cwd` names another repo, so the two cases
    cannot share a builder.
    """
    return {
        "sessionId": "s-nocwd",
        "type": "assistant",
        "message": {"role": "assistant", "content": blocks},
    }


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


# ── --by-agent-type (#243) ─────────────────────────────────────────────────


class DiscoveryBriefPathMatcherTest(unittest.TestCase):
    """`is_discovery_brief_path` — segment-exact AND adjacency-exact.

    The substring test `".sisyphus/discovery" in value` would accept
    `.sisyphus-backup/discovery-notes/`, and a non-adjacent test would accept
    `.sisyphus/plans/discovery/`. Both inflate the brief-read count into a
    healthier-looking number rather than into a visible error.
    """

    def test_a_brief_matches_on_either_separator(self):
        self.assertTrue(cmt.is_discovery_brief_path(".sisyphus/discovery/foo.md"))
        self.assertTrue(cmt.is_discovery_brief_path(r".sisyphus\discovery\foo.md"))
        self.assertTrue(
            cmt.is_discovery_brief_path("C:/p/brain/.sisyphus/discovery/task.md")
        )
        self.assertTrue(
            cmt.is_discovery_brief_path(r"C:\p\brain\.sisyphus\discovery\task.md")
        )

    def test_the_directory_itself_matches(self):
        self.assertTrue(cmt.is_discovery_brief_path(".sisyphus/discovery"))

    def test_a_lookalike_sibling_directory_is_not_a_brief(self):
        self.assertFalse(
            cmt.is_discovery_brief_path(".sisyphus-backup/discovery-notes/foo.md")
        )
        self.assertFalse(cmt.is_discovery_brief_path(".sisyphus/discovery-old/foo.md"))
        self.assertFalse(cmt.is_discovery_brief_path("sisyphus/discovery/foo.md"))

    def test_discovery_must_follow_sisyphus_immediately(self):
        """`.sisyphus/plans/discovery/` holds plans, not briefs."""
        self.assertFalse(cmt.is_discovery_brief_path(".sisyphus/plans/discovery/x.md"))
        self.assertFalse(cmt.is_discovery_brief_path("discovery/.sisyphus/x.md"))

    def test_non_string_and_empty_inputs_are_rejected(self):
        self.assertFalse(cmt.is_discovery_brief_path(""))
        self.assertFalse(cmt.is_discovery_brief_path(None))
        self.assertFalse(cmt.is_discovery_brief_path(42))
        self.assertFalse(cmt.is_discovery_brief_path([".sisyphus", "discovery"]))

    def test_a_memory_note_is_not_a_brief_and_a_brief_is_not_a_note(self):
        """The two columns must not be able to collapse into one."""
        self.assertFalse(cmt.is_discovery_brief_path("memory/repo/x/note.md"))
        self.assertFalse(cmt.is_memory_path(".sisyphus/discovery/foo.md"))


class AgentTypeLabelTest(unittest.TestCase):
    """The privacy gate on a sidecar-derived string, and the missing/malformed
    split `agent_type_label`'s docstring insists on."""

    def test_a_plausible_slug_passes_through(self):
        for name in ("test-author", "Explorer", "code.reviewer", "a", "a_b"):
            self.assertEqual(cmt.agent_type_label(name), name)

    def test_a_missing_value_is_unknown_not_unprintable(self):
        self.assertEqual(cmt.agent_type_label(None), cmt.AGENT_TYPE_UNKNOWN)
        self.assertEqual(cmt.agent_type_label(""), cmt.AGENT_TYPE_UNKNOWN)
        self.assertEqual(cmt.agent_type_label(42), cmt.AGENT_TYPE_UNKNOWN)
        self.assertEqual(cmt.agent_type_label({"a": 1}), cmt.AGENT_TYPE_UNKNOWN)

    def test_a_value_failing_the_shape_gate_is_unprintable(self):
        for bad in (
            "two words",
            "../../etc/passwd",
            "has/slash",
            "-leading-dash",
            "tab\there",
            "new\nline",
            "x" * 65,
        ):
            self.assertEqual(
                cmt.agent_type_label(bad), cmt.AGENT_TYPE_UNPRINTABLE, repr(bad)
            )

    def test_the_length_bound_is_sixty_four(self):
        self.assertEqual(cmt.agent_type_label("x" * 64), "x" * 64)
        self.assertEqual(cmt.agent_type_label("x" * 65), cmt.AGENT_TYPE_UNPRINTABLE)

    def test_an_mcp_prefixed_name_is_bucketed_though_it_passes_the_shape_gate(self):
        """#70's leak class: the shape gate alone would print this."""
        self.assertEqual(
            cmt.agent_type_label("mcp__acme_internal__agent"),
            cmt.AGENT_TYPE_UNPRINTABLE,
        )


class AgentTypeRowRateTest(unittest.TestCase):
    def test_the_two_rates_are_computed_independently(self):
        row = cmt.AgentTypeRow(
            agent_type="a", invocations=4, memory_hits=1, discovery_hits=3, resolved=True
        )
        self.assertEqual(row.memory_hit_rate, 25)
        self.assertEqual(row.discovery_hit_rate, 75)

    def test_a_zero_denominator_does_not_raise(self):
        row = cmt.AgentTypeRow(
            agent_type="a", invocations=0, memory_hits=0, discovery_hits=0, resolved=True
        )
        self.assertEqual(row.memory_hit_rate, 0)
        self.assertEqual(row.discovery_hit_rate, 0)


class AgentTypeScanTest(_Harness):
    """`scan_by_agent_type` — one invocation per `subagents/agent-*.jsonl`."""

    CWD = "C:/p/brain"
    MEM = "C:/p/brain/memory/repo/x/note.md"
    BRIEF = "C:/p/brain/.sisyphus/discovery/task.md"

    def _scan(self, repo_root_posix: str | None = None) -> cmt.AgentTypeScan:
        return cmt.scan_by_agent_type(
            self.transcripts, self.CWD if repo_root_posix is None else repo_root_posix
        )

    def _rows(self, scan: cmt.AgentTypeScan) -> dict[str, cmt.AgentTypeRow]:
        return {row.agent_type: row for row in scan.rows}

    def _read(self, path: str) -> dict:
        return _record("s1", self.CWD, [_tool_use("Read", {"file_path": path})])

    # ── aggregation ────────────────────────────────────────────────────────

    def test_invocations_aggregate_per_agent_type(self):
        for i in range(3):
            _write_subagent(
                self.transcripts, "s1", f"explorer{i}", [self._read(self.MEM)],
                agent_type="explorer",
            )
        for i in range(2):
            _write_subagent(
                self.transcripts, "s1", f"author{i}", [self._read("src/x.py")],
                agent_type="test-author",
            )
        _write_subagent(
            self.transcripts, "s2", "rev0", [self._read(self.BRIEF)],
            agent_type="reviewer",
        )
        scan = self._scan()
        self.assertEqual(scan.files, 6)
        self.assertEqual(scan.invocations, 6)
        rows = self._rows(scan)
        self.assertEqual(
            {k: v.invocations for k, v in rows.items()},
            {"explorer": 3, "test-author": 2, "reviewer": 1},
        )
        self.assertTrue(all(row.resolved for row in scan.rows))

    def test_rows_sort_by_invocations_descending_then_label(self):
        """`check_directory_size`'s convention, so two tables sort one way."""
        for i in range(2):
            _write_subagent(
                self.transcripts, "s1", f"b{i}", [self._read("x.py")], agent_type="bbb"
            )
        _write_subagent(
            self.transcripts, "s1", "z", [self._read("x.py")], agent_type="zzz"
        )
        _write_subagent(
            self.transcripts, "s1", "a", [self._read("x.py")], agent_type="aaa"
        )
        self.assertEqual(
            [row.agent_type for row in self._scan().rows], ["bbb", "aaa", "zzz"]
        )

    # ── the residue buckets ────────────────────────────────────────────────

    def test_a_missing_sidecar_lands_in_unknown_and_is_not_dropped(self):
        _write_subagent(self.transcripts, "s1", "nometa", [self._read(self.MEM)])
        _write_subagent(
            self.transcripts, "s1", "typed", [self._read(self.MEM)],
            agent_type="explorer",
        )
        scan = self._scan()
        self.assertEqual(scan.files, 2)
        self.assertEqual(scan.invocations, 2, "the untyped invocation still happened")
        rows = self._rows(scan)
        self.assertEqual(rows[cmt.AGENT_TYPE_UNKNOWN].invocations, 1)
        self.assertEqual(rows[cmt.AGENT_TYPE_UNKNOWN].memory_hits, 1)
        self.assertFalse(rows[cmt.AGENT_TYPE_UNKNOWN].resolved)
        self.assertTrue(rows["explorer"].resolved)

    def test_a_malformed_sidecar_lands_in_unknown(self):
        _write_subagent(
            self.transcripts, "s1", "nokey", [self._read("x.py")], meta={"other": 1}
        )
        _write_subagent(
            self.transcripts, "s1", "notdict", [self._read("x.py")], meta=["a", "b"]
        )
        bad = self.transcripts / "s1" / "subagents" / "agent-broken.meta.json"
        _write_subagent(self.transcripts, "s1", "broken", [self._read("x.py")])
        bad.write_text("{not json", encoding="utf-8", newline="")
        scan = self._scan()
        self.assertEqual(self._rows(scan)[cmt.AGENT_TYPE_UNKNOWN].invocations, 3)

    def test_an_unprintable_agent_type_is_bucketed_not_echoed(self):
        _write_subagent(
            self.transcripts, "s1", "spaced", [self._read(self.MEM)],
            agent_type="two words",
        )
        _write_subagent(
            self.transcripts, "s1", "mcp", [self._read("x.py")],
            agent_type="mcp__acme_internal__agent",
        )
        scan = self._scan()
        rows = self._rows(scan)
        self.assertNotIn(cmt.AGENT_TYPE_UNKNOWN, rows, "present-but-bad is not missing")
        row = rows[cmt.AGENT_TYPE_UNPRINTABLE]
        self.assertEqual(row.invocations, 2)
        self.assertEqual(row.memory_hits, 1, "the signal survives the redaction")
        self.assertFalse(row.resolved)
        rendered = "\n".join(cmt.render_agent_type_table(scan))
        self.assertNotIn("two words", rendered)
        self.assertNotIn("mcp__", rendered)
        self.assertNotIn("acme_internal", rendered)

    # ── the hit counters ───────────────────────────────────────────────────

    def test_a_memory_read_is_a_hit(self):
        _write_subagent(
            self.transcripts, "s1", "a", [self._read(self.MEM)], agent_type="explorer"
        )
        row = self._rows(self._scan())["explorer"]
        self.assertEqual(row.memory_hits, 1)
        self.assertEqual(row.discovery_hits, 0)
        self.assertEqual(row.memory_hit_rate, 100)

    def test_reading_the_same_note_twice_is_still_one_hit(self):
        """Counting reads would make the rate a measure of verbosity."""
        _write_subagent(
            self.transcripts,
            "s1",
            "a",
            [self._read(self.MEM), self._read(self.MEM), self._read(self.MEM)],
            agent_type="explorer",
        )
        row = self._rows(self._scan())["explorer"]
        self.assertEqual(row.invocations, 1)
        self.assertEqual(row.memory_hits, 1)
        self.assertEqual(row.memory_hit_rate, 100)

    def test_reading_two_different_notes_is_still_one_hit(self):
        _write_subagent(
            self.transcripts,
            "s1",
            "a",
            [
                self._read("C:/p/brain/memory/repo/x/one.md"),
                self._read("C:/p/brain/memory/feedback/two.md"),
            ],
            agent_type="explorer",
        )
        self.assertEqual(self._rows(self._scan())["explorer"].memory_hits, 1)

    def test_a_discovery_brief_read_is_a_separate_hit(self):
        _write_subagent(
            self.transcripts, "s1", "a", [self._read(self.BRIEF)], agent_type="author"
        )
        row = self._rows(self._scan())["author"]
        self.assertEqual(row.discovery_hits, 1)
        self.assertEqual(row.memory_hits, 0, "a brief is not a note")
        self.assertEqual(row.discovery_hit_rate, 100)

    def test_one_invocation_can_register_both_hits_independently(self):
        """Two columns, never one: the counters are neither merged nor
        mutually exclusive."""
        _write_subagent(
            self.transcripts,
            "s1",
            "both",
            [self._read(self.MEM), self._read(self.BRIEF)],
            agent_type="explorer",
        )
        row = self._rows(self._scan())["explorer"]
        self.assertEqual(row.invocations, 1)
        self.assertEqual(row.memory_hits, 1)
        self.assertEqual(row.discovery_hits, 1)
        self.assertEqual(row.memory_hit_rate, 100)
        self.assertEqual(row.discovery_hit_rate, 100)

    def test_both_hits_in_one_block_list_are_registered(self):
        _write_subagent(
            self.transcripts,
            "s1",
            "both",
            [
                _record(
                    "s1",
                    self.CWD,
                    [
                        _tool_use("Read", {"file_path": self.MEM}),
                        _tool_use("Read", {"file_path": self.BRIEF}),
                    ],
                )
            ],
            agent_type="explorer",
        )
        row = self._rows(self._scan())["explorer"]
        self.assertEqual((row.memory_hits, row.discovery_hits), (1, 1))

    def test_an_invocation_with_neither_read_counts_in_the_denominator(self):
        _write_subagent(
            self.transcripts,
            "s1",
            "quiet",
            [self._read("src/app.py"), _record("s1", self.CWD, [_tool_use("Bash", {"command": "pytest"})])],
            agent_type="explorer",
        )
        row = self._rows(self._scan())["explorer"]
        self.assertEqual(row.invocations, 1)
        self.assertEqual(row.memory_hits, 0)
        self.assertEqual(row.discovery_hits, 0)
        self.assertEqual(row.memory_hit_rate, 0)

    def test_only_a_read_counts_not_a_search(self):
        """A `Grep` of `memory/` is T4's subject, not this one's."""
        _write_subagent(
            self.transcripts,
            "s1",
            "searcher",
            [
                _record("s1", self.CWD, [_tool_use("Grep", {"path": "memory"})]),
                _record("s1", self.CWD, [_tool_use("Glob", {"pattern": "memory/**/*.md"})]),
                _record(
                    "s1", self.CWD, [_tool_use("Bash", {"command": "rg x memory/"})]
                ),
            ],
            agent_type="explorer",
        )
        row = self._rows(self._scan())["explorer"]
        self.assertEqual(row.invocations, 1)
        self.assertEqual(row.memory_hits, 0)
        self.assertEqual(row.discovery_hits, 0)

    # ── scoping ────────────────────────────────────────────────────────────

    def test_a_foreign_cwd_is_out_of_scope_and_not_a_row(self):
        _write_subagent(
            self.transcripts,
            "s9",
            "foreign",
            [
                _record(
                    "s9", "C:/p/unrelated", [_tool_use("Read", {"file_path": self.MEM})]
                )
            ],
            agent_type="explorer",
        )
        scan = self._scan()
        self.assertEqual(scan.files, 1)
        self.assertEqual(scan.out_of_scope, 1)
        self.assertEqual(scan.unscopable, 0)
        self.assertEqual(scan.rows, ())
        self.assertEqual(scan.invocations, 0)

    def test_any_repo_includes_everything(self):
        _write_subagent(
            self.transcripts,
            "s9",
            "foreign",
            [
                _record(
                    "s9", "C:/p/unrelated", [_tool_use("Read", {"file_path": self.MEM})]
                )
            ],
            agent_type="explorer",
        )
        scan = self._scan(repo_root_posix="")
        self.assertEqual(scan.out_of_scope, 0)
        self.assertEqual(scan.invocations, 1)
        self.assertEqual(self._rows(scan)["explorer"].memory_hits, 1)

    def test_a_worktree_cwd_attributes_to_the_repository(self):
        _write_subagent(
            self.transcripts,
            "s1",
            "wt",
            [
                _record(
                    "s1",
                    f"{self.CWD}/.claude/worktrees/feature-x",
                    [_tool_use("Read", {"file_path": self.MEM})],
                )
            ],
            agent_type="explorer",
        )
        scan = self._scan()
        self.assertEqual(scan.out_of_scope, 0)
        self.assertEqual(self._rows(scan)["explorer"].invocations, 1)

    def test_a_file_with_no_cwd_is_unscopable_not_out_of_scope(self):
        """A counted, reported omission beats attributing another repo's agents."""
        _write_subagent(
            self.transcripts,
            "s1",
            "nocwd",
            [_no_cwd_record([_tool_use("Read", {"file_path": self.MEM})])],
            agent_type="explorer",
        )
        scan = self._scan()
        self.assertEqual(scan.files, 1)
        self.assertEqual(scan.unscopable, 1)
        self.assertEqual(scan.out_of_scope, 0, "no cwd is a different fact")
        self.assertEqual(scan.rows, ())
        self.assertEqual(scan.invocations, 0)

    def test_the_three_exclusion_counters_are_reported_separately(self):
        _write_subagent(
            self.transcripts, "s1", "ok", [self._read(self.MEM)], agent_type="explorer"
        )
        _write_subagent(
            self.transcripts,
            "s1",
            "foreign",
            [_record("s1", "C:/p/unrelated", [_tool_use("Read", {"file_path": self.MEM})])],
            agent_type="explorer",
        )
        _write_subagent(
            self.transcripts,
            "s1",
            "nocwd",
            [_no_cwd_record([_tool_use("Read", {"file_path": self.MEM})])],
            agent_type="explorer",
        )
        scan = self._scan()
        self.assertEqual(scan.files, 3)
        self.assertEqual(scan.invocations, 1)
        self.assertEqual(scan.out_of_scope, 1)
        self.assertEqual(scan.unscopable, 1)
        self.assertEqual(scan.unreadable, 0)
        table = "\n".join(cmt.render_agent_type_table(scan))
        self.assertIn("3 subagent transcript(s)", table)
        self.assertIn("1 out of scope", table)
        self.assertIn("1 with no cwd", table)

    # ── which files are read at all ────────────────────────────────────────

    def test_a_top_level_transcript_is_never_scanned(self):
        """A main-thread session has no agent type; including it under a
        synthesised label would put the main thread in a delegation table."""
        _write_transcript(
            self.transcripts / "s1.jsonl", [self._read(self.MEM)]
        )
        _write_transcript(
            self.transcripts / "s1" / "s1.jsonl", [self._read(self.MEM)]
        )
        _write_transcript(
            self.transcripts / "s1" / "agent-loose.jsonl", [self._read(self.MEM)]
        )
        _write_subagent(
            self.transcripts, "s1", "real", [self._read(self.MEM)], agent_type="explorer"
        )
        scan = self._scan()
        self.assertEqual(scan.files, 1, "only the subagents/agent-*.jsonl file")
        self.assertEqual(scan.invocations, 1)
        self.assertEqual(self._rows(scan)["explorer"].invocations, 1)

    def test_a_sidecar_is_not_itself_counted_as_a_transcript(self):
        _write_subagent(
            self.transcripts, "s1", "a", [self._read(self.MEM)], agent_type="explorer"
        )
        self.assertEqual(self._scan().files, 1)

    def test_malformed_lines_do_not_derail_the_scan(self):
        path = self.transcripts / "s1" / "subagents" / "agent-a.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write("not json at all\n")
            handle.write('["a list, not an object, mentioning memory and tool_use"]\n')
            handle.write("\n")
            handle.write(json.dumps(self._read(self.MEM)) + "\n")
        path.with_name("agent-a.meta.json").write_text(
            json.dumps({"agentType": "explorer"}), encoding="utf-8", newline=""
        )
        scan = self._scan()
        self.assertEqual(scan.invocations, 1)
        self.assertEqual(self._rows(scan)["explorer"].memory_hits, 1)

    def test_a_missing_transcript_dir_is_not_scanned_rather_than_zero(self):
        scan = cmt.scan_by_agent_type(self.transcripts / "gone", self.CWD)
        self.assertFalse(scan.scanned)
        self.assertEqual(scan.reason, "no-transcripts")
        self.assertEqual(scan.rows, ())
        self.assertIn(
            "not scanned — reason: no-transcripts",
            "\n".join(cmt.render_agent_type_table(scan)),
        )

    def test_an_empty_corpus_renders_as_an_empty_table_not_a_suppressed_one(self):
        scan = self._scan()
        self.assertTrue(scan.scanned)
        self.assertEqual(scan.files, 0)
        table = "\n".join(cmt.render_agent_type_table(scan))
        self.assertIn("by agent type", table)
        self.assertIn("(no subagent invocation in scope)", table)


class AgentTypeCliTest(_Harness):
    """The flag's CLI surface — and, above all, its absence."""

    HEADER = "by agent type"
    MEM = "memory/repo/x/note.md"
    BRIEF = ".sisyphus/discovery/task.md"

    def _seed(self) -> None:
        _seed_notes(self.memory, "repo/x", 3)
        cwd = self.repo_cwd
        _write_subagent(
            self.transcripts,
            "s1",
            "a",
            [
                _record("s1", cwd, [_tool_use("Read", {"file_path": self.MEM})]),
                _record("s1", cwd, [_tool_use("Read", {"file_path": self.BRIEF})]),
            ],
            agent_type="explorer",
        )
        _write_subagent(
            self.transcripts,
            "s1",
            "b",
            [_record("s1", cwd, [_tool_use("Read", {"file_path": "src/app.py"})])],
            agent_type="test-author",
        )

    def test_without_the_flag_the_human_report_gains_no_line(self):
        self._seed()
        rc, out = self.run_cli("--transcripts", str(self.transcripts))
        self.assertEqual(rc, cmt.EXIT_PASS, out)
        self.assertNotIn(self.HEADER, out)
        self.assertNotIn("by_agent_type", out)
        self.assertNotIn("agent type", out)
        self.assertNotIn("explorer", out)
        self.assertNotIn("subagent transcript(s)", out)
        self.assertTrue(out.rstrip().endswith("not clean bills."), out)

    def test_without_the_flag_the_json_payload_gains_no_key(self):
        self._seed()
        rc, out = self.run_cli("--transcripts", str(self.transcripts), "--json")
        self.assertEqual(rc, cmt.EXIT_PASS, out)
        self.assertNotIn("by_agent_type", out)
        payload = json.loads(out)
        self.assertNotIn("by_agent_type", payload)
        self.assertEqual(
            set(payload),
            {
                "memory_root",
                "unrouted_record",
                "transcripts",
                "corpus_notes",
                "directory_notes",
                "limits",
                "scan",
                "triggers",
                "exit",
            },
        )

    def test_skip_transcripts_leaves_the_payload_untouched_too(self):
        self._seed()
        _, out = self.run_cli("--skip-transcripts", "--json")
        self.assertNotIn("by_agent_type", json.loads(out))

    def test_the_flag_adds_the_table_below_the_triggers(self):
        self._seed()
        rc, out = self.run_cli(
            "--transcripts", str(self.transcripts), "--by-agent-type"
        )
        self.assertEqual(rc, cmt.EXIT_PASS, out)
        self.assertIn(self.HEADER, out)
        self.assertIn("explorer", out)
        self.assertIn("test-author", out)
        self.assertLess(
            out.index("not clean bills"),
            out.index(self.HEADER),
            "the table must sit below the four triggers, not among them",
        )

    def test_the_flag_adds_the_json_key(self):
        self._seed()
        _, out = self.run_cli(
            "--transcripts", str(self.transcripts), "--by-agent-type", "--json"
        )
        block = json.loads(out)["by_agent_type"]
        self.assertTrue(block["scanned"])
        self.assertEqual(block["files"], 2)
        self.assertEqual(block["invocations"], 2)
        self.assertEqual(block["out_of_scope"], 0)
        self.assertEqual(block["unscopable"], 0)
        self.assertFalse(block["calibrated"])
        by_type = {r["agent_type"]: r for r in block["agent_types"]}
        self.assertEqual(by_type["explorer"]["memory_hits"], 1)
        self.assertEqual(by_type["explorer"]["discovery_hits"], 1)
        self.assertEqual(by_type["explorer"]["memory_hit_rate"], 100)
        self.assertEqual(by_type["test-author"]["memory_hits"], 0)
        self.assertEqual(by_type["test-author"]["discovery_hit_rate"], 0)
        self.assertTrue(all(r["resolved"] for r in block["agent_types"]))

    def test_the_flag_cannot_change_the_exit_code(self):
        """Uncalibrated, like T4: nothing here fires."""
        self._seed()
        for extra in ((), ("--json",)):
            rc_without, _ = self.run_cli("--transcripts", str(self.transcripts), *extra)
            rc_with, out = self.run_cli(
                "--transcripts", str(self.transcripts), "--by-agent-type", *extra
            )
            self.assertEqual(rc_without, rc_with)
            self.assertEqual(rc_with, cmt.EXIT_PASS, out)

    def test_the_flag_changes_nothing_but_adds(self):
        """Byte-for-byte: the report without the flag is a prefix of the one
        with it. A regression that reworded an existing line would pass a
        mere `assertNotIn` and fail here."""
        self._seed()
        _, plain = self.run_cli("--transcripts", str(self.transcripts))
        _, flagged = self.run_cli(
            "--transcripts", str(self.transcripts), "--by-agent-type"
        )
        self.assertTrue(flagged.startswith(plain), flagged)

    def test_the_json_payload_is_otherwise_identical(self):
        self._seed()
        _, plain = self.run_cli("--transcripts", str(self.transcripts), "--json")
        _, flagged = self.run_cli(
            "--transcripts", str(self.transcripts), "--by-agent-type", "--json"
        )
        a, b = json.loads(plain), json.loads(flagged)
        self.assertEqual(b.pop("by_agent_type")["invocations"], 2)
        self.assertEqual(a, b)

    def test_the_table_leaks_no_mcp_agent_type(self):
        _seed_notes(self.memory, "repo/x", 1)
        cwd = self.repo_cwd
        _write_subagent(
            self.transcripts,
            "s1",
            "leaky",
            [_record("s1", cwd, [_tool_use("Read", {"file_path": self.MEM})])],
            agent_type="mcp__acme_internal_crm__agent",
        )
        for extra in ((), ("--json",)):
            _, out = self.run_cli(
                "--transcripts", str(self.transcripts), "--by-agent-type", *extra
            )
            self.assertNotIn("mcp__", out)
            self.assertNotIn("acme_internal", out.lower())
            self.assertIn(cmt.AGENT_TYPE_UNPRINTABLE, out)

    def test_the_flagged_run_still_writes_nothing(self):
        self._seed()
        watched = list(self.memory.rglob("*")) + list(self.transcripts.rglob("*"))
        before = {p: p.stat().st_mtime_ns for p in watched}
        self.run_cli("--transcripts", str(self.transcripts), "--by-agent-type")
        after = {p: p.stat().st_mtime_ns for p in watched}
        self.assertEqual(before, after)

    def test_any_repo_widens_the_agent_type_scope_too(self):
        _seed_notes(self.memory, "repo/x", 1)
        _write_subagent(
            self.transcripts,
            "s9",
            "foreign",
            [
                _record(
                    "s9", "C:/p/unrelated", [_tool_use("Read", {"file_path": self.MEM})]
                )
            ],
            agent_type="explorer",
        )
        _, scoped = self.run_cli(
            "--transcripts", str(self.transcripts), "--by-agent-type", "--json"
        )
        self.assertEqual(json.loads(scoped)["by_agent_type"]["invocations"], 0)
        self.assertEqual(json.loads(scoped)["by_agent_type"]["out_of_scope"], 1)
        _, wide = self.run_cli(
            "--transcripts",
            str(self.transcripts),
            "--by-agent-type",
            "--any-repo",
            "--json",
        )
        self.assertEqual(json.loads(wide)["by_agent_type"]["invocations"], 1)


if __name__ == "__main__":
    unittest.main()
