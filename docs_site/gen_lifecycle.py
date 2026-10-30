#!/usr/bin/env python3
"""Render the Orchestrator lifecycle page for docs.nescio-ai.org.

The page has two halves, and the split is the whole point:

* **The factual spine is parsed, never typed.** The phase list, the triage table
  and the tier table all come out of ``agents/orchestrator.md`` on every render.
  Rename a phase in the agent file and the page follows with no edit here. There
  is no phase-count literal in this module and none on the page -- not even in a
  heading, which is why the phase section is called simply "The phases". The
  site once shipped "Ten agents" against a roster of sixteen; this page is built
  so that failure mode has nowhere to live.
* **The prose is hand-written and owned by this module** -- the ``*_PROSE``
  constants and ``PHASE_PROSE`` below. It summarises an 878-line agent
  definition; it is not a second copy of it.

Because hand-written prose *can* rot silently -- the orchestrator has changed
meaning without changing a single heading name -- :func:`section_text` exposes,
by stable key, the exact source text of the five sections that prose summarises.
``docs_site/test_gen_lifecycle.py`` hashes those strings and pins the digests, so
a reworded or reversed decision in the agent file fails the suite and demands a
re-read of the prose here. Generator and test therefore cannot disagree about
*what* was hashed: both call that one function.

Agent names are written in the **functional** theme (``builder``,
``builder-standard``, ``builder-simple``), because the committed tree is the
functional theme; the Agents page carries the philosopher mapping.

Stdlib only, like the rest of ``docs_site/``: the docs build must work with
nothing from ``scripts/`` on ``PYTHONPATH``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Top-level, not function-level, on purpose. MkDocs loads hook modules with
# ``importlib.util.spec_from_file_location`` and puts the hook file's directory
# on ``sys.path`` only around module exec, restoring it immediately after
# (``mkdocs.config.config_options.Hooks._load_hook``, mkdocs 1.6.1). A
# function-level sibling import works from the CLI and fails inside
# ``mkdocs build``.
from catalog_core import (
    GENERATED_BANNER,
    REPO_DIR,
    CatalogError,
    _source_link,
)

ORCHESTRATOR_REL = "agents/orchestrator.md"

# ``agents/orchestrator.md`` carries ``## ``-prefixed template skeletons *inside*
# fenced blocks (the brief, plan and progress-report templates). Every scan here
# masks fenced lines first; a naive ``^## `` grep over that file reports phases
# and sections that do not exist.
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^(#{1,6}) +(.*?)\s*$")
_PHASE_RE = re.compile(r"^## PHASE (\d+): +(.+?)\s*$")
_PAREN_RE = re.compile(r"^(.*?)\s*\([^()]*\)$")
_TABLE_RE = re.compile(r"^\s*\|")

# The five sections the prose below summarises, each keyed for the staleness pin
# in ``test_gen_lifecycle.py``. Two anchor kinds:
#
# * ``heading``   -- the literal heading line; the section runs to the next
#   heading of the same or a higher level.
# * ``paragraph`` -- a bold-run literal that opens a paragraph; the section is
#   that one paragraph, ending at the next blank line, heading or fence.
#
# Anchors match outside fenced blocks only, and a missing anchor raises rather
# than hashing the empty string.
SECTION_ANCHORS: dict[str, tuple[str, str]] = {
    "competence_check": (
        "paragraph",
        "**Competence check (before you commit to a path).**",
    ),
    "tiering": ("heading", "### Per-Task Dispatch"),
    "work_placement": (
        "heading",
        "### Work Placement: Inline, Subagent, or Spawned Task",
    ),
    "discovery_brief_carrying": (
        "heading",
        "### Carry the Discovery Brief (every dispatch, no exceptions)",
    ),
    "routing_quality_gate": ("paragraph", "**Routing quality gate.**"),
}


# --------------------------------------------------------------------------
# Source access and parsing
# --------------------------------------------------------------------------


def orchestrator_path(repo_dir: Path = REPO_DIR) -> Path:
    """Path of the agent definition this page is generated from."""
    return repo_dir / "agents" / "orchestrator.md"


@dataclass(frozen=True)
class Phase:
    """One ``## PHASE n: NAME`` heading, as the source spells it."""

    number: str
    name: str
    title: str


def _source(repo_dir: Path) -> tuple[list[str], list[bool]]:
    """The definition's lines plus a mask: True where a line is in a fence."""
    try:
        text = orchestrator_path(repo_dir).read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogError(f"{ORCHESTRATOR_REL}: cannot be read ({exc})") from exc

    lines = text.splitlines()
    mask: list[bool] = []
    open_fence: str | None = None
    for line in lines:
        match = _FENCE_RE.match(line)
        if open_fence is None:
            mask.append(bool(match))
            if match:
                open_fence = match.group(1)[:3]
            continue
        mask.append(True)
        if match and match.group(1).startswith(open_fence):
            open_fence = None
    return lines, mask


def _find_anchor(lines: list[str], mask: list[bool], kind: str, literal: str) -> int:
    """Index of an anchor line outside any fence, or -1. See SECTION_ANCHORS."""
    for index, line in enumerate(lines):
        if mask[index]:
            continue
        if line.rstrip() == literal if kind == "heading" else line.startswith(literal):
            return index
    return -1


def parse_phases(repo_dir: Path = REPO_DIR) -> list[Phase]:
    """Every ``## PHASE n: NAME`` heading outside a fence, in file order.

    :attr:`Phase.title` is the heading text verbatim, trailing parenthetical and
    all (``TRIAGE (Every Request)``); :attr:`Phase.name` is the bare name the
    prose keys on.
    """
    lines, mask = _source(repo_dir)
    phases: list[Phase] = []
    for index, line in enumerate(lines):
        if mask[index]:
            continue
        match = _PHASE_RE.match(line)
        if not match:
            continue
        title = match.group(2)
        bare = _PAREN_RE.match(title)
        phases.append(
            Phase(
                number=match.group(1),
                name=bare.group(1) if bare else title,
                title=title,
            )
        )

    # A silently empty (or near-empty) phase list is precisely the drift this
    # page exists to prevent, so it fails the build instead of rendering.
    if len(phases) < 2:
        raise CatalogError(
            f"{ORCHESTRATOR_REL}: found {len(phases)} '## PHASE n: NAME' heading(s) "
            "outside fenced blocks, which cannot be right. Either the phase "
            "headings were renamed or the fence-skipping scan in "
            "docs_site/gen_lifecycle.py no longer matches the file."
        )
    return phases


def _table_after(lines: list[str], mask: list[bool], start: int, what: str) -> list[str]:
    """First markdown table after line ``start``, before the next heading.

    Returns its lines verbatim -- header, separator, data rows. Raises when the
    section holds no table: a table that moved must not quietly degrade into a
    page with no table.
    """
    index = start + 1
    while index < len(lines):
        if not mask[index]:
            if _TABLE_RE.match(lines[index]):
                break
            if _HEADING_RE.match(lines[index]):
                index = len(lines)
                break
        index += 1

    rows: list[str] = []
    while index < len(lines) and not mask[index] and _TABLE_RE.match(lines[index]):
        rows.append(lines[index].rstrip())
        index += 1
    if len(rows) < 3:
        raise CatalogError(
            f"{ORCHESTRATOR_REL}: expected a markdown table with at least one data "
            f"row for the {what}, found {len(rows)} table line(s). The table moved "
            "or changed shape -- re-point docs_site/gen_lifecycle.py at it."
        )
    return rows


def triage_table(repo_dir: Path = REPO_DIR) -> list[str]:
    """The triage table following the ``PHASE 0`` heading, rows verbatim."""
    lines, mask = _source(repo_dir)
    for index, line in enumerate(lines):
        if mask[index]:
            continue
        match = _PHASE_RE.match(line)
        if match and match.group(1) == "0":
            return _table_after(lines, mask, index, "triage table")
    raise CatalogError(
        f"{ORCHESTRATOR_REL}: no '## PHASE 0: ...' heading outside a fenced block, "
        "so the triage table cannot be located."
    )


def tier_table(repo_dir: Path = REPO_DIR) -> list[str]:
    """The tier table inside the ``### Per-Task Dispatch`` section, verbatim."""
    lines, mask = _source(repo_dir)
    kind, anchor = SECTION_ANCHORS["tiering"]
    index = _find_anchor(lines, mask, kind, anchor)
    if index == -1:
        raise CatalogError(
            f"{ORCHESTRATOR_REL}: heading '{anchor}' not found outside a fenced "
            "block, so the tier table cannot be located."
        )
    return _table_after(lines, mask, index, "tier table")


def section_text(repo_dir: Path, key: str) -> str:
    """Exact source text of one section this page's prose summarises.

    Keys are the ones in :data:`SECTION_ANCHORS`. ``test_gen_lifecycle.py``
    hashes the return value and pins the digest, so this is the single
    definition of *what was summarised* -- generator and test read the same
    bytes. Nothing is normalised beyond a trailing-whitespace strip, so even a
    whitespace-only edit fires the pin. That is the accepted cost of never
    missing a reversed decision.
    """
    if key not in SECTION_ANCHORS:
        raise CatalogError(
            f"section_text: unknown section key '{key}'. Known keys: "
            + ", ".join(sorted(SECTION_ANCHORS))
        )

    kind, anchor = SECTION_ANCHORS[key]
    lines, mask = _source(repo_dir)
    start = _find_anchor(lines, mask, kind, anchor)
    if start == -1:
        raise CatalogError(
            f"{ORCHESTRATOR_REL}: anchor for section '{key}' not found outside a "
            f"fenced block ({kind} anchor {anchor!r}). The section was renamed or "
            "removed -- re-read docs_site/gen_lifecycle.py's prose for it, then "
            "update SECTION_ANCHORS."
        )

    end = len(lines)
    if kind == "heading":
        level = len(_HEADING_RE.match(lines[start]).group(1))
        for index in range(start + 1, len(lines)):
            if mask[index]:
                continue
            heading = _HEADING_RE.match(lines[index])
            if heading and len(heading.group(1)) <= level:
                end = index
                break
    else:
        for index in range(start + 1, len(lines)):
            if not lines[index].strip() or mask[index] or _HEADING_RE.match(lines[index]):
                end = index
                break

    text = "\n".join(lines[start:end]).rstrip()
    if not text:
        raise CatalogError(f"{ORCHESTRATOR_REL}: section '{key}' resolved to empty text")
    return text


# --------------------------------------------------------------------------
# Prose -- hand-written, owned by this module, pinned by section_text()
#
# Every claim below summarises one of the SECTION_ANCHORS sections or a phase
# body. If the pin in test_gen_lifecycle.py fires, re-read the source section
# before touching the digest: the prose is what may need the edit.
# --------------------------------------------------------------------------

LEAD_PROSE = """\
`orchestrator` is Nescio's default agent for anything non-trivial. It writes no
production code: it triages a request, dispatches specialised agents, and holds
an approval gate between phases so that you decide what happens next. This page
is generated — the phase list, the triage table and the tier table below are
parsed out of the agent definition on every build, so they cannot drift from
it."""

TRIAGE_PROSE = """\
Every request is classified before anything else happens, and the classification
decides which phases run. Trivial work goes straight to execution; a research
question stops at discovery."""

# Summarises the `competence_check` section.
COMPETENCE_PROSE = """\
**There is a way out of the table.** If no agent, tool or available knowledge
actually fits the request — or it is under-specified beyond what a discovery
phase could resolve — the orchestrator is required to say so, name what is
missing, and ask for the detail or decision it needs, instead of forcing the
request into the lifecycle to manufacture motion. "I don't know / no competent
path" is a first-class outcome here, not a failure to route: an honest
non-answer beats a confident wrong one."""

PHASES_PROSE = """\
Each phase ends by handing you something and asking a question. The headings
below are the phases as the agent definition spells them."""

PHASE_PROSE: dict[str, str] = {
    "TRIAGE": """\
Classifies the request against the table above, then states which phases will
run and at what estimated complexity. You are asked whether to proceed.""",
    "DISCOVER": """\
Understands the problem space before anything is built. `explore` is always
dispatched; `librarian` only when the task genuinely requires reading something
authored outside this repository, because external research on a task with no
external surface is pure cost. The deliverable is a *reusable* Discovery Brief,
persisted to `.sisyphus/discovery/<plan-name>.md`, so later agents stop paying
for the same rediscovery. You are asked to acknowledge the summary.""",
    "ANALYZE": """\
Runs only when it is needed. `scout` looks for hidden risks and ambiguities;
`advisor` weighs an architecture decision and its tradeoffs. The output is a risk
assessment, architecture guidance, and how the two change the approach. You are
asked whether to move on to planning.""",
    "PLAN": """\
Turns the objective into a task-level plan at `.sisyphus/plans/<name>.md`, in
which every task carries a complexity tier and a work-placement label.
`validator` asks whether the plan *can* be built; `critic` asks whether it
*should* be built this way. You are asked to approve the plan, and may ask for
changes.""",
    "EXECUTE": """\
Implements the plan in waves: one agent per task, each handed the complete task
description, exact file paths, acceptance criteria and the Discovery Brief —
agents have no memory of the conversation. `doc-researcher` runs alongside the
first implementation wave, and a separate `test-writer` phase follows each one.
Agents' incidental findings are collected rather than acted on, and carried to
delivery. You are briefed after each wave, and asked before the next on a large
plan.""",
    "VERIFY": """\
Checks that the whole thing works. `qa-guard` discovers and runs the project's CI
checks and fixes mechanical failures; `reviewer` then audits the implementation
against the plan for bugs, regressions, security and coverage. A genuine bug
found here is implementation work, not a review note. You are asked whether to
deliver.""",
    "DELIVER": """\
Commits, and lands the findings collected on the way. Those carried-forward
findings are presented as *candidate* spawned tasks — findings that never reach
you die with the session. Documentation is written by `doc-writer` from the
research gathered during execution. You are offered the delivery options: commit,
commit and open a PR, commit and merge, or review the diff first.""",
}

# The last bullet summarises the `routing_quality_gate` section.
GATES_PROSE = """\
The gates are the point of the lifecycle, not overhead inside it.

- **Approval between phases.** Each phase ends with a summary and a question, and
  the orchestrator waits. A turn never ends with a passive statement — though an
  honest refusal that names the decision it needs counts as driving forward.
- **Delivery Boundary Check**, before a plan is presented. Work that crosses an
  independent delivery boundary — a separate repo, branch, or separately
  shippable unit — becomes its own spawned task with a self-contained brief
  rather than a wave in this session. Only work whose results must be synthesised
  here stays here.
- **Scope-Drift Reflex**, before each wave. The original task is restated in one
  line and the wave checked against it. An activity two or more steps removed
  from the goal is surfaced to you with the chain named and a cut-back point.
- **Routing quality gate**, before a subagent's result is relayed or acted on. If
  that result is hedged, thin, internally inconsistent, or the orchestrator would
  be *less* sure of it than of its own read, it is not relayed: it is
  re-dispatched with a tighter prompt, cross-checked against a second agent, or
  surfaced to you as uncertainty. Laundering a low-trust answer into a confident
  summary is how a delegation chain ends up confidently wrong."""

# Summarises the `tiering` section (the table above it is parsed from there too).
TIERING_PROSE = """\
Every task carries a tier, and an unclassified task is an omission rather than a
licence to default upward. Tiers are classified on **reasoning load, not diff
size**: a mechanical rename across eight files can run 400 lines and need no
judgment, while a 30-line change to a state machine can need a design decision.

One question decides it — does the task require a decision the plan and the
Discovery Brief have not already settled? No → `simple`. Yes, and the decision is
local to one module → `standard`. Yes, and it is architectural or crosses a
system boundary → `complex`.

`builder` is not the safe default; it is the expensive one. The three tiers carry
an **identical contract** — same method, same verification bar, same output
block, same anti-patterns — and differ only in the model they run on, so
over-tiering buys no extra rigour, just the same behaviour at Opus prices. When
in doubt between two tiers, choose the **lower** one.

Escalation goes **one tier at a time**: a `simple` task that returns `BLOCKED`
because it was harder than classified is re-dispatched as `standard`, and only
then as `complex`. Jumping straight to the top on the first block throws away two
cheaper tiers' worth of evidence. A `BLOCKED` that names a missing **decision**
is a different thing entirely — that comes to **you**, not up a tier. Escalation
is for "harder than expected", never for "underspecified"."""

# Summarises `work_placement`; the closing paragraph summarises
# `discovery_brief_carrying`.
PLACEMENT_PROSE = """\
Work that surfaces while something else is in flight gets *placed* before it is
touched — inline, as a subagent, or as a spawned task. The primary test is
whether the result needs to re-enter this conversation: if the orchestrator needs
the answer to decide its next step, the work is inline or a subagent; if it lands
on its own as a commit, has its own branch or worktree, needs its own
verify-and-deliver cycle, or was noticed *while* doing something else, it is
spawned. The tie-breakers, in order, are scope (would doing it now widen the diff
you are about to review?), self-containment (could a session with zero memory act
on the brief?), coupling (does it share uncommitted state with work in flight?)
and your attention budget — a dozen spawned tasks get ignored, and then the
mechanism is worth nothing.

**The two mistakes are not symmetric.** Spawning what should have been inline
costs a fresh session rediscovering context, but the work still lands. Doing
inline what should have been spawned costs scope drift and a diff you cannot
cleanly review — and it contaminates the thing you actually asked for. So on a
coin flip, out-of-scope work is spawned and in-scope work stays here. Nothing
*blocking* the current task is ever spawned: a blocker is a decision to bring to
you now.

A spawned session starts with no memory of this one, so its brief has to carry
the whole picture — objective, file paths, constraints, and the issue or plan it
should read. For the same reason the Discovery Brief is carried into **every
dispatch from analysis onward**, inline as a digest *and* by path: the path alone
fails for an agent that does not read files before acting, the digest alone fails
for one that needs more depth, and with neither, each agent re-reads the codebase
`explore` already mapped and guesses independently at this repo's conventions. A
brief that stops being updated is worse than none, because agents trust it."""


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def render_lifecycle(repo_dir: Path = REPO_DIR) -> tuple[str, list[str]]:
    """Render the lifecycle page. Returns (page text, warnings)."""
    phases = parse_phases(repo_dir)
    triage = triage_table(repo_dir)
    tiers = tier_table(repo_dir)
    warnings: list[str] = []
    source = _source_link(ORCHESTRATOR_REL)

    lines = [
        GENERATED_BANNER,
        "",
        "# The orchestrator lifecycle",
        "",
        LEAD_PROSE,
        "",
        f"Source of truth: {source}.",
        "",
        "## Triage",
        "",
        TRIAGE_PROSE,
        "",
    ]
    lines += triage
    lines += ["", COMPETENCE_PROSE, "", "## The phases", "", PHASES_PROSE, ""]

    for phase in phases:
        prose = PHASE_PROSE.get(phase.name)
        if prose is None:
            # Never fatal, and never silent: a renamed or newly added phase
            # still reaches the page, carrying a pointer at the source instead
            # of a summary nobody has written yet.
            warnings.append(
                f"{ORCHESTRATOR_REL}: phase '{phase.name}' has no summary in "
                "docs_site/gen_lifecycle.py:PHASE_PROSE -- the page links to the "
                "source for it instead. Write one."
            )
            prose = f"See {source} for this phase; no summary has been written yet."
        lines += [f"### PHASE {phase.number}: {phase.title}", "", prose, ""]

    lines += ["## Gates", "", GATES_PROSE, "", "## Tiering by reasoning load", ""]
    lines += tiers
    lines += [
        "",
        TIERING_PROSE,
        "",
        "Those agent names are the functional theme, which is what the repository",
        "ships; the philosopher-theme equivalents are tabulated on",
        "[the Agents page](agents.md#the-philosopher-theme).",
        "",
        "## Work placement",
        "",
        PLACEMENT_PROSE,
        "",
        "## Where this page comes from",
        "",
        f"{source} is the source of truth. The phase headings, the triage table and",
        "the tier table above are parsed from it on every build; the prose around",
        "them is written by `docs_site/gen_lifecycle.py` and summarises named",
        "sections of that file, under a checksum pin that fails the test suite when",
        "one of them changes. Where this page and the agent definition disagree, the",
        "agent definition governs — it is what actually runs.",
    ]

    return "\n".join(lines).rstrip() + "\n", warnings


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    page, page_warnings = render_lifecycle()
    print(page)
    for warning in page_warnings:
        print(f"warning: {warning}")
