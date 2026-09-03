# tests/test_agent_definitions.py
"""Validate the crew's agent definitions.

Agent behaviour is prose and cannot be unit-tested. What *can* be pinned
mechanically is the frontmatter contract and the orchestrator's dispatch
wiring — which is precisely what drifts silently when these files are
edited by hand.
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

import apply_theme  # noqa: E402
from _crew_common import (  # noqa: E402
    BOUNDARY_PHRASE,
    BOUNDARY_SCOPE_TERMS,
    BOUNDED_WRITERS,
    CODE_WRITERS,
    NEGATION_MARKERS,
    SHAPE_EXCLUSION,
    TIERED_AGENTS,
    WRITE_ACCESS_AFFIRMATIONS,
    WRITE_ACCESS_DECLARERS,
    WRITE_ACCESS_PHRASE,
    WRITE_BOUNDED,
    exclusion,
    expected_roster,
    inclusion,
    themed_name,
)

AGENTS_DIR = ROOT / "agents"

# Models the crew is allowed to name. Anything else is a typo or an
# unreviewed bump.
ALLOWED_MODELS = {
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-haiku-4-5",
}

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# A dispatch declaration in the orchestrator charter. The value may name
# several agents separated by `|` (the builder cost tiers do), so it is parsed
# rather than substring-matched. Deliberately unanchored: the charter writes
# these both inline (`Agent(subagent_type: "explore", ...)`) and on their own
# line inside a multi-line block, and both forms are real dispatches.
DISPATCH_RE = re.compile(r'subagent_type: "([^"]*)"')

# End of the sentence carrying `BOUNDARY_PHRASE`: sentence-final punctuation,
# optionally through trailing markup (`**`, backticks, brackets), followed by
# whitespace or the end of the segment.
#
# The lookahead is the load-bearing part. A plain split on "." cuts the
# planner's boundary in half at `.sisyphus/` — the one path its boundary exists
# to name — and would hide the very term this lint reads the sentence for.
BOUNDARY_SENTENCE_END_RE = re.compile(r"""[.!?][*`"')\]]*(?=\s|$)""")

# Integers spelled the way a charter spells them, for the write-access lint.
#
# Charters are prose: they say "one of four agents", never "one of 4". The lint
# therefore needs the *word*, and the word has to be derived from
# `len(CODE_WRITERS)` rather than written out beside the assertion — a literal
# is exactly the thing that went stale in `agents/` in the first place.
#
# Runs to 17, the size of the whole roster: no more agents can hold write access
# than exist. A `len(CODE_WRITERS)` past the end is a roster that grew, and the
# `KeyError` it raises is the point — a `.get()` with a fallback would turn the
# one bookkeeping slip this test exists to catch into a check that quietly stops
# asserting anything.
NUMBER_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
}


# What the *remainder* of the boundary paragraph looks like when the sentence
# above was cut short: a lowercase continuation of the sentence that was being
# read (`" sections of ..."` after `[tool.*]`).
#
# Leading whitespace and markup are skipped before the first letter is judged,
# so a genuine second sentence opening in bold or a backticked path is not
# misread as a continuation. Only a lowercase *letter* means truncation —
# anything else (a digit, a dash, an em-dash) is left to pass, because this is
# a floor on obvious mid-sentence cuts, not a grammar checker.
BOUNDARY_CONTINUATION_RE = re.compile(r"""\A\s*[*`"'(\[]*[a-z]""")


def _agent_files(agents_dir=AGENTS_DIR):
    return sorted(agents_dir.glob("*.md"))


def _current_theme(agents_dir=AGENTS_DIR):
    """The theme on disk, normalised to a name `_crew_common` accepts.

    `detect_theme` returns None for a tree it cannot classify; treating that as
    'functional' preserves the behaviour these helpers had before they were
    routed through `_crew_common`, which rejects an unknown theme outright.
    """
    return "philosophers" if apply_theme.detect_theme(agents_dir) == "philosophers" else "functional"


def _themed(functional_name, agents_dir=AGENTS_DIR):
    """The on-disk name of `functional_name` under the theme currently applied.

    These tests ship to instances (``tests`` is in ``FRAMEWORK_PATHS``), and an
    instance may have run ``apply_theme.py``. Asserting the functional name
    there asserts this repo's own state rather than a property of the framework.

    Delegates to `_crew_common.themed_name` rather than indexing `PAIRS`: the
    tier variants (`builder-simple`, `builder-standard`) are not PAIRS keys, so
    a `dict(PAIRS)[name]` lookup KeyErrors on exactly the names the write-policy
    tests below map through here.
    """
    return themed_name(functional_name, _current_theme(agents_dir))


def _off_theme(functional_name, agents_dir=AGENTS_DIR):
    """The counterpart name that must *not* survive under the current theme.

    A half-applied rename leaves both names in the tree; asserting the absence
    of this one gives the wiring tests teeth in either direction.
    """
    themed = _themed(functional_name, agents_dir)
    if themed != functional_name:
        return functional_name
    return themed_name(functional_name, "philosophers")


def _tool_tokens(value):
    """Split a `tools:`/`disallowedTools:` frontmatter value into exact tokens.

    Substring matching is not safe here: ``"Edit" in "NotebookEdit"`` is True,
    so a substring check would read `disallowedTools: NotebookEdit` as a ban on
    Edit — the exact drift these tests exist to catch.
    """
    return {t.strip() for t in value.split(",") if t.strip()}


def _dispatch_targets(text):
    """Every `subagent_type:` value declared in a charter, split on `|`.

    Returned as a list of sets because one declaration may offer a choice of
    agents — the builder cost tiers share a single dispatch block. Comparing
    parsed sets rather than raw substrings keeps `"builder"` from matching
    inside `"builder-simple"`, the same token-vs-substring hazard `_tool_tokens`
    exists for.
    """
    return [
        {alternative.strip() for alternative in match.group(1).split("|")}
        for match in DISPATCH_RE.finditer(text)
    ]


def _boundary_paragraph(body):
    """The paragraph in `body` that declares the file boundary, or None.

    Runs from `BOUNDARY_PHRASE` to the end of the paragraph the phrase sits in.
    A blank line is the hard stop, because without one a boundary sentence
    reading "none" would borrow a scope term from whatever paragraph follows it
    and pass.

    Split out of `_boundary_sentence` so `_boundary_sentence_is_truncated` can
    ask what follows the parsed sentence *within the same paragraph* without
    re-deriving the segment. Duplicating the two `find` calls there would have
    worked, but the truncation check is only meaningful against the exact
    segment `_boundary_sentence` cut down — two copies that drift stop
    disagreeing loudly and start disagreeing silently.
    """
    start = body.find(BOUNDARY_PHRASE)
    if start == -1:
        return None
    end = body.find("\n\n", start)
    return body[start:] if end == -1 else body[start:end]


def _boundary_sentence(body):
    """The sentence in `body` that declares the file boundary, or None.

    Runs from `BOUNDARY_PHRASE` to the first sentence-final punctuation, and no
    further than the end of the paragraph the phrase sits in (see
    `_boundary_paragraph`). Charters wrap their prose, so the sentence routinely
    spans newlines.
    """
    segment = _boundary_paragraph(body)
    if segment is None:
        return None
    terminator = BOUNDARY_SENTENCE_END_RE.search(segment)
    return segment if terminator is None else segment[: terminator.end()]


def _write_access_sentence(body):
    """The sentence in `body` that declares who holds write access, or None.

    Shaped exactly like `_boundary_sentence`, for the same two reasons: charters
    wrap their prose, so the sentence routinely spans newlines and cannot be
    read a line at a time; and the paragraph break is a hard stop, so a
    declaration that names no number cannot borrow one from the paragraph below
    it and pass. `WRITE_ACCESS_PHRASE` ends in a colon, which
    `BOUNDARY_SENTENCE_END_RE` does not treat as sentence-final, so the search
    for the terminator can start at the phrase itself.
    """
    start = body.find(WRITE_ACCESS_PHRASE)
    if start == -1:
        return None
    end = body.find("\n\n", start)
    segment = body[start:] if end == -1 else body[start:end]
    terminator = BOUNDARY_SENTENCE_END_RE.search(segment)
    return segment if terminator is None else segment[: terminator.end()]


def _boundary_sentence_is_truncated(body):
    """Did `_boundary_sentence` cut this boundary off mid-sentence?

    `BOUNDARY_SENTENCE_END_RE` ends the sentence at any `.` followed by optional
    markup and whitespace. That is deliberate and load-bearing — it is what
    stops `.sisyphus/` and `.pre-commit-config.yaml` terminating a sentence — but
    it cannot tell a full stop from the dot inside a *spaced* dotted token. A
    boundary reading ``never edit the `[tool.*]` sections of `pyproject.toml`,
    CI workflows, or pre-commit config.`` parses down to ``never edit the
    `[tool.*]``` and the rest of the declared scope vanishes, while
    `test_bounded_writers_declare_their_boundary` stays **green**, because the
    required scope term happened to fall before the cut. A silently shortened
    boundary is worse than a missing one: the lint reports the agent as
    compliant on a sentence that no longer says what it is bounded to.

    The discriminator is what *follows* the cut, and two more obvious ones were
    tried first and rejected:

    * **Parsed length vs. paragraph length** — false-positives on `planner`,
      whose boundary paragraph legitimately carries a second sentence
      ("Everything else in the tree is read-only to you."). Measured 75 of 124
      characters, with nothing wrong with it.
    * **Unclosed markup in the parsed sentence** — does not bite on the case
      being closed. In ``` `[tool.*]` ``` the terminator's own trailing class
      ``[*`"')\\]]*`` consumes the `.`, the `*`, the `]` *and* the closing
      backtick, so the truncated sentence comes out with balanced backticks and
      balanced brackets. The check stays green on exactly the input it was
      reached for.

    What is left is the remainder: after a real sentence end it is empty, or it
    opens a new sentence; after a truncation it continues the old one in
    lowercase. See BOUNDARY_CONTINUATION_RE.

    Returns False for a body carrying no boundary phrase at all — absence is
    `test_bounded_writers_declare_their_boundary`'s failure to report, not this
    one's.
    """
    segment = _boundary_paragraph(body)
    if segment is None:
        return False
    remainder = segment[len(_boundary_sentence(body)):]
    return BOUNDARY_CONTINUATION_RE.match(remainder) is not None


def _may_not_edit(fields):
    """Is this agent barred from editing production code by its frontmatter?

    Either it names Edit in `disallowedTools`, or it restricts itself with a
    `tools` allowlist that does not include Edit (as `vision` does).

    `Edit` alone decides this, in both branches. An earlier form read a `tools`
    allowlist as read-only only when it named neither Edit *nor* Write, so
    `tools: Read, Write` — an agent that demonstrably cannot Edit — came back
    "may edit". That was inert while no charter had the shape, but
    `test_only_declared_writers_can_edit` now asserts this predicate is False
    for every declared writer, which turns the wrong answer into a Write-only
    agent passing as one licensed to edit production code.
    """
    disallowed = _tool_tokens(fields.get("disallowedTools", ""))
    tools = _tool_tokens(fields.get("tools", ""))
    return "Edit" in disallowed or (bool(tools) and "Edit" not in tools)


class TestFrontmatterMixin:
    def _frontmatter(self, path):
        text = path.read_text(encoding="utf-8")
        match = FRONTMATTER_RE.match(text)
        self.assertTrue(match, f"{path.name}: missing YAML frontmatter block")
        fields = {}
        for line in match.group(1).splitlines():
            if ":" in line and not line.startswith((" ", "\t", "#")):
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip()
        return fields


class TestRoster(TestFrontmatterMixin, unittest.TestCase):
    def test_roster_matches_expected(self):
        theme = apply_theme.detect_theme(AGENTS_DIR)
        self.assertIsNotNone(theme, "could not detect the crew's theme in agents/")
        found = {path.stem for path in _agent_files()}
        self.assertEqual(found, expected_roster(theme))

    def test_roster_expectation_follows_the_philosophers_theme(self):
        """Applying the shipped theme must not break the roster assertion."""
        with tempfile.TemporaryDirectory() as d:
            themed_dir = Path(d) / "agents"
            shutil.copytree(AGENTS_DIR, themed_dir)
            with contextlib.redirect_stdout(io.StringIO()):
                rc = apply_theme.apply_theme(themed_dir, "philosophers")
            self.assertEqual(rc, 0)
            self.assertEqual(apply_theme.detect_theme(themed_dir), "philosophers")
            found = {path.stem for path in _agent_files(themed_dir)}
            self.assertEqual(found, expected_roster("philosophers"))


class TestAgentFrontmatter(TestFrontmatterMixin, unittest.TestCase):
    def test_name_matches_filename(self):
        paths = _agent_files()
        self.assertTrue(paths, "no agent files found — nothing asserted")
        for path in paths:
            with self.subTest(agent=path.stem):
                self.assertEqual(self._frontmatter(path).get("name"), path.stem)

    def test_model_is_allowed(self):
        paths = _agent_files()
        self.assertTrue(paths, "no agent files found — nothing asserted")
        for path in paths:
            with self.subTest(agent=path.stem):
                model = self._frontmatter(path).get("model")
                self.assertIn(model, ALLOWED_MODELS, f"{path.name}: unexpected model {model!r}")

    def test_description_is_substantive(self):
        paths = _agent_files()
        self.assertTrue(paths, "no agent files found — nothing asserted")
        for path in paths:
            with self.subTest(agent=path.stem):
                description = self._frontmatter(path).get("description", "")
                self.assertGreaterEqual(
                    len(description), 40, f"{path.name}: description too thin to route on"
                )


class TestEditPermissions(TestFrontmatterMixin, unittest.TestCase):
    def test_only_declared_writers_can_edit(self):
        """The declared writers may Edit production code; nobody else may.

        Note this is about Edit, not Write. orchestrator, planner and reviewer
        deliberately retain Write so they can produce plans and audit reports —
        but none of them may Edit. vision restricts itself with a read-only
        ``tools`` allowlist instead of ``disallowedTools``.

        Both directions are asserted with the same predicate, so an agent
        cannot satisfy this test by being ambiguous: it is either in the
        declared set and demonstrably able to Edit, or outside it and
        demonstrably barred.

        The writers are renamed on a themed instance (``builder`` becomes
        ``archimedes``, and the tiers follow it), so every declared name is
        resolved through the theme actually on disk.
        """
        writers = {_themed(name) for name in CODE_WRITERS | BOUNDED_WRITERS}
        found = {path.stem for path in _agent_files()}
        self.assertEqual(
            writers - found, set(),
            "declared writers with no charter on disk — this test asserts "
            "nothing about them, so either the file or the declaration is wrong",
        )
        for path in _agent_files():
            with self.subTest(agent=path.stem):
                fields = self._frontmatter(path)
                if path.stem in writers:
                    self.assertFalse(
                        _may_not_edit(fields),
                        f"{path.stem}: declared a writer but its frontmatter bars Edit",
                    )
                    disallowed = _tool_tokens(fields.get("disallowedTools", ""))
                    self.assertNotIn(
                        "Write", disallowed, f"{path.stem} must retain Write access"
                    )
                else:
                    self.assertTrue(
                        _may_not_edit(fields),
                        f"{path.stem}: must not be able to Edit production code",
                    )

    def test_the_writer_set_is_pinned(self):
        """Growing the set of agents that may write code costs a deliberate edit.

        A red here does **not** mean "add the new name to the count". It means
        a seventh agent has been given write access to production code, and
        that is an architectural decision someone has to justify in the commit
        message — the whole point of this assertion is to force that
        conversation, which a self-updating registration set would silently
        skip.

        Six is not a magic number; it is the number of writers the crew was
        last deliberately agreed to have.
        """
        self.assertEqual(
            len(CODE_WRITERS | BOUNDED_WRITERS), 6,
            "adding a writer is an architectural decision — say why in the commit message",
        )

    def test_the_writer_partition_is_pinned(self):
        """*Which* writers are bounded, not just how many writers there are.

        The count above pins the union and nothing else, so moving a name across
        the boundary keeps it green: drop `test-writer` from BOUNDED_WRITERS and
        add it to CODE_WRITERS and the union is still six, while an agent whose
        charter says it may touch tests only has just been granted unbounded
        write access to production code. That is the more dangerous of the two
        edits and was the one nothing was watching.

        The names are functional, not themed. BOUNDED_WRITERS is a policy
        constant keyed on the functional roster — `_themed` is applied at the
        point files are looked up (see `test_bounded_writers_declare_their_
        boundary`), never to the constant itself — so a literal is correct here
        under either theme.

        WRITE_BOUNDED is pinned here for the same reason and not counted with
        the others: those two hold `Write` but not `Edit`, so they are outside
        the writer union above entirely. What pinning buys is the doc-lint —
        `test_bounded_writers_declare_their_boundary` checks exactly the names
        in these sets, so quietly dropping one stops the check rather than
        failing it.

        WRITE_ACCESS_DECLARERS is pinned on that same argument, and it is the
        set where the argument bites hardest.
        `test_code_writers_declare_how_many_hold_write_access` iterates it, and
        its two structural assertions — a crew of more than one writer, a domain
        inside CODE_WRITERS — are both satisfied by the empty set. Emptying it
        therefore does not fail that lint; it turns it into a zero-iteration
        loop that reports green while no charter is read at all. Exact equality
        here is what makes that edit visible.

        Same contract as the count: a red is not an invitation to update the
        literal. It means someone changed what an agent is permitted to touch.
        """
        self.assertEqual(
            WRITE_BOUNDED, {"planner", "reviewer"},
            "an agent gained or lost a Write-scoped boundary — its charter sentence "
            "is the only thing pinning what it may write, and this set is what "
            "decides whether that sentence is checked at all",
        )
        self.assertEqual(
            BOUNDED_WRITERS, {"test-writer", "doc-writer", "qa-guard"},
            "a writer moved across the bounded/unbounded boundary — the union count "
            "cannot see this, so say why in the commit message",
        )
        self.assertEqual(
            CODE_WRITERS, {"builder", "builder-standard", "builder-simple"},
            "an agent gained or lost unbounded write access to production code",
        )
        self.assertEqual(
            WRITE_ACCESS_DECLARERS, {"builder", "builder-standard", "builder-simple"},
            "an implementer gained or lost its write-access declaration — emptying "
            "this set does not fail the declaration lint, it silences it",
        )
        self.assertEqual(
            CODE_WRITERS & BOUNDED_WRITERS, set(),
            "a writer cannot be both bounded and unbounded — the union count hides the overlap",
        )

    def test_bounded_writers_declare_their_boundary(self):
        """Each bounded agent's charter body states its file boundary, and says what it is.

        This is a **doc-lint, not enforcement**. Agent frontmatter accepts tool
        *names* only — `tools`/`disallowedTools` have no path-scoped form, so
        `Edit(tests/**)` cannot be expressed here at all. Nothing stops a
        bounded writer from editing a production file; the only thing standing
        between it and one is the sentence this test pins.

        The body, not `description:`. `description:` is routing metadata the
        orchestrator reads to pick an agent; asserting there proves only that
        the blurb advertises a boundary, not that the agent is ever told about
        it. The spec puts enforcement in the prompt
        (docs/specs/2026-08-24-team-workflow-patterns.md:66).

        **Both kinds of bounded agent.** BOUNDED_WRITERS may Edit within a
        boundary (tests only, docs only); WRITE_BOUNDED cannot Edit at all but
        keeps `Write` for one purpose — `planner` for `.sisyphus/` markdown,
        `reviewer` for its own report file. The two boundaries are equally
        unenforceable and equally advertised in README, so an Edit-centric lint
        covering only the first set left the other two on prose alone.

        **The phrase is necessary, not sufficient.** A body reading
        `Hard file boundary: none — edit whatever you like.` carries the phrase
        and revokes the boundary, which is what a bare prefix match certified as
        compliant. So the sentence carrying the phrase must also name this
        agent's scope (BOUNDARY_SCOPE_TERMS).

        How the terms combine is not decided here: it is a property of the
        entry's *shape*, and `BoundaryScope.satisfied_by` derives it. An
        inclusion needs any one of its terms, an exclusion every one of them —
        see the note above BOUNDARY_SCOPE_TERMS for why the two cannot share a
        mode.
        """
        bounded = BOUNDED_WRITERS | WRITE_BOUNDED
        self.assertTrue(bounded, "no bounded agents — nothing asserted")
        self.assertEqual(
            set(BOUNDARY_SCOPE_TERMS), bounded,
            "a bounded agent with no declared scope term is checked for the phrase "
            "and nothing else; a term with no bounded agent pins nothing at all",
        )
        for name in sorted(bounded):
            path = AGENTS_DIR / f"{_themed(name)}.md"
            with self.subTest(agent=path.stem):
                text = path.read_text(encoding="utf-8")
                body = FRONTMATTER_RE.sub("", text, count=1)
                sentence = _boundary_sentence(body)
                self.assertIsNotNone(
                    sentence,
                    f"{path.stem}: boundary declared only in routing metadata",
                )
                scope = BOUNDARY_SCOPE_TERMS[name]
                # Multi-word terms ("may never edit") are why this exists: the
                # charters wrap their prose, so a reword that pushes the phrase
                # across a line break would fail the raw substring match with
                # the misleading "names no scope". Collapsing whitespace cannot
                # remove a substring that contains none, so the single-word
                # terms are unaffected. Normalised here only — `_boundary_
                # sentence`'s raw return is asserted on directly below.
                sentence = " ".join(sentence.split())
                self.assertTrue(
                    scope.satisfied_by(sentence),
                    f"{path.stem}: the boundary sentence does not declare its scope "
                    f"— this {scope.shape}-shaped boundary needs {scope.requirement} "
                    f"{list(scope.terms)} in {sentence!r}",
                )

    def test_code_writers_declare_how_many_hold_write_access(self):
        """Each implementer's charter states the true size of CODE_WRITERS.

        A doc-lint of the same kind as the boundary one above, and for the same
        reason: frontmatter cannot express "and three others may do this too",
        so the prose is the only place the fact lives.

        The drift it catches is a specific one. Three charters opened with *you
        are the only agent in this crew with write access to production code*
        while CODE_WRITERS held four names — false since the commit that added
        the tiers to that set and did not open `agents/`. Nothing was reading
        both, so the claim rotted in place and each of the four implementers was
        told it was alone. Reading the number out of `len(CODE_WRITERS)` and
        looking for its spelled-out form is what couples the two again.

        **The phrase is necessary, not sufficient** — the same lesson as the
        boundary lint above, learned the same way. A body reading
        `Write access to production code: none — the four other agents hold it,
        not you.` carries the phrase *and* the spelled count, and tells an
        implementer the reverse of the fact. So the sentence must also claim the
        access for its reader (WRITE_ACCESS_AFFIRMATIONS) before its count is
        read.

        **Scope, honestly.** This aims at an author who edits CODE_WRITERS and
        forgets `agents/` — exactly how the bug arose. What it pins is one
        sentence, read for two things: that it claims write access for the agent
        reading it, and that the count it names is the true one. Three gaps are
        left open, deliberately.

        *Outside the sentence:* an author who writes it correctly and then
        contradicts it two paragraphs later passes. Prose consistency at large is
        not mechanically checkable.

        *Inside the sentence:* the affirmation is an allowlist of phrasings, so a
        reversal built out of words not on that list, or a hedge that satisfies a
        listed phrase and then qualifies it away, still passes. The list is
        narrow on purpose — the charters already agree on one wording, and a
        wider list is a wider hole.

        *Around the sentence:* `_write_access_sentence` finds the phrase by
        substring and is markdown-blind. The declaration quoted inside a fenced
        code block — an example, a snippet of another agent's charter — satisfies
        this lint while the prose above it says anything at all. No charter has
        that shape today; the fix is a markdown-aware scan, which is a larger
        change than this lint is worth until one does.

        The count word must match whole (`\\b`), or a crew of four would be
        satisfied by a charter claiming fourteen.

        The domain is WRITE_ACCESS_DECLARERS, not CODE_WRITERS — `qa-guard`
        holds write access and deliberately declares none, for the reasons
        `_crew_common` gives at that constant. What is asserted here is only that
        the domain cannot drift *outside* CODE_WRITERS, which would have a
        charter licensing an agent that may not write at all. That it cannot
        drift to empty — which would make this loop run zero times and pass — is
        pinned by exact equality in `test_the_writer_partition_is_pinned`.
        """
        self.assertGreater(
            len(CODE_WRITERS), 1,
            "a single-writer crew makes 'one of one' vacuously true — if the crew "
            "really did shrink to one, the exclusivity claim goes back in the "
            "charters and is argued again, not re-enabled by this lint going quiet",
        )
        self.assertEqual(
            WRITE_ACCESS_DECLARERS - CODE_WRITERS, set(),
            "an agent must declare its write access only if it has any — this "
            "declaration licenses production edits and cannot name a non-writer",
        )
        expected = NUMBER_WORDS[len(CODE_WRITERS)]
        for name in sorted(WRITE_ACCESS_DECLARERS):
            path = AGENTS_DIR / f"{_themed(name)}.md"
            with self.subTest(agent=path.stem):
                text = path.read_text(encoding="utf-8")
                body = FRONTMATTER_RE.sub("", text, count=1)
                sentence = _write_access_sentence(body)
                self.assertIsNotNone(
                    sentence,
                    f"{path.name}: no write-access declaration — expected a sentence "
                    f"opening {WRITE_ACCESS_PHRASE!r} in the charter body",
                )
                self.assertTrue(
                    any(
                        term in sentence.lower()
                        for term in WRITE_ACCESS_AFFIRMATIONS
                    ),
                    f"{path.name}: the declaration carries the phrase but claims no "
                    f"access for this agent — expected one of "
                    f"{list(WRITE_ACCESS_AFFIRMATIONS)} in {sentence!r}",
                )
                self.assertRegex(
                    sentence.lower(), rf"\b{expected}\b",
                    f"{path.name}: declares a count that is not {expected!r} "
                    f"({len(CODE_WRITERS)} agents may write production code) in "
                    f"{sentence!r}",
                )

    def test_a_revoked_boundary_does_not_satisfy_the_lint(self):
        """Regression: `Hard file boundary: none` carries the phrase and means the opposite.

        The check the auditor broke was a prefix match on the whole body, so
        this sentence passed it. Reading the sentence is what makes the lint
        bite: there is nowhere in it for a scope term to hide.
        """
        revoked = "**Hard file boundary: none — edit whatever you like.**\n"
        self.assertNotIn("test", _boundary_sentence(revoked).lower())
        declared = (
            "**Hard file boundary: you may write only inside the project's\n"
            "test directories.**\n"
        )
        self.assertIn("test", _boundary_sentence(declared).lower())

    def test_an_exclusion_boundary_needs_a_negation_bearing_scope_term(self):
        """Regression: a positive term cannot tell an exclusion from its inverse.

        `test-writer` and `doc-writer` name the region they are confined *to*,
        so a term naming that region ("test", "docs") is enough — the sentence
        cannot carry it and mean the opposite. `qa-guard` is bounded the other
        way round: it names the region it may not touch. There the scope word
        appears in the revocation too, so a term like "check" would certify
        `Hard file boundary: you may edit the files that define the checks
        freely.` — the same failure `test_a_revoked_boundary_does_not_satisfy_
        the_lint` covers, in a shape that test cannot see, because substring
        presence has no view of polarity. The negation has to be inside the
        pinned term.

        Pure literals, like the sibling above: reading `agents/*.md` here would
        only duplicate `test_bounded_writers_declare_their_boundary`. What is
        asserted is a property of the term, not of any charter on disk.

        **Shape, then membership — and the shape first.** This used to pin the
        tuple whole (`assertEqual(..., (term,))`), because the lint matched
        any-of: one positive term sitting *alongside* the negation-bearing one
        was enough to certify the inverted sentence, so membership alone would
        have stayed green while the hole reopened. Exclusion entries now match
        all-of, which inverts that — a second term can only tighten the check —
        so membership is safe *given the shape*. The shape is therefore asserted
        first and is the load-bearing half: flipping this entry to
        `inclusion("may never edit", "check")` restores any-of and the old hole
        with it, and no assertion about the terms would notice.

        **Generic over the constant.** The negation requirement is asserted for
        every exclusion-shaped entry, not for `qa-guard` by name. A second
        exclusion agent inherits the check instead of arriving unpinned — which
        was the other way the old per-agent pin could be walked around.
        """
        term = "may never edit"
        qa_guard = BOUNDARY_SCOPE_TERMS["qa-guard"]
        self.assertEqual(
            qa_guard.shape, SHAPE_EXCLUSION,
            "qa-guard names the region it may not touch — as an inclusion its "
            "terms would match any-of, and one positive term beside the "
            "negation would certify the inverted sentence",
        )
        self.assertIn(
            term, qa_guard.terms,
            "all-of over positive terms alone still has no view of polarity — "
            "the negation has to be inside a pinned term",
        )
        for name, scope in sorted(BOUNDARY_SCOPE_TERMS.items()):
            if scope.shape != SHAPE_EXCLUSION:
                continue
            with self.subTest(agent=name):
                self.assertTrue(
                    any(
                        marker in scope_term.lower().split()
                        for scope_term in scope.terms
                        for marker in NEGATION_MARKERS
                    ),
                    f"{name}: an exclusion boundary with no negation-bearing term "
                    f"({list(scope.terms)}) — every term matches the revocation of "
                    f"the boundary as readily as the boundary itself",
                )
        inverted = (
            "**Hard file boundary: you may edit the files that define the\n"
            "checks freely.**\n"
        )
        self.assertNotIn(term, _boundary_sentence(inverted).lower())
        declared = (
            "**Hard file boundary: you may never edit the files that define the\n"
            "checks — CI workflows, pre-commit config, linter and type-checker\n"
            "settings, or build scripts.**\n"
        )
        self.assertIn(term, _boundary_sentence(declared).lower())

    def test_widening_an_exclusion_entry_tightens_it_where_inclusion_loosened(self):
        """The invariant the shape buys: an added exclusion term can only reject more.

        What regressed before: `BOUNDARY_SCOPE_TERMS` held bare tuples matched
        with `any(...)`, so widening `qa-guard` to `("may never edit", "check")`
        — a reasonable-looking edit, "name the region too" — made `Hard file
        boundary: you may edit the files that define the checks freely.` pass on
        "check" alone. Adding a term *revoked* the check, silently, with the
        suite green.

        What is pinned here is the **shape**, not the term list. The sibling
        above asserts `qa-guard` is exclusion-shaped today; this asserts what
        being exclusion-shaped is worth — that the widening which used to open
        the hole no longer can. The same two terms under `inclusion(...)` are
        asserted to still accept the inverted sentence, so the test fails if the
        two shapes ever collapse onto one mode and stops being a tautology.

        Scopes are built locally. Mutating the real constant would leave the
        rest of the suite asserting against whatever this test left behind.
        """
        inverted = " ".join(
            _boundary_sentence(
                "**Hard file boundary: you may edit the files that define the\n"
                "checks freely.**\n"
            ).split()
        )
        declared = " ".join(
            _boundary_sentence(
                "**Hard file boundary: you may never edit the files that define\n"
                "the checks — CI workflows, pre-commit config, linter and\n"
                "type-checker settings, or build scripts.**\n"
            ).split()
        )
        widened = exclusion("may never edit", "check")
        self.assertFalse(
            widened.satisfied_by(inverted),
            "widening an exclusion entry loosened it — the added term certified "
            "the revocation the pinned negation exists to reject",
        )
        self.assertTrue(
            widened.satisfied_by(declared),
            "all-of rejected a genuine boundary sentence carrying both terms — "
            "the mode has to tighten against the inverse, not against everything",
        )
        self.assertTrue(
            inclusion("may never edit", "check").satisfied_by(inverted),
            "the same terms under any-of must still accept the inverted sentence "
            "— if they do not, the two shapes share a mode and the assertion "
            "above proves nothing",
        )

    def test_the_boundary_sentence_ends_at_the_sentence_not_the_first_dot(self):
        """`.sisyphus/` is a path, not a full stop — the planner's scope sits past it.

        And a boundary sentence must not reach into the next paragraph for a
        scope term it does not contain itself.
        """
        planner = "**Hard file boundary: you may write only markdown under `.sisyphus/`.**\n"
        self.assertIn(".sisyphus", _boundary_sentence(planner))

        borrowed = "**Hard file boundary: none.**\n\nYou write only `.sisyphus/` markdown.\n"
        self.assertNotIn(".sisyphus", _boundary_sentence(borrowed))

    def test_a_dotted_token_does_not_silently_shorten_the_boundary_sentence(self):
        """Regression: a `.` inside a token ends the parse, and the lint stays green.

        The sibling above pins that `.sisyphus/` does *not* end the sentence —
        the terminator's lookahead requires whitespace after the dot. This pins
        the other half of that rule: a dotted token that *is* followed by a
        space ends the sentence anyway, and everything the charter declared
        after it is dropped. ``[tool.*]``, `.yaml`, `.github/workflows/` all do
        it.

        Nothing existing catches this, because it is silent by construction.
        `test_bounded_writers_declare_their_boundary` asks only whether a scope
        term appears *somewhere* in the parsed sentence, so a truncation that
        happens to fall after the term certifies an agent as bounded on a
        sentence that no longer names half its scope. This was hit by hand while
        bounding `qa-guard`'s write scope and dodged by writing a dot-free
        charter — which is a habit, not a check.

        Pure literals, like the two regressions above: what is asserted is a
        property of the parse, not of any charter on disk. The charters
        themselves are covered by the sibling loop, which is what would go red
        if someone reintroduced the shape.

        The second half is the one that matters for false positives. `planner`'s
        boundary paragraph genuinely holds two sentences, so any "the parse is
        shorter than the paragraph" rule flags a charter with nothing wrong with
        it. `_boundary_sentence_is_truncated` reads what follows the cut
        instead, and a capitalised new sentence is not a continuation.
        """
        truncated = (
            "**Hard file boundary: never edit the `[tool.*]` sections of\n"
            "`pyproject.toml`, CI workflows, or pre-commit config.**\n"
        )
        # The trap in full: the sentence is cut, and the existing lint's scope
        # term survives inside the stump, so that check cannot see the loss.
        self.assertNotIn("pre-commit", _boundary_sentence(truncated))
        self.assertIn("never edit", _boundary_sentence(truncated).lower())
        self.assertTrue(_boundary_sentence_is_truncated(truncated))

        two_sentences = (
            "**Hard file boundary: you may write only markdown files under\n"
            "`.sisyphus/`.**\n"
            "Everything else in the tree is read-only to you.\n"
        )
        self.assertFalse(_boundary_sentence_is_truncated(two_sentences))

        whole = "**Hard file boundary: you may write only your own report file.**\n"
        self.assertFalse(_boundary_sentence_is_truncated(whole))

    def test_no_bounded_charter_has_a_truncated_boundary_sentence(self):
        """No charter on disk declares a boundary the parse quietly shortens.

        The companion to `test_bounded_writers_declare_their_boundary`, over the
        same files and the same set. That test reads the boundary sentence and
        asks whether it names a scope; this one asks whether the sentence it
        read is the whole sentence the author wrote. Both have to hold for the
        doc-lint to mean anything: a scope term inside a stump proves only that
        the term landed early.

        Today every one of the five is clean — four parse to their full
        paragraph, `planner` to the first of its two sentences. This exists for
        the charter nobody has written yet, where a reworded boundary names
        `pyproject.toml` or `.github/workflows/` and loses everything after it.
        """
        bounded = BOUNDED_WRITERS | WRITE_BOUNDED
        self.assertTrue(bounded, "no bounded agents — nothing asserted")
        for name in sorted(bounded):
            path = AGENTS_DIR / f"{_themed(name)}.md"
            with self.subTest(agent=path.stem):
                body = FRONTMATTER_RE.sub("", path.read_text(encoding="utf-8"), count=1)
                sentence = _boundary_sentence(body)
                self.assertIsNotNone(
                    sentence,
                    f"{path.stem}: boundary declared only in routing metadata",
                )
                self.assertFalse(
                    _boundary_sentence_is_truncated(body),
                    f"{path.stem}: the boundary sentence is cut off mid-sentence — a "
                    f"dotted token ends the parse early, so the scope declared after it "
                    f"is invisible to the lint. Parsed only {sentence!r}, dropping "
                    f"{_boundary_paragraph(body)[len(sentence):]!r}",
                )

    def test_no_boundary_phrase_reads_as_no_boundary(self):
        """A body without the phrase yields None, not a sentence to search."""
        self.assertIsNone(_boundary_sentence("You may write only tests.\n"))

    def test_a_revoked_write_access_declaration_does_not_satisfy_the_lint(self):
        """Regression: the declaration can carry the phrase, the count, and the opposite meaning.

        The sibling hazard to `Hard file boundary: none`, reproduced by an
        auditor against the count check as first shipped. Both halves of that
        check pass here — the phrase anchors the sentence, and `four` is the
        spelled `len(CODE_WRITERS)` the lint looks for — while the sentence
        hands an implementer the reverse of the fact it exists to state.
        WRITE_ACCESS_AFFIRMATIONS is what bites, and this test asserts the split:
        the count is not evidence, the second-person claim is.

        Asserted against literal strings rather than the real charters, like the
        boundary regressions above, so the hazard stays documented here and a
        charter reword cannot quietly retire it.
        """
        revoked = _write_access_sentence(
            "Write access to production code: none — the four other agents\n"
            "hold it, not you.\n"
        )
        self.assertRegex(
            revoked.lower(), r"\bfour\b",
            "the reversal keeps the count — if it did not, this would prove nothing "
            "about the affirmation check",
        )
        self.assertFalse(
            any(term in revoked.lower() for term in WRITE_ACCESS_AFFIRMATIONS),
            f"a revoked declaration claims access for its reader: {revoked!r}",
        )

        declared = _write_access_sentence(
            "Write access to production code: you are one of four agents that\n"
            "hold it.\n"
        )
        self.assertTrue(
            any(term in declared.lower() for term in WRITE_ACCESS_AFFIRMATIONS),
            f"the settled charter wording claims no access: {declared!r}",
        )

    def test_the_write_access_sentence_spans_a_line_wrap(self):
        """Charters wrap their prose, so the declaration is routinely two lines long.

        Read a line at a time this sentence is truncated at `that`, losing both
        the count and the claim. It must also stop at its own full stop rather
        than swallowing the sentence after it, or every word in the paragraph
        becomes evidence.
        """
        wrapped = (
            "Write access to production code: you are one of four agents that\n"
            "hold it. Most of this crew reads, judges, and advises; you build.\n"
        )
        self.assertEqual(
            _write_access_sentence(wrapped),
            "Write access to production code: you are one of four agents that\n"
            "hold it.",
        )

    def test_the_write_access_sentence_stops_at_the_paragraph_break(self):
        """A declaration naming no count must not borrow one from the paragraph below.

        Not hypothetical. `agents/builder-standard.md` follows its declaration
        with a paragraph reading "moderate complexity, 50–200 lines, one or two
        design decisions" — `one` and `two` are both NUMBER_WORDS entries the
        count assertion reads for. `len(CODE_WRITERS)` is 4 today so nothing
        collides; a crew that shrank to two, with no hard stop here, would have
        this lint certify a charter that states no count at all.
        """
        borrowed = (
            "Write access to production code: none.\n"
            "\n"
            "You are the `standard` tier: moderate complexity, 50–200 lines, one\n"
            "or two design decisions.\n"
        )
        sentence = _write_access_sentence(borrowed)
        self.assertEqual(sentence, "Write access to production code: none.")
        self.assertNotRegex(sentence.lower(), r"\btwo\b")

    def test_no_write_access_phrase_reads_as_no_declaration(self):
        """A body without the phrase yields None, not a sentence to search."""
        self.assertIsNone(
            _write_access_sentence("You may edit production code.\n")
        )

    def test_notebook_edit_alone_does_not_bar_editing(self):
        """Regression: `Edit` in `NotebookEdit` is True — tokens, not substrings."""
        self.assertFalse(_may_not_edit({"disallowedTools": "NotebookEdit"}))
        self.assertTrue(_may_not_edit({"disallowedTools": "Edit, NotebookEdit"}))
        self.assertTrue(_may_not_edit({"disallowedTools": "Write, Edit"}))

    def test_read_only_allowlist_containing_notebook_edit_is_accepted(self):
        """Regression: a `tools` allowlist must not trip on `NotebookEdit`.

        The `Read, Write` expectation was flipped deliberately. It asserted
        False ("may edit") because the predicate counted Write as evidence of
        Edit capability, which does not follow: an allowlist naming Write and
        not Edit grants Write and not Edit. `_may_not_edit` now tests Edit
        alone, so the answer is True.

        Not a cosmetic flip. `test_only_declared_writers_can_edit` asserts this
        predicate is False for every declared writer, so under the old answer an
        agent allowlisted `Read, Write` would have satisfied the positive
        assertion for a code writer without being able to edit anything.
        """
        self.assertTrue(_may_not_edit({"tools": "Read, NotebookEdit"}))
        self.assertFalse(_may_not_edit({"tools": "Read, Edit"}))
        self.assertTrue(_may_not_edit({"tools": "Read, Write"}))
        self.assertFalse(_may_not_edit({"tools": "Read, Write, Edit"}))


class TestOrchestratorWiring(unittest.TestCase):
    def _text(self):
        return (AGENTS_DIR / "orchestrator.md").read_text(encoding="utf-8")

    def test_orchestrator_dispatches_a_builder_tier_not_general_purpose(self):
        """Implementation work is dispatched to a builder tier, never elsewhere.

        The template used to name a single `builder`; it now offers the three
        cost tiers on one alternation line, so a literal grep for
        ``subagent_type: "builder"`` no longer sees it. Parsing the declared
        values instead of substring-matching keeps the original point — no
        implementation work goes to `general-purpose` — and additionally pins
        that a tier cannot silently vanish from the menu, which would make the
        planner's `simple`/`standard` classification undispatchable.
        """
        targets = _dispatch_targets(self._text())
        tiers = {_themed(name) for name in ("builder",) + TIERED_AGENTS}
        self.assertIn(
            tiers, targets,
            f"no dispatch block offers exactly the builder tiers {sorted(tiers)}",
        )
        off_theme = _off_theme("builder")
        for value in targets:
            self.assertNotIn(
                "general-purpose", value, "implementation work must not go to general-purpose"
            )
            self.assertNotIn(
                off_theme, value, f"{off_theme}: a half-applied theme left both names in the tree"
            )

    def test_orchestrator_names_builder_as_the_code_writer(self):
        """The capability line delegates code to the builder — and to all its tiers.

        The first two assertions pin the agent and catch a half-applied theme.
        They do not pin the tiers, and that gap was live: the line used to read
        ``(delegate to `builder`)`` while three agents could take the work, so
        the correction that added the tiers to it changed nothing this test
        could see and could revert the same way. Reading the tiers off the same
        line is what makes the correction load-bearing.

        The line names the tiers by suffix (`-simple`, `-standard`) rather than
        by full name, so the suffix is derived — `archimedes-simple` minus
        `archimedes` — instead of written out. A literal `` `-simple` `` would
        happen to be right under both themes today, but only because the theme
        renames the stem; deriving it keeps the assertion true of the tier
        rather than of the punctuation.
        """
        text = self._text()
        builder = _themed("builder")
        self.assertIn(f"delegate to `{builder}`", text)
        self.assertNotIn(f"delegate to `{_off_theme('builder')}`", text)
        line = next(
            (line for line in text.splitlines() if f"delegate to `{builder}`" in line), None
        )
        for tier in TIERED_AGENTS:
            suffix = _themed(tier).removeprefix(builder)
            self.assertIn(
                f"`{suffix}`", line,
                f"the capability line delegates code to `{builder}` without naming its "
                f"`{suffix}` tier — the planner classifies work into tiers the "
                f"orchestrator then has no line to dispatch on",
            )

    def test_orchestrator_has_delivery_boundary_check(self):
        text = self._text()
        self.assertIn("### Delivery Boundary Check", text)
        self.assertIn("does the result need to re-enter this conversation?", text)

    def test_orchestrator_parallelism_is_bounded(self):
        text = self._text()
        self.assertIn("Maximize parallelism within a boundary", text)
        self.assertNotIn("2. **Maximize parallelism** — dispatch", text)

    def test_orchestrator_defers_verification_to_the_agent_contract(self):
        """The dispatch template must not license skipping verification.

        builder.md makes verification mandatory ("you may not report COMPLETE on
        work you have not executed"), so a Constraints line saying "run tests if
        they exist" would compete with the agent's own system prompt.
        """
        text = self._text()
        # The bulleted Constraints line; the orchestrator's own numbered
        # "run relevant tests" step is a different instruction and stays.
        self.assertNotIn("- Run relevant tests if they exist", text)
        self.assertIn("Verify per your contract", text)

    def test_orchestrator_receives_builder_findings(self):
        """The findings channel needs a receiver, not just a sender."""
        text = self._text()
        self.assertIn("<out-of-scope>", text)
        self.assertIn("<deviations>", text)

    def test_orchestrator_routes_blocked_to_the_user(self):
        """BLOCKED means a decision is needed — not another implementer."""
        text = self._text()
        self.assertIn("`BLOCKED`", text)
        self.assertIn("### Blocked", text)


if __name__ == "__main__":
    unittest.main()
