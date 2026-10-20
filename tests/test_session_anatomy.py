"""Tests for scripts/session_anatomy.py (issue #182).

The script answers "where did this session's context go?", so every number it
prints is an accounting claim that has to survive the messy shapes a real
transcript takes: a streamed assistant message re-emitted under one
``message.id``, a truncated JSON line from an interrupted write, a subagent
with no ``meta.json``, an agent that never issued a request at all.

Fixtures are built as throwaway JSONL files under ``tempfile`` -- never real
transcripts, which carry absolute home paths and private content. The ``cwd``
recorded inside each fixture entry is the literal string ``/repo``, not the
temp directory: the script treats ``cwd`` as data for ``normalize_path`` and
never touches the filesystem with it, so pinning it keeps the expected
``files_read`` values independent of where the test happens to run.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import session_anatomy  # noqa: E402

CWD = "/repo"


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _usage(inp=0, cache_read=0, cache_creation=0, out=0) -> dict:
    return {
        "input_tokens": inp,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation,
        "output_tokens": out,
    }


def _user(content, cwd=CWD) -> dict:
    return {"type": "user", "cwd": cwd, "message": {"content": content}}


def _assistant(mid, usage, content=None, cwd=CWD) -> dict:
    return {
        "type": "assistant",
        "cwd": cwd,
        "message": {"id": mid, "usage": usage, "content": content or []},
    }


def _tool_use(use_id, name, tool_input) -> dict:
    return {"type": "tool_use", "id": use_id, "name": name, "input": tool_input}


def _tool_result(use_id, content, cwd=CWD) -> dict:
    return _user(
        [{"type": "tool_result", "tool_use_id": use_id, "content": content}], cwd=cwd
    )


def _write_jsonl(path: Path, entries) -> Path:
    """Write entries as JSONL. A plain ``str`` entry is written verbatim, which
    is how a malformed (truncated) line gets into a fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [e if isinstance(e, str) else json.dumps(e) for e in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _make_session(root: Path, session_id: str, main_entries=None, subagents=()) -> Path:
    """Build ``<root>/<session_id>/`` with its sibling main transcript and subagents.

    ``subagents`` is a sequence of ``(agent_id, agent_type_or_None, entries)``;
    ``None`` writes no ``meta.json``, which is the "unknown" case.
    """
    session_dir = root / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    if main_entries is not None:
        _write_jsonl(session_dir / f"{session_id}.jsonl", main_entries)
    for agent_id, agent_type, entries in subagents:
        jsonl = session_dir / "subagents" / f"agent-{agent_id}.jsonl"
        _write_jsonl(jsonl, entries)
        if agent_type is not None:
            jsonl.with_suffix("").with_suffix(".meta.json").write_text(
                json.dumps({"agentType": agent_type}), encoding="utf-8"
            )
    return session_dir


def _simple_agent(prompt_chars: int, contexts, files=()) -> list:
    """An agent transcript with a prompt of a known length, one request per
    entry in ``contexts``, and one ``Read`` per entry in ``files``.

    The reads ride on the first request rather than on extra assistant entries
    of their own, so ``files`` never silently inflates the request count.
    """
    if files and not contexts:
        raise AssertionError("_simple_agent needs at least one request to carry reads")
    reads = [
        _tool_use(f"t{i}", "Read", {"file_path": f"{CWD}/{path}"})
        for i, path in enumerate(files)
    ]
    entries = [_user("p" * prompt_chars)]
    for i, context in enumerate(contexts):
        entries.append(
            _assistant(f"m{i}", _usage(cache_read=context), reads if i == 0 else [])
        )
    return entries


class TempDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)


# ---------------------------------------------------------------------------
# classify_shell
# ---------------------------------------------------------------------------


class TestClassifyShell(unittest.TestCase):
    def test_families_are_recognised_by_first_word(self):
        for command, family in [
            ("sed -n '1,20p' a.py", "read"),
            ("cat a.py", "read"),
            ("head -5 a.py", "read"),
            ("tail -5 a.py", "read"),
            ("less a.py", "read"),
            ("more a.py", "read"),
            ("type a.py", "read"),
            ("Get-Content a.py", "read"),
            ("gc a.py", "read"),
            ("grep foo a.py", "search"),
            ("rg foo", "search"),
            ("egrep foo a.py", "search"),
            ("find . -name '*.py'", "search"),
            ("ls -la", "search"),
            ("wc -l a.py", "search"),
            ("Select-String foo a.py", "search"),
            ("dir", "search"),
            ("Get-ChildItem", "search"),
            ("git status", "git"),
            ("pytest tests", "test"),
            ("python -m unittest discover", "test"),
            ("npx vitest run", "test"),
            ("npx jest", "test"),
            ("npm test", "test"),
            ("npm run test", "test"),
            ("pnpm test", "test"),
            ("yarn test", "test"),
            ("tox -e py", "test"),
            ("go test ./...", "test"),
            ("cargo test", "test"),
            ("mkdir build", "other"),
        ]:
            with self.subTest(command=command):
                self.assertEqual(session_anatomy.classify_shell(command), family)

    def test_git_wins_over_test_and_search(self):
        """A `git` invocation is never refiled by what its arguments mention --
        `git grep` is version-control work, not a search-tool call, and a diff
        of a pytest file is not a test run."""
        self.assertEqual(session_anatomy.classify_shell("git grep pytest"), "git")
        self.assertEqual(session_anatomy.classify_shell("git diff tests/test_x.py"), "git")

    def test_test_wins_over_read_and_search(self):
        """The marker is matched anywhere in the command, so a test runner
        reached through another command word still files as a test."""
        self.assertEqual(session_anatomy.classify_shell("cat x && pytest"), "test")
        self.assertEqual(session_anatomy.classify_shell("ls && npm test"), "test")

    def test_leading_cd_prefix_is_stripped(self):
        self.assertEqual(session_anatomy.classify_shell("cd /repo && cat a.py"), "read")
        self.assertEqual(session_anatomy.classify_shell("cd /repo; cat a.py"), "read")
        self.assertEqual(session_anatomy.classify_shell("cd pkg && npm test"), "test")

    def test_repeated_cd_prefixes_are_stripped(self):
        self.assertEqual(
            session_anatomy.classify_shell("cd /a && cd /a/b && grep foo ."), "search"
        )

    def test_env_assignment_prefixes_are_stripped(self):
        self.assertEqual(session_anatomy.classify_shell("PYTHONPATH=scripts cat a.py"), "read")
        self.assertEqual(
            session_anatomy.classify_shell("FOO=1 BAR=2 git status"), "git"
        )

    def test_cd_and_env_prefixes_combine(self):
        self.assertEqual(
            session_anatomy.classify_shell("cd /repo && PYTHONPATH=scripts pytest"),
            "test",
        )

    def test_empty_command_is_other(self):
        self.assertEqual(session_anatomy.classify_shell(""), "other")


# ---------------------------------------------------------------------------
# normalize_path
# ---------------------------------------------------------------------------


class TestNormalizePath(unittest.TestCase):
    def test_backslashes_become_forward_slashes(self):
        self.assertEqual(
            session_anatomy.normalize_path(r"C:\repo\src\a.py", None), "C:/repo/src/a.py"
        )

    def test_path_under_cwd_is_relativized(self):
        self.assertEqual(
            session_anatomy.normalize_path("/repo/src/a.py", "/repo"), "src/a.py"
        )

    def test_drive_letter_case_does_not_defeat_the_relativization(self):
        """Two shells on Windows describe one location as `C:\\repo` and
        `c:\\repo`; the same file must not land in `hot_files` twice."""
        self.assertEqual(
            session_anatomy.normalize_path(r"C:\repo\src\a.py", r"c:\repo"), "src/a.py"
        )
        self.assertEqual(
            session_anatomy.normalize_path(r"c:\repo\src\a.py", r"C:\repo"), "src/a.py"
        )

    def test_sibling_worktree_path_folds_to_the_repo_relative_remainder(self):
        self.assertEqual(
            session_anatomy.normalize_path(
                "/home/u/proj/.claude/worktrees/feat-a/src/a.py", "/other/place"
            ),
            "src/a.py",
        )

    def test_worktree_fold_applies_with_no_cwd_at_all(self):
        self.assertEqual(
            session_anatomy.normalize_path(
                "/home/u/proj/.claude/worktrees/feat-a/src/a.py", None
            ),
            "src/a.py",
        )

    def test_unrelated_path_is_returned_normalized_but_unchanged(self):
        self.assertEqual(
            session_anatomy.normalize_path("/elsewhere/src/a.py", "/repo"),
            "/elsewhere/src/a.py",
        )

    def test_trailing_slash_on_cwd_does_not_break_the_prefix_match(self):
        self.assertEqual(
            session_anatomy.normalize_path("/repo/src/a.py", "/repo/"), "src/a.py"
        )


# ---------------------------------------------------------------------------
# Shell read-family path extraction (observed through analyze_transcript)
# ---------------------------------------------------------------------------


class TestShellPathExtraction(TempDirTestCase):
    def _files_read(self, command: str) -> set:
        path = _write_jsonl(
            self.root / "t.jsonl",
            [
                _user("prompt"),
                _assistant(
                    "m0", _usage(), [_tool_use("t0", "Bash", {"command": command})]
                ),
            ],
        )
        return set(session_anatomy.analyze_transcript(path, "a")["files_read"])

    def test_quotes_are_stripped_from_path_arguments(self):
        self.assertEqual(self._files_read("cat '/repo/src/a.py'"), {"src/a.py"})
        self.assertEqual(self._files_read('cat "/repo/src/b.py"'), {"src/b.py"})

    def test_flag_tokens_are_not_paths(self):
        self.assertEqual(
            self._files_read("sed -n /repo/src/a.py"), {"src/a.py"}
        )
        self.assertEqual(self._files_read("cat --show-all /repo/src/a.py"), {"src/a.py"})

    def test_redirects_pipes_and_separators_are_not_paths(self):
        self.assertEqual(
            self._files_read("cat /repo/src/a.py 2>/dev/null"), {"src/a.py"}
        )
        self.assertEqual(self._files_read("cat /repo/src/a.py 2>&1"), {"src/a.py"})
        self.assertEqual(self._files_read("cat /repo/src/a.py /dev/null"), {"src/a.py"})

    def test_only_read_family_commands_contribute_paths(self):
        """A search is not a read: `grep -rn foo src/` scans a tree, it does not
        pull a file into context, so `src/` must not show up as a file read."""
        self.assertEqual(self._files_read("grep -rn foo /repo/src/"), set())
        self.assertEqual(self._files_read("git diff /repo/src/a.py"), set())

    def test_the_command_word_itself_is_never_a_path(self):
        self.assertEqual(self._files_read("cat"), set())

    def test_a_redirect_target_is_not_a_file_that_was_read(self):
        """`cat a.py > out.txt` wrote `out.txt`; it never pulled it into
        context. Counting it would put write-only scratch files at the top of
        `hot_files`, which is a report about what agents *read*."""
        for command in [
            "cat /repo/src/a.py > /repo/out.txt",
            "cat /repo/src/a.py >> /repo/out.txt",
            "head -n 5 /repo/src/a.py 2> /repo/err.log",
            "tail /repo/src/a.py 2>> /repo/err.log",
            "cat /repo/src/a.py &> /repo/all.log",
            "cat /repo/src/a.py &>> /repo/all.log",
        ]:
            with self.subTest(command=command):
                self.assertEqual(self._files_read(command), {"src/a.py"})

    def test_an_input_redirect_contributes_nothing_from_its_target(self):
        self.assertEqual(self._files_read("cat < /repo/in.txt"), set())

    def test_a_glued_redirect_is_still_rejected_as_a_whole_token(self):
        """`>out.txt` is one token carrying a metacharacter -- it must stay
        rejected now that a bare `>` is handled separately."""
        self.assertEqual(
            self._files_read("cat /repo/src/a.py >/repo/out.txt"), {"src/a.py"}
        )
        self.assertEqual(
            self._files_read("cat /repo/src/a.py 2>/repo/err.log"), {"src/a.py"}
        )

    def test_only_the_token_after_the_operator_is_swallowed(self):
        self.assertEqual(
            self._files_read("cat /repo/src/a.py > /repo/out.txt /repo/src/b.py"),
            {"src/a.py", "src/b.py"},
        )


# ---------------------------------------------------------------------------
# analyze_transcript
# ---------------------------------------------------------------------------


def _mixed_transcript(path: Path) -> Path:
    """One transcript exercising every counter at once, with known totals."""
    return _write_jsonl(
        path,
        [
            _user("p" * 40),
            _assistant(
                "msg-1",
                _usage(inp=100, cache_read=900, out=50),
                [_tool_use("tu-1", "Read", {"file_path": "/repo/src/a.py"})],
            ),
            # Same message.id re-emitted as the stream resolves: one request.
            _assistant("msg-1", _usage(inp=100, cache_read=900, out=50)),
            _tool_result("tu-1", "o" * 1000),
            _assistant(
                "msg-2",
                _usage(inp=200, cache_read=1800, cache_creation=100, out=20),
                [_tool_use("tu-2", "Bash", {"command": "cat /repo/src/b.py"})],
            ),
            _tool_result("tu-2", [{"type": "text", "text": "y" * 500}]),
            _assistant(
                "msg-3",
                _usage(inp=50, cache_read=3000, out=5),
                [_tool_use("tu-3", "Read", {"file_path": "/repo/src/a.py"})],
            ),
            '{"type": "assistant", "message": {"id": "trunc"',
        ],
    )


class TestAnalyzeTranscript(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.result = session_anatomy.analyze_transcript(
            _mixed_transcript(self.root / "agent-x.jsonl"), "explore"
        )

    def test_agent_type_and_transcript_name_are_reported(self):
        self.assertEqual(self.result["agent_type"], "explore")
        self.assertEqual(self.result["transcript"], "agent-x.jsonl")

    def test_prompt_is_taken_from_the_first_user_entry(self):
        self.assertEqual(self.result["prompt_chars"], 40)
        self.assertEqual(self.result["prompt_tokens_est"], 10)

    def test_a_streamed_message_id_counts_as_one_request(self):
        self.assertEqual(self.result["requests"], 3)

    def test_context_is_input_plus_both_cache_fields(self):
        self.assertEqual(self.result["context_first"], 1000)
        self.assertEqual(self.result["context_last"], 3050)
        self.assertEqual(self.result["context_peak"], 3050)
        self.assertEqual(self.result["input_processed"], 6150)

    def test_output_tokens_are_counted_once_per_message_id(self):
        self.assertEqual(self.result["output_tokens"], 75)

    def test_tool_calls_and_output_chars_are_keyed_by_tool_name(self):
        self.assertEqual(self.result["tool_calls"], {"Read": 2, "Bash": 1})
        self.assertEqual(self.result["tool_output_chars"], {"Read": 1000, "Bash": 500})

    def test_shell_calls_and_output_are_keyed_by_family(self):
        self.assertEqual(self.result["shell_calls"], {"read": 1})
        self.assertEqual(self.result["shell_output_chars"], {"read": 500})

    def test_file_reads_count_read_calls_and_read_family_shell_calls(self):
        self.assertEqual(self.result["file_reads"], 3)

    def test_an_identical_repeated_call_is_a_duplicate(self):
        self.assertEqual(self.result["duplicate_reads"], 1)

    def test_files_read_are_normalized_against_the_entry_cwd(self):
        self.assertEqual(self.result["files_read"], ["src/a.py", "src/b.py"])

    def test_a_truncated_line_is_counted_and_skipped_not_fatal(self):
        self.assertEqual(self.result["malformed_lines"], 1)

    def test_a_block_list_prompt_is_measured_by_its_text(self):
        path = _write_jsonl(
            self.root / "blocks.jsonl",
            [_user([{"type": "text", "text": "z" * 24}])],
        )
        result = session_anatomy.analyze_transcript(path, "a")
        self.assertEqual(result["prompt_chars"], 24)
        self.assertEqual(result["prompt_tokens_est"], 6)

    def test_an_empty_transcript_reports_zeroes_not_an_error(self):
        path = _write_jsonl(self.root / "empty.jsonl", [])
        result = session_anatomy.analyze_transcript(path, "a")
        self.assertEqual(result["requests"], 0)
        self.assertEqual(result["input_processed"], 0)
        self.assertEqual(result["context_peak"], 0)
        self.assertEqual(result["files_read"], [])

    def test_powershell_commands_are_classified_like_bash(self):
        path = _write_jsonl(
            self.root / "ps.jsonl",
            [
                _user("p"),
                _assistant(
                    "m0",
                    _usage(),
                    [
                        _tool_use(
                            "t0", "PowerShell", {"command": "Get-Content /repo/src/a.py"}
                        )
                    ],
                ),
                _tool_result("t0", "q" * 7),
            ],
        )
        result = session_anatomy.analyze_transcript(path, "a")
        self.assertEqual(result["shell_calls"], {"read": 1})
        self.assertEqual(result["shell_output_chars"], {"read": 7})
        self.assertEqual(result["files_read"], ["src/a.py"])


# ---------------------------------------------------------------------------
# duplicate_reads scoping
# ---------------------------------------------------------------------------


class TestDuplicateReads(TempDirTestCase):
    """`duplicate_reads` is the "this file was pulled into context twice"
    counter that sits beside `file_reads` in the report. A repeated search or
    a re-run `git status` is ordinary agent work, not wasted context, and must
    not inflate it."""

    def _duplicates(self, calls) -> int:
        entries = [_user("prompt")]
        for i, (name, tool_input) in enumerate(calls):
            entries.append(
                _assistant(f"m{i}", _usage(), [_tool_use(f"t{i}", name, tool_input)])
            )
        path = _write_jsonl(self.root / "dup.jsonl", entries)
        return session_anatomy.analyze_transcript(path, "a")["duplicate_reads"]

    def test_a_repeated_read_tool_call_counts(self):
        self.assertEqual(
            self._duplicates(
                [("Read", {"file_path": "/repo/a.py"})] * 2
            ),
            1,
        )

    def test_every_repeat_beyond_the_first_counts(self):
        self.assertEqual(
            self._duplicates([("Read", {"file_path": "/repo/a.py"})] * 3), 2
        )

    def test_a_repeated_read_family_shell_call_counts(self):
        self.assertEqual(
            self._duplicates(
                [("Bash", {"command": "sed -n 1,10p /repo/a.py"})] * 2
            ),
            1,
        )

    def test_a_repeated_powershell_read_counts(self):
        self.assertEqual(
            self._duplicates(
                [("PowerShell", {"command": "Get-Content /repo/a.py"})] * 2
            ),
            1,
        )

    def test_a_repeated_grep_does_not_count(self):
        self.assertEqual(
            self._duplicates([("Grep", {"pattern": "foo", "path": "src"})] * 2), 0
        )

    def test_a_repeated_edit_does_not_count(self):
        self.assertEqual(
            self._duplicates(
                [("Edit", {"file_path": "/repo/a.py", "old_string": "x",
                           "new_string": "y"})] * 2
            ),
            0,
        )

    def test_a_repeated_non_read_shell_call_does_not_count(self):
        self.assertEqual(
            self._duplicates([("Bash", {"command": "git status"})] * 2), 0
        )
        self.assertEqual(
            self._duplicates([("Bash", {"command": "grep -rn foo /repo/src"})] * 2), 0
        )
        self.assertEqual(self._duplicates([("Bash", {"command": "pytest"})] * 2), 0)

    def test_distinct_reads_are_not_duplicates(self):
        self.assertEqual(
            self._duplicates(
                [
                    ("Read", {"file_path": "/repo/a.py"}),
                    ("Read", {"file_path": "/repo/b.py"}),
                    ("Bash", {"command": "cat /repo/a.py"}),
                ]
            ),
            0,
        )

    def test_a_non_read_repeat_does_not_mask_a_later_read_repeat(self):
        """Regression guard: the non-read calls must be skipped outright, not
        recorded into the signature set where they could shadow a real one."""
        self.assertEqual(
            self._duplicates(
                [
                    ("Grep", {"pattern": "foo"}),
                    ("Grep", {"pattern": "foo"}),
                    ("Read", {"file_path": "/repo/a.py"}),
                    ("Read", {"file_path": "/repo/a.py"}),
                ]
            ),
            1,
        )


# ---------------------------------------------------------------------------
# analyze_session
# ---------------------------------------------------------------------------


class TestAnalyzeSession(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.session_dir = _make_session(
            self.root,
            "sess-1",
            main_entries=_simple_agent(400, [5000], files=["main-only.py"]),
            subagents=[
                (
                    "aaa",
                    "explore",
                    _simple_agent(40, [1000, 2000], files=["x.py", "shared.py"]),
                ),
                ("bbb", None, _simple_agent(80, [500], files=["shared.py"])),
            ],
        )
        self.result = session_anatomy.analyze_session(self.session_dir)

    def test_main_transcript_is_reported_under_its_own_agent_type(self):
        self.assertIn(session_anatomy.MAIN_AGENT_TYPE, self.result["by_type"])
        self.assertEqual(
            self.result["by_type"][session_anatomy.MAIN_AGENT_TYPE]["agents"], 1
        )

    def test_a_subagent_without_meta_is_grouped_as_unknown_not_dropped(self):
        self.assertIn("unknown", self.result["by_type"])
        self.assertEqual(self.result["by_type"]["unknown"]["requests"], 1)

    def test_by_type_aggregates_the_named_agent_type(self):
        explore = self.result["by_type"]["explore"]
        self.assertEqual(explore["agents"], 1)
        self.assertEqual(explore["requests"], 2)
        self.assertEqual(explore["input_processed"], 3000)
        self.assertEqual(explore["file_reads"], 2)

    def test_main_is_excluded_from_the_subagent_totals(self):
        """Main carries the orchestration context; folding it into the subagent
        totals would drown out the per-subagent shares this report exists for."""
        totals = self.result["subagent_totals"]
        self.assertEqual(totals["agents"], 2)
        self.assertEqual(totals["requests"], 3)
        self.assertEqual(totals["input_processed"], 3500)

    def test_prompt_share_is_request_weighted_over_input_processed(self):
        totals = self.result["subagent_totals"]
        self.assertAlmostEqual(totals["prompt_share"], (10 * 2 + 20 * 1) / 3500)

    def test_baseline_share_is_request_weighted_over_input_processed(self):
        totals = self.result["subagent_totals"]
        self.assertAlmostEqual(totals["baseline_share"], (1000 * 2 + 500 * 1) / 3500)

    def test_hot_files_rank_by_distinct_subagents_then_path(self):
        self.assertEqual(
            self.result["hot_files"],
            [
                {"path": "shared.py", "agents": 2},
                {"path": "x.py", "agents": 1},
            ],
        )

    def test_hot_files_ignore_what_only_main_read(self):
        self.assertNotIn(
            "main-only.py", [entry["path"] for entry in self.result["hot_files"]]
        )

    def test_an_agent_with_zero_requests_does_not_divide_by_zero(self):
        session_dir = _make_session(
            self.root,
            "sess-silent",
            main_entries=None,
            subagents=[("ccc", "explore", [_user("dispatched but never answered")])],
        )
        result = session_anatomy.analyze_session(session_dir)
        self.assertEqual(result["subagent_totals"]["requests"], 0)
        self.assertEqual(result["subagent_totals"]["prompt_share"], 0.0)
        self.assertEqual(result["subagent_totals"]["baseline_share"], 0.0)
        self.assertEqual(result["by_type"]["explore"]["mean_context_first"], 0.0)

    def test_a_session_with_no_subagents_directory_still_reports(self):
        session_dir = _make_session(
            self.root, "sess-solo", main_entries=_simple_agent(40, [100])
        )
        result = session_anatomy.analyze_session(session_dir)
        self.assertEqual(result["subagent_totals"]["agents"], 0)
        self.assertEqual(result["hot_files"], [])
        self.assertEqual(
            result["by_type"][session_anatomy.MAIN_AGENT_TYPE]["requests"], 1
        )

    def test_malformed_lines_are_summed_across_every_transcript(self):
        session_dir = _make_session(
            self.root,
            "sess-damaged",
            main_entries=[_user("p"), "{broken"],
            subagents=[("ddd", "explore", [_user("p"), "{also broken"])],
        )
        result = session_anatomy.analyze_session(session_dir)
        self.assertEqual(result["malformed_lines"], 2)

    def test_an_unreadable_meta_file_falls_back_to_unknown(self):
        session_dir = _make_session(
            self.root, "sess-badmeta", main_entries=None,
            subagents=[("eee", None, _simple_agent(40, [100]))],
        )
        (session_dir / "subagents" / "agent-eee.meta.json").write_text(
            "{not json", encoding="utf-8"
        )
        result = session_anatomy.analyze_session(session_dir)
        self.assertEqual(list(result["by_type"]), ["unknown"])

    def test_the_result_is_json_serializable(self):
        payload = json.loads(json.dumps(self.result))
        self.assertEqual(payload["subagent_totals"]["agents"], 2)


# ---------------------------------------------------------------------------
# resolve_session
# ---------------------------------------------------------------------------


class TestResolveSession(TempDirTestCase):
    def test_an_existing_directory_resolves_to_itself(self):
        session_dir = self.root / "projects" / "proj-a" / "sess-1"
        session_dir.mkdir(parents=True)
        self.assertEqual(
            session_anatomy.resolve_session(str(session_dir), self.root / "projects"),
            session_dir,
        )

    def test_a_bare_id_resolves_to_its_unique_match(self):
        projects = self.root / "projects"
        (projects / "proj-a" / "sess-1").mkdir(parents=True)
        (projects / "proj-b" / "sess-2").mkdir(parents=True)
        self.assertEqual(
            session_anatomy.resolve_session("sess-1", projects),
            projects / "proj-a" / "sess-1",
        )

    def test_no_match_raises_value_error_naming_the_id(self):
        projects = self.root / "projects"
        projects.mkdir()
        with self.assertRaises(ValueError) as ctx:
            session_anatomy.resolve_session("sess-missing", projects)
        self.assertIn("sess-missing", str(ctx.exception))

    def test_an_ambiguous_id_raises_rather_than_picking_one(self):
        """Silently analyzing one of two same-named sessions would produce a
        report attributed to the wrong project."""
        projects = self.root / "projects"
        (projects / "proj-a" / "sess-dup").mkdir(parents=True)
        (projects / "proj-b" / "sess-dup").mkdir(parents=True)
        with self.assertRaises(ValueError) as ctx:
            session_anatomy.resolve_session("sess-dup", projects)
        self.assertIn("ambiguous", str(ctx.exception))

    def test_a_missing_projects_root_is_not_an_attribute_error(self):
        with self.assertRaises(ValueError):
            session_anatomy.resolve_session("sess-1", self.root / "no-such-root")


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


class TestFormatReport(TempDirTestCase):
    def _report(self, session_dir: Path, top_files: int = 8) -> str:
        result = session_anatomy.analyze_session(session_dir)
        result["session_id"] = session_dir.name
        return session_anatomy.format_report({"sessions": [result]}, top_files)

    def test_report_is_ascii_only(self):
        """The report is printed to whatever console the operator has; a box
        glyph or an en dash is what makes a legacy Windows console throw."""
        session_dir = _make_session(
            self.root,
            "sess-1",
            main_entries=_simple_agent(40, [100]),
            subagents=[("aaa", "explore", _simple_agent(40, [100], files=["x.py"]))],
        )
        report = self._report(session_dir)
        self.assertTrue(report.isascii(), report)

    def test_report_names_the_session_and_its_agent_types(self):
        session_dir = _make_session(
            self.root,
            "sess-named",
            main_entries=_simple_agent(40, [100]),
            subagents=[("aaa", "explore", _simple_agent(40, [100]))],
        )
        report = self._report(session_dir)
        self.assertIn("session sess-named", report)
        self.assertIn("explore", report)
        self.assertIn(session_anatomy.MAIN_AGENT_TYPE, report)

    def test_the_duplicate_column_is_labelled_dup_reads(self):
        """"dups" read as "duplicate anything"; the column counts re-read files
        only, and the header has to say so next to "reads"."""
        session_dir = _make_session(
            self.root,
            "sess-header",
            main_entries=_simple_agent(40, [100]),
        )
        report = self._report(session_dir)
        self.assertIn("dup reads", report)

    def test_top_files_truncates_the_hot_file_rows(self):
        session_dir = _make_session(
            self.root,
            "sess-files",
            main_entries=None,
            subagents=[
                ("aaa", "explore", _simple_agent(40, [100], files=["a.py", "b.py"])),
                ("bbb", "explore", _simple_agent(40, [100], files=["a.py"])),
            ],
        )
        self.assertIn("b.py", self._report(session_dir, top_files=8))
        self.assertNotIn("b.py", self._report(session_dir, top_files=1))

    def test_a_tool_row_below_a_tenth_of_a_percent_is_omitted_from_the_text(self):
        """A one-off MCP tool that returned a handful of characters is noise in
        a report about where the context went -- but it stays in the JSON,
        which is for machines that can filter for themselves."""
        session_dir = _make_session(
            self.root,
            "sess-tail",
            main_entries=None,
            subagents=[
                (
                    "aaa",
                    "explore",
                    [
                        _user("p" * 40),
                        _assistant(
                            "m0",
                            _usage(cache_read=1000),
                            [
                                _tool_use("t0", "Read", {"file_path": "/repo/a.py"}),
                                _tool_use("t1", "Glob", {"pattern": "**/*.py"}),
                            ],
                        ),
                        _tool_result("t0", "o" * 20000),
                        _tool_result("t1", "x"),
                    ],
                )
            ],
        )
        result = session_anatomy.analyze_session(session_dir)
        self.assertEqual(result["tool_output_chars"], {"Read": 20000, "Glob": 1})
        result["session_id"] = session_dir.name
        report = session_anatomy.format_report({"sessions": [result]}, 8)
        self.assertIn("Read", report)
        self.assertNotIn("Glob", report)


# ---------------------------------------------------------------------------
# main / CLI
# ---------------------------------------------------------------------------


class TestMain(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.session_dir = _make_session(
            self.root,
            "sess-cli",
            main_entries=_simple_agent(40, [100]),
            subagents=[("aaa", "explore", _simple_agent(40, [200], files=["x.py"]))],
        )

    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = session_anatomy.main(argv)
        return rc, buf.getvalue()

    def test_a_completed_report_exits_zero(self):
        """It is a report, not a gate: a non-zero exit would make it unusable
        from a wrapper script that checks return codes."""
        rc, out = self._run([str(self.session_dir)])
        self.assertEqual(rc, 0)
        self.assertIn("session sess-cli", out)

    def test_json_output_carries_the_schema_version_and_session_id(self):
        rc, out = self._run([str(self.session_dir), "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual([s["session_id"] for s in payload["sessions"]], ["sess-cli"])

    def test_several_sessions_are_reported_in_argument_order(self):
        other = _make_session(
            self.root, "sess-other", main_entries=_simple_agent(40, [100])
        )
        rc, out = self._run([str(self.session_dir), str(other), "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(
            [s["session_id"] for s in payload["sessions"]], ["sess-cli", "sess-other"]
        )

    def test_an_unresolvable_session_exits_two(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                session_anatomy.main(
                    ["no-such-session", "--projects-root", str(self.root)]
                )
        self.assertEqual(ctx.exception.code, 2)

    def test_top_files_zero_is_rejected(self):
        """`--top-files 0` would silently print no hot files at all, which reads
        as "nothing was read" rather than "you asked for none"."""
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                session_anatomy.main([str(self.session_dir), "--top-files", "0"])
        self.assertEqual(ctx.exception.code, 2)

    def test_a_non_integer_top_files_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                session_anatomy.main([str(self.session_dir), "--top-files", "many"])
        self.assertEqual(ctx.exception.code, 2)

    def test_no_session_argument_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                session_anatomy.main([])
        self.assertEqual(ctx.exception.code, 2)

    def test_main_reconfigures_stdout_before_printing(self):
        """A session id or agent type may be non-ASCII; on a legacy Windows
        console that is a UnicodeEncodeError *after* all the work is done."""
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with mock.patch.object(sys, "stdout", stream):
            rc = session_anatomy.main([str(self.session_dir)])
        self.assertEqual(rc, 0)
        self.assertEqual(stream.encoding.lower().replace("-", ""), "utf8")
        stream.write("\u2014\n")


# ---------------------------------------------------------------------------
# Weighted decomposition (issue #185)
# ---------------------------------------------------------------------------


def _thinking(text="", signature=""):
    return {"type": "thinking", "thinking": text, "signature": signature}


def _text(text):
    return {"type": "text", "text": text}


# The two tool_use inputs below, as `json.dumps` encodes them. Pinned by
# `test_fixture_tool_use_input_lengths` so a miscount fails loudly there
# rather than as an unexplained arithmetic mismatch further down.
_READ_INPUT = {"file_path": "/repo/x.py"}  # 27 chars as JSON
_BASH_INPUT = {"command": "ls"}  # 17 chars as JSON


def _weighted_transcript(path: Path) -> Path:
    """Three requests with every content category, at known positions.

    Request boundaries: m1 (seen=1), m2 (seen=2), m3 (seen=3); total 3, so a
    block appearing while ``seen`` is 1 / 2 / 3 is re-sent by 2 / 1 / 0 later
    requests.

    Hand-computed expectation (chars, then tokens at 4 chars/token):
      baseline          context_first 1000 * 3 requests      = 3000 tokens
      thinking          max(0, 80) * 2                       = 160 -> 40.0
      assistant_output  40*2 + 27*2 (Read input) + 80*1
                        + 17*1 (Bash input) + 12*0           = 231 -> 57.75
      tool_results      400*2 + 200*1                        = 1000 -> 250.0
      other_user        20*2                                 = 40 -> 10.0
      input_processed   1000 + 1500 + 2000                   = 4500
      unexplained       4500 - 3000 - 40 - 57.75 - 250 - 10  = 1142.25
    """
    return _write_jsonl(
        path,
        [
            # Before the first boundary: part of the baseline, never weighted.
            _user("p" * 40),
            _user("e" * 999),
            # m1 is the boundary; its three entries are request 1's output.
            _assistant("m1", _usage(cache_read=1000), [_thinking("", "s" * 80)]),
            _assistant("m1", _usage(cache_read=1000), [_text("a" * 40)]),
            _assistant(
                "m1", _usage(cache_read=1000), [_tool_use("t1", "Read", _READ_INPUT)]
            ),
            _tool_result("t1", "o" * 400),
            _user("r" * 20),
            # An attachment record is deliberately not attributed.
            {"type": "attachment", "attachment": {"type": "hook_success", "content": "z" * 5000}},
            _assistant("m2", _usage(cache_read=1500), [_text("b" * 80)]),
            _assistant(
                "m2", _usage(cache_read=1500), [_tool_use("t2", "Bash", _BASH_INPUT)]
            ),
            _tool_result("t2", [{"type": "text", "text": "q" * 200}]),
            # Output of the last request: no later request carries it.
            _assistant("m3", _usage(cache_read=2000), [_text("c" * 12)]),
        ],
    )


class TestWeightedDecomposition(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.result = session_anatomy.analyze_transcript(
            _weighted_transcript(self.root / "agent-w.jsonl"), "archimedes"
        )
        self.weighted = self.result["weighted_tokens"]

    def test_fixture_tool_use_input_lengths(self):
        self.assertEqual(len(json.dumps(_READ_INPUT)), 27)
        self.assertEqual(len(json.dumps(_BASH_INPUT)), 17)

    def test_request_boundaries_are_distinct_usage_carrying_message_ids(self):
        self.assertEqual(self.result["requests"], 3)
        self.assertEqual(self.result["input_processed"], 4500)

    def test_baseline_is_first_context_times_requests(self):
        self.assertEqual(self.weighted["baseline"], 3000)

    def test_tool_results_are_weighted_by_later_requests(self):
        self.assertEqual(self.weighted["tool_results"], (400 * 2 + 200 * 1) / 4)

    def test_thinking_is_sized_by_its_signature_when_the_text_is_empty(self):
        self.assertEqual(self.weighted["thinking"], 80 * 2 / 4)

    def test_assistant_text_and_tool_use_inputs_are_one_category(self):
        expected = (40 * 2 + 27 * 2 + 80 * 1 + 17 * 1 + 12 * 0) / 4
        self.assertEqual(self.weighted["assistant_output"], expected)

    def test_other_user_text_after_the_first_request_is_weighted(self):
        """The 40-char prompt and 999-char pre-request message are baseline;
        only the 20-char reminder after m1 counts here."""
        self.assertEqual(self.weighted["other_user"], 20 * 2 / 4)

    def test_unexplained_is_the_remainder(self):
        self.assertEqual(self.weighted["unexplained"], 4500 - 3000 - 40 - 57.75 - 250 - 10)

    def test_categories_sum_to_input_processed(self):
        self.assertEqual(
            list(self.weighted), list(session_anatomy.WEIGHTED_CATEGORIES)
        )
        self.assertAlmostEqual(sum(self.weighted.values()), 4500)

    def test_chars_per_token_is_the_named_constant(self):
        with mock.patch.object(session_anatomy, "CHARS_PER_TOKEN", 2.0):
            result = session_anatomy.analyze_transcript(
                _weighted_transcript(self.root / "agent-w2.jsonl"), "a"
            )
        self.assertEqual(result["weighted_tokens"]["tool_results"], 1000 / 2)
        self.assertEqual(result["weighted_tokens"]["baseline"], 3000)

    def test_raw_char_counters_are_unchanged_by_the_weighting(self):
        self.assertEqual(self.result["tool_output_chars"], {"Read": 400, "Bash": 200})

    def test_thinking_text_longer_than_its_signature_wins(self):
        path = _write_jsonl(
            self.root / "think.jsonl",
            [
                _user("p"),
                _assistant("m1", _usage(cache_read=10), [_thinking("t" * 100, "s" * 8)]),
                _assistant("m2", _usage(cache_read=10)),
            ],
        )
        weighted = session_anatomy.analyze_transcript(path, "a")["weighted_tokens"]
        self.assertEqual(weighted["thinking"], 100 / 4)

    def test_redacted_thinking_is_sized_by_its_data(self):
        path = _write_jsonl(
            self.root / "redacted.jsonl",
            [
                _user("p"),
                _assistant(
                    "m1", _usage(cache_read=10), [{"type": "redacted_thinking", "data": "d" * 40}]
                ),
                _assistant("m2", _usage(cache_read=10)),
            ],
        )
        weighted = session_anatomy.analyze_transcript(path, "a")["weighted_tokens"]
        self.assertEqual(weighted["thinking"], 40 / 4)

    def test_an_assistant_entry_without_usage_is_not_a_boundary(self):
        path = _write_jsonl(
            self.root / "nousage.jsonl",
            [
                _user("p"),
                _assistant("m1", _usage(cache_read=10)),
                {"type": "assistant", "message": {"id": "x", "content": [_text("n" * 8)]}},
                _tool_result("t", "o" * 40),
                _assistant("m2", _usage(cache_read=10)),
            ],
        )
        result = session_anatomy.analyze_transcript(path, "a")
        self.assertEqual(result["requests"], 2)
        self.assertEqual(result["weighted_tokens"]["tool_results"], 40 / 4)
        self.assertEqual(result["weighted_tokens"]["assistant_output"], 8 / 4)

    def test_an_empty_transcript_has_all_zero_weighted_tokens(self):
        path = _write_jsonl(self.root / "empty-w.jsonl", [])
        weighted = session_anatomy.analyze_transcript(path, "a")["weighted_tokens"]
        self.assertEqual(set(weighted.values()), {0})


class TestWeightedAggregation(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        session_dir = self.root / "sess-w"
        _weighted_transcript(session_dir / "subagents" / "agent-aaa.jsonl")
        (session_dir / "subagents" / "agent-aaa.meta.json").write_text(
            json.dumps({"agentType": "archimedes"}), encoding="utf-8"
        )
        # A second agent with no content after its first request: pure baseline.
        _make_session(
            self.root,
            "sess-w",
            main_entries=_simple_agent(40, [100, 200]),
            subagents=[("bbb", "explore", _simple_agent(40, [500, 500]))],
        )
        self.result = session_anatomy.analyze_session(session_dir)
        self.result["session_id"] = "sess-w"

    def test_per_type_shares_are_weighted_tokens_over_input_processed(self):
        entry = self.result["by_type"]["archimedes"]
        self.assertEqual(entry["weighted_tokens"]["tool_results"], 250.0)
        self.assertAlmostEqual(entry["weighted_shares"]["tool_results"], 250 / 4500)
        self.assertAlmostEqual(entry["weighted_shares"]["baseline"], 3000 / 4500)

    def test_subagent_totals_sum_agents_and_exclude_main(self):
        totals = self.result["subagent_totals"]
        # archimedes 4500 + explore 1000; main's 300 is excluded.
        self.assertEqual(totals["input_processed"], 5500)
        self.assertEqual(totals["weighted_tokens"]["baseline"], 3000 + 1000)
        self.assertAlmostEqual(totals["weighted_shares"]["tool_results"], 250 / 5500)
        self.assertAlmostEqual(sum(totals["weighted_shares"].values()), 1.0)

    def test_weighted_baseline_share_matches_the_v1_baseline_share(self):
        totals = self.result["subagent_totals"]
        self.assertAlmostEqual(totals["weighted_shares"]["baseline"], totals["baseline_share"])

    def test_report_prints_the_weighted_table_and_labels_raw_shares(self):
        report = session_anatomy.format_report({"sessions": [self.result]}, 8)
        self.assertIn("weighted input decomposition", report)
        self.assertIn("4 chars/token", report)
        weighted_part = report.split("weighted input decomposition", 1)[1]
        self.assertIn("subagents (excl. main)", weighted_part)
        # archimedes: tool results 250 / 4500 = 5.6%.
        self.assertIn("5.6%", weighted_part.split("archimedes", 1)[1].splitlines()[0])
        self.assertIn("raw chars, unweighted", report)

    def test_json_v2_keeps_v1_keys_and_adds_the_weighted_ones(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = session_anatomy.main([str(self.root / "sess-w"), "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["chars_per_token"], 4.0)
        session = payload["sessions"][0]
        for key in ("by_type", "subagent_totals", "tool_output_chars",
                    "shell_output_chars", "hot_files", "malformed_lines"):
            self.assertIn(key, session)
        totals = session["subagent_totals"]
        for key in ("agents", "requests", "input_processed", "prompt_share",
                    "baseline_share", "mean_context_first", "mean_context_last",
                    "file_reads", "duplicate_reads"):
            self.assertIn(key, totals)
        self.assertEqual(
            list(totals["weighted_shares"]), list(session_anatomy.WEIGHTED_CATEGORIES)
        )
        self.assertIn("weighted_tokens", session["by_type"]["archimedes"])


if __name__ == "__main__":
    unittest.main()
