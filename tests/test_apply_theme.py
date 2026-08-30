# tests/test_apply_theme.py
"""Round-trip and dry-run coverage for `scripts/apply_theme.py`.

The script renames agent files (functional <-> philosophers) and rewrites
cross-references in place, so the property worth pinning is that applying
both directions in sequence is a no-op — the tree returns exactly to what it
started as. Runs only against a temp copy; never against the real `agents/`.

The temp copy is seeded from the real `agents/`, and these tests ship to
instances that may already be themed. So the starting theme is *detected*, not
assumed, and every expectation (rename direction, no-op message, dry-run
report) is derived from it. The property under test is unchanged: the tests
still round-trip a real crew through the other theme and back and demand a
byte-for-byte restore — only the direction is now read off the tree.
"""

import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_theme  # noqa: E402

AGENTS_DIR = ROOT / "agents"

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _tree_snapshot(agents_dir: Path) -> dict[str, bytes]:
    """Filename -> raw file bytes, for comparing a tree before and after.

    Bytes, not text: `read_text` normalises line endings on the way in, which
    would make the round-trip comparison blind to the rewrite changing them.
    """
    return {p.name: p.read_bytes() for p in sorted(agents_dir.glob("*.md"))}


def _other_theme(theme: str) -> str:
    """The theme that is not `theme`."""
    return next(t for t in apply_theme.THEMES if t != theme)


def _expected_renames(target: str) -> list[tuple[str, str]]:
    """(src, dst) filenames apply_theme renames when switching to `target`."""
    if target == "philosophers":
        return [(f"{f}.md", f"{p}.md") for f, p in apply_theme.PAIRS]
    return [(f"{p}.md", f"{f}.md") for f, p in apply_theme.PAIRS]


def _frontmatter_name(path: Path) -> str | None:
    """The `name:` value declared in an agent charter's YAML frontmatter.

    Returns None when the file has no frontmatter block or no `name:` key —
    both of which are failures at the call site, not conditions to skip.
    """
    block = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    if block is None:
        return None
    for line in block.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "name":
            return value.strip()
    return None


class ApplyThemeRoundTripTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.agents_dir = Path(self._tmp.name) / "agents"
        self.agents_dir.mkdir()
        for src in AGENTS_DIR.glob("*.md"):
            (self.agents_dir / src.name).write_bytes(src.read_bytes())
        self.original = _tree_snapshot(self.agents_dir)
        self.start = apply_theme.detect_theme(self.agents_dir)
        self.assertIn(self.start, apply_theme.THEMES,
                      "could not detect a theme in the seeded agents/ copy")
        self.other = _other_theme(self.start)

    def tearDown(self):
        self._tmp.cleanup()

    def test_switching_to_the_other_theme_and_back_restores_the_tree(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = apply_theme.apply_theme(self.agents_dir, self.other)
        self.assertEqual(rc, 0)
        self.assertEqual(apply_theme.detect_theme(self.agents_dir), self.other)

        switched_names = {p.name for p in self.agents_dir.glob("*.md")}
        for src, dst in _expected_renames(self.other):
            self.assertNotIn(src, switched_names)
            self.assertIn(dst, switched_names)
        # The outbound leg must actually have rewritten content, otherwise the
        # restore below would be vacuously true.
        self.assertNotEqual(_tree_snapshot(self.agents_dir), self.original)

        with contextlib.redirect_stdout(io.StringIO()):
            rc = apply_theme.apply_theme(self.agents_dir, self.start)
        self.assertEqual(rc, 0)
        self.assertEqual(apply_theme.detect_theme(self.agents_dir), self.start)

        self.assertEqual(_tree_snapshot(self.agents_dir), self.original)

    def test_line_endings_survive_the_round_trip(self):
        """Regression: the rewrite must not normalise line endings.

        `Path.write_text` expands "\\n" to os.linesep, so on Windows every
        rewritten charter came back as CRLF — dirtying a tree `.gitattributes`
        pins to `eol=lf`. os.linesep is "\\n" on Linux CI, so the bug is
        invisible there unless the fixture supplies CRLF explicitly.
        """
        for p in self.agents_dir.glob("*.md"):
            p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        crlf = _tree_snapshot(self.agents_dir)

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(apply_theme.apply_theme(self.agents_dir, self.other), 0)
        for name, body in _tree_snapshot(self.agents_dir).items():
            with self.subTest(agent=name):
                self.assertNotIn(b"\n", body.replace(b"\r\n", b""),
                                 f"{name}: line endings were rewritten to LF")

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(apply_theme.apply_theme(self.agents_dir, self.start), 0)
        self.assertEqual(_tree_snapshot(self.agents_dir), crlf)

    def _assert_names_match_filenames(self, when: str):
        """Every charter in the tree declares the name its filename promises."""
        agents = sorted(self.agents_dir.glob("*.md"))
        self.assertTrue(agents, f"{when}: no agent files found — nothing asserted")
        for path in agents:
            with self.subTest(when=when, agent=path.name):
                declared = _frontmatter_name(path)
                self.assertEqual(
                    declared, path.stem,
                    f"{when}: {path.name} declares `name: {declared}` — a charter whose "
                    "name and filename disagree does not load at all",
                )

    def test_theme_never_desyncs_name_from_filename(self):
        """A themed charter's `name:` must equal its filename stem, both directions.

        Regression test for the builder-tier corruption. `_transform` rewrites
        on ``\\bbuilder\\b`` and ``-`` is a non-word character, so it happily
        rewrote ``name: builder-simple`` to ``name: archimedes-simple`` — while
        the file-rename list knew only ``builder.md``. The theme therefore
        produced ``builder-simple.md`` declaring itself ``archimedes-simple``,
        and that agent silently stops loading.

        The round-trip test above is structurally blind to this. The corruption
        was *symmetric*: the reverse leg mangled the file back exactly as it had
        mangled it out, so the tree restored byte-for-byte and the assertion
        passed over a broken intermediate state. Any property checked only as
        "start == end" cannot see damage that both legs share.

        So the oracle here is deliberately local: each file's own content
        against its own name. No roster constant takes part, which is the point
        — the roster tests derive both sides from ``_crew_common`` and can only
        prove the script is self-consistent. This one can fail while every
        constant in the repo agrees with itself.
        """
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(apply_theme.apply_theme(self.agents_dir, self.other), 0)
        self.assertEqual(apply_theme.detect_theme(self.agents_dir), self.other)
        self._assert_names_match_filenames(f"after switching to '{self.other}'")

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(apply_theme.apply_theme(self.agents_dir, self.start), 0)
        self.assertEqual(apply_theme.detect_theme(self.agents_dir), self.start)
        self._assert_names_match_filenames(f"after reverting to '{self.start}'")

    def test_reapplying_the_current_theme_is_a_noop(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = apply_theme.apply_theme(self.agents_dir, self.start)
        self.assertEqual(rc, 0)
        self.assertIn(f"already on the '{self.start}' theme", out.getvalue())
        self.assertEqual(_tree_snapshot(self.agents_dir), self.original)

    def test_dry_run_reports_without_writing(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = apply_theme.apply_theme(self.agents_dir, self.other, dry_run=True)
        self.assertEqual(rc, 0)
        report = out.getvalue()
        for src, dst in _expected_renames(self.other):
            self.assertIn(f"would rename {src} -> {dst}", report)
        # nothing on disk actually changed
        self.assertEqual(apply_theme.detect_theme(self.agents_dir), self.start)
        self.assertEqual(_tree_snapshot(self.agents_dir), self.original)


class ThemeMappingSafetyTest(unittest.TestCase):
    """Properties of the rename table itself, independent of any agent file."""

    def test_no_mapping_replacement_is_another_mappings_search_term(self):
        """No rename may feed another rename.

        `_transform` applies its rules sequentially with `re.sub` over the whole
        text, so if one mapping's replacement is another mapping's search term
        the second rule rewrites the first rule's output and a name lands two
        hops from where it started — in a single pass, invisibly. Nothing in
        `_mappings` prevents that; today's pairs merely happen to be disjoint.

        `apply_theme`'s module docstring already advertises the neighbouring
        hazard — the word "Socratic" must survive a `critic` revert — with no
        test standing behind it. This closes that class going forward: it is the
        guard that fires on the *next* name added to `PAIRS`, not on the ones
        already vetted.

        Asserted over all pairs rather than only over rules emitted later, so
        the guarantee does not quietly depend on the order `_mappings` returns.
        """
        for theme in apply_theme.THEMES:
            mappings = apply_theme._mappings(theme)
            self.assertTrue(mappings, f"{theme}: no mappings — nothing asserted")
            search_terms = {frm for frm, _ in mappings}
            for frm, to in mappings:
                with self.subTest(theme=theme, mapping=f"{frm} -> {to}"):
                    self.assertNotIn(
                        to, search_terms - {frm},
                        f"{theme}: '{frm}' -> '{to}', but '{to}' is itself a search term "
                        "of another mapping — sequential re.sub would chain the two "
                        "renames and carry the name past its target",
                    )


if __name__ == "__main__":
    unittest.main()
