"""Behaviour tests for the review core's "Restore base-branch Claude configuration" step.

`github-action/scripts/claude-review/restore-trusted-config.sh` is run directly
with bash inside a throwaway clone. The contract under test: after the step,
the Claude configuration paths in the work tree are the base branch's (restored
where the base has them, removed where it does not) while every other file keeps
its PR-head content and HEAD stays on the PR commit; the step is idempotent,
never follows a symlink, and fails closed (without touching the work tree) when
the base ref is invalid or missing.

The clone mirrors the workflow's checkout: all branches fetched, the PR head
checked out detached. Skipped unless `bash` and `git` are on PATH.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BASH = shutil.which("bash")
GIT = shutil.which("git")

SCRIPT = (Path(__file__).resolve().parent.parent / "github-action" / "scripts"
          / "claude-review" / "restore-trusted-config.sh")

CONFIG_PATHS = (".claude", ".mcp.json", ".claude.json", ".gitmodules", ".ripgreprc",
                "CLAUDE.md", "CLAUDE.local.md", ".husky")

BASE_FILES = {
    ".claude/settings.json": b'{"base": true}\n',
    "CLAUDE.md": b"base instructions\n",
    ".mcp.json": b'{"mcpServers": {}}\n',
    "src/a.txt": b"base source\n",
}

PR_FILES = {
    ".claude/settings.json": b'{"base": false, "hook": "evil"}\n',
    ".claude/extra.json": b"{}\n",
    "CLAUDE.md": b"pr instructions\n",
    "CLAUDE.local.md": b"pr local\n",
    ".claude.json": b"{}\n",
    ".ripgreprc": b"--glob=x\n",
    ".gitmodules": b"[submodule \"s\"]\n",
    ".husky/pre-commit": b"#!/bin/sh\nexit 0\n",
    "src/a.txt": b"pr source\n",
}


def _posix(path):
    return str(path).replace("\\", "/")


@unittest.skipUnless(BASH and GIT, "bash and git are required on PATH")
class RestoreConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.env = dict(os.environ)
        for key in [k for k in self.env if k.startswith("GIT_")]:
            del self.env[key]
        self.env.update({
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        })

        origin = self.root / "origin.git"
        seed = self.root / "seed"
        self.clone = self.root / "clone"
        self.git(self.root, "init", "-q", "--bare", "-b", "main", str(origin))
        self.git(self.root, "init", "-q", "-b", "main", str(seed))
        self._config(seed)
        self._write(seed, BASE_FILES)
        self.git(seed, "add", "-A")
        self.git(seed, "commit", "-q", "-m", "base")
        self.git(seed, "remote", "add", "origin", str(origin))
        self.git(seed, "push", "-q", "origin", "main")

        self.git(seed, "checkout", "-q", "-b", "pr")
        self._write(seed, PR_FILES)
        self.git(seed, "add", "-A")
        self.git(seed, "commit", "-q", "-m", "pr")
        self.git(seed, "push", "-q", "origin", "pr")
        self.pr_sha = self.git(seed, "rev-parse", "HEAD").strip()

        self.git(self.root, "clone", "-q", str(origin), str(self.clone))
        self._config(self.clone)
        self.git(self.clone, "checkout", "-q", "--detach", self.pr_sha)

    # -- helpers ----------------------------------------------------------------

    def git(self, cwd, *args):
        proc = subprocess.run([GIT, *args], cwd=cwd, env=self.env, capture_output=True,
                              timeout=60)
        out = proc.stdout.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 0,
                         f"git {' '.join(args)}: {proc.stderr.decode('utf-8', 'replace')}")
        return out

    def _config(self, repo):
        self.git(repo, "config", "core.autocrlf", "false")
        self.git(repo, "config", "core.symlinks", "true")

    @staticmethod
    def _write(repo, files):
        for rel, data in files.items():
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def run_step(self, base_ref="main", cwd=None):
        env = dict(self.env)
        if base_ref is None:
            env.pop("BASE_REF", None)
        else:
            env["BASE_REF"] = base_ref
        proc = subprocess.run([BASH, _posix(SCRIPT)], cwd=cwd or self.clone, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        self.output = proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        return proc

    def tree(self):
        """{relative posix path: bytes} for every file and symlink outside .git."""
        out = {}
        for dirpath, dirnames, filenames in os.walk(self.clone):
            if ".git" in dirnames:
                dirnames.remove(".git")
            for name in filenames + [d for d in dirnames if (Path(dirpath) / d).is_symlink()]:
                path = Path(dirpath) / name
                rel = path.relative_to(self.clone).as_posix()
                out[rel] = (os.readlink(path).encode() if path.is_symlink()
                            else path.read_bytes())
        return out

    def assertExit(self, proc, code):
        self.assertEqual(proc.returncode, code, self.output)

    def assertRestored(self):
        tree = self.tree()
        for rel in (".claude/settings.json", "CLAUDE.md", ".mcp.json"):
            self.assertEqual(tree[rel], BASE_FILES[rel], rel)
        for rel in (".claude/extra.json", "CLAUDE.local.md", ".claude.json", ".ripgreprc",
                    ".gitmodules", ".husky/pre-commit"):
            self.assertNotIn(rel, tree)
        self.assertFalse((self.clone / ".husky").exists())
        self.assertEqual(tree["src/a.txt"], PR_FILES["src/a.txt"])
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD").strip(), self.pr_sha)

    # -- behaviour --------------------------------------------------------------

    def test_pr_head_configuration_is_replaced_by_the_base_branchs(self):
        self.assertExit(self.run_step(), 0)
        self.assertRestored()

    def test_index_matches_the_work_tree_for_config_paths(self):
        self.assertExit(self.run_step(), 0)
        tracked = set(self.git(self.clone, "ls-files", "--", *CONFIG_PATHS).split())
        self.assertEqual(tracked, {".claude/settings.json", "CLAUDE.md", ".mcp.json"})
        # Nothing outside the listed paths is staged or modified.
        status = self.git(self.clone, "status", "--porcelain", "--untracked-files=no")
        changed = {line[3:] for line in status.splitlines()}
        self.assertTrue(all(any(p == c or p.startswith(c + "/") for c in CONFIG_PATHS)
                            for p in changed), status)

    def test_reports_one_line_per_changed_path_only(self):
        self.assertExit(self.run_step(), 0)
        lines = self.output.splitlines()
        self.assertIn("restored .claude from the base branch", lines)
        self.assertIn("restored CLAUDE.md from the base branch", lines)
        self.assertIn("restored .mcp.json from the base branch", lines)
        self.assertIn("removed .husky (not on the base branch)", lines)
        self.assertIn("removed CLAUDE.local.md (not on the base branch)", lines)
        self.assertEqual(len(lines), 8, self.output)

    def test_a_path_absent_from_both_sides_is_not_reported(self):
        self.git(self.clone, "rm", "-q", "-r", "--", ".husky")
        self.git(self.clone, "commit", "-q", "-m", "drop husky")
        self.assertExit(self.run_step(), 0)
        self.assertNotIn(".husky", self.output)

    def test_running_twice_gives_the_same_result(self):
        self.assertExit(self.run_step(), 0)
        first = self.tree()
        self.assertExit(self.run_step(), 0)
        self.assertEqual(self.tree(), first)
        self.assertRestored()

    def test_runs_from_the_pr_branch_without_origin_access(self):
        # No fetch: the step must work with the remote unreachable.
        self.git(self.clone, "remote", "set-url", "origin", str(self.root / "missing.git"))
        self.assertExit(self.run_step(), 0)
        self.assertRestored()

    def test_symlinked_config_directory_is_replaced_and_its_target_untouched(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_bytes(b"keep\n")
        shutil.rmtree(self.clone / ".claude")
        try:
            os.symlink(outside, self.clone / ".claude", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("this OS cannot create symlinks here")
        self.git(self.clone, "add", "-A", "--", ".claude")
        self.assertIn("120000", self.git(self.clone, "ls-files", "-s", "--", ".claude"))

        self.assertExit(self.run_step(), 0)
        claude = self.clone / ".claude"
        self.assertFalse(claude.is_symlink())
        self.assertTrue(claude.is_dir())
        self.assertEqual((claude / "settings.json").read_bytes(),
                         BASE_FILES[".claude/settings.json"])
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ["secret.txt"])
        self.assertEqual((outside / "secret.txt").read_bytes(), b"keep\n")

    def test_symlinked_file_is_removed_as_a_link(self):
        outside = self.root / "outside.txt"
        outside.write_bytes(b"keep\n")
        (self.clone / "CLAUDE.local.md").unlink()
        try:
            os.symlink(outside, self.clone / "CLAUDE.local.md")
        except (OSError, NotImplementedError):
            self.skipTest("this OS cannot create symlinks here")
        self.git(self.clone, "add", "-A", "--", "CLAUDE.local.md")

        self.assertExit(self.run_step(), 0)
        self.assertFalse((self.clone / "CLAUDE.local.md").is_symlink())
        self.assertFalse((self.clone / "CLAUDE.local.md").exists())
        self.assertEqual(outside.read_bytes(), b"keep\n")

    # -- fail closed ------------------------------------------------------------

    def test_invalid_base_ref_fails_before_changing_anything(self):
        before = self.tree()
        status = self.git(self.clone, "status", "--porcelain")
        for bad in (None, "", "-x", "a..b", "a b", "@{-1}", "x~1", "a:b"):
            with self.subTest(base_ref=bad):
                proc = self.run_step(base_ref=bad)
                self.assertNotEqual(proc.returncode, 0, self.output)
                self.assertIn("::error::", self.output)
                self.assertEqual(self.tree(), before)
                self.assertEqual(self.git(self.clone, "status", "--porcelain"), status)

    def test_missing_base_ref_fails_closed(self):
        before = self.tree()
        proc = self.run_step(base_ref="nope")
        self.assertNotEqual(proc.returncode, 0, self.output)
        self.assertIn("::error::", self.output)
        self.assertEqual(self.tree(), before)

    def test_local_branch_is_not_a_substitute_for_the_remote_tracking_ref(self):
        # A branch named like the base exists locally only: it must not be used.
        self.git(self.clone, "branch", "local-only", "origin/main")
        before = self.tree()
        proc = self.run_step(base_ref="local-only")
        self.assertNotEqual(proc.returncode, 0, self.output)
        self.assertEqual(self.tree(), before)

    def test_a_ref_prefixed_name_is_not_accepted(self):
        before = self.tree()
        proc = self.run_step(base_ref="refs/heads/main")
        self.assertNotEqual(proc.returncode, 0, self.output)
        self.assertEqual(self.tree(), before)


class ScriptShapeTest(unittest.TestCase):
    def test_script_follows_the_sibling_conventions(self):
        data = SCRIPT.read_bytes()
        self.assertTrue(data.startswith(b"#!/usr/bin/env bash\n"))
        self.assertNotIn(b"\r", data)
        self.assertNotIn(b"${{", data)
        self.assertLess(data.count(b"\n"), 400)

    def test_script_does_not_fetch_or_use_a_token(self):
        text = SCRIPT.read_text(encoding="utf-8")
        code = "\n".join(line for line in text.splitlines()
                         if not line.lstrip().startswith("#"))
        for word in ("git fetch", "git pull", "git clone", "GH_TOKEN", "GITHUB_TOKEN"):
            self.assertNotIn(word, code)


if __name__ == "__main__":
    unittest.main()
