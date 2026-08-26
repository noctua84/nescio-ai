import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
sys.path.insert(0, str(ROOT / "scripts"))
import record_stop as rs  # noqa: E402
import _trail_scope as scope  # noqa: E402


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _record(git_root: str | None = None, **extra) -> str:
    rec: dict = {"ts": "2026-07-12T08:00:00+00:00"}
    if git_root is not None:
        rec["git_root"] = git_root
    rec.update(extra)
    return json.dumps(rec) + "\n"


def _trail_name(repo_root: Path) -> str:
    """The trail filename `record_stop` would write for ``repo_root``.

    `record_stop` keys the file on git's output, which is forward-slashed on
    every platform — so fixtures must use that spelling, not `str(Path(...))`.
    """
    return f"{rs.repo_key(repo_root.as_posix())}.jsonl"


class ResolveRepoRootTest(unittest.TestCase):
    """The collapse lives in `resolve_repo_root`, not in one of its callers.

    `compute_readiness` calls `resolve_repo_root` directly and never goes through
    `trail_repo_root`, so a fix applied only in the latter would leave the two
    tools bucketing a degraded record differently — the exact disagreement
    `_trail_scope` exists to prevent.
    """

    def test_degraded_repo_root_naming_a_worktree_collapses_to_the_repo(self):
        wt = "C:/p/repo/.claude/worktrees/feat"
        self.assertEqual(
            scope.resolve_repo_root({"git_root": wt, "repo_root": wt}),
            "C:/p/repo",
        )

    def test_collapse_applies_without_live_resolution(self):
        wt = "C:/p/repo/.claude/worktrees/feat"
        self.assertEqual(
            scope.resolve_repo_root({"repo_root": wt}, resolve_live=False),
            "C:/p/repo",
        )

    def test_backslash_degraded_repo_root_collapses_too(self):
        wt = "C:\\p\\repo\\.claude\\worktrees\\feat"
        self.assertEqual(
            scope.resolve_repo_root({"repo_root": wt}, resolve_live=False),
            "C:/p/repo",
        )

    def test_plain_repo_root_is_returned_unchanged(self):
        self.assertEqual(
            scope.resolve_repo_root({"repo_root": "C:/p/repo"}, resolve_live=False),
            "C:/p/repo",
        )


class TrailRepoRootTest(unittest.TestCase):
    def test_empty_trail_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            t = _write(Path(d) / "t.jsonl", "")
            self.assertIsNone(scope.trail_repo_root(t))

    def test_blank_lines_only_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            t = _write(Path(d) / "t.jsonl", "\n\n   \n")
            self.assertIsNone(scope.trail_repo_root(t))

    def test_malformed_first_line_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            t = _write(Path(d) / "t.jsonl", "{not json at all\n")
            self.assertIsNone(scope.trail_repo_root(t))

    def test_trail_of_only_rootless_records_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            t = _write(
                Path(d) / "t.jsonl",
                (json.dumps({"ts": "x"}) + "\n") * 3,
            )
            self.assertIsNone(scope.trail_repo_root(t))

    def test_rootless_first_record_does_not_abandon_the_trail(self):
        # A head record that parses but carries neither `repo_root` nor
        # `git_root` says nothing about the owner. Stopping there made the whole
        # trail unattributable — dropped from `trails_for_repo`, so never
        # stamped, so never pruned, and reported UNATTRIBUTED by
        # `unmark_harvested` — on the strength of one rootless line.
        with tempfile.TemporaryDirectory() as d:
            t = _write(
                Path(d) / "t.jsonl",
                json.dumps({"ts": "x"}) + "\n" + _record("C:/Users/x/repo"),
            )
            self.assertEqual(scope.trail_repo_root(t), "C:/Users/x/repo")

    def test_rootless_head_is_skipped_past_malformed_lines_too(self):
        with tempfile.TemporaryDirectory() as d:
            t = _write(
                Path(d) / "t.jsonl",
                "{not json\n"
                + json.dumps({"ts": "x"}) + "\n"
                + json.dumps([1, 2]) + "\n"
                + _record("C:/Users/x/repo"),
            )
            self.assertEqual(scope.trail_repo_root(t), "C:/Users/x/repo")

    def test_scan_bound_is_honoured(self):
        # The bound keeps a corrupt multi-megabyte trail from being read end to
        # end. Asserted on both sides of the boundary so the bound cannot drift
        # silently.
        rootless = json.dumps({"ts": "x"}) + "\n"
        n = scope.HEAD_SCAN_RECORDS
        with tempfile.TemporaryDirectory() as d:
            inside = _write(
                Path(d) / "inside.jsonl",
                rootless * (n - 1) + _record("C:/Users/x/repo"),
            )
            beyond = _write(
                Path(d) / "beyond.jsonl",
                rootless * n + _record("C:/Users/x/repo"),
            )
            self.assertEqual(scope.trail_repo_root(inside), "C:/Users/x/repo")
            self.assertIsNone(scope.trail_repo_root(beyond))

    def test_shared_cache_gives_the_same_answer_with_fewer_git_calls(self):
        # Attribution is the only live-git caller in a `trails_for_repo` sweep,
        # and that sweep runs over the machine-global trail dir (~100 files here,
        # each with a multi-second git timeout). The cache must collapse repeated
        # resolutions of one path without changing a single answer.
        with tempfile.TemporaryDirectory() as d:
            live = Path(d) / "live-repo"
            live.mkdir()
            a = _write(Path(d) / "a.jsonl", _record(live.as_posix()))
            b = _write(Path(d) / "b.jsonl", _record(live.as_posix()))
            calls: list[str] = []
            saved = rs.git_roots
            try:
                rs.git_roots = lambda cwd: (calls.append(cwd), (cwd, str(live)))[1]
                uncached = [scope.trail_repo_root(t) for t in (a, b)]
                self.assertEqual(len(calls), 2)
                calls.clear()
                cache: dict[str, str] = {}
                cached = [scope.trail_repo_root(t, cache=cache) for t in (a, b)]
                self.assertEqual(len(calls), 1)
            finally:
                rs.git_roots = saved
            self.assertEqual(cached, uncached)
            self.assertEqual(cached, [live.as_posix()] * 2)

    def test_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(scope.trail_repo_root(Path(d) / "nope.jsonl"))

    def test_unreadable_path_returns_none(self):
        # A directory is not readable as a file; must degrade, never raise.
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(scope.trail_repo_root(Path(d)))

    def test_first_parseable_record_wins(self):
        with tempfile.TemporaryDirectory() as d:
            t = _write(
                Path(d) / "t.jsonl",
                _record("C:/Users/x/repo") + _record("C:/Users/x/other"),
            )
            self.assertEqual(scope.trail_repo_root(t), "C:/Users/x/repo")

    def test_repo_root_field_wins_over_worktree_git_root(self):
        # `repo_root` has been recorded at source since #66 and is authoritative;
        # `git_root` is the ephemeral worktree root.
        with tempfile.TemporaryDirectory() as d:
            t = _write(
                Path(d) / "t.jsonl",
                _record(
                    "C:/p/somewhere/.claude/worktrees/feat",
                    repo_root="C:/p/right",
                ),
            )
            self.assertEqual(scope.trail_repo_root(t), "C:/p/right")

    def test_worktree_git_root_is_stripped_to_the_repo(self):
        with tempfile.TemporaryDirectory() as d:
            t = _write(
                Path(d) / "t.jsonl",
                _record("C:/p/repo/.claude/worktrees/feat-x"),
            )
            self.assertEqual(scope.trail_repo_root(t), "C:/p/repo")

    def test_degraded_repo_root_naming_a_worktree_is_stripped(self):
        # `git_roots`' degraded branch mirrors the worktree toplevel into
        # `repo_root`. A `repo_root` that is literally a worktree path is that
        # degradation, not a distinct repository.
        with tempfile.TemporaryDirectory() as d:
            wt = "C:/p/repo/.claude/worktrees/feat"
            t = _write(Path(d) / "t.jsonl", _record(wt, repo_root=wt))
            self.assertEqual(scope.trail_repo_root(t), "C:/p/repo")

    def test_windows_backslashes_are_normalised_to_posix(self):
        # ~2,100 legacy records predate the write-site fix and carry native
        # separators; the returned root is always posix.
        with tempfile.TemporaryDirectory() as d:
            t = _write(Path(d) / "t.jsonl", _record("C:\\Users\\x\\repo"))
            self.assertEqual(scope.trail_repo_root(t), "C:/Users/x/repo")


class BelongsToRepoTest(unittest.TestCase):
    def test_own_canonical_trail_matches_with_zero_records(self):
        # The filename rule is the only one that can match a trail with no
        # records at all — there is no root to resolve.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "proj"
            repo.mkdir()
            t = _write(Path(d) / _trail_name(repo), "")
            self.assertTrue(scope.belongs_to_repo(t, repo))

    def test_both_repo_key_spellings_resolve_to_the_same_repo(self):
        # `repo_key` hashes the *raw string*, so `C:\x\y` and `C:/x/y` — one
        # repository — produce two different keys. The posix form is canonical
        # (git emits forward slashes everywhere, so that is the key normally
        # written); the native form is still reachable through `git_roots`'
        # degraded `cwd` fallback. Both must select the same repository.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "proj"
            repo.mkdir()
            if os.sep != "/":
                # Guard the fixture: the hazard is real on this platform.
                self.assertNotEqual(
                    rs.repo_key(str(repo)), rs.repo_key(repo.as_posix())
                )
            posix_named = _write(Path(d) / _trail_name(repo), "")
            native_named = _write(
                Path(d) / f"{rs.repo_key(str(repo))}.jsonl", ""
            )
            self.assertTrue(scope.belongs_to_repo(posix_named, repo))
            self.assertTrue(scope.belongs_to_repo(native_named, repo))

    def test_worktree_trail_matches_by_git_root(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "proj"
            wt = repo / ".claude" / "worktrees" / "feature"
            wt.mkdir(parents=True)
            t = _write(Path(d) / "unrelated-name.jsonl", _record(wt.as_posix()))
            self.assertTrue(scope.belongs_to_repo(t, repo))

    def test_trail_with_repo_root_matches_even_when_git_root_is_a_worktree(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "proj"
            wt = repo / ".claude" / "worktrees" / "feature"
            repo.mkdir()
            t = _write(
                Path(d) / "wt.jsonl",
                _record(wt.as_posix(), repo_root=repo.as_posix()),
            )
            self.assertTrue(scope.belongs_to_repo(t, repo))

    def test_legacy_backslash_record_matches_forward_slash_repo(self):
        # The normalisation regression: on Windows a legacy `C:\x\y` must still
        # compare equal to the `C:/x/y` spelling git (and `Path.as_posix`) uses.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "proj"
            repo.mkdir()
            native = repo.as_posix().replace("/", "\\")
            t = _write(Path(d) / "legacy.jsonl", _record(native))
            self.assertTrue(scope.belongs_to_repo(t, repo))
            back = _write(Path(d) / "legacy2.jsonl", _record(None, repo_root=native))
            self.assertTrue(scope.belongs_to_repo(back, repo))

    def test_deleted_worktree_still_matches(self):
        # Behaviour contract: `strip_worktree` is a *textual* match, so a
        # worktree that has been deleted from disk — the `repo-hygiene` skill
        # deletes them routinely — is still attributed to its owning repo and
        # can still be stamped. Neither the worktree nor the repo dir exists here.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "vanished-repo"
            gone = repo / ".claude" / "worktrees" / "deleted"
            self.assertFalse(gone.exists())
            self.assertFalse(repo.exists())
            t = _write(Path(d) / "gone.jsonl", _record(gone.as_posix()))
            self.assertTrue(scope.belongs_to_repo(t, repo))

    def test_worktree_outside_the_repo_tree_matches(self):
        # `git worktree add ../feature` puts the checkout beside the repo, not
        # under it. `repo_root` still names the repo, so equality on the resolved
        # root attributes it — an at-or-under path test would drop it.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "proj"
            outside = Path(d) / "feature-checkout"
            repo.mkdir()
            outside.mkdir()
            # Guard the fixture: it really is outside the repo tree.
            self.assertFalse(
                outside.as_posix().startswith(repo.as_posix() + "/")
            )
            t = _write(
                Path(d) / "outside.jsonl",
                _record(outside.as_posix(), repo_root=repo.as_posix()),
            )
            self.assertTrue(scope.belongs_to_repo(t, repo))

    def test_repo_root_itself_matches(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "proj"
            repo.mkdir()
            t = _write(Path(d) / "any.jsonl", _record(repo.as_posix()))
            self.assertTrue(scope.belongs_to_repo(t, repo))

    def test_prefix_sibling_repo_does_not_match(self):
        # `proj-docs` is a string prefix collision with `proj` in BOTH the
        # slugified filename and the raw path. Neither may match.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "proj"
            sibling = Path(d) / "proj-docs"
            repo.mkdir()
            sibling.mkdir()
            by_name = _write(Path(d) / _trail_name(sibling), "")
            by_root = _write(Path(d) / "sib.jsonl", _record(sibling.as_posix()))
            # Guard the fixture: the sibling's slug really is a prefix collision.
            slug = lambda p: re.sub(r"[^0-9A-Za-z]", "-", str(p))  # noqa: E731
            self.assertTrue(slug(sibling).startswith(slug(repo)))
            self.assertFalse(scope.belongs_to_repo(by_name, repo))
            self.assertFalse(scope.belongs_to_repo(by_root, repo))

    def test_nested_repo_below_the_root_does_not_match(self):
        # Ownership is equality on the resolved root, not "lives under". A
        # separate repository checked out inside another one is its own repo.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "proj"
            nested = repo / "vendor" / "inner"
            nested.mkdir(parents=True)
            t = _write(Path(d) / "nested.jsonl", _record(None, repo_root=nested.as_posix()))
            self.assertFalse(scope.belongs_to_repo(t, repo))

    def test_unrelated_repo_does_not_match(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "proj"
            other = Path(d) / "elsewhere"
            repo.mkdir()
            other.mkdir()
            t = _write(Path(d) / "other.jsonl", _record(other.as_posix()))
            self.assertFalse(scope.belongs_to_repo(t, repo))

    def test_unresolvable_git_root_does_not_match_and_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "proj"
            repo.mkdir()
            # An embedded null byte cannot be resolved on any platform.
            t = _write(Path(d) / "bad.jsonl", _record("C:/x\u0000/y"))
            self.assertFalse(scope.belongs_to_repo(t, repo))

    def test_case_differences_never_match_on_any_platform(self):
        # `posix_path` deliberately does not case-fold, so `_trail_scope` and
        # `compute_readiness` cannot bucket a trail differently. Asserted on
        # every platform so a future case-folding change has to break a test.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "Proj"
            repo.mkdir()
            shouty = (Path(d) / "PROJ").as_posix()
            t = _write(Path(d) / "case.jsonl", _record(shouty))
            self.assertFalse(scope.belongs_to_repo(t, repo))


class TrailsForRepoTest(unittest.TestCase):
    def test_selects_only_matching_trails_sorted(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as d:
            saved = os.environ.get("CLAUDE_CONFIG_DIR")
            os.environ["CLAUDE_CONFIG_DIR"] = cfg
            try:
                repo = Path(d) / "proj"
                other = Path(d) / "elsewhere"
                wt = repo / ".claude" / "worktrees" / "feature"
                other.mkdir(parents=True)
                wt.mkdir(parents=True)
                td = rs.trail_dir()
                own = _write(td / _trail_name(repo), "")
                wtt = _write(td / "aaa-worktree.jsonl", _record(wt.as_posix()))
                _write(td / "zzz-other.jsonl", _record(other.as_posix()))
                _write(td / "ignored.txt", _record(repo.as_posix()))
                self.assertEqual(scope.trails_for_repo(repo), sorted([own, wtt]))
                # The optional cache is a performance lever only: same selection,
                # and the caller's dict is reusable across subject repos.
                cache: dict[str, str] = {}
                self.assertEqual(
                    scope.trails_for_repo(repo, cache=cache), sorted([own, wtt])
                )
                self.assertEqual(
                    scope.trails_for_repo(other, cache=cache),
                    scope.trails_for_repo(other),
                )
            finally:
                if saved is None:
                    os.environ.pop("CLAUDE_CONFIG_DIR", None)
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = saved


class CurrentRepoRootTest(unittest.TestCase):
    def test_non_repo_cwd_falls_back_to_that_dir(self):
        with tempfile.TemporaryDirectory() as d:
            root = scope.current_repo_root(d)
            self.assertIsInstance(root, Path)
            self.assertEqual(
                os.path.normcase(str(root.resolve())),
                os.path.normcase(str(Path(d).resolve())),
            )

    def test_returns_repo_root_not_worktree_root(self):
        # `git_roots` returns (worktree_root, repo_root); the second is wanted.
        saved = rs.git_roots
        try:
            rs.git_roots = lambda cwd: ("/x/repo/.claude/worktrees/foo", "/x/repo")
            self.assertEqual(scope.current_repo_root("anything"), Path("/x/repo"))
        finally:
            rs.git_roots = saved


if __name__ == "__main__":
    unittest.main()
