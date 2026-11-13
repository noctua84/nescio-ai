#!/usr/bin/env python3
"""CI gate: a PR that adds, crosses, or balloons an over-tripwire file must say what it found.

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

  * **A verdict is required on crossing or substantial growth, not on size.**
    The gate used to flag every changed file that was over the tripwire at
    head. On PR 251 that flagged three files and only one was real: a new
    538-line hook, plus a 1062->1114 edit to `install.py` and a cohesive test
    file gaining cases -- noise that teaches people to write a verdict without
    thinking. A changed file (added >= 1 line, not excluded, readable at head)
    now needs a `Module-check:` only when it is over its tripwire at head AND
    one of these holds:
      - `new`: absent at the merge base. Born big.
      - `crossed`: at or under the tripwire at the merge base, over it now.
      - `grew`: already over at the merge base and net growth is at least
        `min(growth_lines, ceil(base * growth_percent / 100))` (150 lines /
        25% by default). The percentage catches a mid-size file ballooning;
        the line cap stops a huge file absorbing a whole module unnoticed.
    Any other over-tripwire file is *listed* as informational and passes. A
    file that only shrank is never nagged about -- exactly the outcome the
    doctrine wants.

  * **Growth is *net* (head lines minus merge-base lines), not `added`.** A
    rewrite that churns 300 lines but ends the same size has not ballooned;
    gross `added` would flag it, and the verdict would be a sentence written
    to clear a gate.

  * **Test files use a higher tripwire** (`module_scan.is_test_file`,
    `DEFAULT_TEST_TRIPWIRE = 800`): each case is independent, so length there
    says little about tangled responsibilities. The production default of 400
    is unchanged.

  * **"Before" is the merge base, not the base ref's tip.** The PR's own
    commits are `merge_base..head`; comparing against base's tip would count
    main's unrelated growth of the same file as this PR's. A failure to find a
    merge base is a `GateError` (exit 2), never a quiet fallback.

  * **Reuses `module_scan.is_excluded` and `module_scan.count_lines_from_bytes`.**
    The denylist and the byte-counting behaviour live in exactly one place; a
    second implementation here would drift from the first the moment either
    one changed.

  * **Size comes from the `head` ref's blob (`git show <head>:<path>`), never
    the working tree.** `--head` must be reproducible for a ref that is not
    checked out locally. Reading `repo / path` off disk instead answers for
    whatever happens to be on disk, which fails open the moment the checkout
    disagrees with `head` -- see issue #194, which this file used to get wrong.

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

DEFAULT_TRIPWIRE = module_scan.DEFAULT_TRIPWIRE
DEFAULT_TEST_TRIPWIRE = module_scan.DEFAULT_TEST_TRIPWIRE
DEFAULT_GROWTH_LINES = module_scan.DEFAULT_GROWTH_LINES
DEFAULT_GROWTH_PERCENT = module_scan.DEFAULT_GROWTH_PERCENT

# Config parsing lives in `module_scan` so the report and the gate read the
# same CLAUDE.md the same way; re-exported here for callers of the gate.
TripwireConfig = module_scan.TripwireConfig
resolve_config = module_scan.resolve_config

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
    literal placeholder `Module tripwire: <N> lines.`. Kept as a thin wrapper
    over `resolve_config` (the full set of thresholds) for existing callers.
    """
    return resolve_config(claude_md).tripwire


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


def read_blob_at_ref(repo: Path, ref: str, path: str) -> bytes | None:
    """Bytes of `path` as it exists at `ref`, or None when it doesn't.

    `text=False` (the default for `subprocess.run`) is deliberate: a text-mode
    `git show` would have `subprocess` translate `\\r\\n` to `\\n` on Windows,
    which would corrupt both the line count this feeds into and the null-byte
    binary sniff it feeds into first. Both the gate itself and its test suite
    run on a Windows dev box, so this would not even show up in CI, which runs
    on Linux and would silently mask it.

    A nonzero exit (missing path at this ref -- most commonly a file the diff
    shows as deleted, which cannot be read back from `head`) returns None
    rather than raising: the caller's job is to skip it, the same as the
    pre-ref-based code did via `full_path.exists()`.
    """
    proc = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def merge_base_of(repo: Path, base: str, head: str) -> str:
    """The merge base of `base` and `head` -- the "before" for every file.

    A failure is a `GateError`, never a fallback to `base`'s tip: comparing
    against the tip would attribute main's own growth of a file to this PR,
    and quietly answering the wrong question is worse than not running.
    """
    proc = _run_git(repo, "merge-base", base, head)
    sha = proc.stdout.strip()
    if proc.returncode != 0 or not sha:
        raise GateError(
            f"`git merge-base {base} {head}` failed (exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip() or 'no common ancestor'}"
        )
    return sha.splitlines()[0]


def classify_changes(
    repo: Path,
    head: str,
    changes: dict[str, tuple[int, int]],
    tripwire: int,
    excludes: tuple[str, ...],
    *,
    merge_base: str | None = None,
    test_tripwire: int = DEFAULT_TEST_TRIPWIRE,
    growth_lines: int = DEFAULT_GROWTH_LINES,
    growth_percent: int = DEFAULT_GROWTH_PERCENT,
) -> list[dict]:
    """Every changed file that is over its tripwire at head, classified.

    Each entry: `path`, `lines` (at head), `added`, `base_lines` (at the merge
    base; None when absent or binary there), `growth` (net, head minus base;
    the whole file when there is no base), `tripwire` (the one that applied),
    `reason` and `required`. Reasons: `new`, `crossed`, `grew` (all
    `required`) and `small` (over the tripwire, but only a small edit to an
    already-large file -- informational, never blocks).

    `growth` is *net*, deliberately: a rewrite that churns hundreds of lines
    but ends the same size has not ballooned the file, and gross `added`
    would demand a verdict for it.

    With `merge_base=None` there is no "before" to compare against, so every
    changed over-tripwire file is treated as `new` -- the strictest reading,
    chosen because the failure mode of the alternative is a gate that
    silently stops asking.

    Sizes come from git blobs (`head` and the merge base), never the working
    tree: `--head` must be reproducible for a ref that is not checked out
    locally, and a working-tree read answers for whatever happens to be on
    disk, which fails open the moment the checkout disagrees with `head`
    (issue 194).
    """
    entries: list[dict] = []
    for path, (added, _deleted) in changes.items():
        if added < 1:
            continue
        if module_scan.is_excluded(path, excludes):
            continue
        data = read_blob_at_ref(repo, head, path)
        if data is None:
            continue
        lines = module_scan.count_lines_from_bytes(data)
        if lines is None:
            continue

        limit = test_tripwire if module_scan.is_test_file(path) else tripwire
        if lines <= limit:
            continue

        base_lines: int | None = None
        if merge_base is not None:
            base_data = read_blob_at_ref(repo, merge_base, path)
            if base_data is not None:
                base_lines = module_scan.count_lines_from_bytes(base_data)

        growth = lines - (base_lines or 0)
        growth_limit: int | None = None
        if base_lines is None:
            reason, required = "new", True
        elif base_lines <= limit:
            reason, required = "crossed", True
        else:
            growth_limit = module_scan.growth_threshold(
                base_lines, growth_lines, growth_percent
            )
            if growth >= growth_limit:
                reason, required = "grew", True
            else:
                reason, required = "small", False
        entries.append(
            {
                "path": path,
                "lines": lines,
                "added": added,
                "base_lines": base_lines,
                "growth": growth,
                "growth_limit": growth_limit,
                "tripwire": limit,
                "reason": reason,
                "required": required,
            }
        )
    entries.sort(key=lambda e: (-e["lines"], e["path"]))
    return entries


def find_hits(
    repo: Path,
    head: str,
    changes: dict[str, tuple[int, int]],
    tripwire: int,
    excludes: tuple[str, ...],
    *,
    merge_base: str | None = None,
    test_tripwire: int = DEFAULT_TEST_TRIPWIRE,
    growth_lines: int = DEFAULT_GROWTH_LINES,
    growth_percent: int = DEFAULT_GROWTH_PERCENT,
) -> list[dict]:
    """The entries from `classify_changes` that need a `Module-check:` verdict
    (reason `new`, `crossed` or `grew`). See `classify_changes` for the shape."""
    return [
        entry
        for entry in classify_changes(
            repo,
            head,
            changes,
            tripwire,
            excludes,
            merge_base=merge_base,
            test_tripwire=test_tripwire,
            growth_lines=growth_lines,
            growth_percent=growth_percent,
        )
        if entry["required"]
    ]


def describe(entry: dict) -> str:
    """One-line, assertable description of a classified entry."""
    lines, added, tripwire = entry["lines"], entry["added"], entry["tripwire"]
    reason, base = entry["reason"], entry["base_lines"]
    if reason == "new":
        return f"[new]  new file, {lines} lines (+{added}, tripwire {tripwire})"
    growth = f"{entry['growth']:+d}"
    detail = f"{base} -> {lines} lines ({growth} net, tripwire {tripwire}"
    if reason == "crossed":
        return f"[crossed]  {detail})"
    limit = entry["growth_limit"]
    return f"[{reason}]  {detail}, growth limit +{limit})"


def format_failure(hits: list[dict]) -> str:
    lines = ["module-gate: FAIL", ""]
    for hit in hits:
        lines.append(f"  {hit['path']}  {describe(hit)}")
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


INFORMATIONAL_HEADING = "over tripwire, small change: no verdict needed"


def format_success(
    hits_acked: list[dict],
    tripwire: int,
    informational: list[dict] | None = None,
    test_tripwire: int = DEFAULT_TEST_TRIPWIRE,
) -> str:
    lines = [
        f"module-gate: PASS (tripwire {tripwire} lines, test files {test_tripwire})"
    ]
    if hits_acked:
        lines.append("")
        lines.append("  acknowledged:")
        for hit in hits_acked:
            lines.append(f"    {hit['path']}  {describe(hit)}")
    if informational:
        lines.append("")
        lines.append(f"  {INFORMATIONAL_HEADING}:")
        for entry in informational:
            lines.append(f"    {entry['path']}  {describe(entry)}")
    if not hits_acked and not informational:
        lines.append("  no over-tripwire file was added, crossed, or grown in this range")
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
            "Fail a PR that adds, crosses, or substantially grows an over-tripwire file without an "
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
        "--test-tripwire",
        type=int,
        default=None,
        help="override the test-file tripwire (default: parsed from CLAUDE.md, else 800)",
    )
    parser.add_argument(
        "--growth-lines",
        type=int,
        default=None,
        help=(
            "net lines an already-over-tripwire file must gain to need a "
            "verdict, capped by --growth-percent (default: CLAUDE.md, else 150)"
        ),
    )
    parser.add_argument(
        "--growth-percent",
        type=int,
        default=None,
        help=(
            "percent of its base size an already-over-tripwire file must "
            "gain to need a verdict (default: CLAUDE.md, else 25)"
        ),
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
    # Precedence per field: CLI flag, then CLAUDE.md, then the default.
    config = resolve_config(repo / "CLAUDE.md")
    tripwire = args.tripwire if args.tripwire is not None else config.tripwire
    test_tripwire = (
        args.test_tripwire if args.test_tripwire is not None else config.test_tripwire
    )
    growth_lines = (
        args.growth_lines if args.growth_lines is not None else config.growth_lines
    )
    growth_percent = (
        args.growth_percent if args.growth_percent is not None else config.growth_percent
    )

    try:
        base, head = resolve_refs(repo, args.base, args.head)
        changes = numstat(repo, base, head)
        merge_base = merge_base_of(repo, base, head)
        classified = classify_changes(
            repo,
            head,
            changes,
            tripwire,
            tuple(args.exclude),
            merge_base=merge_base,
            test_tripwire=test_tripwire,
            growth_lines=growth_lines,
            growth_percent=growth_percent,
        )
        hits = [e for e in classified if e["required"]]
        informational = [e for e in classified if not e["required"]]

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

    print(format_success(acked, tripwire, informational, test_tripwire))
    return 0


if __name__ == "__main__":
    sys.exit(main())
