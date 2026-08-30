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
PAIRS = [
    ("planner", "plato"),
    ("advisor", "aristotle"),
    ("reviewer", "pyrrho"),
    ("critic", "socrates"),
    ("builder", "archimedes"),
]

# The builder's cost tiers: `builder-simple.md` / `builder-standard.md`.
#
# These drive **file renames only** and are deliberately kept out of PAIRS.
# The reason is coupling, not double-mapping: PAIRS is consumed as a word-pair
# rename *dictionary* by tests/test_apply_theme.py:49 and
# tests/test_agent_definitions.py:57, :70 and :82, so it has to stay purely
# word-level — a `builder-simple` entry would show up in those callers as a
# bogus "word". It is also unnecessary: `_transform`'s `\bbuilder\b` rule
# already rewrites the *text* of `builder-simple` correctly, because `-` is a
# non-word character. Only the *filename* was being missed.
#
# (An earlier rationale claimed a PAIRS entry would double-map. It would not —
# `_transform` applies its rules sequentially, so the extra rule is a dead
# no-op. Coupling is the real reason; do not restate the double-mapping one.)
TIER_VARIANTS = ("simple", "standard")
TIERED_AGENTS = tuple(f"builder-{variant}" for variant in TIER_VARIANTS)

# Agents whose names are identical under every theme — the theme script never
# touches their files or their `name:` frontmatter.
THEME_INVARIANT_ROSTER = {
    "doc-researcher",
    "doc-writer",
    "explore",
    "librarian",
    "orchestrator",
    "qa-guard",
    "scout",
    "test-writer",
    "validator",
    "vision",
}

# Agents permitted to edit production code, by functional name. Adding to this
# set is an architectural decision, not bookkeeping.
CODE_WRITERS = {"builder", "builder-standard", "builder-simple", "qa-guard"}

# Agents permitted to edit, but whose charters declare a hard file boundary
# limiting *what* they may touch (tests only, docs only).
BOUNDED_WRITERS = {"test-writer", "doc-writer"}

# The phrase a bounded writer's charter must carry to declare its boundary.
#
# Named, not inlined: the boundary is a doc-lint (agent frontmatter takes tool
# names only — path-scoped permissions do not exist), and the charters already
# diverge in wording *after* this prefix. A bare literal at the call site would
# be one reword away from a check that silently passes on nothing.
BOUNDARY_PHRASE = "Hard file boundary:"

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
    """
    if theme not in THEMES:
        raise ValueError(f"unknown theme {theme!r} (expected one of {THEMES})")
    if theme == "functional":
        return functional_name
    base, sep, variant = functional_name.partition("-")
    if sep and variant in TIER_VARIANTS and base in _FUNCTIONAL_TO_PHILOSOPHER:
        return f"{_FUNCTIONAL_TO_PHILOSOPHER[base]}-{variant}"
    return _FUNCTIONAL_TO_PHILOSOPHER.get(functional_name, functional_name)


def expected_roster(theme: str) -> set[str]:
    """The agent filename stems expected under `theme`, tier variants included."""
    return {themed_name(name, theme) for name in FUNCTIONAL_ROSTER}


def renamed_agents(theme: str) -> list[tuple[str, str]]:
    """(src, dst) filename stems the theme script renames when switching to `theme`.

    The seven files the theme touches: the five PAIRS plus the two builder
    tiers. Derived from `themed_name`, so the two directions cannot drift.
    """
    if theme not in THEMES:
        raise ValueError(f"unknown theme {theme!r} (expected one of {THEMES})")
    functional = [functional for functional, _ in PAIRS] + list(TIERED_AGENTS)
    if theme == "philosophers":
        return [(name, themed_name(name, "philosophers")) for name in functional]
    return [(themed_name(name, "philosophers"), name) for name in functional]
