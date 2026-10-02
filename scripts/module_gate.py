#!/usr/bin/env python3
"""CI gate: a PR that grows an over-tripwire file must say what it found.

Distinct from `module_scan.py`, which is a read-only report and must stay
exit-0 forever. This is the gate that makes that report's finding
*enforceable* at the one place every change -- hand-edited or agent-written --
actually lands: the pull request.

Why this exists at all: the `modular-design` doctrine ("measure before you
append") is written into `agents/builder.md` and `agents/planner.md`, but
those charters only load for an agent that writes code *on instruction*. A
top-level session editing a file by hand never reads either charter, so the
obligation was structurally unreachable for that whole class of change. This
gate does not care who or what made the edit -- it looks at the diff.

**Splitting is never required. Saying what you found is.** A hit is cleared
by a one-line acknowledgement (see `ACK_RE` below), not by shrinking the file.

Design decisions, each with a failure mode behind it:

  * **`git diff --numstat <base>...<head>`, three dots.** Symmetric
    difference: only commits reachable from `head` but not from `base` (i.e.
    this PR's own commits), never main's unrelated churn that happened to land
    between when the branch forked and when the gate runs.

  * **A hit requires *both* "over the tripwire at head" *and* "added at least
    one line in the range".** A file that is over the tripwire but only shrank
    is exactly the outcome the doctrine wants -- never nag about it. A
    brand-new file created over the tripwire is a hit: it is over, and every
    one of its lines was added.

  * **Reuses `module_scan.is_excluded` and `module_scan.count_lines`.** The
    denylist and the byte-counting behaviour live in exactly one place; a
    second implementation here would drift from the first the moment either
    one changed.

  * **Exit 2 on a gate failure, distinct from exit 1 on an unacknowledged
    hit.** A bad `--base`/`--head` ref or a missing git repo is not "no
    violations found" -- it is "the check did not run", and those two must
    never look the same to CI.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import module_scan  # noqa: E402

DEFAULT_TRIPWIRE = 400

# Matches the literal placeholder documenting the syntax -- not a real
# override. `skills/modular-design/SKILL.md` also contains the string
# "Module tripwire: 500 lines." as explanatory prose; that is handled by only
# ever searching inside CLAUDE.md's own `## Architecture` section, never this
# file's text.
_PLACEHOLDER_TRIPWIRE = re.compile(r"Module tripwire:\s*<N>\s*lines\.", re.IGNORECASE)

# A real override: digits only.
_TRIPWIRE_OVERRIDE_RE = re.compile(
    r"Module tripwire:\s*(\d+)\s*lines\.", re.IGNORECASE
)

# `## Architecture` up to the next `##` heading (or end of file).
_ARCHITECTURE_SECTION_RE = re.compile(
    r"^##\s+Architecture\s*$(.*?)(?=^##\s|\Z)", re.IGNORECASE | re.MULTILINE | re.DOTALL
)

# `Module-check: <path> — <free text>` -- accepts "—", "-", or ":" as the
# separator after the path, tolerates surrounding whitespace, and requires
# non-empty free text (whitespace-only is not an acknowledgement).
ACK_RE = re.compile(
    r"Module-check:\s*(?P<path>\S+)\s*[—:-]\s*(?P<text>\S.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def resolve_tripwire(claude_md: Path) -> int:
    """Read the `## Architecture` section of `claude_md` for an override.

    Returns `DEFAULT_TRIPWIRE` when the file is missing, has no `##
    Architecture` section, or that section declares no numeric override --
    including this repo's own case, where the section contains only the
    literal placeholder `Module tripwire: <N> lines.`.
    """
    try:
        text = claude_md.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_TRIPWIRE

    section_match = _ARCHITECTURE_SECTION_RE.search(text)
    if not section_match:
        return DEFAULT_TRIPWIRE
    section = section_match.group(1)

    # Strip the documented placeholder before looking for a real override, so
    # the digits-only regex never has a chance to even see `<N>`.
    section = _PLACEHOLDER_TRIPWIRE.sub("", section)

    override_match = _TRIPWIRE_OVERRIDE_RE.search(section)
    if not override_match:
        return DEFAULT_TRIPWIRE
    return int(override_match.group(1))


class GateError(Exception):
    """Raised when the gate itself could not run -- maps to exit 2."""


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError as exc:
        raise GateError(f"could not run `git {' '.join(args)}` in {repo}: {exc}") from exc


def resolve_refs(repo: Path, base: str | None, head: str) -> tuple[str, str]:
    """Resolve the base ref per the documented precedence.

    `--base` wins when given. Otherwise, in a GitHub Actions PR run,
    `GITHUB_BASE_REF` names the base *branch*, not a ref git understands
    directly -- it must be prefixed with `origin/`. Absent both, default to
    `origin/main`.
    """
    import os

    if base:
        return base, head
    base_branch = os.environ.get("GITHUB_BASE_REF")
    if base_branch:
        return f"origin/{base_branch}", head
    return "origin/main", head


def numstat(repo: Path, base: str, head: str) -> dict[str, tuple[int, int]]:
    """Per-file (added, deleted) line counts for the symmetric difference.

    Raises `GateError` when the diff itself cannot be produced -- a bad ref,
    missing merge base, or `repo` not being a git repository at all.
    """
    # --no-renames: a renamed path would otherwise appear as a single combined
    # "old => new" pathspec in the numstat column, which complicates both the
    # existence check and the acknowledgement path match for no benefit here.
    # Showing a rename as a plain delete + add keeps "skip it if it no longer
    # exists" doing all the work the spec asks of it.
    proc = _run_git(repo, "diff", "--no-renames", "--numstat", f"{base}...{head}")
    if proc.returncode != 0:
        raise GateError(
            f"`git diff --numstat {base}...{head}` failed (exit "
            f"{proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
        )
    result: dict[str, tuple[int, int]] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added_raw, deleted_raw, path = parts
        # Binary files report "-" for both counts; skip, they can't be hits.
        if added_raw == "-" or deleted_raw == "-":
            continue
        result[path] = (int(added_raw), int(deleted_raw))
    return result


def commit_messages(repo: Path, base: str, head: str) -> list[str]:
    """Every commit message in `<base>..<head>` (two dots -- head's ancestry
    minus base's), one entry per commit."""
    proc = _run_git(repo, "log", f"{base}..{head}", "--format=%B%x00")
    if proc.returncode != 0:
        raise GateError(
            f"`git log {base}..{head}` failed (exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return [chunk for chunk in proc.stdout.split("\x00") if chunk.strip()]


def collect_acknowledgements(texts: list[str]) -> dict[str, list[str]]:
    """Parse every `Module-check:` line out of `texts` into {path: [notes]}.

    Keys are normalised to forward slashes so a hit's repo-relative path (also
    forward-slash, from `git diff`) compares equal regardless of how the
    acknowledgement's author typed the path.
    """
    acks: dict[str, list[str]] = {}
    for text in texts:
        for match in ACK_RE.finditer(text):
            path = match.group("path").strip().replace("\\", "/")
            note = match.group("text").strip()
            if not path or not note:
                continue
            acks.setdefault(path, []).append(note)
    return acks


def find_hits(
    repo: Path,
    changes: dict[str, tuple[int, int]],
    tripwire: int,
    excludes: tuple[str, ...],
) -> list[dict]:
    """A hit: over the tripwire at head, excluded-and-existing, and grew."""
    hits: list[dict] = []
    for path, (added, _deleted) in changes.items():
        if added < 1:
            continue
        if module_scan.is_excluded(path, excludes):
            continue
        full_path = repo / path
        if not full_path.exists():
            continue
        lines = module_scan.count_lines(full_path)
        if lines is None:
            continue
        if lines > tripwire:
            hits.append({"path": path, "lines": lines, "added": added})
    hits.sort(key=lambda h: (-h["lines"], h["path"]))
    return hits


def format_failure(hits: list[dict]) -> str:
    lines = ["module-gate: FAIL", ""]
    for hit in hits:
        lines.append(f"  {hit['path']}  {hit['lines']} lines (+{hit['added']})")
    lines.append("  no module verdict found")
    lines.append("")
    lines.append("Add one line to a commit message or the PR body, then re-run:")
    lines.append("")
    example = hits[0]["path"] if hits else "path/to/file.py"
    lines.append(f"  Module-check: {example} — cohesive, one reason to change")
    lines.append("")
    lines.append("Splitting is NOT required. Saying what you found is.")
    lines.append("Run the three tests from the modular-design skill to decide what to say.")
    return "\n".join(lines)


def format_success(hits_acked: list[dict], tripwire: int) -> str:
    lines = [f"module-gate: PASS (tripwire {tripwire} lines)"]
    if hits_acked:
        lines.append("")
        lines.append("  acknowledged:")
        for hit in hits_acked:
            lines.append(f"    {hit['path']}  {hit['lines']} lines (+{hit['added']})")
    else:
        lines.append("  no over-tripwire file grew in this range")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    # The failure banner's "Module-check: <path> — ..." example, and any
    # non-ASCII repo-relative path a hit reports, can carry characters a
    # legacy Windows console (cp1252) cannot encode -- which would turn a
    # correctly-failing gate into a crash indistinguishable from a pass.
    # Reconfigure to UTF-8 up front, before any print (guarded -- a
    # redirected StringIO in tests has no reconfigure).
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description=(
            "Fail a PR that grows an already over-tripwire file without an "
            "acknowledgement of what was found. Splitting is never required."
        ),
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--base", default=None, help="base ref (default: origin/main, or origin/$GITHUB_BASE_REF)")
    parser.add_argument("--head", default="HEAD", help="head ref (default: HEAD)")
    parser.add_argument(
        "--tripwire",
        type=int,
        default=None,
        help="override the tripwire (default: parsed from CLAUDE.md, else 400)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="additional path or filename glob to skip (repeatable)",
    )
    parser.add_argument(
        "--ack-file",
        type=Path,
        default=None,
        help="path to a file (e.g. the PR body) to search for Module-check: lines",
    )
    args = parser.parse_args(argv)

    repo = args.repo
    tripwire = args.tripwire if args.tripwire is not None else resolve_tripwire(repo / "CLAUDE.md")

    try:
        base, head = resolve_refs(repo, args.base, args.head)
        changes = numstat(repo, base, head)
        hits = find_hits(repo, changes, tripwire, tuple(args.exclude))

        texts = commit_messages(repo, base, head)
        if args.ack_file is not None:
            try:
                texts.append(args.ack_file.read_text(encoding="utf-8"))
            except OSError as exc:
                raise GateError(f"could not read --ack-file {args.ack_file}: {exc}") from exc
        acks = collect_acknowledgements(texts)
    except GateError as exc:
        print(f"module-gate: ERROR — {exc}", file=sys.stderr)
        return 2

    unacked = [h for h in hits if h["path"] not in acks]
    acked = [h for h in hits if h["path"] in acks]

    if unacked:
        print(format_failure(unacked))
        return 1

    print(format_success(acked, tripwire))
    return 0


if __name__ == "__main__":
    sys.exit(main())
