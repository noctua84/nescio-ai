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
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import _crew_common  # noqa: E402
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
    """(src, dst) filenames apply_theme renames when switching to `target`.

    Derived from `_crew_common.renamed_agents` — the same list the script drives
    its rename loop from — so this covers all eleven files. Deriving it from
    `PAIRS` alone would miss the two builder tiers: they are renamed by the
    script but asserted by nothing, so the dry-run report could stop mentioning
    them without a test noticing.
    """
    return [(f"{src}.md", f"{dst}.md") for src, dst in _crew_common.renamed_agents(target)]


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

    def test_a_tree_desynced_by_an_older_run_is_repaired_by_re_running(self):
        """Re-running the script must converge a tree an older build half-converted.

        `detect_theme` classifies the whole tree from one representative file
        (`plato.md` exists -> "philosophers"), and the no-op path used to
        short-circuit on `current == target` alone. So the tree left behind by
        the build that renamed only five of the seven files — themed charters
        under two un-renamed tier filenames, two agents that do not load —
        reported "already on the 'philosophers' theme — nothing to do." The
        obvious remedy, re-running the fixed script, claimed success and
        repaired nothing.

        The corruption is reproduced the way it actually happened rather than
        hand-written: switch cleanly, then undo the tier *file* renames, leaving
        their content themed. The oracle is each file's own `name:` against its
        own filename — no roster constant takes part, so this can fail while
        every constant in the repo agrees with itself.
        """
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(apply_theme.apply_theme(self.agents_dir, self.other), 0)
        healthy = _tree_snapshot(self.agents_dir)

        for name in _crew_common.TIERED_AGENTS:
            on_disk = self.agents_dir / f"{_crew_common.themed_name(name, self.other)}.md"
            on_disk.rename(self.agents_dir / f"{_crew_common.themed_name(name, self.start)}.md")

        self.assertEqual(apply_theme.detect_theme(self.agents_dir), self.other,
                         "precondition: detect_theme must still report the target theme")
        self.assertTrue(apply_theme.desynced_agents(self.agents_dir),
                        "precondition: the reproduced tree must actually be desynced")

        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = apply_theme.apply_theme(self.agents_dir, self.other)
        self.assertEqual(rc, 0)
        self.assertNotIn("nothing to do", out.getvalue(),
                         "a desynced tree must not be reported as already themed")
        self.assertEqual(apply_theme.desynced_agents(self.agents_dir), [])
        self._assert_names_match_filenames("after repairing a desynced tree")
        self.assertEqual(_tree_snapshot(self.agents_dir), healthy,
                         "the repair must land on the same tree a clean switch produces")

        # ...and the repair converges: the next run is a clean no-op again.
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(apply_theme.apply_theme(self.agents_dir, self.other), 0)
        self.assertIn(f"already on the '{self.other}' theme", out.getvalue())
        self.assertEqual(_tree_snapshot(self.agents_dir), healthy)

    def test_a_desync_the_theme_cannot_fix_is_reported_and_fails(self):
        """A repair pass must verify it repaired something before claiming it did.

        The convergence path above fixes the stragglers an older build left
        behind. It cannot fix a desync that is not a rename or a word rewrite —
        a hand-edited `name:`, a name in no roster. Such a file is correctly
        *detected* (the run stops calling itself a no-op and lists it), the pass
        does nothing to it, and the run used to print "converged" and exit 0
        anyway. That is a worse failure than the no-op it replaced: the operator
        is now told the tree was repaired.

        The subject is deliberately a THEME_INVARIANT agent, so no rename rule
        and no word mapping in the script can touch it — the residue is
        unfixable by construction, not by a fixture's choice of name.
        """
        victim = self.agents_dir / "scout.md"
        self.assertTrue(victim.exists(), "precondition: scout.md must be in the crew")
        victim.write_text(
            victim.read_text(encoding="utf-8", newline="").replace(
                "name: scout", "name: sccout", 1),
            encoding="utf-8", newline="")
        self.assertEqual(apply_theme.desynced_agents(self.agents_dir),
                         [("scout.md", "sccout")],
                         "precondition: exactly one unfixable desync")
        self.assertEqual(apply_theme.detect_theme(self.agents_dir), self.start,
                         "precondition: the tree is still on its own theme")
        before = victim.read_bytes()

        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            rc = apply_theme.apply_theme(self.agents_dir, self.start)

        self.assertNotEqual(rc, 0, "an unrepaired desync must not exit 0")
        self.assertIn("scout.md", err.getvalue(),
                      "the file that could not be converged must be named")
        self.assertIn("sccout", err.getvalue(),
                      "the name that could not be converged must be named")
        self.assertNotIn("converged crew", out.getvalue(),
                         "the run must not claim a convergence it did not achieve")
        # The pass is allowed to run — it just may not lie about the outcome.
        # Nothing in the machinery addresses this file, so it is still desynced.
        self.assertEqual(victim.read_bytes(), before)
        self.assertEqual(apply_theme.desynced_agents(self.agents_dir),
                         [("scout.md", "sccout")])

    def test_a_tree_carrying_both_themes_is_refused_not_guessed(self):
        """Representatives of both themes present is a broken tree, not a theme.

        `detect_theme` tested `plato.md` before `planner.md`, so a tree holding
        both was classified "philosophers" by *source order* — the answer would
        have flipped had the two branches been written the other way round. The
        rename-conflict guard means this can no longer clobber anything, so what
        is at stake is the claim, not the data: the run must say it cannot tell
        rather than pick a branch.

        Asserted in both directions and in dry-run as well as live, and the
        oracle for "did not guess" is the snapshot being byte-identical — a run
        that guessed would have rewritten every charter before reaching the
        rename loop.
        """
        stray = self.agents_dir / apply_theme.THEME_REPRESENTATIVES[self.other]
        self.assertFalse(stray.exists(), "precondition: the other theme is not on disk")
        stray.write_bytes(b"# a file the user put here themselves\n")
        before = _tree_snapshot(self.agents_dir)

        self.assertIsNone(apply_theme.detect_theme(self.agents_dir),
                          "a tree carrying both themes must not classify as either")

        for target in apply_theme.THEMES:
            for dry_run in (False, True):
                with self.subTest(target=target, dry_run=dry_run):
                    with contextlib.redirect_stdout(io.StringIO()), \
                            contextlib.redirect_stderr(io.StringIO()) as err:
                        rc = apply_theme.apply_theme(self.agents_dir, target,
                                                     dry_run=dry_run)
                    self.assertEqual(rc, 2, "an ambiguous tree must be refused")
                    # Naming the files is not enough on its own: the "could not
                    # detect the crew (neither planner.md nor plato.md found)"
                    # branch names both too, and is exactly the wrong diagnosis
                    # for a tree that has both. So the report must attribute
                    # each file to the theme it evidences, and must not claim
                    # the crew is missing.
                    for theme, name in apply_theme.THEME_REPRESENTATIVES.items():
                        self.assertIn(f"{name} ({theme})", err.getvalue(),
                                      "each colliding representative must be named "
                                      "with the theme it evidences")
                    self.assertNotIn("neither", err.getvalue(),
                                     "both representatives are present — reporting the "
                                     "tree as unrecognisable is a misdiagnosis")
                    self.assertEqual(
                        _tree_snapshot(self.agents_dir), before,
                        "the tree must be byte-identical after a refused run",
                    )

    def test_a_rename_conflict_aborts_with_the_tree_untouched(self):
        """A destination that already exists must abort *before* anything is written.

        The rename loop guarded `src.exists()` and never `dst.exists()`.
        `Path.rename` raises FileExistsError on Windows and silently clobbers a
        user's own file on POSIX — and because step 1 rewrites every charter
        before step 2 renames anything, an exception raised mid-loop left the
        whole tree rewritten and only some files renamed. That state is
        self-perpetuating: `detect_theme` still reports the target theme, so
        every later run re-crashes at the same file.

        The assertion that matters is therefore not the exit code but
        `_tree_snapshot` being byte-identical to before the call — "no partial
        write", checked once per destination and in both dry-run and live mode,
        since a dry run that pre-flights nothing reports a rename it cannot do.
        """
        original = _tree_snapshot(self.agents_dir)
        renames = _expected_renames(self.other)
        self.assertTrue(renames, "no renames — nothing asserted")

        for _src, dst in renames:
            stray = self.agents_dir / dst
            for dry_run in (False, True):
                with self.subTest(destination=dst, dry_run=dry_run):
                    stray.write_bytes(b"# a file the user put here themselves\n")
                    before = _tree_snapshot(self.agents_dir)

                    with contextlib.redirect_stdout(io.StringIO()), \
                            contextlib.redirect_stderr(io.StringIO()) as err:
                        rc = apply_theme.apply_theme(self.agents_dir, self.other,
                                                     dry_run=dry_run)

                    self.assertEqual(rc, 2, f"{dst} already exists — the run must refuse")
                    self.assertIn(dst, err.getvalue(),
                                  "the conflicting destination must be named on stderr")
                    self.assertEqual(
                        _tree_snapshot(self.agents_dir), before,
                        f"{dst}: the tree must be byte-identical after a refused run — "
                        "a partial write leaves charters rewritten and files half-renamed",
                    )
            stray.unlink()
            self.assertEqual(_tree_snapshot(self.agents_dir), original)

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


class ThemeNamePinTest(unittest.TestCase):
    """The rename table, spelled out — the suite's only external oracle.

    Every other roster assertion in this repo derives *both* sides from
    ``_crew_common.PAIRS``: the round trip, the dry-run report, the roster
    expectation, the write-policy names. That makes them all blind to the same
    class of defect — a wrong name. Rewriting ``PAIRS`` so ``builder`` mapped to
    ``"WRONGNAME"`` passed the entire suite, green, because every expectation
    dutifully recomputed itself from the typo.

    So the duplication below is deliberate and is the whole point. This is the
    one place where the expected mapping is written independently of the code
    under test, which makes it the one place a misspelt philosopher, a dropped
    pair, or an accidental remap can go red. Do not "DRY this up" by deriving it
    from ``_crew_common`` — that deletes the test while leaving it passing.

    Changing a crew name is therefore a two-file edit on purpose: the constant
    and this pin. The second edit is the moment someone has to look at the name
    and agree to it.
    """

    EXPECTED_PAIRS = {
        "planner": "plato",
        "advisor": "aristotle",
        "reviewer": "pyrrho",
        "critic": "socrates",
        "builder": "archimedes",
        "test-writer": "euclid",
        "qa-guard": "cato",
        "doc-researcher": "callimachus",
        "doc-writer": "cicero",
    }

    def test_pairs_are_exactly_the_agreed_names(self):
        self.assertEqual(dict(_crew_common.PAIRS), self.EXPECTED_PAIRS)

    def test_pairs_has_no_duplicate_functional_names(self):
        """`dict(PAIRS)` would hide a duplicated key by keeping only the last.

        The assertion above compares dicts, so two entries for the same
        functional name collapse silently and the extra rule stays live in
        `_mappings`. Checked on the list, where the duplicate is still visible.
        """
        functional = [f for f, _ in _crew_common.PAIRS]
        self.assertEqual(len(functional), len(set(functional)))
        self.assertEqual(len(functional), len(self.EXPECTED_PAIRS))


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


class ThemeCasingCoverageTest(unittest.TestCase):
    """The rename table must cover every casing the real charters actually use."""

    def test_no_agent_file_writes_a_mapped_term_in_an_uncovered_casing(self):
        """Every `\\b<term>\\b` in `agents/` must be a casing `_mappings` rewrites.

        Motivating finding: ``agents/planner.md`` shouts its role in two places
        — ``**YOU ARE A PLANNER. YOU ARE NOT AN IMPLEMENTER...**`` (:12) and
        ``You are a CONSULTANT first, PLANNER second`` (:24). ``_mappings``
        emitted only ``planner`` and ``Planner``, so ``\\bPLANNER\\b`` had no
        rule and applying the philosopher theme produced a ``plato.md`` still
        calling itself a PLANNER — the functional name leaking into the
        philosopher tree.

        The round-trip test cannot see this, and stays green while it happens:
        the leak is **symmetric**. A word neither leg rewrites is restored by
        doing nothing to it, so "start == end" holds over a broken middle. Same
        blindness class as the builder-tier corruption above.

        The oracle is the *real* ``agents/`` tree, not a fixture, and the
        covered set is read out of ``_mappings`` rather than restated here — so
        this fails if a charter grows a new casing **or** if a casing rule is
        removed from the script.

        Live hazard, caught here rather than prevented: **intercaps**
        (``QA-guard``, ``Doc-Writer``, ``docWriter``). ``_mappings`` emits only
        lower / ``.capitalize()`` / ``.upper()``, and ``.capitalize()``
        lowercases the tail — so ``qa-guard`` yields ``Qa-guard`` and never
        ``QA-guard``. Four hyphenated names are mapped terms now
        (``test-writer``, ``qa-guard``, ``doc-researcher``, ``doc-writer``) and
        every one of them has an intercaps spelling a human would plausibly
        reach for. None appears in ``agents/`` today, which is a fact about the
        charters and not a property of the script — so this scan is what keeps
        it true. A red here means a charter grew such a spelling: the fix is a
        fourth variant rule in ``_mappings``, not a reword of the charter.
        """
        terms = {name for pair in apply_theme.PAIRS for name in pair}
        covered = {frm for theme in apply_theme.THEMES
                   for frm, _ in apply_theme._mappings(theme)}
        self.assertTrue(covered, "no mappings — nothing asserted")

        offenders = []
        for md in sorted(AGENTS_DIR.glob("*.md")):
            text = md.read_text(encoding="utf-8", newline="")
            for term in sorted(terms):
                for match in re.finditer(rf"\b{re.escape(term)}\b", text, re.IGNORECASE):
                    found = match.group(0)
                    if found not in covered:
                        line = text.count("\n", 0, match.start()) + 1
                        offenders.append(f"{md.name}:{line}: {found!r}")

        self.assertEqual(
            offenders, [],
            "these agent files spell a themed name in a casing `_mappings` has no "
            "rule for, so the theme would leave the name behind on rename:\n  "
            + "\n  ".join(offenders),
        )


class ThemeReferenceBlastRadiusTest(unittest.TestCase):
    """The theme rewrites words inside `agents/`; it renames nothing outside it."""

    # Tokens containing at least one "/" — the shape a path reference takes in
    # prose. Deliberately permissive; the two filters below decide what counts.
    _PATH_TOKEN_RE = re.compile(r"[\w.-]+(?:/[\w.-]+)+")

    # Extensions that make a slash-token a path regardless of where it is
    # rooted, so a reference to an unwritten file (or one under a directory
    # that does not exist yet) is still scanned.
    _SOURCE_SUFFIXES = (".py", ".md", ".json", ".sh", ".yml", ".yaml", ".ts", ".js", ".toml")

    def _outside_agents_path_references(self) -> list[tuple[str, str]]:
        """(offender label, token) for every non-`agents/` path a charter names.

        The label is `<file>:<line>` so a failure points at the exact
        occurrence, matching `ThemeCasingCoverageTest`'s style.
        """
        top_level = {p.name for p in ROOT.iterdir()}
        found: list[tuple[str, str]] = []
        for md in sorted(AGENTS_DIR.glob("*.md")):
            text = md.read_text(encoding="utf-8", newline="")
            for match in self._PATH_TOKEN_RE.finditer(text):
                token = match.group(0)
                first = token.split("/", 1)[0]
                # Two ways to qualify as a path: rooted at something that really
                # exists at the top of the repo, or carrying a source/doc
                # extension. Prose slashes ("pass/fail", "authN/authZ",
                # "reviewer/critic") satisfy neither, which is the point — the
                # last of those is a mapped term and would otherwise flood this
                # scan with false offenders.
                if not (first in top_level or token.endswith(self._SOURCE_SUFFIXES)):
                    continue
                # `agents/...` references are rewritten *and* the file renamed,
                # in lockstep, by the same run. That is the script working, not
                # the hazard.
                if first == "agents":
                    continue
                line = text.count("\n", 0, match.start()) + 1
                found.append((f"{md.name}:{line}", token))
        return found

    def test_no_charter_references_an_outside_path_the_theme_would_rewrite(self):
        """A path outside `agents/` must not contain a word the theme renames.

        What breaks: `apply_theme` does two things, and only one of them reaches
        past `agents/`. `_transform` rewrites mapped names **inside charter
        bodies**; the rename loop renames **`agents/*.md` files**. Both are
        scoped to `agents_dir.glob("*.md")`. So a charter that mentions, say,
        `hooks/qa-guard-scope.py` has that reference rewritten in place to
        `hooks/cato-scope.py` — while the file on disk keeps its name, because
        it lives outside the only directory the script touches. The charter now
        points at a path that does not exist, and the failure surfaces at
        whatever later moment something tries to follow it.

        Why nothing else sees it: every existing test of this behaviour globs
        `agents/` and nothing else — `ThemeCasingCoverageTest` above, and
        `test_roster_expectation_follows_the_philosophers_theme` in
        tests/test_agent_definitions.py. A dangling reference *into another
        directory* is outside all of their fields of view, and it is symmetric
        besides, so the round-trip test restores it byte-for-byte over the
        broken middle exactly as it does the casing leak.

        The underscore form is immune, and that is the mitigation: `_` is a word
        character, so `\\bqa-guard\\b` does not match inside `qa_guard_scope.py`.
        A red here is a request to rename the *referenced file* to the
        underscore spelling — not to reword the charter, which would only hide
        the reference from this scan while leaving the next author free to
        write it again.

        `_transform`/`_mappings` are the oracle rather than a re-derived
        `\\b...\\b` rule of our own, so this cannot drift from the script it
        guards: a fourth casing variant, or a new pair, is picked up here the
        moment it lands in the script.

        Latent, not hypothetical: today's charters reference
        `scripts/verify_commit_position.py`, `skills/code-navigation`,
        `memory/repo/`, `.sisyphus/plans/` and friends, none of which contains a
        mapped word — so this lands green and stays a guard rather than a
        finding. `test_apply_theme_leaves_files_outside_agents_untouched` below
        is what makes it necessary rather than belt-and-braces: it pins the
        blast radius shut, which is precisely why a rewritten reference can
        never be followed by a matching rename.
        """
        references = self._outside_agents_path_references()
        # Anti-vacuity: several such references exist today. If this list comes
        # back empty the extractor has regressed and the assertion below is
        # asserting nothing.
        self.assertTrue(
            references,
            "found no outside-`agents/` path references at all — the extractor has "
            "regressed and this test is asserting nothing",
        )

        offenders = []
        for where, token in references:
            for theme in apply_theme.THEMES:
                if apply_theme._transform(token, apply_theme._mappings(theme)) != token:
                    offenders.append(f"{where}: {token!r}")
                    break

        self.assertEqual(
            offenders, [],
            "these charters reference a path outside `agents/` that contains a themed "
            "name, so applying a theme rewrites the reference in the charter but cannot "
            "rename the file — the reference would dangle:\n  "
            + "\n  ".join(offenders)
            + "\nFix: rename the referenced file to use `_` instead of `-` (an "
              "underscore is a word character, so `\\bname\\b` no longer matches "
              "inside it), then update the reference.",
        )

    def test_apply_theme_leaves_files_outside_agents_untouched(self):
        """Nothing outside `agents/` is read, written, renamed or created.

        Pinned explicitly rather than left as an omission. The script's scope is
        a single `glob` deep inside `apply_theme`, and "we never noticed it
        touch anything else" is not a property — this makes the boundary an
        assertion, over a tree seeded with sibling files whose *names and bodies*
        both carry mapped words, so a widened scope has something to damage.

        This is also exactly why
        `test_no_charter_references_an_outside_path_the_theme_would_rewrite`
        above has to exist. Because the boundary holds, a charter reference into
        another directory gets the rewrite half of the operation and never the
        rename half. The boundary is correct; the dangling reference it can
        produce is what needs guarding.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            agents_dir = tmp / "agents"
            # agents/ only — never the repo. The script must not be pointed at a
            # tree that contains the real working copy.
            shutil.copytree(AGENTS_DIR, agents_dir)

            # Siblings that would be collateral damage if the scope ever
            # widened: hyphenated mapped words in the filenames, and mapped
            # words from *both* themes in the bodies, so the fixture bites
            # whichever direction this instance is themed in.
            body = (
                "# Sibling\n"
                "The builder writes code and the reviewer reads it; qa-guard gates it.\n"
                "Under the other theme those are archimedes, pyrrho and cato.\n"
                "See hooks/qa-guard-scope.py and skills/test-writer-helper/SKILL.md.\n"
            )
            siblings = [
                tmp / "README.md",
                tmp / "hooks" / "qa-guard-scope.py",
                tmp / "hooks" / "cato-scope.py",
                tmp / "skills" / "test-writer-helper" / "SKILL.md",
            ]
            for path in siblings:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8", newline="")

            start = apply_theme.detect_theme(agents_dir)
            self.assertIn(start, apply_theme.THEMES,
                          "could not detect a theme in the seeded agents/ copy")
            target = _other_theme(start)

            def outside_snapshot() -> dict[str, bytes]:
                return {
                    str(p.relative_to(tmp).as_posix()): p.read_bytes()
                    for p in sorted(tmp.rglob("*"))
                    if p.is_file() and not p.is_relative_to(agents_dir)
                }

            before = outside_snapshot()
            # Anti-vacuity: the sibling bodies must actually contain words this
            # run rewrites, or "unchanged" would be true for the boring reason.
            self.assertNotEqual(
                apply_theme._transform(body, apply_theme._mappings(target)), body,
                f"the sibling fixture contains no name the '{target}' theme rewrites — "
                "an unchanged snapshot would prove nothing",
            )

            with contextlib.redirect_stdout(io.StringIO()):
                rc = apply_theme.apply_theme(agents_dir, target)
            self.assertEqual(rc, 0)
            # The run must have done real work inside agents/, otherwise the
            # boundary held only because nothing happened at all.
            self.assertEqual(apply_theme.detect_theme(agents_dir), target)

            after = outside_snapshot()
            self.assertEqual(
                sorted(after), sorted(before),
                "applying a theme added, removed or renamed a file outside `agents/` — "
                "the script's scope is supposed to be `agents_dir.glob('*.md')`",
            )
            self.assertEqual(
                after, before,
                "applying a theme rewrote the contents of a file outside `agents/` — "
                "the script's scope is supposed to be `agents_dir.glob('*.md')`",
            )


if __name__ == "__main__":
    unittest.main()
