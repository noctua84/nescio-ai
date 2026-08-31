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

Stdlib-only, no I/O: pure data plus two derivations over it.
"""

from __future__ import annotations

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

# Agents permitted to edit production code, by functional name. Adding to this
# set is an architectural decision, not bookkeeping.
CODE_WRITERS = {"builder", "builder-standard", "builder-simple", "qa-guard"}

# Agents permitted to edit, but whose charters declare a hard file boundary
# limiting *what* they may touch (tests only, docs only).
BOUNDED_WRITERS = {"test-writer", "doc-writer"}

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

# What each boundary sentence must actually *say*, by functional agent name.
#
# The phrase above is a nineteen-character prefix and nothing more: a charter
# reading `Hard file boundary: none — edit whatever you like.` carries it and
# declares the opposite. Each entry lists terms of which the sentence carrying
# the phrase must contain at least one, so the lint pins the *scope* an agent
# declares rather than the fact that it said something.
#
# Keyed on the functional roster, like BOUNDED_WRITERS — the on-disk name is
# resolved through `themed_name` where the file is opened, never here.
BOUNDARY_SCOPE_TERMS = {
    "test-writer": ("test",),
    "doc-writer": ("documentation", "docs"),
    "planner": (".sisyphus",),
    "reviewer": ("report",),
}

# The phrase an implementer's charter must carry to declare its write access.
#
# Named for the same reason as BOUNDARY_PHRASE: the three charters diverge in
# wording *after* this prefix — each names a different set of neighbours it is
# unlike — so a bare literal at the call site would be one reword away from a
# check that silently passes on nothing.
WRITE_ACCESS_PHRASE = "Write access to production code:"

# Who must carry that declaration, by functional agent name.
#
# **Not CODE_WRITERS, and deliberately so.** `qa-guard` is a CODE_WRITER and is
# absent here. The declaration is a *licensing* sentence: it tells an implementer
# that it may write production code and that few others may. `qa-guard`'s charter
# does the opposite job — it opens `You have one job: make the CI-equivalent
# checks pass`, then spends its length narrowing that to the mechanical
# (formatting, imports, lint, types, test setup, in that order) and returning
# `BLOCKED` at the first judgment call. Adding a licensing sentence there would
# widen the only control that charter has: frontmatter accepts tool names only,
# so the prose *is* the control surface — the same fact
# `test_bounded_writers_declare_their_boundary` already rests on.
#
# A partial domain with a stated reason beats a total one bought by editing a
# charter to fit a test. If `qa-guard` ever belongs here, the charter changes
# first and this set follows; do not "fix" the asymmetry by widening the set to
# CODE_WRITERS.
WRITE_ACCESS_DECLARERS = {"builder", "builder-standard", "builder-simple"}

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
