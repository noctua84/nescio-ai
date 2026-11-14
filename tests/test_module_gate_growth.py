"""Tests for the calibrated rule in scripts/module_gate.py: when a verdict is
*required* (new / crossed / grew) versus merely *listed* (small), the separate
test-file tripwire, and the CLAUDE.md overrides that tune both.

Kept out of `tests/test_module_gate.py` so each file keeps one subject: that
one covers acknowledgement parsing, the plain tripwire and gate errors; this
one covers the crossing/growth calibration.

Same house pattern as `test_module_gate.py`: real throwaway git repositories,
real `git`, `user.email` / `user.name` / `commit.gpgsign` set locally per repo,
and every call into `module_gate` goes through `contextlib.redirect_stdout` so
the gate's banner never reaches the suite log.
"""

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import module_gate  # noqa: E402
import module_scan  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8"
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"`git {' '.join(args)}` failed in {repo} (exit {proc.returncode}):\n"
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout.strip()


def _init_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


def _write(repo: Path, rel: str, lines: int, token: str = "x") -> None:
    """Overwrite `rel` with exactly `lines` physical lines of `token` and stage it."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{token}\n" * lines, encoding="utf-8")
    _git(repo, "add", "--", rel)


def _commit(repo: Path, message: str) -> str:
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _run_gate(repo: Path, **kwargs) -> tuple[int, str]:
    """Run module_gate.main against `repo` with stdout/stderr captured."""
    args = ["--repo", str(repo)]
    for flag, value in kwargs.items():
        if value is None:
            continue
        args += [f"--{flag.replace('_', '-')}", str(value)]
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = module_gate.main(args)
    return rc, out_buf.getvalue()


def _informational_section(out: str) -> str:
    """The part of a PASS banner after the informational heading ('' if absent)."""
    heading = f"{module_gate.INFORMATIONAL_HEADING}:"
    _, sep, rest = out.partition(heading)
    return rest if sep else ""


class GrowthTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = _init_repo(Path(self._tmp.name))
        _write(self.repo, "README.md", 5)
        self.base_sha = _commit(self.repo, "chore: initial commit")

    def _change(self, rel: str, before: int | None, after: int, **gate) -> tuple[int, str]:
        """Commit `rel` at `before` lines (or not at all), then at `after`, and
        gate the second commit against the first."""
        if before is not None:
            _write(self.repo, rel, before)
            base = _commit(self.repo, f"feat: add {rel} at {before}")
        else:
            base = self.base_sha
        _write(self.repo, rel, after)
        head = _commit(self.repo, f"feat: {rel} to {after}")
        return _run_gate(self.repo, base=base, head=head, **gate)

    def assertRequired(self, rc: int, out: str, path: str, reason: str) -> None:
        self.assertEqual(rc, 1, f"expected a required verdict, got:\n{out}")
        self.assertIn("module-gate: FAIL", out)
        self.assertIn(path, out)
        self.assertIn(f"[{reason}]", out)

    def assertSmall(self, rc: int, out: str, path: str) -> None:
        self.assertEqual(rc, 0, f"expected PASS, got:\n{out}")
        self.assertNotIn("FAIL", out)
        section = _informational_section(out)
        self.assertIn(path, section, f"{path} not listed as informational:\n{out}")
        self.assertIn("[small]", section)


class TestNewFile(GrowthTestCase):
    def test_new_production_file_over_400_is_required(self):
        rc, out = self._change("pkg/hook.py", None, 538)
        self.assertRequired(rc, out, "pkg/hook.py", "new")
        self.assertIn("538 lines", out)

    def test_new_production_file_at_exactly_400_is_not_listed(self):
        rc, out = self._change("pkg/edge.py", None, 400)
        self.assertEqual(rc, 0)
        self.assertNotIn("pkg/edge.py", out)


class TestCrossing(GrowthTestCase):
    def test_crossing_390_to_410_is_required(self):
        rc, out = self._change("mod.py", 390, 410)
        self.assertRequired(rc, out, "mod.py", "crossed")
        self.assertIn("390 -> 410", out)

    def test_base_exactly_at_tripwire_then_over_counts_as_crossing(self):
        rc, out = self._change("mod.py", 400, 401)
        self.assertRequired(rc, out, "mod.py", "crossed")


class TestAlreadyOver(GrowthTestCase):
    def test_small_growth_of_a_big_file_passes_and_is_listed(self):
        rc, out = self._change("install.py", 1000, 1050)
        self.assertSmall(rc, out, "install.py")

    def test_growth_above_the_line_cap_is_required(self):
        rc, out = self._change("install.py", 1000, 1151)
        self.assertRequired(rc, out, "install.py", "grew")

    def test_growth_exactly_at_the_line_cap_is_required(self):
        """1000 lines: min(150, ceil(250)) = 150, and the rule is `>=`."""
        rc, out = self._change("install.py", 1000, 1150)
        self.assertRequired(rc, out, "install.py", "grew")
        self.assertIn("growth limit +150", out)

    def test_growth_one_below_the_line_cap_is_small(self):
        rc, out = self._change("install.py", 1000, 1149)
        self.assertSmall(rc, out, "install.py")

    def test_proportional_growth_exactly_at_25_percent_is_required(self):
        """450 lines: min(150, ceil(112.5)) = 113."""
        rc, out = self._change("mid.py", 450, 563)
        self.assertRequired(rc, out, "mid.py", "grew")
        self.assertIn("growth limit +113", out)

    def test_proportional_growth_one_below_25_percent_is_small(self):
        rc, out = self._change("mid.py", 450, 562)
        self.assertSmall(rc, out, "mid.py")

    def test_growth_is_net_not_churn(self):
        """A rewrite of a 500-line file into 500 *different* lines adds 500
        lines gross but grows by zero net -- not a balloon."""
        _write(self.repo, "rewrite.py", 500, token="x")
        base = _commit(self.repo, "feat: add rewrite.py")
        _write(self.repo, "rewrite.py", 500, token="y")
        head = _commit(self.repo, "refactor: rewrite rewrite.py")
        numstat = module_gate.numstat(self.repo, base, head)
        self.assertEqual(numstat["rewrite.py"], (500, 500))  # real churn

        rc, out = _run_gate(self.repo, base=base, head=head)

        self.assertSmall(rc, out, "rewrite.py")

    def test_small_file_is_not_named_in_a_failure_banner(self):
        _write(self.repo, "install.py", 1000)
        base = _commit(self.repo, "feat: add install.py")
        _write(self.repo, "install.py", 1010)
        _write(self.repo, "born_big.py", 500)
        head = _commit(self.repo, "feat: two changes")

        rc, out = _run_gate(self.repo, base=base, head=head)

        self.assertRequired(rc, out, "born_big.py", "new")
        self.assertNotIn("install.py", out)


class TestTestFiles(GrowthTestCase):
    def test_new_600_line_test_file_is_not_required(self):
        rc, out = self._change("tests/test_big.py", None, 600)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("FAIL", out)
        self.assertNotIn("tests/test_big.py", out)  # under its tripwire

    def test_new_600_line_test_named_file_outside_tests_dir_is_not_required(self):
        rc, out = self._change("pkg/widget_test.py", None, 600)
        self.assertEqual(rc, 0, out)

    def test_test_file_crossing_800_is_required(self):
        rc, out = self._change("tests/test_big.py", 700, 810)
        self.assertRequired(rc, out, "tests/test_big.py", "crossed")
        self.assertIn("tripwire 800", out)

    def test_new_test_file_over_800_is_required(self):
        rc, out = self._change("tests/test_huge.py", None, 801)
        self.assertRequired(rc, out, "tests/test_huge.py", "new")

    def test_cli_test_tripwire_override_is_honoured(self):
        rc, out = self._change("tests/test_big.py", 700, 810, test_tripwire=900)
        self.assertEqual(rc, 0, out)

    def test_production_tripwire_does_not_apply_to_test_files(self):
        """Lowering --tripwire must not drag test files down with it."""
        rc, out = self._change("tests/test_big.py", None, 600, tripwire=100)
        self.assertEqual(rc, 0, out)


class TestAcknowledgedHitStillPasses(GrowthTestCase):
    def test_acknowledged_grew_hit_passes_and_is_listed_as_acknowledged(self):
        _write(self.repo, "install.py", 1000)
        base = _commit(self.repo, "feat: add install.py")
        _write(self.repo, "install.py", 1200)
        head = _commit(
            self.repo,
            "feat: grow install.py\n\nModule-check: install.py — cohesive, one reason",
        )

        rc, out = _run_gate(self.repo, base=base, head=head)

        self.assertEqual(rc, 0, out)
        self.assertIn("acknowledged:", out)
        self.assertIn("[grew]", out)

    def test_acknowledged_new_hit_passes(self):
        _write(self.repo, "born_big.py", 500)
        head = _commit(
            self.repo, "feat: add\n\nModule-check: born_big.py - one reason to change"
        )
        rc, out = _run_gate(self.repo, base=self.base_sha, head=head)
        self.assertEqual(rc, 0, out)
        self.assertIn("[new]", out)


class TestCliGrowthFlags(GrowthTestCase):
    def test_growth_lines_flag_lowers_the_cap(self):
        rc, out = self._change("install.py", 1000, 1050, growth_lines=50)
        self.assertRequired(rc, out, "install.py", "grew")

    def test_growth_percent_flag_lowers_the_proportional_bar(self):
        """450 at 10%: ceil(45) = 45 < 150, so +45 is required."""
        rc, out = self._change("mid.py", 450, 495, growth_percent=10)
        self.assertRequired(rc, out, "mid.py", "grew")


class TestIsTestFile(unittest.TestCase):
    POSITIVE = (
        "tests/test_a.py",
        "tests/helpers.py",
        "tests/fixtures/data.json",
        "pkg/tests/conftest.py",
        "test_x.py",
        "src/test_x.py",
        "src/x_test.py",
        "web/button.spec.ts",
        "web/button.test.tsx",
        "foo.test.js",
    )
    NEGATIVE = (
        "src/testing.py",
        "contest.py",
        "src/attest_x.py",
        "latests/foo.py",
        "test_dir/foo.py",
        "src/tests.py",
        "testdata/x.py",
        "src/test_x.txt",
        "README.md",
    )

    def test_positives(self):
        for rel in self.POSITIVE:
            with self.subTest(rel=rel):
                self.assertTrue(module_scan.is_test_file(rel))

    def test_negatives(self):
        for rel in self.NEGATIVE:
            with self.subTest(rel=rel):
                self.assertFalse(module_scan.is_test_file(rel))


class TestGrowthThreshold(unittest.TestCase):
    def test_table(self):
        cases = (
            ((1000, 150, 25), 150),  # line cap wins
            ((450, 150, 25), 113),  # ceil(112.5)
            ((400, 150, 25), 100),  # exact percentage, no rounding
            ((600, 150, 25), 150),  # 25% == cap exactly
            ((1, 150, 25), 1),
            ((0, 150, 25), 1),  # floored at 1
            ((10**15 + 1, 10**18, 25), 250_000_000_000_001),  # integer ceil
        )
        for args, expected in cases:
            with self.subTest(args=args):
                self.assertEqual(module_scan.growth_threshold(*args), expected)


class TestResolveConfig(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "CLAUDE.md"

    def _config(self, text: str):
        self.path.write_text(text, encoding="utf-8")
        return module_scan.resolve_config(self.path)

    def test_gate_reexports_the_same_function(self):
        self.assertIs(module_gate.resolve_config, module_scan.resolve_config)

    def test_missing_file_gives_defaults(self):
        cfg = module_scan.resolve_config(self.path)
        self.assertEqual(cfg, module_scan.TripwireConfig(400, 800, 150, 25))

    def test_all_four_overrides_are_parsed(self):
        cfg = self._config(
            "# P\n\n## Architecture\n\n"
            "Module tripwire: 500 lines.\n"
            "Test tripwire: 1200 lines.\n"
            "Module growth: 60 lines.\n"
            "Module growth: 10%.\n\n"
            "## Git\n"
        )
        self.assertEqual(cfg, module_scan.TripwireConfig(500, 1200, 60, 10))

    def test_each_field_falls_back_independently(self):
        cfg = self._config("## Architecture\n\nTest tripwire: 1000 lines.\n")
        self.assertEqual(cfg, module_scan.TripwireConfig(400, 1000, 150, 25))

    def test_placeholders_are_not_overrides(self):
        cfg = self._config(
            "## Architecture\n\n"
            "`Module tripwire: <N> lines.` `Test tripwire: <N> lines.`\n"
            "`Module growth: <N> lines.` / `Module growth: <P>%.`\n"
        )
        self.assertEqual(cfg, module_scan.TripwireConfig())

    def test_real_value_beside_placeholder_is_picked_up(self):
        cfg = self._config(
            "## Architecture\n\n"
            "Syntax: `Test tripwire: <N> lines.`\n"
            "Test tripwire: 950 lines.\n"
        )
        self.assertEqual(cfg.test_tripwire, 950)

    def test_lines_outside_the_architecture_section_are_ignored(self):
        cfg = self._config(
            "# P\n\nModule tripwire: 999 lines.\n\n"
            "## Architecture\n\nNothing declared.\n\n"
            "## Skills\n\nTest tripwire: 2000 lines.\nModule growth: 5%.\n"
        )
        self.assertEqual(cfg, module_scan.TripwireConfig())

    def test_this_repos_own_claude_md_resolves_to_defaults(self):
        self.assertEqual(
            module_gate.resolve_config(ROOT / "CLAUDE.md"),
            module_scan.TripwireConfig(400, 800, 150, 25),
        )


class TestConfigEndToEnd(GrowthTestCase):
    """main() reads CLAUDE.md at the repo root and applies every override."""

    def _declare(self, body: str) -> None:
        (self.repo / "CLAUDE.md").write_text(
            f"# Project\n\n## Architecture\n\n{body}\n\n## Git / PRs\n\nbranch\n",
            encoding="utf-8",
        )
        _git(self.repo, "add", "--", "CLAUDE.md")
        self.base_sha = _commit(self.repo, "docs: declare thresholds")

    def test_test_tripwire_from_claude_md(self):
        self._declare("Test tripwire: 1000 lines.")
        rc, out = self._change("tests/test_big.py", 700, 810)
        self.assertEqual(rc, 0, out)
        rc, out = self._change("tests/test_other.py", 900, 1001)
        self.assertRequired(rc, out, "tests/test_other.py", "crossed")

    def test_module_tripwire_and_test_tripwire_together(self):
        self._declare("Module tripwire: 500 lines.\nTest tripwire: 600 lines.")
        rc, out = self._change("prod.py", None, 450)
        self.assertEqual(rc, 0, out)
        rc, out = self._change("tests/test_t.py", None, 650)
        self.assertRequired(rc, out, "tests/test_t.py", "new")

    def test_growth_lines_from_claude_md(self):
        self._declare("Module growth: 50 lines.")
        rc, out = self._change("install.py", 1000, 1050)
        self.assertRequired(rc, out, "install.py", "grew")

    def test_growth_percent_from_claude_md(self):
        self._declare("Module growth: 10%.")
        rc, out = self._change("mid.py", 450, 495)
        self.assertRequired(rc, out, "mid.py", "grew")

    def test_placeholders_in_claude_md_keep_the_defaults(self):
        self._declare(
            "`Module tripwire: <N> lines.` `Test tripwire: <N> lines.` "
            "`Module growth: <N> lines.` `Module growth: <P>%.`"
        )
        rc, out = self._change("install.py", 1000, 1050)
        self.assertSmall(rc, out, "install.py")
        prior = _git(self.repo, "rev-parse", "HEAD")
        _write(self.repo, "tests/test_big.py", 600)
        head = _commit(self.repo, "test: add a 600-line test file")
        rc, out = _run_gate(self.repo, base=prior, head=head)
        self.assertEqual(rc, 0, out)

    def test_cli_flag_beats_claude_md(self):
        self._declare("Module growth: 50 lines.")
        rc, out = self._change("install.py", 1000, 1050, growth_lines=150)
        self.assertSmall(rc, out, "install.py")


if __name__ == "__main__":
    unittest.main()
