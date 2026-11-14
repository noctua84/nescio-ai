"""Behaviour tests for the "Prune staged files before upload" step of the review core.

`github-action/scripts/claude-review/scrub-staged.sh` is executed directly with
bash against temp staging directories (REVIEW_OUTBOX / REVIEW_LEARNINGS). The
step is hygiene for the benign case, not a boundary, so these tests pin what it
keeps, what it removes, that it never follows or prints a credential, and that
it resets PATH before running anything.

Fixture credentials are built at runtime so no token-shaped literal is tracked.

Skipped unless `bash` is on PATH.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "github-action" / "scripts" / "claude-review" / "scrub-staged.sh"
BASH = shutil.which("bash")

SECRET_RE_LITERAL = (
    "(gh[opusr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
    "|sk-ant-[A-Za-z0-9_-]{20,})"
)


def _posix(path):
    return str(path).replace("\\", "/")


def _secret(family="ghs_"):
    """A credential-shaped string, assembled at runtime."""
    if family == "sk-ant-":
        return "sk-" + "ant-" + "A" * 24
    if family == "github_pat_":
        return "github" + "_pat_" + "A" * 36
    return "gh" + family[2:] + "A" * 36


def _script_text():
    return SCRIPT.read_bytes().decode("utf-8").replace("\r\n", "\n")


class ScriptShapeTest(unittest.TestCase):
    def test_first_command_resets_path(self):
        lines = [ln for ln in _script_text().splitlines()[1:]
                 if ln.strip() and not ln.lstrip().startswith("#")]
        self.assertEqual(lines[0], "export PATH=/usr/bin:/bin")

    def test_shebang_lf_and_no_expression(self):
        raw = SCRIPT.read_bytes()
        self.assertTrue(raw.startswith(b"#!/usr/bin/env bash\n"))
        self.assertNotIn(b"\r", raw)
        self.assertNotIn(b"${{", raw)

    def test_sources_nothing(self):
        for ln in _script_text().splitlines():
            code = ln.split("#", 1)[0].strip()
            self.assertFalse(code.startswith("source ") or code.startswith(". "), ln)

    def test_secret_re_matches_the_plan_literal(self):
        m = re.search(r"^\s*SECRET_RE='([^']*)'\s*$", _script_text(), re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), SECRET_RE_LITERAL)

    def test_under_module_tripwire(self):
        self.assertLess(len(_script_text().splitlines()), 400)


@unittest.skipUnless(BASH, "bash is required on PATH")
class ScrubBehaviourTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.outbox = self.root / "review-outbox"
        self.learnings = self.root / "review-learnings"
        self.outside = self.root / "outside"
        self.outside.mkdir()

    # -- helpers ----------------------------------------------------------------

    def stage(self, rel, text="hello\n", base=None):
        path = (base or self.outbox) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def learn(self, rel, text="note\n"):
        return self.stage(rel, text, base=self.learnings)

    def run_scrub(self, extra_env=None, outbox=None, learnings=None):
        env = dict(os.environ)
        env["REVIEW_OUTBOX"] = _posix(outbox if outbox is not None else self.outbox)
        env["REVIEW_LEARNINGS"] = _posix(
            learnings if learnings is not None else self.learnings)
        env.update(extra_env or {})
        proc = subprocess.run(
            [BASH, _posix(SCRIPT)], env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=120)
        self.output = proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        return proc

    def assertExit(self, proc, code):
        self.assertEqual(proc.returncode, code,
                         f"exit {proc.returncode}; output:\n{self.output}")

    def symlink(self, link, target, is_dir=False):
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(target, link, target_is_directory=is_dir)
        except (OSError, NotImplementedError):
            self.skipTest("this OS cannot create symlinks")
        # A tool may silently copy instead of linking; require a real link.
        if not os.path.islink(link):
            self.skipTest("this OS cannot create symlinks")

    def snapshot(self, base):
        return {p.relative_to(base).as_posix(): p.read_bytes()
                for p in sorted(base.rglob("*")) if p.is_file() and not p.is_symlink()}

    def full_layout(self):
        self.stage("summary.md", "summary\n")
        self.stage("review.md", "<!-- claude-comprehensive-review -->\nbody\n")
        self.stage("findings/a.md", "finding a\n")
        self.stage("findings/b.md", "finding b\n")
        self.stage("replies/r.md", "reply\n")
        self.learn("one.md", "---\nkind: security\n---\nx\n")
        self.learn("two.md", "two\n")

    # -- keep -------------------------------------------------------------------

    def test_valid_layout_is_left_byte_identical(self):
        self.full_layout()
        before = (self.snapshot(self.outbox), self.snapshot(self.learnings))
        proc = self.run_scrub()
        self.assertExit(proc, 0)
        self.assertEqual(
            (self.snapshot(self.outbox), self.snapshot(self.learnings)), before)
        self.assertNotIn("::warning::", self.output)

    def test_both_dirs_missing_is_a_quiet_success(self):
        proc = self.run_scrub()
        self.assertExit(proc, 0)
        self.assertEqual(self.output.strip(), "")

    def test_trailing_slash_in_env_paths_is_handled(self):
        self.full_layout()
        self.stage("notes.txt", "x")
        proc = self.run_scrub(extra_env={
            "REVIEW_OUTBOX": _posix(self.outbox) + "/",
            "REVIEW_LEARNINGS": _posix(self.learnings) + "/"})
        self.assertExit(proc, 0)
        self.assertFalse((self.outbox / "notes.txt").exists())
        self.assertTrue((self.outbox / "review.md").exists())

    # -- credential-shaped content ---------------------------------------------

    def test_secret_in_review_is_removed_and_never_printed(self):
        self.full_layout()
        secret = _secret()
        self.stage("review.md", f"verdict\n{secret}\n")
        proc = self.run_scrub()
        self.assertExit(proc, 0)
        self.assertFalse((self.outbox / "review.md").exists())
        for kept in ("summary.md", "findings/a.md", "findings/b.md", "replies/r.md"):
            self.assertTrue((self.outbox / kept).exists(), kept)
        self.assertTrue((self.learnings / "one.md").exists())
        self.assertNotIn(secret, self.output)
        self.assertIn("credential-shaped", self.output)

    def test_every_credential_family_is_removed(self):
        for family in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_", "sk-ant-"):
            with self.subTest(family=family):
                self.full_layout()
                secret = _secret(family)
                self.stage("findings/a.md", f"text {secret} text\n")
                self.learn("one.md", f"{secret}\n")
                proc = self.run_scrub()
                self.assertExit(proc, 0)
                self.assertFalse((self.outbox / "findings" / "a.md").exists())
                self.assertFalse((self.learnings / "one.md").exists())
                self.assertTrue((self.outbox / "findings" / "b.md").exists())
                self.assertNotIn(secret, self.output)

    def test_near_misses_are_kept(self):
        self.full_layout()
        self.stage("summary.md",
                   "ghp_" + "A" * 10 + "\nsk-ant and github_pat_ in prose\n")
        proc = self.run_scrub()
        self.assertExit(proc, 0)
        self.assertTrue((self.outbox / "summary.md").exists())

    # -- links ------------------------------------------------------------------

    def test_symlinked_file_dir_and_root_are_removed_not_followed(self):
        target_file = self.outside / "secret.md"
        target_file.write_text("keep me\n", encoding="utf-8", newline="\n")
        target_dir = self.outside / "dir"
        target_dir.mkdir()
        (target_dir / "x.md").write_text("dir file\n", encoding="utf-8", newline="\n")
        self.stage("summary.md")
        self.symlink(self.outbox / "findings" / "link.md", target_file)
        self.symlink(self.outbox / "replies", target_dir, is_dir=True)
        learn_target = self.outside / "learn-root"
        learn_target.mkdir()
        (learn_target / "n.md").write_text("n\n", encoding="utf-8", newline="\n")
        self.symlink(self.learnings, learn_target, is_dir=True)

        proc = self.run_scrub()
        self.assertExit(proc, 0)
        self.assertFalse(os.path.lexists(self.outbox / "findings" / "link.md"))
        self.assertFalse(os.path.lexists(self.outbox / "replies"))
        self.assertFalse(os.path.lexists(self.learnings))
        self.assertTrue((self.outbox / "summary.md").exists())
        self.assertEqual(target_file.read_text(encoding="utf-8"), "keep me\n")
        self.assertEqual((target_dir / "x.md").read_text(encoding="utf-8"), "dir file\n")
        self.assertEqual((learn_target / "n.md").read_text(encoding="utf-8"), "n\n")

    def test_symlinked_outbox_root_is_removed_not_followed(self):
        target = self.outside / "box"
        target.mkdir()
        (target / "review.md").write_text("r\n", encoding="utf-8", newline="\n")
        self.symlink(self.outbox, target, is_dir=True)
        proc = self.run_scrub()
        self.assertExit(proc, 0)
        self.assertFalse(os.path.lexists(self.outbox))
        self.assertEqual((target / "review.md").read_text(encoding="utf-8"), "r\n")

    # -- layout -----------------------------------------------------------------

    def test_unpublishable_paths_are_removed(self):
        self.full_layout()
        self.stage("notes.txt", "x")
        self.stage(".hidden.md", "x")
        self.stage("findings/nested/x.md", "x")
        self.stage("findings/.dot.md", "x")
        self.stage("findings/a.txt", "x")
        self.stage("other/x.md", "x")
        self.learn("sub/x.md", "x")
        self.learn(".hidden.md", "x")
        self.learn("data.json", "x")
        proc = self.run_scrub()
        self.assertExit(proc, 0)
        gone = [self.outbox / "notes.txt", self.outbox / ".hidden.md",
                self.outbox / "findings" / "nested", self.outbox / "findings" / ".dot.md",
                self.outbox / "findings" / "a.txt", self.outbox / "other",
                self.learnings / "sub", self.learnings / ".hidden.md",
                self.learnings / "data.json"]
        for path in gone:
            self.assertFalse(path.exists(), str(path))
        self.assertEqual(
            sorted(self.snapshot(self.outbox)),
            sorted(["summary.md", "review.md", "findings/a.md", "findings/b.md",
                    "replies/r.md"]))
        self.assertTrue((self.learnings / "one.md").exists())

    def test_directory_in_place_of_a_file_is_removed(self):
        self.full_layout()
        (self.outbox / "review.md").unlink()
        (self.outbox / "review.md").mkdir()
        (self.outbox / "review.md" / "inner.md").write_text("x", encoding="utf-8")
        proc = self.run_scrub()
        self.assertExit(proc, 0)
        self.assertFalse((self.outbox / "review.md").exists())

    def test_hostile_file_name_is_sanitised_in_the_log(self):
        self.stage("summary.md")
        self.stage("bad name;x.txt", "x")
        proc = self.run_scrub()
        self.assertExit(proc, 0)
        self.assertIn("'bad_name_x.txt'", self.output)

    # -- PATH reset -------------------------------------------------------------

    def test_path_is_reset_so_planted_tools_do_not_run(self):
        self.full_layout()
        self.stage("notes.txt", "x")
        planted = self.root / "planted"
        planted.mkdir()
        marker = self.root / "marker"
        for tool in ("grep", "rm", "find", "tr", "basename", "mktemp"):
            path = planted / tool
            path.write_text(
                f"#!/bin/sh\necho {tool} >> '{_posix(marker)}'\nexit 0\n",
                encoding="utf-8", newline="\n")
            path.chmod(0o755)
        proc = self.run_scrub(extra_env={
            "PATH": str(planted) + os.pathsep + os.environ.get("PATH", "")})
        self.assertExit(proc, 0)
        self.assertFalse(marker.exists(), "a planted tool on PATH was executed")
        self.assertFalse((self.outbox / "notes.txt").exists())


if __name__ == "__main__":
    unittest.main()
