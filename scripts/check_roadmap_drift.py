#!/usr/bin/env python3
"""Reconcile `ROADMAP.md` against the issues GitHub says are planned work (#60).

`ROADMAP.md` duplicates state GitHub owns — which issues are open, and which
milestone each belongs to — with nothing detecting divergence. It has drifted
three times. This script is the detector.

**It never writes.** Not to `ROADMAP.md`, not to any file, not to GitHub. The
file's bullets carry hand-written editorial clauses deliberately trimmed from the
issue titles (#53's bullet is shorter and clearer than #53's title; several carry
judgements that appear in no issue at all). A generator emitting raw titles would
replace all of that with more verbose, less considered text, so the design is a
checker, not a generator — the same conclusion `scripts/compute_readiness.py`
reached from the other direction, after this repo shipped a generator that
destroyed human prose (#25, fixed in #45).

**The failure mode is OMISSION, not tag rot.** A full audit found that after 68
commits and three releases of drift, *every* milestone tag in the file was still
correct. The real drift was two issues closed-but-still-listed and seven open
issues never added. #60 proposes policing tags; tags are not what rots.
Membership is. This script checks both, but it is aimed at membership.

**Membership is an allow-list, not a bijection.** Only issues a maintainer has
labelled `roadmap` are expected to appear here. An earlier design asserted a
bijection against *all* open issues, on the evidence that the two sets matched
exactly — but that match was an artefact of 100% solo authorship. This repo is
public, MIT, and carries `good first issue` and `help wanted`; the first outside
bug report would have redded the build with no escape hatch. So an open issue
that is neither labelled nor referenced is a non-event, by design.

**The `open_issues` gotcha (#60 names it, and it is still live).** The milestones
API reports an `open_issues` count that includes pull requests. It happens to
agree with the filtered issue count today only because no PR is currently
milestoned. Nothing in this script may read that field: per-milestone counts are
derived from the issue list with pull requests filtered out. The gotcha is
silent right now and bites the first time a PR is assigned to a milestone.

Exit codes are three-valued, mirroring `scripts/verify_commit_position.py`, so a
caller can tell "the file is wrong" from "the check could not run":

  0  checks passed (advisory findings may still print)
  1  a hard check reported drift
  2  could not check — the reconciliation half could not reach GitHub

This module holds the parser, the offline checks, and the CLI. The network half
(`fetch_issue_state` and the five reconciliation checks) is a later task; the
stub below is the single seam every network call goes through, which is what
keeps the test suite hermetic.

Usage:
    python scripts/check_roadmap_drift.py --offline      # no network, ever
    python scripts/check_roadmap_drift.py --json         # machine-readable
    python scripts/check_roadmap_drift.py --roadmap PATH
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ROADMAP = REPO_DIR / "ROADMAP.md"

# The repository whose issues `ROADMAP.md` may cite. A link pointing anywhere
# else is drift, not a reference.
REPO = "noctua84/nescio-ai"

# Membership in the roadmap is **maintainer-asserted opt-in**: an issue earns a
# line when someone applies this label at triage, never at filing. GitHub already
# enforces that — applying a label requires the *triage* role or above, so an
# outside contributor cannot self-apply it and cannot force a line onto this
# file. That permission property is what makes the allow-list safe on a public
# repo; it is not a convention anyone has to remember.
ROADMAP_LABEL = "roadmap"

# The tag vocabulary, and what each tag claims about GitHub state. Declared here
# rather than derived, because a checker that learns its own expectations from
# the thing it is checking cannot detect drift. `check_milestone_vocabulary` (a
# later task, network side) is what keeps this table honest: it fails if a
# milestone holding roadmap-labelled work has no tag, or if a value here no
# longer names a real open milestone.
TAG_TO_MILESTONE = {
    "loop": "Loop integrity",
    "readiness": "Readiness signal",
    "cross-repo": "Cross-repo knowledge",
    "parked": "Parked",
}

# Sections excluded from every issue-reference check. `## Shipped` is a *history*
# section — it may legitimately cite an issue that is closed, which is exactly
# what the reconciliation checks flag everywhere else. The intro/legend paragraph
# (everything before the first `##`) is excluded too: its bare
# `https://github.com/noctua84/nescio-ai/issues` link carries no `/N` and must
# not be mistaken for a reference to issue-something.
#
# This is an explicit set rather than an accident of the regex so that adding an
# exclusion is a visible decision. A section is excluded by the text before its
# em dash, so `## Shipped — anything` is still excluded.
EXCLUDED_SECTIONS = {"Shipped"}

# Exit codes, named so the distinction between "failed" and "could not check" is
# explicit at every return site. Mirrors `verify_commit_position.py`.
EXIT_PASS = 0
EXIT_DRIFT = 1
EXIT_ERROR = 2

# Finding severities. The asymmetry is deliberate and is argued in the plan's
# "Direction semantics": an advisory finding is one whose remedy is GitHub
# metadata that no commit in this repo can carry, so a red build would block the
# wrong person. Advisories print loudly and never change the exit code.
SEVERITY_HARD = "hard"
SEVERITY_ADVISORY = "advisory"

# The narrow [#N](.../issues/N) anchor is LOAD-BEARING, not incidental. ROADMAP.md
# has historically contained bare "#N" in prose — before commit 5281661 amended
# the file, line 59 read "(in tension with #53 …)" and line 90 read "fixed in #83",
# and **#83 is a merged PR, not an issue**. Those two bullets are gone today, so
# the traps are currently latent rather than live; that is a property of this
# week's text, not a guarantee. Loosening this to a bare r"#(\d+)" would make
# ordinary editorial prose fail three checks at once (uniqueness, membership,
# closed-ref). Do not "simplify" it.
#
# Nor may this be replaced by a shell `grep`. Verified in this repo's own
# environment: Git Bash strips the backslash from '\[?#[0-9]+', turning it into a
# character class that matches "84" inside every `noctua84` URL — a parser that
# invents phantom references. All parsing here is Python `re`.
#
# The link *text* may be `#43` or carry a prefix (`[Epic #43](…)`), which is how
# the two epic headings reference their issues. The URL is captured loosely on
# purpose: `check_link_wellformed` is what validates host, repo, and number, and
# it can only flag a wrong-host link if the parser was willing to see it.
_REFERENCE_RE = re.compile(r"\[(?:[^\]]*\s)?#(\d+)\]\(([^)\s]+)\)")

# A well-formed reference URL: this repo, the issues path, and nothing after it.
_ISSUE_URL_RE = re.compile(
    r"^https://github\.com/" + re.escape(REPO) + r"/issues/(\d+)$"
)

# `## ` starts a section. Deeper headings (`###`) stay inside their parent, so a
# sub-heading under `## Shipped` inherits the exclusion.
_SECTION_RE = re.compile(r"^##\s+(.*\S)\s*$")

# A list item. Bullet continuation lines (indented, no marker) are not items, so
# a link on one is treated as commentary — see the primary-reference rule below.
_BULLET_RE = re.compile(r"^\s*[-*]\s+")

# A bullet's milestone tag: a backticked word immediately after the list marker,
# before the reference link. Anchored so a backticked word *inside* a bullet's
# prose (`CLAUDE.md`, `readiness.md`) can never be read as a tag.
_TAG_RE = re.compile(r"^\s*[-*]\s+`([^`]+)`")


@dataclass(frozen=True)
class Entry:
    """One primary issue reference in `ROADMAP.md`.

    `number` is the number the file *displays* (`[#53]`), not the one its URL
    points at. The displayed number is the claim a reader takes away, so it is
    what the reconciliation checks reason about; `check_link_wellformed` is the
    guard that the two never disagree silently.

    `url` is carried raw rather than validated at parse time so that a wrong-host
    or mismatched link survives into the checks that exist to report it.

    `tag` is None for an untagged bullet and always None for a heading — epics
    are unmilestoned, and the tag rule exempts headings.
    """

    number: int
    tag: str | None
    kind: str  # "bullet" | "heading"
    line_no: int  # 1-based, matching what an editor shows
    url: str


@dataclass(frozen=True)
class Finding:
    """One thing a check has to say, and how much it should cost.

    `str(finding)` is the human-readable line; `severity` is what `main()`
    consults for the exit code. Findings are objects rather than bare strings so
    the advisory channel exists from the start — retrofitting severity onto
    strings later is how an advisory becomes a hard failure by accident.
    """

    check: str
    message: str
    severity: str = SEVERITY_HARD

    def __str__(self) -> str:
        return self.message


def _section_title(heading_text: str) -> str:
    """The name a `##` heading declares, minus any trailing ` — [Epic #N](…)`.

    Split on the em dash the file uses for heading annotations, so exclusion
    matches on the section's actual name rather than on its decoration.
    """
    return heading_text.split("—", 1)[0].strip()


def parse_roadmap(text: str) -> tuple[list[Entry], list[str]]:
    """Extract the primary issue references from `ROADMAP.md` text.

    Returns ``(entries, notes)``. `notes` records every issue-shaped link the
    parser deliberately did *not* turn into an entry, with the reason — so the
    discards are auditable rather than silent. Nothing in `notes` is a finding.

    **Primary reference rule.** A line contributes at most one entry: the *first*
    ``[#N](url)`` link on it. Any further issue link later on the same line is
    commentary and is discarded. Linking a cross-reference is an ordinary
    editorial act; without this rule a single such link would trip uniqueness,
    membership, and the closed-reference check simultaneously. No line in the
    file carries two links today — this is forward-protection, and it costs one
    `break`.

    Only `##` headings and list items produce entries. A reference in a plain
    prose paragraph is ignored (and noted): the model here is exactly the two
    shapes the file uses, and inventing a third kind is not this parser's call.

    Bullets with no issue link at all — "A2", "Layer B", "Crew benchmarking" —
    are tolerated and produce nothing. They are roadmap items that are not yet
    tracked as issues, which is a legitimate state, not drift.
    """
    entries: list[Entry] = []
    notes: list[str] = []
    section: str | None = None  # None == the intro/legend, always excluded

    for line_no, line in enumerate(text.splitlines(), start=1):
        heading = _SECTION_RE.match(line)
        if heading:
            section = _section_title(heading.group(1))

        excluded = section is None or section in EXCLUDED_SECTIONS
        is_heading = heading is not None
        is_bullet = bool(_BULLET_RE.match(line))

        matches = list(_REFERENCE_RE.finditer(line))
        if not matches:
            continue

        if excluded:
            where = "the intro/legend" if section is None else f"the '{section}' section"
            for m in matches:
                notes.append(
                    f"line {line_no}: reference to #{m.group(1)} ignored — "
                    f"{where} is excluded from reference checks"
                )
            continue

        if not (is_heading or is_bullet):
            for m in matches:
                notes.append(
                    f"line {line_no}: reference to #{m.group(1)} ignored — "
                    "not a heading or a list item"
                )
            continue

        primary, *commentary = matches
        tag_match = None if is_heading else _TAG_RE.match(line)
        entries.append(
            Entry(
                number=int(primary.group(1)),
                tag=tag_match.group(1) if tag_match else None,
                kind="heading" if is_heading else "bullet",
                line_no=line_no,
                url=primary.group(2),
            )
        )
        for m in commentary:
            notes.append(
                f"line {line_no}: link to #{m.group(1)} treated as commentary — "
                f"the line's primary reference is #{primary.group(1)}"
            )

    return entries, notes


# ── offline checks ─────────────────────────────────────────────────────────
# Each takes the parsed entries and returns findings. None of them touch the
# network, the filesystem, or `gh`, which is why they can run on a fork, on a
# contributor's laptop with no token, and inside the hermetic test suite.


def check_unique_references(entries: list[Entry]) -> list[Finding]:
    """No issue is the primary reference of two different lines.

    Two bullets for one issue means one of them is stale, or the same work is
    claimed by two sections. Commentary links are exempt — they never became
    entries, so they cannot collide.
    """
    seen: dict[int, list[int]] = {}
    for entry in entries:
        seen.setdefault(entry.number, []).append(entry.line_no)

    findings = []
    for number, lines in sorted(seen.items()):
        if len(lines) > 1:
            where = ", ".join(f"line {n}" for n in lines)
            findings.append(
                Finding(
                    "unique-references",
                    f"#{number} is the primary reference of {len(lines)} lines "
                    f"({where}) — one of them is stale; keep a single bullet and "
                    "link the other as commentary if a cross-reference is meant.",
                )
            )
    return findings


def check_link_wellformed(entries: list[Entry]) -> list[Finding]:
    """The displayed `#N` matches the `issues/N` its link points at.

    Two distinct failures, reported distinctly: a link that does not point at
    this repo's issues at all, and a link that does but names a different number
    than the text. The second is the dangerous one — the file reads correctly
    while sending every reader somewhere else, and every downstream
    reconciliation check reasons about the number the *reader* sees.
    """
    findings = []
    for entry in entries:
        m = _ISSUE_URL_RE.match(entry.url)
        if m is None:
            findings.append(
                Finding(
                    "link-wellformed",
                    f"line {entry.line_no}: #{entry.number} does not link to "
                    f"https://github.com/{REPO}/issues/{entry.number} — got "
                    f"{entry.url!r}",
                )
            )
        elif int(m.group(1)) != entry.number:
            findings.append(
                Finding(
                    "link-wellformed",
                    f"line {entry.line_no}: text says #{entry.number} but the "
                    f"link points at issue {m.group(1)} — the reader and the "
                    "checker would follow different issues.",
                )
            )
    return findings


def check_tag_vocabulary(entries: list[Entry]) -> list[Finding]:
    """Every tag used is a key of `TAG_TO_MILESTONE`.

    This is the whole check. An earlier draft also string-matched the backticked
    tags against the legend paragraph at the top of the file; that half was cut
    deliberately, not forgotten. Matching generated expectations against
    hand-written prose is the same brittleness that got a prose-level README
    check rejected — it fails the moment someone rewords a sentence correctly.
    Do not restore it as an oversight.

    Whether a tag is the *right* one for its issue is a different question, and
    it needs GitHub state; `check_tag_agreement` (network side) answers it.
    """
    known = ", ".join(sorted(TAG_TO_MILESTONE))
    return [
        Finding(
            "tag-vocabulary",
            f"line {entry.line_no}: #{entry.number} is tagged `{entry.tag}`, "
            f"which is not a known milestone tag ({known}).",
        )
        for entry in entries
        if entry.tag is not None and entry.tag not in TAG_TO_MILESTONE
    ]


# Name → check. The names are what the report prints as PASS/FAIL, and what a
# reader greps for when a build goes red.
OFFLINE_CHECKS = (
    ("unique-references", check_unique_references),
    ("link-wellformed", check_link_wellformed),
    ("tag-vocabulary", check_tag_vocabulary),
)


def run_offline_checks(entries: list[Entry]) -> list[tuple[str, list[Finding]]]:
    """Run every offline check and return `(name, findings)` in report order.

    All of them run; none short-circuits. A report that stops at the first
    failure makes a reviewer fix one thing, push, and wait to discover the next.
    """
    return [(name, check(entries)) for name, check in OFFLINE_CHECKS]


# ── the network seam ───────────────────────────────────────────────────────


def fetch_issue_state(repo: str = REPO) -> tuple[object | None, str | None]:
    """The one and only place this script may touch the network.

    Returns ``(state, None)`` on success and ``(None, reason)`` on any failure —
    it must never raise. Every reconciliation check takes already-fetched state
    as a parameter, which is what makes the test suite hermetic: there is no call
    to guard, because this function is the seam.

    **Not implemented yet.** The `gh` fetch, the pull-request filter, explicit
    pagination, and the degradation contract are a later task. Until then this
    returns the honest answer — "could not check" — rather than an empty state
    that would look like "nothing to reconcile" and quietly pass.
    """
    return None, "not implemented"


# ── reporting ──────────────────────────────────────────────────────────────


def _summarise(entries: list[Entry]) -> str:
    bullets = sum(1 for e in entries if e.kind == "bullet")
    headings = sum(1 for e in entries if e.kind == "heading")
    tagged = sum(1 for e in entries if e.tag)
    return (
        f"{len(entries)} references — {bullets} bullet, {headings} heading; "
        f"{tagged} tagged"
    )


def render_report(
    roadmap: Path,
    entries: list[Entry],
    notes: list[str],
    results: list[tuple[str, list[Finding]]],
    fetch_reason: str | None,
    offline: bool,
) -> list[str]:
    """Build the human report as lines. The caller prints them."""
    tags = " | ".join(
        f"{tag} → {milestone}" for tag, milestone in TAG_TO_MILESTONE.items()
    )
    lines = [
        f"roadmap:  {roadmap}",
        f"entries:  {_summarise(entries)}",
        f"tags:     {tags}",
        "",
    ]

    for name, findings in results:
        if not findings:
            lines.append(f"PASS  {name}")
            continue
        hard = [f for f in findings if f.severity == SEVERITY_HARD]
        lines.append(f"{'FAIL' if hard else 'note'}  {name}")
        for finding in findings:
            prefix = "      " if finding.severity == SEVERITY_HARD else "      (advisory) "
            lines.append(f"{prefix}{finding}")

    if notes:
        lines.append("")
        lines.append("ignored (not findings):")
        lines.extend(f"      {note}" for note in notes)

    lines.append("")
    if offline:
        lines.append(
            "offline mode: reconciliation against GitHub was not attempted."
        )
    elif fetch_reason is not None:
        lines.append(f"could not check — {fetch_reason}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Reconcile ROADMAP.md against the issues GitHub says are planned "
            "work. Read-only: this never writes ROADMAP.md or anything else."
        ),
    )
    ap.add_argument(
        "--roadmap",
        default=str(DEFAULT_ROADMAP),
        help="path to ROADMAP.md (default: this repo's ROADMAP.md)",
    )
    ap.add_argument(
        "--offline",
        action="store_true",
        help="run only the checks that need no network; never exits 2",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="print the findings as JSON instead of a report",
    )
    args = ap.parse_args(argv)

    # The report prints → and — glyphs, bullet text, and (once the network half
    # lands) issue titles. A legacy Windows console defaults to cp1252 and would
    # raise UnicodeEncodeError while formatting a *successful* run's output —
    # this repo has already shipped that bug once (#55, and #71 is the same class
    # still open). Guarded, because a redirected StringIO in tests has no
    # `reconfigure`.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    roadmap = Path(args.roadmap)
    try:
        text = roadmap.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: could not read {roadmap}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    entries, notes = parse_roadmap(text)

    # R6: the offline checks always run, and always run first. A failed fetch
    # never suppresses what could be determined without one — the report says
    # what it knows before it says what it could not find out.
    results = run_offline_checks(entries)

    fetch_reason: str | None = None
    if not args.offline:
        _state, fetch_reason = fetch_issue_state()
        # The reconciliation checks consume `_state` here once they exist. While
        # `fetch_issue_state` is a stub they cannot run, and a fetch that
        # returned nothing is reported as "could not check", never as "clean".

    findings = [f for _, fs in results for f in fs]
    hard = [f for f in findings if f.severity == SEVERITY_HARD]

    # R5 exit semantics, in precedence order. A definite finding outranks an
    # unknown: drift plus a failed fetch is 1, not 2, because the drift is real
    # whether or not GitHub was reachable.
    if hard:
        rc = EXIT_DRIFT
    elif fetch_reason is not None:
        rc = EXIT_ERROR  # unreachable under --offline; see R7
    else:
        rc = EXIT_PASS

    if args.json:
        print(
            json.dumps(
                {
                    "roadmap": roadmap.as_posix(),
                    "offline": bool(args.offline),
                    "exit": rc,
                    "fetch_reason": fetch_reason,
                    "entries": [
                        {
                            "number": e.number,
                            "tag": e.tag,
                            "kind": e.kind,
                            "line_no": e.line_no,
                            "url": e.url,
                        }
                        for e in entries
                    ],
                    "findings": [
                        {
                            "check": f.check,
                            "severity": f.severity,
                            "message": f.message,
                        }
                        for f in findings
                    ],
                    "ignored": notes,
                    "tag_to_milestone": TAG_TO_MILESTONE,
                },
                indent=2,
            )
        )
    else:
        for line in render_report(
            roadmap, entries, notes, results, fetch_reason, bool(args.offline)
        ):
            print(line)

    # R10: exit 2 must name its reason on stderr, never a bare traceback and
    # never a bare "failed".
    if rc == EXIT_ERROR:
        print(f"roadmap: could not check — {fetch_reason}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
