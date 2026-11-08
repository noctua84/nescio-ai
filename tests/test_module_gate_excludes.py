"""The module gate's prose excludes must actually match the prose in the tree.

`module_scan.is_excluded` matches with ``fnmatch``, where ``*`` already crosses
``/``. So ``memory/*.md`` matches both ``memory/CONVENTIONS.md`` and
``memory/repo/nescio/adr/0005-x.md``, while ``memory/**/*.md`` translates to a
pattern needing a literal ``/`` after the wildcard and silently misses every
``.md`` sitting directly in the directory.

That is not hypothetical twice over. ``memory/**/*.md`` was the spelling in
`.github/workflows/module-gate.yml`, so `memory/CONVENTIONS.md` was still gated
-- latent only because it is far short of the tripwire. And the first attempt at
the `docs/reports` exclusion was spelled ``docs/reports/**/*.md``, which
excluded none of the four reports it was added for. Both failures are invisible:
a non-matching exclude pattern raises nothing, it just does not exclude.

So these tests read the patterns out of the workflow itself and assert against
the real tree. A pattern that stops matching -- because it was retyped, or
because a file moved -- fails here rather than quietly reinstating a verdict
demand on prose.
"""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import module_scan  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "module-gate.yml"

# Directories the workflow's comment calls "long-form prose records, not
# modules". Every tracked `.md` under these must be excluded.
PROSE_DIRS = ("docs/plans", "docs/specs", "docs/reports", ".sisyphus", "memory")


def workflow_excludes() -> tuple[str, ...]:
    """The `--exclude` patterns the workflow actually passes.

    Read from the YAML text rather than hardcoded here: a copy would drift from
    the workflow the moment either changed, which is the whole failure mode
    under test.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    return tuple(re.findall(r"--exclude '([^']+)'", text))


def tracked_md(prefix: str) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z", "--", f"{prefix}/*.md"],
        capture_output=True,
        check=True,
    )
    raw = proc.stdout.decode("utf-8", errors="surrogateescape")
    return [name for name in raw.split("\0") if name]


class WorkflowExcludeParsingTest(unittest.TestCase):
    def test_patterns_are_found(self):
        """A parse that silently returns nothing would make every test vacuous."""
        pats = workflow_excludes()
        self.assertGreaterEqual(len(pats), 6, pats)

    def test_prose_dirs_are_each_named_by_some_pattern(self):
        joined = " ".join(workflow_excludes())
        for d in PROSE_DIRS:
            self.assertIn(d, joined, f"{d} has no exclude pattern at all")


class ProseIsExcludedTest(unittest.TestCase):
    def test_every_tracked_prose_md_is_excluded(self):
        pats = workflow_excludes()
        missed: list[str] = []
        checked = 0
        for d in PROSE_DIRS:
            for rel in tracked_md(d):
                checked += 1
                if not module_scan.is_excluded(rel, pats):
                    missed.append(rel)
        self.assertGreater(checked, 0, "found no tracked prose at all to check")
        self.assertEqual(missed, [], f"not excluded by {pats}: {missed}")

    def test_memory_md_directly_in_the_directory_is_excluded(self):
        """The `memory/**/*.md` bug, pinned by name.

        `memory/CONVENTIONS.md` is the file that spelling missed.
        """
        self.assertTrue(
            module_scan.is_excluded("memory/CONVENTIONS.md", workflow_excludes())
        )

    def test_report_md_directly_in_the_directory_is_excluded(self):
        """The `docs/reports/**/*.md` bug, pinned by name."""
        self.assertTrue(
            module_scan.is_excluded(
                "docs/reports/2026-08-29-wiki-index-marker-preservation.md",
                workflow_excludes(),
            )
        )


class CodeIsStillGatedTest(unittest.TestCase):
    """The prose excludes must not become a hole for code.

    `*.md` scoping is the point: a script that lands in a prose directory is
    still a module and still gets a verdict.
    """

    def test_python_in_a_prose_dir_is_not_excluded(self):
        pats = workflow_excludes()
        for rel in (
            "memory/scripts/thing.py",
            "memory/thing.py",
            "docs/reports/helper.py",
        ):
            self.assertFalse(
                module_scan.is_excluded(rel, pats), f"{rel} should still be gated"
            )

    def test_source_trees_are_not_excluded(self):
        pats = workflow_excludes()
        for rel in ("scripts/wiki_index.py", "tests/test_wiki_index.py"):
            self.assertFalse(
                module_scan.is_excluded(rel, pats), f"{rel} should still be gated"
            )


if __name__ == "__main__":
    unittest.main()
