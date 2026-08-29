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

This module holds the parser, the offline checks, the reconciliation checks, and
the CLI. `fetch_issue_state` is the single seam every network call goes through —
every check takes already-fetched state as a parameter, which is what keeps the
test suite hermetic.

**One check looks at `README.md` instead — and its scope is narrow.**
`check_readme` asserts that the `## Roadmap` section of `README.md` links to
`ROADMAP.md` and lists no individual issue numbers. That is the *whole* claim.
It does not stop the duplication class in general: enumerable issue state can
still relocate to another README section, to `CONTRIBUTING.md`, to `docs_site/`,
or to a wiki, and none of those would be seen here. It also makes no claim about
whether the section's prose is *accurate* — "is this paragraph still a fair
characterisation" needs judgement no string match has, and stays a human
responsibility. What it buys is that the one place the summary already lives
cannot quietly grow a second copy of the issue list.

**The four reconciliation directions are deliberately asymmetric.** Let L be the
open issues labelled `roadmap` and R the primary references in this file:

  D1  n ∈ L, n ∉ R                    → drift (exit 1)
  D2  n ∈ R, not an open issue        → drift (exit 1)
  D3  n ∈ R, open, unlabelled         → ADVISORY (exit 0), printed
  D4  n ∉ L, n ∉ R                    → silent; a non-event, by design

D3 is advisory because **its remedy is not in this repository.** No commit and no
pull request can apply a GitHub label, so a red build here would block a
contributor who has no way to clear it. D1 and D2 are hard because their remedy
is one line in this file, in the same commit-space as the check.

Usage:
    python scripts/check_roadmap_drift.py --offline      # no network, ever
    python scripts/check_roadmap_drift.py --json         # machine-readable
    python scripts/check_roadmap_drift.py --roadmap PATH --readme PATH
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ROADMAP = REPO_DIR / "ROADMAP.md"
DEFAULT_README = REPO_DIR / "README.md"

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

# R3: every `gh` invocation is bounded, so this can never hang a CI job.
GH_TIMEOUT = 30

# R4: one retry, after a short sleep, absorbs the common transient 502 without
# masking a real outage. A rate limit is *not* retried — retrying makes it worse.
# Module-level so a test can shrink it rather than sleep for real.
RETRY_SLEEP_SECONDS = 5.0

# R12: pagination is explicit and bounded. 20 pages × 100 is far more headroom
# than this repo will ever need, and it means a pathological API response cannot
# spin the loop forever.
PER_PAGE = 100
MAX_PAGES = 20

# D2 resolves each unknown reference with its own API call, to tell "closed" from
# "never existed / is a PR". That is one request per number, so it is bounded: a
# file that has gone badly stale (or a malicious edit adding 500 bogus links)
# must not turn one check into a request storm. Past the bound the numbers are
# still reported — just without the closed-vs-missing detail.
MAX_INDIVIDUAL_RESOLUTIONS = 20

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


@dataclass(frozen=True)
class Issue:
    """One open issue, projected down to the three fields this script reasons about.

    Pull requests never become an `Issue` — they are filtered out at the fetch,
    which is the #60 gotcha made structural rather than remembered.
    """

    number: int
    milestone: str | None
    labels: tuple[str, ...]

    @property
    def is_roadmap(self) -> bool:
        return ROADMAP_LABEL in self.labels


@dataclass(frozen=True)
class IssueState:
    """Everything the reconciliation checks are allowed to know about GitHub.

    Built once by `fetch_issue_state` and passed to every check, so the checks
    themselves are pure functions over injected data — that is the seam the
    hermetic tests inject at.

    `issues` holds only *open, non-PR* issues, keyed by number. `milestones` is
    the open milestone titles. `resolved` answers "what is this number, then?"
    for references absent from `issues`: ``"closed"``, ``"missing"`` (no such
    number, or it is a pull request), or ``"open"`` (raced with the list call).
    `unresolved` names references deliberately left un-looked-up because
    `MAX_INDIVIDUAL_RESOLUTIONS` was exceeded — reported, but without detail.
    """

    issues: dict[int, Issue] = field(default_factory=dict)
    milestones: tuple[str, ...] = ()
    resolved: dict[int, str] = field(default_factory=dict)
    unresolved: tuple[int, ...] = ()

    def labelled(self) -> set[int]:
        """The allow-list: open issues a maintainer has declared to be planned work."""
        return {n for n, issue in self.issues.items() if issue.is_roadmap}


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


# ── the README guard ───────────────────────────────────────────────────────
# Offline like the three above, but it reads a *different file*, so it takes
# `readme_text` rather than `entries` and is called on its own (see `main`).

# The one section of the one file this guard covers. Both are named as constants
# so the narrowness is visible at a glance rather than buried in a regex.
README_SECTION = "Roadmap"
README_CHECK = "readme-scope"

# The named escape. A maintainer with a real reason to cite one issue from that
# section adds this line to it; the alternative is patching this script, which
# turns a legitimate exception into a reason to delete the check.
README_ALLOW_MARKER = "<!-- roadmap-check: allow -->"

# "Enumerable issue state" means a link that names an *individual* issue number.
# The bare `https://github.com/noctua84/nescio-ai/issues` link the section
# already carries has no `/N`, so it is a pointer at the tracker rather than a
# copy of anything in it — exactly what belongs there, and the trailing `\d+` is
# what keeps it legal.
#
# Deliberately not anchored to this repo's host: an enumerated issue list is a
# second copy that drifts whichever tracker it names, and the escape marker is
# there for the case where one is wanted anyway.
_README_ISSUE_RE = re.compile(r"issues/(\d+)")

# A markdown link whose target is ROADMAP.md. Matching the link *target* rather
# than the bare string means a passing mention of the filename in prose does not
# satisfy the check.
_README_ROADMAP_LINK_RE = re.compile(r"\]\([^)]*ROADMAP\.md[^)]*\)")


def check_readme(readme_text: str) -> list[Finding]:
    """`README.md`'s `## Roadmap` section stays a pointer, not a second copy.

    Two assertions over that section and nothing else: it links to `ROADMAP.md`,
    and it names no individual issue numbers.

    **Scope, stated accurately.** This guards *one section of one file*. It is
    not a guard against the duplication class in general — the same state can
    relocate to another README section, to `CONTRIBUTING.md`, to `docs_site/`,
    or to a wiki, and this check would see none of it. Nor does it say anything
    about whether the prose there is *true*; #60 asked for that and the answer
    was that verifying "earned per-repo autonomy is parked" against a milestone
    means string-matching prose against headings, which fails the moment someone
    rewords a sentence correctly. That stays a human judgement, named here as a
    limitation rather than quietly dropped.

    Why the check is inverted this way at all: README's summary is prose with no
    issue numbers in it, so there is nothing to reconcile mechanically. What is
    worth preventing is the summary *acquiring* numbers — which is how #60's
    "the same drift just relocates" would actually happen.

    A section containing `README_ALLOW_MARKER` suppresses the issue-reference
    finding. It does **not** suppress the missing-link finding: an exception for
    citing an issue is a plausible editorial need, whereas a roadmap section that
    does not link the roadmap is not something anyone needs an opt-out from.

    A README with no `## Roadmap` section at all is reported rather than passed
    silently. A guard that quietly stops guarding when its subject is renamed is
    the same silence #60 was filed about.
    """
    section: list[tuple[int, str]] = []
    found = False
    inside = False
    for line_no, line in enumerate(readme_text.splitlines(), start=1):
        heading = _SECTION_RE.match(line)
        if heading is not None:
            inside = _section_title(heading.group(1)) == README_SECTION
            found = found or inside
            continue
        if inside:
            section.append((line_no, line))

    if not found:
        return [
            Finding(
                README_CHECK,
                f"README has no `## {README_SECTION}` section — this guard has "
                "nothing to police. Restore the section, or point --readme at "
                "the file that carries it.",
            )
        ]

    findings = []
    if not any(_README_ROADMAP_LINK_RE.search(line) for _, line in section):
        findings.append(
            Finding(
                README_CHECK,
                f"README's `## {README_SECTION}` section does not link to "
                "ROADMAP.md — the summary has to point at the file it "
                "summarises, or the two stop being the same subject.",
            )
        )

    if any(README_ALLOW_MARKER in line for _, line in section):
        return findings

    for line_no, line in section:
        for match in _README_ISSUE_RE.finditer(line):
            findings.append(
                Finding(
                    README_CHECK,
                    f"README line {line_no}: the `## {README_SECTION}` section "
                    f"references issue {match.group(1)}. That summary must stay "
                    "prose-level — enumerated issue state here becomes a third "
                    "copy that drifts (#60). Move it to ROADMAP.md, or add "
                    f"`{README_ALLOW_MARKER}` to this section if the duplication "
                    "is deliberate.",
                )
            )
    return findings


# Name → check. The names are what the report prints as PASS/FAIL, and what a
# reader greps for when a build goes red.
#
# `check_readme` is deliberately NOT in this table. Every entry here is a
# function of the parsed `ROADMAP.md` entries; `check_readme` is a function of a
# different file's raw text. Widening the table to a uniform context object, or
# giving `check_readme` an `entries` parameter it never reads, would buy one
# fewer call site at the cost of making all four signatures dishonest about what
# they consume. It gets its own call site in `main()` instead — three lines, and
# the seam each check actually depends on stays visible in its signature.
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
# Everything below this line and above the reconciliation checks is the only
# code in this script that touches the network (R1). It never raises: every
# failure becomes a `(None, reason)` return, because a checker that dies with a
# traceback teaches a reader nothing about whether the roadmap is correct.

# This narrow projection IS the privacy control. This repo is public and CI logs
# are public; widening to --jq '.' "just to debug" would dump every open issue
# body into a public log. Debug by printing the projected dicts, never the raw
# API payload.
#
# `select(.pull_request | not)` is mandatory, not tidiness: the milestones API's
# `open_issues` field counts pull requests, so anything derived from an unfiltered
# list reports false drift the moment a PR is assigned to a milestone (#60 names
# this gotcha explicitly). Per-milestone facts here are derived from this
# filtered list only — the API's own count is never read.
#
# `count` is the RAW page length, deliberately captured *before* the filter.
# Verified against this repo at per_page=20: page 1 held 20 rows of which 18
# survived the PR filter. Terminating the page loop on the *filtered* length
# would have stopped after page 1 and silently lost the remaining 13 issues.
_ISSUES_PROJECTION = (
    "{count: length, rows: [.[] | select(.pull_request | not) "
    "| {number, milestone: (.milestone.title // null), labels: [.labels[].name]}]}"
)

_MILESTONES_PROJECTION = "{count: length, rows: [.[] | {number, title}]}"

# What one number turns out to be, when it is not in the open-issue list.
_RESOLVE_PROJECTION = '{number, state, is_pr: (has("pull_request"))}'


def _run_gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run `gh <args>` capturing text output; bounded by `GH_TIMEOUT` (R3).

    Mirrors `_hygiene_common.run`: it does not raise on a non-zero exit, because
    every caller here branches on `returncode` to tell "GitHub answered no" from
    "GitHub could not be asked". A missing `gh` binary still raises `OSError`,
    and `subprocess.TimeoutExpired` still propagates — both are caught by
    `fetch_issue_state`, which is the one place that can report them usefully.

    This is the single subprocess seam. Tests patch *this* function, never
    `subprocess` globally.
    """
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=GH_TIMEOUT
    )


def _is_rate_limited(proc: subprocess.CompletedProcess[str]) -> bool:
    """Whether a failed `gh api` call failed because of the rate limit.

    Checked so R4's retry can be skipped: retrying a rate limit spends another
    request against the budget that is already exhausted, making the situation
    strictly worse and delaying the honest "could not check" by five seconds.
    """
    return "rate limit" in (proc.stderr + proc.stdout).lower()


def _gh_api(path: str, jq: str) -> tuple[object | None, str | None]:
    """One `gh api` call, with R4's single retry. Returns `(parsed, reason)`.

    A non-zero exit is retried once after `RETRY_SLEEP_SECONDS` — enough to
    absorb the transient 502 that GitHub emits under load, not enough to mask a
    real outage. A rate limit short-circuits that retry (see `_is_rate_limited`).
    """
    attempts = 2
    for attempt in range(attempts):
        proc = _run_gh(["api", path, "--jq", jq])
        if proc.returncode == 0:
            break
        detail = (proc.stderr.strip() or proc.stdout.strip() or "no detail").splitlines()[0]
        if _is_rate_limited(proc):
            return None, f"api error (rate limited): {detail}"
        if attempt + 1 < attempts:
            time.sleep(RETRY_SLEEP_SECONDS)
            continue
        return None, f"api error: {detail}"

    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as exc:
        # Reached if gh ever emits something other than one JSON document. The
        # explicit page loop below exists precisely so this stays unreachable —
        # see its comment on `--paginate`.
        return None, f"malformed api response for {path}: {exc}"


def _gh_pages(path: str, jq: str) -> tuple[list[dict] | None, str | None]:
    """Accumulate every page of `path` into one list. Returns `(rows, reason)`.

    **Do not replace this with `--paginate`.** Verified against this repo at
    per_page=20: `gh api … --paginate --jq '[…]'` emits **one JSON array per
    page** — two separate `[…]` documents on stdout — so `json.loads` raises and
    the failure is laundered into a false "could not check". It is silent at 31
    issues and breaks at 101. `--slurp` is not the fix either: gh 2.87.3 rejects
    it outright with *"the `--slurp` option is not supported with `--jq` or
    `--template`"*. Both were tried; this loop is what remains.

    Termination is on the raw page count, never on `len(rows)` — the projection
    filters pull requests out, so a full page can yield a short row list.
    """
    accumulated: list[dict] = []
    # Do NOT "simplify" this loop into `gh api --paginate`: it emits one JSON
    # array per page, so `json.loads` raises "Extra data" and a working fetch is
    # laundered into a false "could not check". `--slurp` does not rescue it —
    # gh 2.87.3 rejects `--slurp` combined with `--jq`. Both were reproduced
    # against this repo; the loop is what survived. See this function's docstring.
    for page in range(1, MAX_PAGES + 1):
        sep = "&" if "?" in path else "?"
        payload, reason = _gh_api(f"{path}{sep}per_page={PER_PAGE}&page={page}", jq)
        if reason is not None:
            return None, reason
        if not isinstance(payload, dict) or "rows" not in payload:
            return None, f"unexpected api response shape for {path}"
        accumulated.extend(payload["rows"])
        if int(payload.get("count", 0)) < PER_PAGE:
            return accumulated, None
    return None, f"too many pages for {path} (stopped at {MAX_PAGES})"


def _resolve_reference(repo: str, number: int) -> tuple[str | None, str | None]:
    """What number `number` actually is. Returns `(verdict, reason)`.

    Verdict is ``"closed"``, ``"missing"`` (no such number, or it is a pull
    request), or ``"open"``. A 404 is a legitimate *answer* here — "there is no
    such issue" is exactly what D2 wants to report — so it is translated to
    ``"missing"`` rather than treated as a fetch failure.
    """
    proc_payload, reason = _gh_api(f"repos/{repo}/issues/{number}", _RESOLVE_PROJECTION)
    if reason is not None:
        if "404" in reason or "not found" in reason.lower():
            return "missing", None
        return None, reason
    if not isinstance(proc_payload, dict):
        return None, f"unexpected api response shape for issue {number}"
    # A pull request answers /issues/N happily (verified: #83 is a merged PR and
    # resolves here), so `is_pr` is the discriminator, not the HTTP status.
    if proc_payload.get("is_pr"):
        return "missing", None
    return ("closed" if proc_payload.get("state") == "closed" else "open"), None


def fetch_issue_state(
    repo: str = REPO, referenced: Iterable[int] = ()
) -> tuple[IssueState | None, str | None]:
    """The one and only place this script may touch the network (R1).

    Returns ``(state, None)`` on success and ``(None, reason)`` on any failure —
    **it never raises** (R2). Every reconciliation check takes the returned state
    as a parameter, which is what makes the test suite hermetic: there is no
    live call to guard, because this function is the seam.

    `referenced` is the set of numbers `ROADMAP.md` cites. Numbers absent from
    the open-issue list are resolved individually so D2 can tell "closed" from
    "never existed", bounded by `MAX_INDIVIDUAL_RESOLUTIONS`. It is a parameter
    rather than a second network entry point precisely so R1 keeps holding.

    Failure reasons are phrased for R10 — the caller prints them verbatim after
    "could not check — ", so each must read as a cause, never as "failed".
    """
    try:
        # `gh auth status` exits 0 exactly when a usable authenticated session
        # exists, per `_hygiene_common.gh_available`. Split into two reasons
        # here because "install gh" and "run gh auth login" are different fixes.
        auth = _run_gh(["auth", "status"])
    except OSError:
        return None, "gh unavailable (the GitHub CLI is not installed or not on PATH)"
    except subprocess.TimeoutExpired:
        return None, f"gh auth status timed out after {GH_TIMEOUT}s"
    if auth.returncode != 0:
        return None, "not authenticated (run `gh auth login`, or set GH_TOKEN)"

    try:
        rows, reason = _gh_pages(f"repos/{repo}/issues?state=open", _ISSUES_PROJECTION)
        if reason is not None:
            return None, reason

        issues: dict[int, Issue] = {}
        for row in rows or []:
            number = int(row["number"])
            issues[number] = Issue(
                number=number,
                milestone=row.get("milestone"),
                labels=tuple(row.get("labels") or ()),
            )

        milestone_rows, reason = _gh_pages(
            f"repos/{repo}/milestones?state=open", _MILESTONES_PROJECTION
        )
        if reason is not None:
            return None, reason
        milestones = tuple(row["title"] for row in milestone_rows or [])

        unknown = sorted(set(referenced) - set(issues))
        resolved: dict[int, str] = {}
        unresolved: tuple[int, ...] = ()
        if len(unknown) > MAX_INDIVIDUAL_RESOLUTIONS:
            unresolved = tuple(unknown)
        else:
            for number in unknown:
                verdict, reason = _resolve_reference(repo, number)
                if reason is not None:
                    return None, reason
                resolved[number] = verdict
    except OSError:
        return None, "gh unavailable (the GitHub CLI is not installed or not on PATH)"
    except subprocess.TimeoutExpired:
        return None, f"gh timed out after {GH_TIMEOUT}s"

    return (
        IssueState(
            issues=issues,
            milestones=milestones,
            resolved=resolved,
            unresolved=unresolved,
        ),
        None,
    )


# ── reconciliation checks ──────────────────────────────────────────────────
# Each takes `(entries, state)` and returns findings. None of them touch the
# network — they read the `IssueState` the seam above produced, which is what
# lets the tests drive every branch from a literal dict.


def check_labelled_present(entries: list[Entry], state: IssueState) -> list[Finding]:
    """D1 (hard): every open issue labelled `roadmap` appears in the file.

    Hard because the maintainer made an explicit, machine-readable declaration
    and the file contradicts it — zero policy judgement, and the remedy is one
    line in this repo. This is the failure mode the audit actually found:
    omission, not tag rot.
    """
    referenced = {entry.number for entry in entries}
    return [
        Finding(
            "labelled-present",
            f"labelled `{ROADMAP_LABEL}` but not on the roadmap: #{number} — "
            "add a bullet, or drop the label.",
        )
        for number in sorted(state.labelled() - referenced)
    ]


def check_reference_resolves(entries: list[Entry], state: IssueState) -> list[Finding]:
    """D2 (hard): every primary reference resolves to an open issue.

    The file asserts *planned future work* that GitHub says is finished,
    abandoned, or never existed. This is the one direction that depends on issue
    **state** rather than on metadata someone has to remember to apply, so it
    stays meaningful even if the labelling policy is later dropped.

    Closed is reported separately from missing because they are different
    mistakes with different fixes — and because a merged pull request answers
    the issues endpoint (#83 is one), so "not an issue" must not read as "gone".
    """
    findings = []
    seen: set[int] = set()
    for entry in sorted(entries, key=lambda e: e.line_no):
        if entry.number in state.issues or entry.number in seen:
            continue
        seen.add(entry.number)
        if entry.number in state.unresolved:
            continue
        verdict = state.resolved.get(entry.number)
        if verdict == "open":
            continue
        if verdict == "closed":
            findings.append(
                Finding(
                    "reference-resolves",
                    f"line {entry.line_no}: referenced but closed: "
                    f"#{entry.number} — move to Shipped or remove.",
                )
            )
        else:
            findings.append(
                Finding(
                    "reference-resolves",
                    f"line {entry.line_no}: referenced but not an open issue: "
                    f"#{entry.number} (not found, or is a pull request).",
                )
            )

    if state.unresolved:
        numbers = ", ".join(f"#{n}" for n in state.unresolved)
        findings.append(
            Finding(
                "reference-resolves",
                f"{len(state.unresolved)} references are not open issues and were "
                f"not resolved individually (over the {MAX_INDIVIDUAL_RESOLUTIONS}"
                f"-request bound): {numbers}.",
            )
        )
    return findings


def check_reference_labelled(entries: list[Entry], state: IssueState) -> list[Finding]:
    """D3 (ADVISORY — never affects the exit code): a reference lacking the label.

    **The severity here is the design, not an oversight, and promoting it to a
    hard failure would be a regression.** Nothing in this direction is
    necessarily wrong: the file may be right and the label merely un-applied.
    Critically, **the remedy is not in this repository** — applying a label is a
    GitHub metadata change that no commit can make and no pull request can
    carry, so a red build would block someone with no way to clear it. It is
    also the only direction that fires en masse during the label migration.
    Report it loudly, name the exact command, and exit 0. See the plan's
    "Direction semantics" before changing this.
    """
    findings = []
    for number in sorted({e.number for e in entries}):
        issue = state.issues.get(number)
        if issue is None or issue.is_roadmap:
            continue
        findings.append(
            Finding(
                "reference-labelled",
                f"on the roadmap but not labelled: #{number} — "
                f"`gh issue edit {number} --add-label {ROADMAP_LABEL}` "
                "(advisory; the remedy is GitHub metadata, which no commit can carry).",
                severity=SEVERITY_ADVISORY,
            )
        )
    return findings


def check_tag_agreement(entries: list[Entry], state: IssueState) -> list[Finding]:
    """The tag on a bullet agrees with the issue's milestone, both directions.

    Scoped to **roadmap-labelled issues only**: an unlabelled issue's milestone
    is none of this check's business, since the allow-list says it need not be
    in the file at all.

    Heading entries are exempt from the tag rule — the two epics are
    unmilestoned and their headings carry no tag slot — but they still count for
    D1 and D2, so an epic cannot silently rot.

    A milestone with no `TAG_TO_MILESTONE` mapping is left alone here and
    reported once by `check_milestone_vocabulary` instead; reporting it in both
    places would make one new milestone produce a finding per issue in it.
    """
    milestone_to_tag = {
        milestone: tag for tag, milestone in TAG_TO_MILESTONE.items()
    }
    findings = []
    for entry in sorted(entries, key=lambda e: e.line_no):
        if entry.kind == "heading":
            continue
        issue = state.issues.get(entry.number)
        if issue is None or not issue.is_roadmap:
            continue

        if issue.milestone is None:
            if entry.tag is not None:
                findings.append(
                    Finding(
                        "tag-agreement",
                        f"line {entry.line_no}: #{entry.number} is tagged "
                        f"`{entry.tag}` but belongs to no milestone — drop the "
                        "tag, or assign the milestone on GitHub.",
                    )
                )
            continue

        expected = milestone_to_tag.get(issue.milestone)
        if expected is None:
            continue  # check_milestone_vocabulary reports this, once.
        if entry.tag is None:
            findings.append(
                Finding(
                    "tag-agreement",
                    f"line {entry.line_no}: #{entry.number} is in milestone "
                    f"{issue.milestone!r} but carries no tag — add `{expected}`.",
                )
            )
        elif entry.tag != expected:
            findings.append(
                Finding(
                    "tag-agreement",
                    f"line {entry.line_no}: #{entry.number} is tagged "
                    f"`{entry.tag}` but its milestone is {issue.milestone!r} — "
                    f"expected `{expected}`.",
                )
            )
    return findings


def check_milestone_vocabulary(
    entries: list[Entry], state: IssueState
) -> list[Finding]:
    """`TAG_TO_MILESTONE` still describes the milestones GitHub actually has.

    This is what keeps the hardcoded table honest, in both directions: a new
    milestone holding roadmap-labelled work has no tag to express it, and a
    renamed milestone leaves a table value pointing at nothing. Without this the
    table would quietly become fiction and `check_tag_agreement` would keep
    passing while checking the wrong thing.

    Restricted to milestones holding **labelled** issues, so a milestone used
    only for maintenance work does not demand a roadmap tag it will never need.
    `entries` is unused — the signature is uniform so `NETWORK_CHECKS` can be a
    plain table.
    """
    del entries  # uniform signature; this check reasons about GitHub alone.

    findings = []
    tagged_milestones = set(TAG_TO_MILESTONE.values())

    holding = sorted(
        {
            issue.milestone
            for issue in state.issues.values()
            if issue.is_roadmap and issue.milestone is not None
        }
    )
    for milestone in holding:
        if milestone not in tagged_milestones:
            findings.append(
                Finding(
                    "milestone-vocabulary",
                    f"milestone {milestone!r} holds roadmap-labelled issues but "
                    "has no tag in TAG_TO_MILESTONE — add one, or the roadmap "
                    "cannot express where that work belongs.",
                )
            )

    for tag, milestone in TAG_TO_MILESTONE.items():
        if milestone not in state.milestones:
            findings.append(
                Finding(
                    "milestone-vocabulary",
                    f"tag `{tag}` maps to milestone {milestone!r}, which is not "
                    "an open milestone on GitHub — it was renamed, closed, or "
                    "deleted; update TAG_TO_MILESTONE.",
                )
            )
    return findings


# Name → check, in report order. Mirrors `OFFLINE_CHECKS`; the names are what
# the report prints as PASS/FAIL and what a reader greps for.
NETWORK_CHECKS = (
    ("labelled-present", check_labelled_present),
    ("reference-resolves", check_reference_resolves),
    ("reference-labelled", check_reference_labelled),
    ("tag-agreement", check_tag_agreement),
    ("milestone-vocabulary", check_milestone_vocabulary),
)


def run_network_checks(
    entries: list[Entry], state: IssueState
) -> list[tuple[str, list[Finding]]]:
    """Run every reconciliation check and return `(name, findings)` in report order.

    All of them run; none short-circuits, for the same reason `run_offline_checks`
    does not — a report that stops at the first failure makes a reviewer fix one
    thing, push, and wait to discover the next.
    """
    return [(name, check(entries, state)) for name, check in NETWORK_CHECKS]


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
    readme: Path,
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
        f"readme:   {readme}",
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
        "--readme",
        default=str(DEFAULT_README),
        help="path to README.md (default: this repo's README.md)",
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
    # stderr gets the same treatment: R10's "could not check — <reason>" line
    # interpolates `gh`'s own stderr, which is not guaranteed to be ASCII, and a
    # UnicodeEncodeError raised while reporting a failure would replace a useful
    # diagnosis with a traceback about printing it.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    roadmap = Path(args.roadmap)
    readme = Path(args.readme)
    try:
        text = roadmap.read_text(encoding="utf-8")
        readme_text = readme.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: could not read {exc.filename or roadmap}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    entries, notes = parse_roadmap(text)

    # R6: the offline checks always run, and always run first. A failed fetch
    # never suppresses what could be determined without one — the report says
    # what it knows before it says what it could not find out.
    results = run_offline_checks(entries)
    # The README guard's own call site — it reads a different file, so it is not
    # in `OFFLINE_CHECKS`; see the comment on that table. It is offline in every
    # other respect and belongs in the same batch, which is why `--offline`
    # reports four checks rather than three.
    results.append((README_CHECK, check_readme(readme_text)))

    # R7: `--offline` skips the fetch entirely, so it can never exit 2. This is
    # what a contributor with no `gh` and no token runs locally, and what the
    # `pull_request` trigger runs in CI.
    fetch_reason: str | None = None
    if not args.offline:
        # The referenced set is handed to the seam so D2 can resolve the numbers
        # GitHub's open list does not explain — keeping `fetch_issue_state` the
        # only function in this script that touches the network (R1).
        state, fetch_reason = fetch_issue_state(
            referenced={entry.number for entry in entries}
        )
        # A fetch that returned nothing is reported as "could not check", never
        # as "clean": running the reconciliation checks against an empty state
        # would print five reassuring PASS lines that mean nothing at all.
        if state is not None:
            results.extend(run_network_checks(entries, state))

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
                    "readme": readme.as_posix(),
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
            roadmap, readme, entries, notes, results, fetch_reason, bool(args.offline)
        ):
            print(line)

    # R10: exit 2 must name its reason on stderr, never a bare traceback and
    # never a bare "failed".
    if rc == EXIT_ERROR:
        print(f"roadmap: could not check — {fetch_reason}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
