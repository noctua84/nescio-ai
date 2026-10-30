"""Parse orchestrator structure: phases, triage table, tier table.

This module owns the *structured spine* of ``agents/orchestrator.md``: the phase
list (``## PHASE n: NAME`` headings), the triage table (under PHASE 0), and the
tier table (under ``### Per-Task Dispatch``). It reads the file, masks fenced
blocks so they don't confuse the scan, and returns what the lifecycle page needs.
Moved here from ``gen_lifecycle.py`` so the rendering logic can stay independent
of the parser -- the two halves of the page (generated structure and hand-written
prose) change at different rates and for different reasons.
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
    REPO_DIR,
    CatalogError,
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
    index = _find_anchor(lines, mask, "heading", "### Per-Task Dispatch")
    if index == -1:
        raise CatalogError(
            f"{ORCHESTRATOR_REL}: heading '### Per-Task Dispatch' not found outside a fenced "
            "block, so the tier table cannot be located."
        )
    return _table_after(lines, mask, index, "tier table")
