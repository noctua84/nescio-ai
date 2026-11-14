"""Behaviour tests for the "Open review-learning PRs" step of the review core.

`github-action/scripts/claude-review/open-learning-prs.sh` is executed with bash
inside a real git clone whose `origin` is a local bare repository, with a
test-local fake `gh` that only logs its argv. Assertions are on the remote's refs
(`git ls-remote`), the pushed tree and the gh log, never on log wording, except
that a rejected note's credential-shaped text must be absent from the output.

Credential-shaped fixtures are built by string concatenation at runtime so that no
token-shaped literal appears in this file.

Skipped unless `bash`, `jq` and `git` are on PATH.
"""
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _review_step_harness import StepHarness, posix  # noqa: E402

GIT = shutil.which("git")

PR = "7"
REPO = "o/r"
NOTE_DIR = ".claude/memory/review-learnings"

FAKE_GH = r"""#!/usr/bin/env bash
# Test-local gh: logs argv (unit-separator terminated) and answers `pr create`.
{ for a in "$@"; do printf '%s\x1f' "$a"; done; printf '\n'; } >> "$FAKE_GH_DIR/gh.log"
if [ "${1:-}" = pr ] && [ "${2:-}" = create ]; then
  echo "https://github.com/o/r/pull/99"
  exit 0
fi
echo "fake-gh: unsupported command $*" >&2
exit 2
"""

GIT_ID = {
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_TERMINAL_PROMPT": "0",
}


def _shaped(prefix, n=36):
    """A credential-shaped string, assembled at runtime."""
    return prefix + "A" * n


# One entry per family the filter must reject.
FAMILIES = {
    "ghp": _shaped("gh" + "p_"),
    "gho": _shaped("gh" + "o_"),
    "ghu": _shaped("gh" + "u_"),
    "ghs": _shaped("gh" + "s_"),
    "ghr": _shaped("gh" + "r_"),
    "github-pat": _shaped("github" + "_pat_"),
    "sk-ant": _shaped("sk-" + "ant-", 30),
}


def _note(kind="security", body="Watch for this pattern."):
    return f"---\nkind: {kind}\n---\n{body}\n"


@unittest.skipUnless(GIT, "git is required on PATH")
class _LearningHarness(StepHarness):
    SCRIPT = "open-learning-prs"

    def setUp(self):
        super().setUp()
        self._write_exec(self.bin / "gh", FAKE_GH)
        self.origin = self.root / "origin.git"
        self.clone = self.root / "work"
        self.stage = self.root / "learnings"
        self.stage.mkdir()
        self.git(self.root, "init", "--quiet", "--bare", "-b", "main", posix(self.origin))
        self.git(self.root, "clone", "--quiet", posix(self.origin), posix(self.clone))
        self.git(self.clone, "checkout", "--quiet", "-b", "main")
        (self.clone / "README.md").write_text("hello\n", encoding="utf-8", newline="\n")
        self.git(self.clone, "add", "README.md")
        self.git(self.clone, "commit", "--quiet", "-m", "init")
        self.git(self.clone, "push", "--quiet", "-u", "origin", "main")

    def git(self, cwd, *args):
        env = dict(os.environ)
        env.update(GIT_ID)
        proc = subprocess.run([GIT, *args], cwd=cwd, env=env, capture_output=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        return proc.stdout.decode("utf-8", "replace")

    def stage_note(self, slug, text):
        path = self.stage / f"{slug}.md"
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def run_learning(self, stage=None):
        env = dict(GIT_ID)
        env.update({
            "REVIEW_LEARNINGS": posix(stage if stage is not None else self.stage),
            "PR_NUMBER": PR,
            "BASE_REF": "main",
            "REPO": REPO,
            "GITHUB_SERVER_URL": "https://github.com",
        })
        return self.run_step(env, cwd=self.clone)

    def remote_branches(self):
        out = self.git(self.root, "ls-remote", "--heads", posix(self.origin))
        return sorted(line.split("\t", 1)[1] for line in out.splitlines() if line)

    def learning_branches(self):
        prefix = "refs/heads/claude/review-learning/"
        return [b for b in self.remote_branches() if b.startswith(prefix)]

    def gh_calls(self):
        log = self.fake / "gh.log"
        if not log.exists():
            return []
        return [line.rstrip("\x1f").split("\x1f")
                for line in log.read_text(encoding="utf-8").splitlines() if line]

    def pr_creates(self):
        return [c for c in self.gh_calls() if c[:2] == ["pr", "create"]]


class OpensLearningPrTest(_LearningHarness):
    def test_benign_note_creates_branch_note_and_pr(self):
        self.stage_note("watch-nulls", _note("security"))
        proc = self.run_learning()
        self.assertExit(proc, 0)
        branch = f"claude/review-learning/{PR}-watch-nulls"
        self.assertEqual(self.learning_branches(), [f"refs/heads/{branch}"])
        tree = self.git(self.origin, "ls-tree", "-r", "--name-only", branch).splitlines()
        self.assertIn(f"{NOTE_DIR}/watch-nulls.md", tree)
        creates = self.pr_creates()
        self.assertEqual(len(creates), 1)
        args = creates[0]
        self.assertEqual(args[args.index("--base") + 1], "main")
        self.assertEqual(args[args.index("--head") + 1], branch)
        self.assertEqual(args[args.index("--repo") + 1], REPO)

    def test_rerun_does_not_open_a_second_pr(self):
        self.stage_note("watch-nulls", _note("regression"))
        self.assertExit(self.run_learning(), 0)
        self.assertExit(self.run_learning(), 0)
        self.assertEqual(len(self.learning_branches()), 1)
        self.assertEqual(len(self.pr_creates()), 1)


class CredentialFilterTest(_LearningHarness):
    def test_secret_note_creates_no_branch_and_no_gh_call(self):
        sample = FAMILIES["ghs"]
        self.stage_note("leaky", _note(body=f"token is {sample}"))
        proc = self.run_learning()
        self.assertExit(proc, 0)
        self.assertEqual(self.learning_branches(), [])
        self.assertEqual(self.gh_calls(), [])
        self.assertNotIn(sample, self.output)

    def test_every_family_is_rejected(self):
        for name, sample in FAMILIES.items():
            self.stage_note(f"note-{name}", _note(body=f"see {sample} here"))
        proc = self.run_learning()
        self.assertExit(proc, 0)
        self.assertEqual(self.learning_branches(), [])
        self.assertEqual(self.gh_calls(), [])
        for name, sample in FAMILIES.items():
            with self.subTest(family=name):
                self.assertNotIn(sample, self.output)

    def test_secret_in_frontmatter_is_rejected(self):
        sample = FAMILIES["github-pat"]
        self.stage_note("fm-leak", f"---\nkind: security\nref: {sample}\n---\nbody\n")
        self.assertExit(self.run_learning(), 0)
        self.assertEqual(self.learning_branches(), [])
        self.assertNotIn(sample, self.output)

    def test_secret_and_benign_notes_only_benign_gets_a_branch(self):
        self.stage_note("a-leaky", _note(body=FAMILIES["ghp"]))
        self.stage_note("b-clean", _note("architecture"))
        proc = self.run_learning()
        self.assertExit(proc, 0)
        self.assertEqual(self.learning_branches(),
                         [f"refs/heads/claude/review-learning/{PR}-b-clean"])
        self.assertEqual(len(self.pr_creates()), 1)
        self.assertNotIn(FAMILIES["ghp"], self.output)

    def test_near_misses_are_accepted(self):
        near = {
            "short-ghp": "gh" + "p_" + "A" * 10,
            "bare-words": "the sk" + "-ant prefix and github" + "_pat_ are only words here",
        }
        for slug, body in near.items():
            self.stage_note(slug, _note(body=body))
        self.assertExit(self.run_learning(), 0)
        self.assertEqual(
            self.learning_branches(),
            sorted(f"refs/heads/claude/review-learning/{PR}-{s}" for s in near))


class NotRegularFileTest(_LearningHarness):
    def test_directory_named_like_a_note_is_rejected(self):
        (self.stage / "dir-note.md").mkdir()
        proc = self.run_learning()
        self.assertExit(proc, 0)
        self.assertEqual(self.learning_branches(), [])
        self.assertEqual(self.gh_calls(), [])

    def test_symlinked_stage_dir_is_skipped(self):
        real = self.root / "real-learnings"
        real.mkdir()
        (real / "watch-nulls.md").write_text(_note(), encoding="utf-8", newline="\n")
        link = self.root / "linked-learnings"
        try:
            os.symlink(real, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create symlinks here")
        proc = self.run_learning(stage=link)
        self.assertExit(proc, 0)
        self.assertEqual(self.learning_branches(), [])
        self.assertEqual(self.gh_calls(), [])


class StageDirTest(_LearningHarness):
    def test_missing_stage_dir_exits_zero_without_work(self):
        proc = self.run_learning(stage=self.root / "absent")
        self.assertExit(proc, 0)
        self.assertEqual(self.learning_branches(), [])
        self.assertEqual(self.gh_calls(), [])


if __name__ == "__main__":
    unittest.main()
