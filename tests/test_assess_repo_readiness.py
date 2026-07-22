import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import assess_repo_readiness as arr  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────

def _make_repo_mem(memory_root: Path, name: str, *, notes=0, adrs=0,
                   overview=False, readiness=False, memory_index=False):
    """Build memory_root/repo/<name>/ with N generic notes and M ADRs."""
    repo_mem = memory_root / "repo" / name
    repo_mem.mkdir(parents=True, exist_ok=True)
    for i in range(notes):
        (repo_mem / f"note-{i}.md").write_text(f"# note {i}\n", encoding="utf-8")
    if memory_index:
        (repo_mem / "MEMORY.md").write_text("# index\n", encoding="utf-8")
    if overview:
        (repo_mem / "overview.md").write_text("# overview\n", encoding="utf-8")
    if readiness:
        (repo_mem / "readiness.md").write_text("# readiness\n", encoding="utf-8")
    if adrs:
        adr_dir = repo_mem / "adr"
        adr_dir.mkdir(exist_ok=True)
        for i in range(adrs):
            (adr_dir / f"{i:04d}-decision.md").write_text(f"# adr {i}\n", encoding="utf-8")
    return repo_mem


def _touch(path: Path, content: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ── memory depth ───────────────────────────────────────────────────────────

class MemoryDepthTest(unittest.TestCase):
    def test_absent_dir_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            res = arr.assess_memory_depth("ghost", root)
            self.assertEqual(res["level"], "none")
            self.assertEqual(res["notes"], 0)
            self.assertEqual(res["adrs"], 0)
            self.assertFalse(res["has_overview"])
            self.assertFalse(res["has_readiness"])

    def test_memory_index_not_counted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_repo_mem(root, "r", notes=2, memory_index=True)
            res = arr.assess_memory_depth("r", root)
            # MEMORY.md excluded → only the 2 real notes.
            self.assertEqual(res["notes"], 2)

    def test_counts_and_flags(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_repo_mem(root, "r", notes=4, adrs=3, overview=True,
                           readiness=True, memory_index=True)
            res = arr.assess_memory_depth("r", root)
            # notes = 4 generic + overview = 5. MEMORY.md and readiness.md are
            # both excluded; overview.md stays counted.
            self.assertEqual(res["notes"], 5)
            self.assertEqual(res["adrs"], 3)
            self.assertTrue(res["has_overview"])
            self.assertTrue(res["has_readiness"])

    def test_readiness_excluded_from_count_but_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            # Only overview.md + readiness.md present: overview counts, readiness
            # does not, so notes=1 — yet has_readiness still reflects the file.
            _make_repo_mem(root, "r", notes=0, overview=True, readiness=True)
            res = arr.assess_memory_depth("r", root)
            self.assertEqual(res["notes"], 1)
            self.assertTrue(res["has_readiness"])
            self.assertTrue(res["has_overview"])

    def test_overview_counted_readiness_not(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            # readiness.md alone → not counted (notes=0, level none) but flagged.
            _make_repo_mem(root, "r", notes=0, readiness=True)
            res = arr.assess_memory_depth("r", root)
            self.assertEqual(res["notes"], 0)
            self.assertEqual(res["level"], "none")
            self.assertTrue(res["has_readiness"])

    def test_level_boundary_zero_none(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_repo_mem(root, "r", notes=0, memory_index=True)
            self.assertEqual(arr.assess_memory_depth("r", root)["level"], "none")

    def test_level_boundary_two_thin(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_repo_mem(root, "r", notes=2)
            self.assertEqual(arr.assess_memory_depth("r", root)["level"], "thin")

    def test_level_boundary_three_moderate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_repo_mem(root, "r", notes=3)
            self.assertEqual(arr.assess_memory_depth("r", root)["level"], "moderate")

    def test_level_boundary_ten_deep(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_repo_mem(root, "r", notes=10)
            self.assertEqual(arr.assess_memory_depth("r", root)["level"], "deep")

    def test_notes_plus_adrs_drive_level(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            # 8 notes + 2 ADRs = 10 → deep.
            _make_repo_mem(root, "r", notes=8, adrs=2)
            self.assertEqual(arr.assess_memory_depth("r", root)["level"], "deep")


# ── AI-friendliness signal detection ───────────────────────────────────────

class SignalDetectionTest(unittest.TestCase):
    def _blank(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return Path(d.name)

    def test_blank_repo_all_absent(self):
        repo = self._blank()
        sig = arr.assess_ai_friendliness(repo)["signals"]
        self.assertEqual(set(sig.values()), {False})

    def test_tests_dir(self):
        repo = self._blank()
        (repo / "tests").mkdir()
        self.assertTrue(arr.assess_ai_friendliness(repo)["signals"]["tests"])

    def test_tests_file_pattern(self):
        repo = self._blank()
        _touch(repo / "test_thing.py")
        self.assertTrue(arr.assess_ai_friendliness(repo)["signals"]["tests"])

    def test_tests_pyproject_pytest_section(self):
        repo = self._blank()
        _touch(repo / "pyproject.toml", "[tool.pytest.ini_options]\naddopts = ''\n")
        self.assertTrue(arr.assess_ai_friendliness(repo)["signals"]["tests"])

    def test_ci_github_workflows(self):
        repo = self._blank()
        _touch(repo / ".github" / "workflows" / "ci.yml", "on: push\n")
        self.assertTrue(arr.assess_ai_friendliness(repo)["signals"]["ci"])

    def test_typecheck_tsconfig(self):
        repo = self._blank()
        _touch(repo / "tsconfig.json", "{}")
        self.assertTrue(arr.assess_ai_friendliness(repo)["signals"]["typecheck"])

    def test_typecheck_pyproject_mypy(self):
        repo = self._blank()
        _touch(repo / "pyproject.toml", "[tool.mypy]\nstrict = true\n")
        self.assertTrue(arr.assess_ai_friendliness(repo)["signals"]["typecheck"])

    def test_adrs_dir_with_md(self):
        repo = self._blank()
        _touch(repo / "adr" / "0001-x.md", "# adr\n")
        self.assertTrue(arr.assess_ai_friendliness(repo)["signals"]["adrs"])

    def test_adrs_dir_without_md_is_absent(self):
        repo = self._blank()
        (repo / "adr").mkdir()
        self.assertFalse(arr.assess_ai_friendliness(repo)["signals"]["adrs"])

    def test_conventions_claude_md(self):
        repo = self._blank()
        _touch(repo / "CLAUDE.md", "# rules\n")
        self.assertTrue(arr.assess_ai_friendliness(repo)["signals"]["conventions"])

    def test_project_package_json(self):
        repo = self._blank()
        _touch(repo / "package.json", "{}")
        self.assertTrue(arr.assess_ai_friendliness(repo)["signals"]["project"])

    def test_detail_readme_and_docs(self):
        repo = self._blank()
        _touch(repo / "README.md", "# hi\n")
        (repo / "docs").mkdir()
        detail = arr.assess_ai_friendliness(repo)["detail"]
        self.assertTrue(detail["has_readme"])
        self.assertTrue(detail["has_docs"])


# ── AI-friendliness level rule ─────────────────────────────────────────────

class FriendlinessLevelTest(unittest.TestCase):
    def _repo(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return Path(d.name)

    def test_low_when_bare(self):
        repo = self._repo()
        _touch(repo / "README.md")
        self.assertEqual(arr.assess_ai_friendliness(repo)["level"], "low")

    def test_medium_tests_plus_ci(self):
        repo = self._repo()
        (repo / "tests").mkdir()
        _touch(repo / ".github" / "workflows" / "ci.yml", "on: push\n")
        self.assertEqual(arr.assess_ai_friendliness(repo)["level"], "medium")

    def test_medium_tests_plus_typecheck(self):
        repo = self._repo()
        (repo / "tests").mkdir()
        _touch(repo / "tsconfig.json", "{}")
        self.assertEqual(arr.assess_ai_friendliness(repo)["level"], "medium")

    def test_heavy_without_supporting_is_medium(self):
        # tests + ci + typecheck but no adrs/conventions → not high.
        repo = self._repo()
        (repo / "tests").mkdir()
        _touch(repo / ".github" / "workflows" / "ci.yml", "on: push\n")
        _touch(repo / "tsconfig.json", "{}")
        self.assertEqual(arr.assess_ai_friendliness(repo)["level"], "medium")

    def test_high_all_heavy_plus_conventions(self):
        repo = self._repo()
        (repo / "tests").mkdir()
        _touch(repo / ".github" / "workflows" / "ci.yml", "on: push\n")
        _touch(repo / "tsconfig.json", "{}")
        _touch(repo / "CLAUDE.md", "# rules\n")
        self.assertEqual(arr.assess_ai_friendliness(repo)["level"], "high")

    def test_high_all_heavy_plus_adrs(self):
        repo = self._repo()
        (repo / "tests").mkdir()
        _touch(repo / ".github" / "workflows" / "ci.yml", "on: push\n")
        _touch(repo / "tsconfig.json", "{}")
        _touch(repo / "adr" / "0001-x.md", "# adr\n")
        self.assertEqual(arr.assess_ai_friendliness(repo)["level"], "high")

    def test_ci_only_is_low(self):
        # No tests → cannot reach medium even with ci + typecheck.
        repo = self._repo()
        _touch(repo / ".github" / "workflows" / "ci.yml", "on: push\n")
        _touch(repo / "tsconfig.json", "{}")
        self.assertEqual(arr.assess_ai_friendliness(repo)["level"], "low")


# ── missing items ──────────────────────────────────────────────────────────

class MissingItemsTest(unittest.TestCase):
    def test_all_absent_produces_all_gaps(self):
        memory = {"level": "none"}
        ai = {"signals": {k: False for k in
                          ("tests", "ci", "typecheck", "adrs", "conventions", "project")}}
        gaps = arr.missing_items(memory, ai)
        joined = "\n".join(gaps)
        self.assertIn("No tests", joined)
        self.assertIn("No CI", joined)
        self.assertIn("typecheck", joined)
        self.assertIn("No ADRs", joined)
        self.assertIn("CLAUDE.md", joined)
        self.assertIn("project manifest", joined)
        self.assertIn("no durable knowledge", joined)

    def test_present_signals_produce_no_gaps(self):
        memory = {"level": "deep"}
        ai = {"signals": {k: True for k in
                          ("tests", "ci", "typecheck", "adrs", "conventions", "project")}}
        self.assertEqual(arr.missing_items(memory, ai), [])

    def test_memory_gap_only_when_none(self):
        ai = {"signals": {k: True for k in
                          ("tests", "ci", "typecheck", "adrs", "conventions", "project")}}
        self.assertEqual(arr.missing_items({"level": "thin"}, ai), [])
        self.assertEqual(len(arr.missing_items({"level": "none"}, ai)), 1)


# ── assess() end-to-end ────────────────────────────────────────────────────

class AssessComposeTest(unittest.TestCase):
    def test_schema_and_values(self):
        with tempfile.TemporaryDirectory() as md, tempfile.TemporaryDirectory() as rd:
            memory_root = Path(md)
            repo = Path(rd)
            # Repo basename drives repo_name; make a matching memory dir.
            _make_repo_mem(memory_root, repo.name, notes=5, adrs=0)
            (repo / "tests").mkdir()
            _touch(repo / "pyproject.toml", "[tool.pytest.ini_options]\n")

            res = arr.assess(repo, memory_root=memory_root)
            self.assertEqual(
                set(res),
                {"repo", "repo_path", "memory_depth", "ai_friendliness", "missing"},
            )
            self.assertEqual(res["repo"], repo.name)
            self.assertEqual(res["memory_depth"]["level"], "moderate")
            self.assertTrue(res["ai_friendliness"]["signals"]["tests"])
            self.assertIsInstance(res["missing"], list)
            # Memory present → no "durable knowledge" gap.
            self.assertFalse(any("durable knowledge" in g for g in res["missing"]))


# ── main() ─────────────────────────────────────────────────────────────────

class MainTest(unittest.TestCase):
    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = arr.main(argv)
        return rc, buf.getvalue()

    def test_json_output_parses_with_schema(self):
        with tempfile.TemporaryDirectory() as md, tempfile.TemporaryDirectory() as rd:
            _make_repo_mem(Path(md), Path(rd).name, notes=1)
            rc, out = self._run([rd, "--json", "--memory-root", md])
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertEqual(
                set(data),
                {"repo", "repo_path", "memory_depth", "ai_friendliness", "missing"},
            )

    def test_markdown_has_section_headers(self):
        with tempfile.TemporaryDirectory() as md, tempfile.TemporaryDirectory() as rd:
            rc, out = self._run([rd, "--memory-root", md])
            self.assertEqual(rc, 0)
            self.assertIn("# Repo readiness", out)
            self.assertIn("## Memory depth", out)
            self.assertIn("## AI-friendliness", out)
            self.assertIn("## What's missing", out)

    def test_nonexistent_repo_returns_zero_all_absent(self):
        with tempfile.TemporaryDirectory() as md:
            missing_path = str(Path(md) / "does-not-exist")
            rc, out = self._run([missing_path, "--json", "--memory-root", md])
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertEqual(data["memory_depth"]["level"], "none")
            self.assertEqual(data["ai_friendliness"]["level"], "low")
            self.assertEqual(set(data["ai_friendliness"]["signals"].values()), {False})


if __name__ == "__main__":
    unittest.main()
