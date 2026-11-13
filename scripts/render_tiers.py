#!/usr/bin/env python3
"""Render the three builder tier charters from one source.

`builder`, `builder-standard` and `builder-simple` are one charter at three
prices: the orchestrator's escalation logic depends on them carrying an
identical contract. Kept as three hand-maintained copies, every correction had
to land three times. They are now generated from one template:

    agents/_src/tiers.md.tmpl  ->  agents/builder.md
                                   agents/builder-standard.md
                                   agents/builder-simple.md

    python scripts/render_tiers.py           # write the three charters
    python scripts/render_tiers.py --check   # exit 1 if any is stale

Template syntax: plain text, plus three kinds of marker. Each marker sits alone
on its own line and is never copied to the output:

    <!-- tier: builder-simple builder-standard -->
        opens a block kept only for the named tiers. A new `tier:` marker closes
        the open block first, so consecutive per-tier variants need no closer.
    <!-- end tier -->
        closes the open block. Text after it goes to every tier again.
    <!-- note: ... -->
        a comment for the template's readers.

Everything outside a block is the shared contract and reaches all three tiers
byte for byte. See docs/design/builder-tiers.md for what may be tier-specific.

Theme-aware: the template is always written with functional names. If the
target agents directory is on the philosopher theme, each charter is rewritten
through `apply_theme.theme_text` and written under its themed filename, so the
output is the same bytes `apply_theme.py` (and therefore `sync_from_upstream.py`)
would produce from the functional charter.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Works whether this file is run as a script, imported by the tests (which put
# scripts/ on the path themselves), or collected under PYTHONPATH=scripts in CI.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _crew_common import TIERED_AGENTS, themed_name  # noqa: E402
from _theme_common import detect_theme  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "agents"
TEMPLATE = AGENTS_DIR / "_src" / "tiers.md.tmpl"

# Functional names, top tier first. Derived from the roster, not restated.
TIERS = ("builder",) + TIERED_AGENTS

_TIER_RE = re.compile(r"\A<!-- tier: (?P<names>[a-z][a-z -]*?) -->\Z")
_END_RE = re.compile(r"\A<!-- end tier -->\Z")
_NOTE_RE = re.compile(r"\A<!-- note: .* -->\Z")


class TemplateError(ValueError):
    """The template is malformed. The message names the line."""


def render(template: str, tier: str) -> str:
    """The functional-theme charter for `tier`, from `template`'s text."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r} (expected one of {TIERS})")
    out: list[str] = []
    block: set[str] | None = None  # None = shared text, outside any block
    for number, line in enumerate(template.split("\n"), start=1):
        tier_marker = _TIER_RE.match(line)
        if tier_marker:
            names = set(tier_marker["names"].split())
            unknown = names - set(TIERS)
            if unknown:
                raise TemplateError(
                    f"line {number}: unknown tier(s) {sorted(unknown)} "
                    f"(expected names from {TIERS})")
            block = names
            continue
        if _END_RE.match(line):
            if block is None:
                raise TemplateError(f"line {number}: `end tier` with no open block")
            block = None
            continue
        if _NOTE_RE.match(line):
            continue
        if line.startswith("<!-- tier") or line.startswith("<!-- end"):
            raise TemplateError(f"line {number}: malformed marker {line!r}")
        if block is None or tier in block:
            out.append(line)
    if block is not None:
        raise TemplateError("template ends inside a tier block (missing `<!-- end tier -->`)")
    return "\n".join(out)


def _theme_of(agents_dir: Path) -> str:
    theme = detect_theme(agents_dir)
    return "philosophers" if theme == "philosophers" else "functional"


def rendered_charters(agents_dir: Path = AGENTS_DIR,
                      template_path: Path = TEMPLATE) -> dict[Path, str]:
    """{output path: expected text} for every tier, under `agents_dir`'s theme."""
    template = template_path.read_text(encoding="utf-8", newline="")
    theme = _theme_of(agents_dir)
    charters = {}
    for tier in TIERS:
        text = render(template, tier)
        if theme != "functional":
            # Imported here, not at module level: an unthemed checkout never
            # needs the cosmetic module, the same rule sync_from_upstream follows.
            from apply_theme import theme_text
            text = theme_text(text, theme)
        charters[agents_dir / f"{themed_name(tier, theme)}.md"] = text
    return charters


def stale_charters(agents_dir: Path = AGENTS_DIR,
                   template_path: Path = TEMPLATE) -> list[Path]:
    """Charters whose on-disk bytes differ from the rendering (or are missing)."""
    stale = []
    for path, expected in rendered_charters(agents_dir, template_path).items():
        current = path.read_text(encoding="utf-8", newline="") if path.exists() else None
        if current != expected:
            stale.append(path)
    return stale


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render the builder tier charters.")
    ap.add_argument("--check", action="store_true",
                    help="report stale charters and exit 1 instead of writing")
    ap.add_argument("--agents-dir", type=Path, default=AGENTS_DIR,
                    help="the agents/ directory to write into (default: repo agents/)")
    ap.add_argument("--template", type=Path, default=None,
                    help="template path (default: <agents-dir>/_src/tiers.md.tmpl)")
    args = ap.parse_args(argv)
    template = args.template or args.agents_dir / "_src" / "tiers.md.tmpl"
    try:
        charters = rendered_charters(args.agents_dir, template)
    except (OSError, TemplateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.check:
        stale = stale_charters(args.agents_dir, template)
        for path in stale:
            print(f"  ! {path.name} differs from {template.name} — "
                  f"run `python scripts/render_tiers.py`", file=sys.stderr)
        return 1 if stale else 0

    for path, text in charters.items():
        current = path.read_text(encoding="utf-8", newline="") if path.exists() else None
        if current == text:
            continue
        # newline="" so the charter is written with LF on every OS, matching
        # .gitattributes and apply_theme.py.
        path.write_text(text, encoding="utf-8", newline="")
        print(f"  wrote {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
