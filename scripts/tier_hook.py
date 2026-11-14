#!/usr/bin/env python3
"""Claude Code project hook that keeps the builder tier charters generated.

`agents/builder.md`, `builder-standard.md` and `builder-simple.md` are rendered
from `agents/_src/tiers.md.tmpl` by `scripts/render_tiers.py`. CI catches a stale
charter, but only after the push. This hook closes the gap while a maintainer is
editing this repo inside Claude Code, in two directions:

* PreToolUse, target is a generated charter: refuse (exit 2). The stderr text
  goes back to Claude, which should edit the template instead. A hand edit to a
  charter would be overwritten by the next render anyway.
* PostToolUse, target is the template: run the generator in-process (exit 0,
  the rewritten charters on stdout). A malformed template exits 2 with the
  generator's error on stderr, so Claude sees it and fixes the template.

Everything else exits 0 silently: other files, other tools, missing or invalid
JSON, no file_path. The hook must never break an unrelated edit.

This is a *project* hook, registered by `.claude/settings.json` for maintainers
of this repo. It is not wired by `install.py` and is unrelated to `hooks/`,
which are user-scope hooks installed into `~/.claude/settings.json`. The repo
root is taken from this file's location, not from the cwd, so a worktree uses
its own template and charters.

    python scripts/tier_hook.py [--agents-dir DIR] < payload.json

`--agents-dir` exists for the tests; the default is this repo's `agents/`.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

# Works as a script and when imported by the tests (which put scripts/ on the
# path themselves), same as render_tiers.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import render_tiers  # noqa: E402
from _crew_common import THEMES, themed_name  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "agents"
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})
TEMPLATE_REL = Path("_src") / "tiers.md.tmpl"


def _key(path: Path | str) -> str:
    """A comparable form of `path`: resolved, and case-folded where the OS is."""
    return os.path.normcase(os.path.realpath(path))


def _charter_paths(agents_dir: Path, template: Path) -> set[Path]:
    """Where the generated charters live, under whichever theme `agents_dir` has.

    Asks the generator, so the answer cannot drift from what it writes. If the
    template is unreadable or malformed the generator cannot answer; the
    fallback then guards the charter names of every theme, so breaking the
    template does not unlock hand edits to the charters.
    """
    try:
        return set(render_tiers.rendered_charters(agents_dir, template))
    except (OSError, render_tiers.TemplateError):
        return {agents_dir / f"{themed_name(tier, theme)}.md"
                for tier in render_tiers.TIERS for theme in THEMES}


def process(raw: str, agents_dir: Path = AGENTS_DIR) -> tuple[int, str, str]:
    """Decide on one hook payload. Returns (exit code, stdout, stderr)."""
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return 0, "", ""
        event = payload.get("hook_event_name")
        if payload.get("tool_name") not in EDIT_TOOLS or event not in (
                "PreToolUse", "PostToolUse"):
            return 0, "", ""
        tool_input = payload.get("tool_input")
        file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
        if not isinstance(file_path, str) or not file_path:
            return 0, "", ""
        target = Path(file_path)
        cwd = payload.get("cwd")
        if not target.is_absolute() and isinstance(cwd, str) and cwd:
            target = Path(cwd) / target
        target_key = _key(target)
        template = agents_dir / TEMPLATE_REL
    except (ValueError, TypeError, OSError):
        return 0, "", ""

    if event == "PreToolUse":
        if target_key in {_key(p) for p in _charter_paths(agents_dir, template)}:
            return 2, "", (
                f"{target.name} is generated; do not edit it directly. Edit "
                f"agents/_src/tiers.md.tmpl instead. The charters are "
                f"regenerated automatically after a template edit.\n")
        return 0, "", ""

    if target_key != _key(template):
        return 0, "", ""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = render_tiers.main(["--agents-dir", str(agents_dir)])
    if code != 0:
        return 2, "", (f"agents/_src/tiers.md.tmpl did not render; fix the "
                       f"template and the charters will regenerate.\n{err.getvalue()}")
    written = out.getvalue()
    return 0, (f"Regenerated builder charters from the template:\n{written}"
               if written else ""), ""


def main(argv: list[str] | None = None, stdin: io.TextIOBase | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    agents_dir = AGENTS_DIR
    if len(args) == 2 and args[0] == "--agents-dir":
        agents_dir = Path(args[1])
    raw = stdin.read() if stdin is not None else sys.stdin.buffer.read().decode(
        "utf-8", errors="replace")
    code, out, err = process(raw, agents_dir)
    if out:
        sys.stdout.write(out)
    if err:
        # A Windows console codepage must not turn a message into a traceback.
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(errors="replace")
        sys.stderr.write(err)
    return code


if __name__ == "__main__":
    sys.exit(main())
