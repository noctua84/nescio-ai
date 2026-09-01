# scripts/_crew_common.py
"""Facts about the crew roster and its write policy, shared by scripts and tests.

These constants deliberately do **not** live in ``apply_theme.py``. The
philosopher theme is an *opt-in cosmetic feature* — an instance may never run
it, and a future one may delete it. The crew's write policy is not cosmetic:
which agents may edit production code, and which of them must declare a file
boundary, is an architectural fact that has to outlive any rename script.
Parking it inside the theme script would mean deleting the theme deletes the
policy, and would leave the policy tests importing a module whose only job is
an optional flourish.

``apply_theme.py`` therefore consumes this module rather than owning it, and
declares no roster facts of its own.

Stdlib-only, no I/O: pure data, one small value type describing it, and
derivations over it.
"""

from __future__ import annotations

from typing import NamedTuple

THEMES = ("functional", "philosophers")

# functional (default)  <->  philosopher
#
# Spelled out literally in tests/test_apply_theme.py:ThemeNamePinTest. That is
# the only assertion in the suite with an oracle *outside* this file, so it is
# the only thing standing between a typo here and a silently renamed crew —
# every other roster assertion derives both sides from this list and stays green
# over any self-consistent misspelling. Edit one, edit the other.
PAIRS = [
    ("planner", "plato"),
    ("advisor", "aristotle"),
    ("reviewer", "pyrrho"),
    ("critic", "socrates"),
    ("builder", "archimedes"),
    ("test-writer", "euclid"),
    ("qa-guard", "cato"),
    ("doc-researcher", "callimachus"),
    ("doc-writer", "cicero"),
]

# The builder's cost tiers: `builder-simple.md` / `builder-standard.md`.
#
# These drive **file renames only** and are deliberately kept out of PAIRS.
# The reason is coupling, not double-mapping: PAIRS is consumed as a word-pair
# rename *dictionary* by `apply_theme._mappings`, by `themed_name` below (via
# `_FUNCTIONAL_TO_PHILOSOPHER`), and by ThemeCasingCoverageTest in
# tests/test_apply_theme.py, so it has to stay purely word-level — a
# `builder-simple` entry would show up in those callers as a bogus "word".
#
# Cited by symbol, not by line. The line numbers that stood here
# (test_apply_theme.py:49, test_agent_definitions.py:57/:70/:82) named helpers
# that indexed PAIRS directly; two of them have since been folded into this
# module as `expected_roster` and `themed_name`, and the numbers were stale
# well before that. Symbols move with their code; line numbers do not.
#
# The entry is also unnecessary: `_transform`'s `\bbuilder\b` rule
# already rewrites the *text* of `builder-simple` correctly, because `-` is a
# non-word character. Only the *filename* was being missed.
#
# (An earlier rationale claimed a PAIRS entry would double-map. It would not —
# `_transform` applies its rules sequentially, so the extra rule is a dead
# no-op. Coupling is the real reason; do not restate the double-mapping one.)
#
# Note the hazard this comment describes is *specific to a name with tiers*, not
# to hyphens as such. Four PAIRS entries are themselves hyphenated
# (`test-writer`, `qa-guard`, `doc-researcher`, `doc-writer`) and need no entry
# here: no other agent name contains one of them as a `\b`-delimited substring,
# so `\btest-writer\b` and friends match only their own name. `builder` is the
# sole term that matches inside *another* roster name, and TIERED_AGENTS is what
# keeps the corresponding files renamed alongside the text rewrite.
TIER_VARIANTS = ("simple", "standard")
TIERED_AGENTS = tuple(f"builder-{variant}" for variant in TIER_VARIANTS)

# Agents whose names are identical under every theme — the theme script never
# touches their files or their `name:` frontmatter.
THEME_INVARIANT_ROSTER = {
    "explore",
    "librarian",
    "orchestrator",
    "scout",
    "validator",
    "vision",
}

# Agents permitted to edit production code with no declared file boundary, by
# functional name. Adding to this set is an architectural decision, not
# bookkeeping.
CODE_WRITERS = {"builder", "builder-standard", "builder-simple"}

# Agents permitted to edit, but whose charters declare a hard file boundary
# limiting *what* they may touch (tests only, docs only, everything except the
# files that define the CI checks).
#
# A boundary may be stated either way round: `test-writer` and `doc-writer`
# name the region they are confined *to*, `qa-guard` names the region it is
# excluded *from*. Both shapes are pinned by BOUNDARY_SCOPE_TERMS below, but an
# exclusion needs a term that carries the negation — see the note there.
BOUNDED_WRITERS = {"test-writer", "doc-writer", "qa-guard"}

# Agents barred from Edit by their frontmatter, but holding `Write` for one
# narrow purpose their charter has to name: `planner` writes work plans under
# `.sisyphus/`, `reviewer` writes its audit report and nothing else.
#
# Kept apart from BOUNDED_WRITERS rather than merged into it, because the Edit
# permission tests derive their "may edit" set from that constant and these two
# belong on the *cannot* side of it. The boundary doc-lint covers both sets: a
# `Write`-scoped boundary is the same unenforceable prose promise as an
# `Edit`-scoped one — frontmatter accepts tool names only, with no path-scoped
# form — and README advertises both to users, so both need pinning.
WRITE_BOUNDED = {"planner", "reviewer"}

# The phrase a bounded agent's charter must carry to declare its boundary.
#
# Named, not inlined: the boundary is a doc-lint (agent frontmatter takes tool
# names only — path-scoped permissions do not exist), and the charters already
# diverge in wording *after* this prefix. A bare literal at the call site would
# be one reword away from a check that silently passes on nothing.
BOUNDARY_PHRASE = "Hard file boundary:"

# The two shapes a boundary sentence can take, and the match mode each one
# implies. An *inclusion* names the region an agent is confined **to**; an
# *exclusion* names the region it is kept **out of**.
#
# The mode is derived from the shape rather than declared per entry on purpose:
# an entry that could say `any` or `all` independently of its shape would be a
# second thing to get right, and the one that was got wrong. Written this way an
# entry reads as what it *is*, and how its terms combine follows mechanically.
SHAPE_INCLUSION = "inclusion"
SHAPE_EXCLUSION = "exclusion"

# shape -> (how the terms combine, how to phrase that in a lint failure).
# One table so the check and the message it prints cannot drift apart. An
# unknown shape KeyErrors rather than quietly falling back to a mode.
_SHAPE_RULES = {
    SHAPE_INCLUSION: (any, "at least one of"),
    SHAPE_EXCLUSION: (all, "every one of"),
}

# The words that make a scope term carry a negation, matched as whole words
# within the term.
#
# Deliberately minimal: these are what a charter in this repo actually uses to
# say "you may not", and every addition widens what counts as a negation —
# the loosest direction this constant can drift, since it is the floor an
# exclusion entry has to clear. `cannot` is listed beside `not` because the
# match is word-level, not substring: `cannot` is one word, and a substring
# rule would also accept `notation`.
NEGATION_MARKERS = ("never", "not", "cannot")


class BoundaryScope(NamedTuple):
    """What a boundary sentence must say, and how its terms combine."""

    shape: str
    terms: tuple[str, ...]

    def satisfied_by(self, sentence: str) -> bool:
        """Does `sentence` declare this scope? Case-insensitive on both sides."""
        combine, _ = _SHAPE_RULES[self.shape]
        lowered = sentence.lower()
        return combine(term.lower() in lowered for term in self.terms)

    @property
    def requirement(self) -> str:
        """How to phrase this shape's match mode in a lint failure message."""
        return _SHAPE_RULES[self.shape][1]


def inclusion(*terms: str) -> BoundaryScope:
    """A boundary naming the region the agent is confined to (any-of)."""
    return BoundaryScope(SHAPE_INCLUSION, terms)


def exclusion(*terms: str) -> BoundaryScope:
    """A boundary naming the region the agent is kept out of (all-of)."""
    return BoundaryScope(SHAPE_EXCLUSION, terms)


# What each boundary sentence must actually *say*, by functional agent name.
#
# The phrase above is a nineteen-character prefix and nothing more: a charter
# reading `Hard file boundary: none — edit whatever you like.` carries it and
# declares the opposite. Each entry pins the *scope* an agent declares, so the
# lint checks what was said rather than that something was said.
#
# **Why the shape decides the mode.** An inclusion term names the region
# itself, and a sentence carrying it cannot mean the opposite — so any-of is
# safe, and `doc-writer` may say either "documentation" or "docs". An exclusion
# term has to carry the negation, because the scope word appears in the
# *revocation* too: `qa-guard` is bounded by what it may not touch, so under
# any-of a tuple like `("may never edit", "check")` would certify `Hard file
# boundary: you may edit the files that define the checks freely.` on "check"
# alone — the failure `test_a_revoked_boundary_does_not_satisfy_the_lint` exists
# to prevent, in a shape that test cannot see, because substring presence has no
# view of polarity.
#
# All-of inverts that footgun. For an exclusion entry **every term added
# tightens the check and none can loosen it**: widening the tuple can only
# reject more sentences, where under any-of widening was a silent revocation.
# That property is the whole point of the type.
#
# NEGATION_MARKERS is the other half of it. All-of over nothing but positive
# terms still sees no polarity, so an exclusion entry must carry at least one
# negation-bearing term. That is asserted over the constant as a whole in
# `test_an_exclusion_boundary_needs_a_negation_bearing_scope_term`, so a second
# exclusion agent inherits the requirement instead of needing its own pin.
#
# Keyed on the functional roster, like BOUNDED_WRITERS — the on-disk name is
# resolved through `themed_name` where the file is opened, never here.
BOUNDARY_SCOPE_TERMS = {
    "test-writer": inclusion("test"),
    "doc-writer": inclusion("documentation", "docs"),
    "qa-guard": exclusion("may never edit"),
    "planner": inclusion(".sisyphus"),
    "reviewer": inclusion("report"),
}

_FUNCTIONAL_TO_PHILOSOPHER = dict(PAIRS)

# Every agent, by functional name. The single source the roster derives from.
FUNCTIONAL_ROSTER = (
    THEME_INVARIANT_ROSTER
    | {functional for functional, _ in PAIRS}
    | set(TIERED_AGENTS)
)


def themed_name(functional_name: str, theme: str) -> str:
    """The on-disk name of `functional_name` under `theme`.

    Resolves **both** PAIRS and the tier variants: `builder-simple` becomes
    `archimedes-simple`, which a naive ``dict(PAIRS)[name]`` cannot do — it
    raises KeyError, and CODE_WRITERS contains exactly those names.

    A name the theme does not rename (every member of THEME_INVARIANT_ROSTER)
    is returned unchanged, so callers can map the whole roster through this.

    The tier branch is gated on TIERED_AGENTS — membership, not shape. Gating it
    on "any PAIRS base with a known variant suffix" made this function claim
    `planner-simple` becomes `plato-simple`, while `renamed_agents` (which
    derives its file list from TIERED_AGENTS) would never rename such a file.
    Only `builder` has tiers; the two derivations must not disagree about that.
    """
    if theme not in THEMES:
        raise ValueError(f"unknown theme {theme!r} (expected one of {THEMES})")
    if theme == "functional":
        return functional_name
    if functional_name in TIERED_AGENTS:
        base, _, variant = functional_name.partition("-")
        return f"{_FUNCTIONAL_TO_PHILOSOPHER[base]}-{variant}"
    return _FUNCTIONAL_TO_PHILOSOPHER.get(functional_name, functional_name)


def expected_roster(theme: str) -> set[str]:
    """The agent filename stems expected under `theme`, tier variants included."""
    return {themed_name(name, theme) for name in FUNCTIONAL_ROSTER}


def renamed_agents(theme: str) -> list[tuple[str, str]]:
    """(src, dst) filename stems the theme script renames when switching to `theme`.

    The eleven files the theme touches: the nine PAIRS plus the two builder
    tiers. Derived from `themed_name`, so the two directions cannot drift.
    """
    if theme not in THEMES:
        raise ValueError(f"unknown theme {theme!r} (expected one of {THEMES})")
    functional = [functional for functional, _ in PAIRS] + list(TIERED_AGENTS)
    if theme == "philosophers":
        return [(name, themed_name(name, "philosophers")) for name in functional]
    return [(themed_name(name, "philosophers"), name) for name in functional]
