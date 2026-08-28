# tests/test_roadmap_drift.py — all of scripts/check_roadmap_drift.py.
"""Tests for the parser, the offline checks, reconciliation, and the exits.

**Hermetic by construction, not by discipline.** Nothing here touches the
network, spawns `gh`, or reads GitHub state. That is not a convention this file
promises to keep — `fetch_issue_state` is the script's single network seam, so a
test that wants to prove "no fetch happened" replaces the seam with a function
that raises, and a test that wants a fetch failure replaces it with one that
returns the failure. Neither needs a network, and neither can accidentally reach
one. The suite therefore passes with `gh` unreachable:

    PY=$(command -v python); PATH=/nonexistent PYTHONPATH=scripts "$PY" \
        -m unittest tests.test_roadmap_drift

(The naive `PATH=/nonexistent python …` removes `python` itself and exits 127 —
it proves nothing. `command -v python` is resolved before `PATH` is clobbered.)

**Counts.** Against the six committed fixtures, exact counts are asserted: those
files are controlled by this suite and a changed count there is a real change.
Against the repo's own `ROADMAP.md` only *invariants* are asserted — one entry
per source line, every displayed number present in a well-formed link on that
line, every tag in the vocabulary, zero offline findings. Which issues earn a
roadmap line is an approved editorial decision that moves (the file went from 31
references to 24 when it was scoped to planned features), so a hardcoded total
would turn an owner's decision into a red build.

**Findings are objects.** `Finding` is a frozen dataclass with `check`,
`message`, and `severity`; `str(f)` renders the human line. Assertions here go
through those fields rather than comparing against bare strings.

**Two injection points, deliberately at different depths.** The reconciliation
checks are pure functions over an `IssueState`, so their tests build one from
literals (`_state`) and never go near a subprocess. The fetch layer *is* the
subprocess, so its tests replace `crd._run_gh` — the script's single
`subprocess.run` site — with a scripted stand-in (`_FakeGh` / `_RecordingGh`).
Neither depth patches `subprocess` globally, and nothing here starts a process.

**Why this half of the suite carries the weight it does.** On the live repo three
of these checks currently pass *vacuously*: D1 (`labelled-present`),
`check_tag_agreement`, and half of `check_milestone_vocabulary` are all scoped to
issues carrying the `roadmap` label, and no issue carries it — the label does not
exist yet. A green CI run against this repository is therefore not evidence that
any of them works. These injected-state tests are.
"""

import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_roadmap_drift as crd  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "roadmap"


# ── helpers ────────────────────────────────────────────────────────────────

def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _parse(name: str):
    """`(entries, notes)` for a fixture by file name."""
    return crd.parse_roadmap(_text(name))


def _entries(name: str):
    return _parse(name)[0]


def _shape(entries):
    """Entries as comparable tuples: (number, tag, kind, line_no)."""
    return [(e.number, e.tag, e.kind, e.line_no) for e in entries]


def _results(name: str) -> dict[str, list]:
    """`{check name: findings}` for a fixture, every offline check run."""
    return dict(crd.run_offline_checks(_entries(name)))


def _all_findings(name: str) -> list:
    return [f for _, fs in crd.run_offline_checks(_entries(name)) for f in fs]


def _run_main(argv: list[str]) -> tuple[int, str, str]:
    """Invoke `main()` with stdout and stderr captured."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = crd.main(argv)
    return rc, out.getvalue(), err.getvalue()


def _offline(name: str, *extra: str) -> tuple[int, str, str]:
    return _run_main(["--offline", "--roadmap", str(FIXTURES / name), *extra])


def _exploding_fetch(*args, **kwargs):
    """A network seam that fails the test if anything calls it."""
    raise AssertionError(
        "fetch_issue_state was called — this test must not touch the network"
    )


# ── injected GitHub state ──────────────────────────────────────────────────
# The reconciliation checks are pure functions over an `IssueState`, so their
# tests build one from literals. Against injected state exact counts and exact
# message fragments are correct assertions — unlike against the real ROADMAP.md,
# where only invariants may be asserted.

# Labels are spelled out at every call site rather than defaulted, because the
# whole allow-list policy is a function of them: a helper that quietly added
# `roadmap` would make D1 and D3 untestable by construction.
LABELLED = ("enhancement", crd.ROADMAP_LABEL)
UNLABELLED = ("enhancement",)


def _issue(number: int, milestone: str | None = None, labels=UNLABELLED):
    return crd.Issue(number=number, milestone=milestone, labels=tuple(labels))


def _state(issues=(), milestones=None, resolved=None, unresolved=()):
    """An `IssueState` from literals — the seam every reconciliation test uses.

    `milestones` defaults to exactly the milestones `TAG_TO_MILESTONE` claims
    exist, so `check_milestone_vocabulary` is silent unless a test deliberately
    makes GitHub disagree with the table. A default of `()` would instead make
    every unrelated test emit four vocabulary findings.
    """
    return crd.IssueState(
        issues={issue.number: issue for issue in issues},
        milestones=(
            tuple(crd.TAG_TO_MILESTONE.values())
            if milestones is None
            else tuple(milestones)
        ),
        resolved=dict(resolved or {}),
        unresolved=tuple(unresolved),
    )


def _entry(number: int, tag=None, kind="bullet", line_no=1):
    """An `Entry` with a well-formed URL, so offline checks stay out of the way."""
    return crd.Entry(
        number=number,
        tag=tag,
        kind=kind,
        line_no=line_no,
        url=f"https://github.com/{crd.REPO}/issues/{number}",
    )


def _network_findings(entries, state) -> list:
    """Every finding from every reconciliation check, flattened."""
    return [f for _, fs in crd.run_network_checks(entries, state) for f in fs]


def _clean_state() -> crd.IssueState:
    """GitHub state that agrees with `clean.md` on all five directions.

    #29 is the fixture's untagged bullet, so it must be unmilestoned for the tag
    rule to be satisfied; #43 is the epic heading, exempt from tags but not from
    D1/D2.
    """
    return _state(
        [
            _issue(43, None, LABELLED),
            _issue(53, "Loop integrity", LABELLED),
            _issue(35, "Readiness signal", LABELLED),
            _issue(10, "Cross-repo knowledge", LABELLED),
            _issue(29, None, LABELLED),
        ]
    )


def _run_with_state(name: str, state, *extra: str) -> tuple[int, str, str]:
    """`main()` against a fixture with the fetch seam returning `state`."""
    with mock.patch.object(crd, "fetch_issue_state", return_value=(state, None)):
        return _run_main(["--roadmap", str(FIXTURES / name), *extra])


# ── the subprocess seam ────────────────────────────────────────────────────
# `crd._run_gh` is the script's only `subprocess.run` site. Everything below
# replaces *that function*, never `subprocess` itself, so no process is started
# and nothing depends on whether `gh` exists on the machine running this.


def _proc(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _row(number: int, milestone=None, labels=UNLABELLED) -> dict:
    """One row as `_ISSUES_PROJECTION` would emit it (post-jq, post-PR-filter)."""
    return {"number": number, "milestone": milestone, "labels": list(labels)}


def _page(rows, count=None) -> dict:
    """One projected page: `count` is the RAW length, `rows` the survivors.

    They differ exactly when the page held pull requests, which the projection
    drops. Keeping them independent here is the whole point — see
    `PaginationTest.test_multi_page_response_is_accumulated`.
    """
    return {"count": len(rows) if count is None else count, "rows": rows}


def _milestone_page(titles=None) -> dict:
    titles = crd.TAG_TO_MILESTONE.values() if titles is None else titles
    return _page(
        [{"number": i, "title": title} for i, title in enumerate(titles, start=1)]
    )


class _FakeGh:
    """A scripted stand-in for `crd._run_gh`.

    It plays `gh` *and* the `--jq` projection gh applies, so what it writes to
    stdout is the already-projected document `_gh_api` parses. That is the honest
    boundary for a hermetic suite: the PR filter itself is jq's, evaluated in a
    process these tests never start.

    Routing mirrors the three call shapes `fetch_issue_state` makes: `auth
    status`, a paginated list, and a single-issue resolution.
    """

    def __init__(self, issue_pages=(), milestone_pages=None, resolve=None, auth_rc=0):
        self.issue_pages = list(issue_pages) or [_page([])]
        self.milestone_pages = (
            [_milestone_page()] if milestone_pages is None else list(milestone_pages)
        )
        self.resolve = dict(resolve or {})
        self.auth_rc = auth_rc
        self.calls: list[list[str]] = []

    @property
    def api_paths(self) -> list[str]:
        return [c[1] for c in self.calls if c and c[0] == "api"]

    def __call__(self, args):
        self.calls.append(list(args))
        if args[:2] == ["auth", "status"]:
            return _proc(self.auth_rc, stderr="" if self.auth_rc == 0 else "gh: no token")
        path = args[1]
        single = re.search(r"/issues/(\d+)", path)
        if single:
            return _proc(0, json.dumps(self.resolve[int(single.group(1))]))
        pages = self.milestone_pages if "/milestones" in path else self.issue_pages
        page = int(re.search(r"[?&]page=(\d+)", path).group(1))
        if page > len(pages):
            return _proc(0, json.dumps(_page([])))
        return _proc(0, json.dumps(pages[page - 1]))


class _RecordingGh:
    """`crd._run_gh` as a fixed script of outcomes; the last one repeats.

    An outcome that is an exception instance is raised — that is how "gh is not
    installed" (`OSError`) and "gh hung" (`TimeoutExpired`) are expressed without
    a process. Call-counting is what the retry tests assert on.
    """

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[list[str]] = []

    @property
    def api_calls(self) -> list[list[str]]:
        return [c for c in self.calls if c and c[0] == "api"]

    def __call__(self, args):
        self.calls.append(list(args))
        outcome = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


# ── parser ─────────────────────────────────────────────────────────────────

class ParseRoadmapTest(unittest.TestCase):
    def test_clean_fixture_parses_headings_tags_and_untagged_bullets(self):
        entries, notes = _parse("clean.md")
        self.assertEqual(
            _shape(entries),
            [
                (43, None, "heading", 11),   # `[Epic #43]` on a `##` heading
                (53, "loop", "bullet", 15),
                (35, "readiness", "bullet", 16),
                (10, "cross-repo", "bullet", 17),
                (29, None, "bullet", 18),    # untagged bullet -> tag is None
            ],
        )
        self.assertEqual(notes, [])

    def test_heading_reference_is_never_tagged(self):
        """Epics are unmilestoned; the tag rule exempts headings by design."""
        headings = [e for e in _entries("clean.md") if e.kind == "heading"]
        self.assertEqual(len(headings), 1)
        self.assertIsNone(headings[0].tag)

    def test_bullet_with_no_link_produces_no_entry_and_no_finding(self):
        """`- **A2 — section-level `CLAUDE.md` import**` is untracked, not drift."""
        text = _text("clean.md")
        self.assertIn("**A2 — section-level", text)
        a2_line = next(
            i for i, ln in enumerate(text.splitlines(), start=1)
            if "**A2 — section-level" in ln
        )
        self.assertNotIn(a2_line, [e.line_no for e in _entries("clean.md")])
        self.assertEqual(_all_findings("clean.md"), [])

    def test_legend_bare_issues_link_is_not_a_reference(self):
        """`https://…/issues` with no `/N` must not be read as a reference.

        The intro/legend is excluded from reference checks, but the stronger
        property is that the link never even matches: its text is `open issues`,
        not `#N`. So it yields neither an entry nor an ignored-note.
        """
        text = _text("clean.md")
        self.assertIn("(https://github.com/noctua84/nescio-ai/issues)", text)
        entries, notes = crd.parse_roadmap(text)
        self.assertEqual(notes, [])
        # Nothing before the first `##` heading became an entry.
        first_heading = next(
            i for i, ln in enumerate(text.splitlines(), start=1)
            if ln.startswith("## ")
        )
        self.assertTrue(all(e.line_no >= first_heading for e in entries))

    def test_prose_commentary_is_not_a_reference(self):
        """The two R2-9 traps, on one fixture.

        1. A bare `#83` in prose. `ROADMAP.md:90` once read "fixed in #83", and
           **#83 is a merged PR, not an issue** — a bare-`#N` parser would have
           invented a reference to a PR and then failed three checks on it. The
           anchored `[#N](url)` regex never sees it.
        2. A second `[#N](url)` link after a bullet's primary one.
           `ROADMAP.md:59` once read "(in tension with #53 …)". Linking a
           cross-reference is an ordinary editorial act; the primary-reference
           rule keeps it out of the entry list and records it as a note instead.
        """
        entries, notes = _parse("prose_only.md")
        self.assertEqual(
            _shape(entries),
            [(59, "loop", "bullet", 15), (52, "loop", "bullet", 16)],
        )
        # The bare `#83` produced nothing at all — not an entry, not a note.
        self.assertIn("fixed in #83", _text("prose_only.md"))
        self.assertNotIn(83, [e.number for e in entries])
        self.assertFalse([n for n in notes if "#83" in n])
        # The commentary link to #53 is discarded, and the discard is auditable.
        self.assertNotIn(53, [e.number for e in entries])
        self.assertEqual(len(notes), 1)
        self.assertIn("#53", notes[0])
        self.assertIn("commentary", notes[0])
        self.assertIn("line 16", notes[0])
        self.assertEqual(_all_findings("prose_only.md"), [])

    def test_shipped_section_reference_is_excluded_from_the_entry_list(self):
        """The exclusion must be visible in what the parser *produced*.

        Asserting only "zero findings" would pass with `EXCLUDED_SECTIONS`
        deleted outright: #42 is closed, and closed-ness is a network check that
        never runs here, so an un-excluded #42 would sail through every offline
        check. The load-bearing assertion is that #42 never became an entry.
        """
        entries, notes = _parse("shipped_section_closed_ref.md")
        self.assertEqual({e.number for e in entries}, {53})
        self.assertEqual(_shape(entries), [(53, "loop", "bullet", 19)])
        self.assertEqual(len(notes), 1)
        self.assertIn("#42", notes[0])
        self.assertIn("Shipped", notes[0])
        self.assertIn("excluded", notes[0])
        self.assertEqual(_all_findings("shipped_section_closed_ref.md"), [])

    def test_section_after_shipped_is_not_excluded(self):
        """Exclusion is per-section, not "everything after `## Shipped`"."""
        entries, _ = _parse("shipped_section_closed_ref.md")
        shipped_line = next(
            i for i, ln in enumerate(
                _text("shipped_section_closed_ref.md").splitlines(), start=1
            )
            if ln.startswith("## Shipped")
        )
        self.assertTrue(all(e.line_no > shipped_line for e in entries))

    def test_reference_in_a_plain_paragraph_is_noted_not_entered(self):
        """Only `##` headings and list items produce entries.

        No committed fixture carries a paragraph-level reference, so the text is
        inline here rather than added to `tests/fixtures/roadmap/`.
        """
        entries, notes = crd.parse_roadmap(
            "## Learning loop\n"
            "\n"
            "See [#53](https://github.com/noctua84/nescio-ai/issues/53) for the\n"
            "data-model change.\n"
        )
        self.assertEqual(entries, [])
        self.assertEqual(len(notes), 1)
        self.assertIn("#53", notes[0])
        self.assertIn("not a heading or a list item", notes[0])

    def test_url_is_carried_raw_so_a_bad_link_survives_into_the_checks(self):
        """`mismatched_link.md`: the entry keeps the URL the file actually has."""
        bad = next(e for e in _entries("mismatched_link.md") if e.number == 53)
        self.assertEqual(bad.url, "https://github.com/noctua84/nescio-ai/issues/35")


# ── offline checks ─────────────────────────────────────────────────────────

class OfflineCheckTest(unittest.TestCase):
    def test_findings_are_finding_objects_not_strings(self):
        (finding,) = crd.check_unique_references(_entries("duplicate_reference.md"))
        self.assertIsInstance(finding, crd.Finding)
        self.assertEqual(str(finding), finding.message)
        self.assertEqual(finding.severity, crd.SEVERITY_HARD)

    def test_clean_fixture_is_silent_on_every_check(self):
        self.assertEqual(
            {name: fs for name, fs in _results("clean.md").items() if fs}, {}
        )

    def test_prose_only_fixture_is_silent_on_every_check(self):
        self.assertEqual(
            {name: fs for name, fs in _results("prose_only.md").items() if fs}, {}
        )

    def test_duplicate_reference_fires_only_unique_references(self):
        results = _results("duplicate_reference.md")
        (finding,) = results["unique-references"]
        self.assertEqual(finding.check, "unique-references")
        self.assertEqual(finding.severity, crd.SEVERITY_HARD)
        self.assertIn("#53", finding.message)
        self.assertIn("line 13", finding.message)
        self.assertIn("line 15", finding.message)
        self.assertEqual(results["link-wellformed"], [])
        self.assertEqual(results["tag-vocabulary"], [])

    def test_mismatched_link_fires_only_link_wellformed(self):
        results = _results("mismatched_link.md")
        (finding,) = results["link-wellformed"]
        self.assertEqual(finding.check, "link-wellformed")
        self.assertEqual(finding.severity, crd.SEVERITY_HARD)
        self.assertIn("line 13", finding.message)
        self.assertIn("text says #53", finding.message)
        self.assertIn("issue 35", finding.message)
        self.assertEqual(results["unique-references"], [])
        self.assertEqual(results["tag-vocabulary"], [])

    def test_link_to_another_repo_is_reported_as_not_well_formed(self):
        """The wrong-host failure, distinct from the wrong-number one."""
        entry = crd.Entry(
            number=53,
            tag="loop",
            kind="bullet",
            line_no=7,
            url="https://github.com/someone-else/nescio-ai/issues/53",
        )
        (finding,) = crd.check_link_wellformed([entry])
        self.assertEqual(finding.check, "link-wellformed")
        self.assertIn("does not link to", finding.message)
        self.assertIn("someone-else", finding.message)

    def test_unknown_tag_fires_only_tag_vocabulary(self):
        results = _results("unknown_tag.md")
        (finding,) = results["tag-vocabulary"]
        self.assertEqual(finding.check, "tag-vocabulary")
        self.assertEqual(finding.severity, crd.SEVERITY_HARD)
        self.assertIn("line 14", finding.message)
        self.assertIn("`v2`", finding.message)
        # The message names the vocabulary so the fix is obvious from the line.
        for tag in crd.TAG_TO_MILESTONE:
            self.assertIn(tag, finding.message)
        self.assertEqual(results["unique-references"], [])
        self.assertEqual(results["link-wellformed"], [])

    def test_untagged_entries_are_not_vocabulary_failures(self):
        untagged = [e for e in _entries("clean.md") if e.tag is None]
        self.assertTrue(untagged)
        self.assertEqual(crd.check_tag_vocabulary(untagged), [])

    def test_every_check_runs_even_when_an_earlier_one_fails(self):
        """No short-circuit: a reviewer must see all of it in one run."""
        entries = _entries("duplicate_reference.md") + _entries("unknown_tag.md")
        results = dict(crd.run_offline_checks(entries))
        self.assertEqual(
            list(results), ["unique-references", "link-wellformed", "tag-vocabulary"]
        )
        self.assertTrue(results["unique-references"])
        self.assertTrue(results["tag-vocabulary"])

    def test_report_order_is_stable(self):
        names = [name for name, _ in crd.run_offline_checks([])]
        self.assertEqual([name for name, _ in crd.OFFLINE_CHECKS], names)


# ── exit convention ────────────────────────────────────────────────────────

class ExitConventionTest(unittest.TestCase):
    """0 / 1 / 2 must stay distinguishable: "wrong" is not "could not check"."""

    def test_exit_codes_are_the_documented_values(self):
        self.assertEqual(
            (crd.EXIT_PASS, crd.EXIT_DRIFT, crd.EXIT_ERROR), (0, 1, 2)
        )

    def test_clean_fixture_offline_exits_pass(self):
        rc, out, err = _offline("clean.md")
        self.assertEqual(rc, crd.EXIT_PASS, out + err)
        self.assertIn("PASS  unique-references", out)
        self.assertIn("offline mode", out)

    def test_drift_offline_exits_drift_not_error(self):
        rc, out, err = _offline("duplicate_reference.md")
        self.assertEqual(rc, crd.EXIT_DRIFT, out + err)
        self.assertIn("FAIL  unique-references", out)

    def test_every_drift_fixture_exits_drift_offline(self):
        for name in (
            "duplicate_reference.md",
            "mismatched_link.md",
            "unknown_tag.md",
        ):
            with self.subTest(fixture=name):
                rc, out, err = _offline(name)
                self.assertEqual(rc, crd.EXIT_DRIFT, out + err)

    def test_shipped_and_prose_fixtures_exit_pass_offline(self):
        for name in ("shipped_section_closed_ref.md", "prose_only.md"):
            with self.subTest(fixture=name):
                rc, out, err = _offline(name)
                self.assertEqual(rc, crd.EXIT_PASS, out + err)

    def test_fetch_failure_exits_error_never_pass(self):
        """A fetch that could not run is 2, not a quiet 0."""
        with mock.patch.object(
            crd, "fetch_issue_state", return_value=(None, "gh not on PATH")
        ):
            rc, out, err = _run_main(
                ["--roadmap", str(FIXTURES / "clean.md")]
            )
        self.assertEqual(rc, crd.EXIT_ERROR, out + err)
        self.assertIn("could not check", out)
        # R10: exit 2 names its reason on stderr rather than dying silently.
        self.assertIn("gh not on PATH", err)

    def test_drift_outranks_a_failed_fetch(self):
        """Drift is real whether or not GitHub was reachable — so 1, not 2."""
        with mock.patch.object(
            crd, "fetch_issue_state", return_value=(None, "gh not on PATH")
        ):
            rc, out, err = _run_main(
                ["--roadmap", str(FIXTURES / "duplicate_reference.md")]
            )
        self.assertEqual(rc, crd.EXIT_DRIFT, out + err)

    def test_unreadable_roadmap_exits_error(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out, err = _run_main(
                ["--offline", "--roadmap", str(Path(d) / "no-such-file.md")]
            )
        self.assertEqual(rc, crd.EXIT_ERROR, out + err)
        self.assertIn("could not read", err)

    def test_json_output_carries_findings_entries_and_exit_code(self):
        rc, out, _ = _offline("duplicate_reference.md", "--json")
        payload = json.loads(out)
        self.assertEqual(rc, crd.EXIT_DRIFT)
        self.assertEqual(payload["exit"], crd.EXIT_DRIFT)
        self.assertTrue(payload["offline"])
        self.assertIsNone(payload["fetch_reason"])
        (finding,) = payload["findings"]
        self.assertEqual(finding["check"], "unique-references")
        self.assertEqual(finding["severity"], crd.SEVERITY_HARD)
        self.assertIn("#53", finding["message"])
        self.assertEqual(
            [e["number"] for e in payload["entries"]], [43, 53, 35, 53]
        )
        self.assertEqual(payload["tag_to_milestone"], crd.TAG_TO_MILESTONE)

    def test_json_ignored_list_records_the_shipped_exclusion(self):
        rc, out, _ = _offline("shipped_section_closed_ref.md", "--json")
        payload = json.loads(out)
        self.assertEqual(rc, crd.EXIT_PASS)
        self.assertEqual([e["number"] for e in payload["entries"]], [53])
        self.assertEqual(payload["findings"], [])
        self.assertTrue(any("#42" in note for note in payload["ignored"]))


# ── hermeticity ────────────────────────────────────────────────────────────

class HermeticityTest(unittest.TestCase):
    """`--offline` must not merely *skip* the fetch — it must never call it."""

    def test_offline_does_not_call_the_network_seam(self):
        """Stronger than trusting the flag: the seam raises if touched.

        Whether `gh` happens to be installed on the machine running this is
        irrelevant, which is the point — the assertion holds either way.
        """
        gh = shutil.which("gh")
        with mock.patch.object(crd, "fetch_issue_state", _exploding_fetch):
            rc, out, err = _run_main(["--offline", "--roadmap", str(crd.DEFAULT_ROADMAP)])
        self.assertEqual(
            rc, crd.EXIT_PASS, f"gh={gh!r}\n{out}{err}"
        )

    def test_offline_does_not_call_the_seam_even_when_reporting_drift(self):
        with mock.patch.object(crd, "fetch_issue_state", _exploding_fetch):
            rc, out, err = _offline("duplicate_reference.md")
        self.assertEqual(rc, crd.EXIT_DRIFT, out + err)

    def test_offline_json_does_not_call_the_seam(self):
        with mock.patch.object(crd, "fetch_issue_state", _exploding_fetch):
            rc, out, _ = _offline("clean.md", "--json")
        self.assertEqual(rc, crd.EXIT_PASS)
        self.assertIsNone(json.loads(out)["fetch_reason"])

    def test_offline_never_returns_exit_error(self):
        """R7: the offline path has no route to 2 other than an unreadable file."""
        for name in sorted(p.name for p in FIXTURES.glob("*.md")):
            with self.subTest(fixture=name):
                rc, out, err = _offline(name)
                self.assertIn(rc, (crd.EXIT_PASS, crd.EXIT_DRIFT), out + err)


# ── reconciliation: the four directions ────────────────────────────────────

class DirectionTest(unittest.TestCase):
    """D1–D4. The asymmetry is the design; each direction is pinned separately.

      D1  labelled, not in the file      → drift, exit 1
      D2  in the file, not open          → drift, exit 1
      D3  in the file, open, unlabelled  → ADVISORY, exit 0
      D4  unlabelled and unreferenced    → nothing at all
    """

    # D1 ──────────────────────────────────────────────────────────────────

    def test_d1_labelled_but_absent_from_the_file_is_hard_drift(self):
        """The failure mode the audit actually found: omission, not tag rot."""
        state = _state([_issue(53, "Loop integrity", LABELLED),
                        _issue(77, "Loop integrity", LABELLED)])
        (finding,) = crd.check_labelled_present([_entry(53, "loop")], state)
        self.assertEqual(finding.check, "labelled-present")
        self.assertEqual(finding.severity, crd.SEVERITY_HARD)
        self.assertIn("#77", finding.message)
        self.assertIn(crd.ROADMAP_LABEL, finding.message)
        self.assertNotIn("#53", finding.message)

    def test_d1_is_silent_when_every_labelled_issue_is_present(self):
        state = _state([_issue(53, "Loop integrity", LABELLED)])
        self.assertEqual(crd.check_labelled_present([_entry(53, "loop")], state), [])

    def test_d1_counts_a_heading_entry_as_present(self):
        """An epic is referenced by a `##` heading; that still satisfies D1."""
        state = _state([_issue(43, None, LABELLED)])
        self.assertEqual(
            crd.check_labelled_present([_entry(43, kind="heading")], state), []
        )

    def test_d1_reports_every_missing_number_in_ascending_order(self):
        state = _state(
            [_issue(n, "Loop integrity", LABELLED) for n in (77, 12, 40)]
        )
        findings = crd.check_labelled_present([], state)
        self.assertEqual(
            [f.message.split("#")[1].split(" ")[0] for f in findings],
            ["12", "40", "77"],
        )

    # D2 ──────────────────────────────────────────────────────────────────

    def test_d2_closed_and_missing_produce_distinguishable_messages(self):
        """Different mistakes, different fixes — the wordings must not collapse.

        A merged pull request answers `/issues/N` happily (#83 is one), so "not
        an issue" must never read as "gone".
        """
        state = _state([], resolved={42: "closed", 83: "missing"})
        entries = [_entry(42, "loop", line_no=15), _entry(83, "loop", line_no=16)]
        closed, missing = crd.check_reference_resolves(entries, state)

        self.assertEqual(closed.check, "reference-resolves")
        self.assertEqual(closed.severity, crd.SEVERITY_HARD)
        self.assertIn("line 15", closed.message)
        self.assertIn("referenced but closed", closed.message)
        self.assertIn("Shipped", closed.message)

        self.assertEqual(missing.severity, crd.SEVERITY_HARD)
        self.assertIn("line 16", missing.message)
        self.assertIn("not an open issue", missing.message)
        self.assertIn("pull request", missing.message)

        # The load-bearing property: a reader can tell the two apart.
        self.assertNotEqual(closed.message, missing.message)
        self.assertNotIn("closed", missing.message)

    def test_d2_is_silent_for_a_reference_that_is_an_open_issue(self):
        state = _state([_issue(53, "Loop integrity", LABELLED)])
        self.assertEqual(crd.check_reference_resolves([_entry(53, "loop")], state), [])

    def test_d2_is_silent_when_the_list_call_raced_and_the_issue_is_open(self):
        """`resolved == "open"` means the fetch raced, not that the file is wrong."""
        state = _state([], resolved={53: "open"})
        self.assertEqual(crd.check_reference_resolves([_entry(53, "loop")], state), [])

    def test_d2_reports_an_unknown_number_once_even_if_two_lines_cite_it(self):
        state = _state([], resolved={42: "closed"})
        entries = [_entry(42, "loop", line_no=15), _entry(42, "loop", line_no=30)]
        (finding,) = crd.check_reference_resolves(entries, state)
        self.assertIn("line 15", finding.message)

    def test_d2_reports_unresolved_references_without_the_closed_detail(self):
        """Past `MAX_INDIVIDUAL_RESOLUTIONS` the numbers still surface."""
        numbers = tuple(range(200, 200 + crd.MAX_INDIVIDUAL_RESOLUTIONS + 1))
        state = _state([], unresolved=numbers)
        entries = [_entry(n, "loop", line_no=10 + i) for i, n in enumerate(numbers)]
        (finding,) = crd.check_reference_resolves(entries, state)
        self.assertEqual(finding.severity, crd.SEVERITY_HARD)
        self.assertIn(str(len(numbers)), finding.message)
        self.assertIn(str(crd.MAX_INDIVIDUAL_RESOLUTIONS), finding.message)
        for n in numbers:
            self.assertIn(f"#{n}", finding.message)

    # D3 ──────────────────────────────────────────────────────────────────

    def test_d3_referenced_but_unlabelled_is_advisory_not_hard(self):
        """**Promoting this to a hard failure would be a regression.**

        The remedy is a GitHub label, which no commit and no pull request in this
        repository can apply — a red build here would block someone with no way
        to clear it. This test exists to stop the promotion happening quietly.
        """
        state = _state([_issue(53, "Loop integrity", UNLABELLED)])
        (finding,) = crd.check_reference_labelled([_entry(53, "loop")], state)
        self.assertEqual(finding.check, "reference-labelled")
        self.assertEqual(finding.severity, crd.SEVERITY_ADVISORY)
        self.assertNotEqual(finding.severity, crd.SEVERITY_HARD)
        self.assertIn("#53", finding.message)
        # The exact remedy, so the reader does not have to guess the command.
        self.assertIn(f"gh issue edit 53 --add-label {crd.ROADMAP_LABEL}", finding.message)

    def test_d3_advisory_alone_exits_pass_through_main(self):
        """The severity must survive all the way to the process exit code."""
        state = _state(
            [
                _issue(43, None, LABELLED),
                _issue(53, "Loop integrity", LABELLED),
                _issue(35, "Readiness signal", LABELLED),
                _issue(10, "Cross-repo knowledge", LABELLED),
                _issue(29, None, UNLABELLED),  # the only disagreement
            ]
        )
        rc, out, err = _run_with_state("clean.md", state)
        self.assertEqual(rc, crd.EXIT_PASS, out + err)
        self.assertIn("note  reference-labelled", out)
        self.assertIn("(advisory)", out)
        self.assertNotIn("FAIL", out)

    def test_d3_is_silent_for_a_labelled_reference(self):
        state = _state([_issue(53, "Loop integrity", LABELLED)])
        self.assertEqual(crd.check_reference_labelled([_entry(53, "loop")], state), [])

    def test_d3_does_not_double_report_a_reference_d2_already_owns(self):
        """A closed reference is D2's finding; D3 must not pile on."""
        state = _state([], resolved={42: "closed"})
        self.assertEqual(crd.check_reference_labelled([_entry(42, "loop")], state), [])

    # D4 ──────────────────────────────────────────────────────────────────

    def test_unlabelled_unreferenced_issue_is_silent(self):
        """D4: the escape hatch, and the reason the allow-list design exists.

        An open issue that carries no `roadmap` label and appears nowhere in the
        file is a **non-event** — the first outside bug report on a public,
        MIT-licensed repo carrying `good first issue` and `help wanted`.

        The earlier design asserted a *bijection* against all open issues and
        would have hard-failed on exactly this input. It looked correct only
        because the repo was at 100% solo authorship, so the two sets happened to
        match; the very first contributor would have reddened the build with no
        remedy available to them. The assertion is therefore **zero findings of
        any severity**, not "no hard findings" — an advisory here would still
        print noise at every outside contributor.
        """
        entries = [_entry(53, "loop", line_no=15)]
        state = _state(
            [
                _issue(53, "Loop integrity", LABELLED),
                _issue(99, None, ("bug",)),  # the outside bug report
                _issue(100, "Loop integrity", ("bug",)),  # milestoned, still not ours
            ]
        )
        self.assertEqual(_network_findings(entries, state), [])
        # And stated per direction, so a future regression names itself.
        for name, findings in crd.run_network_checks(entries, state):
            with self.subTest(check=name):
                self.assertEqual([str(f) for f in findings], [])

    def test_d4_stays_silent_through_main_and_exits_pass(self):
        state = _clean_state()
        state = _state(
            list(state.issues.values()) + [_issue(99, None, ("bug",))]
        )
        rc, out, err = _run_with_state("clean.md", state)
        self.assertEqual(rc, crd.EXIT_PASS, out + err)
        self.assertNotIn("#99", out)
        self.assertNotIn("FAIL", out)


# ── tag agreement ──────────────────────────────────────────────────────────

class TagAgreementTest(unittest.TestCase):
    """The tag on a bullet vs the milestone GitHub holds, both directions.

    Scoped to roadmap-labelled issues: an unlabelled issue's milestone is none of
    this check's business, since the allow-list says it need not be in the file.
    """

    def test_wrong_tag_names_the_milestone_and_the_expected_tag(self):
        state = _state([_issue(53, "Readiness signal", LABELLED)])
        (finding,) = crd.check_tag_agreement([_entry(53, "loop", line_no=15)], state)
        self.assertEqual(finding.check, "tag-agreement")
        self.assertEqual(finding.severity, crd.SEVERITY_HARD)
        self.assertIn("line 15", finding.message)
        self.assertIn("`loop`", finding.message)
        self.assertIn("Readiness signal", finding.message)
        self.assertIn("expected `readiness`", finding.message)

    def test_missing_tag_on_a_milestoned_issue_names_the_tag_to_add(self):
        state = _state([_issue(53, "Loop integrity", LABELLED)])
        (finding,) = crd.check_tag_agreement([_entry(53, None, line_no=15)], state)
        self.assertIn("carries no tag", finding.message)
        self.assertIn("add `loop`", finding.message)

    def test_tag_on_an_unmilestoned_issue_is_reported(self):
        """The third direction: the file claims a milestone GitHub does not have."""
        state = _state([_issue(53, None, LABELLED)])
        (finding,) = crd.check_tag_agreement([_entry(53, "loop", line_no=15)], state)
        self.assertIn("belongs to no milestone", finding.message)
        self.assertIn("`loop`", finding.message)

    def test_agreeing_tag_is_silent(self):
        state = _state([_issue(53, "Loop integrity", LABELLED)])
        self.assertEqual(crd.check_tag_agreement([_entry(53, "loop")], state), [])

    def test_untagged_and_unmilestoned_is_silent(self):
        state = _state([_issue(29, None, LABELLED)])
        self.assertEqual(crd.check_tag_agreement([_entry(29, None)], state), [])

    def test_an_unlabelled_issues_milestone_is_ignored_entirely(self):
        """Every shape that would fire for a labelled issue must stay silent."""
        for tag, milestone in (
            ("loop", "Readiness signal"),  # would be "wrong tag"
            (None, "Loop integrity"),      # would be "missing tag"
            ("loop", None),                # would be "no milestone"
        ):
            with self.subTest(tag=tag, milestone=milestone):
                state = _state([_issue(53, milestone, UNLABELLED)])
                self.assertEqual(
                    crd.check_tag_agreement([_entry(53, tag)], state), []
                )

    def test_a_heading_entry_is_exempt_from_the_tag_rule(self):
        """Epics are unmilestoned and their headings carry no tag slot."""
        state = _state([_issue(43, "Loop integrity", LABELLED)])
        heading = _entry(43, None, kind="heading", line_no=11)
        self.assertEqual(crd.check_tag_agreement([heading], state), [])
        # Exempt from tags, but still fully subject to D1 and D2.
        self.assertEqual(crd.check_labelled_present([heading], state), [])
        self.assertEqual(
            crd.check_labelled_present([], state)[0].message.count("#43"), 1
        )

    def test_a_reference_with_no_open_issue_is_left_to_d2(self):
        state = _state([], resolved={42: "closed"})
        self.assertEqual(crd.check_tag_agreement([_entry(42, "loop")], state), [])

    def test_a_milestone_with_no_mapping_is_left_to_the_vocabulary_check(self):
        """Reporting it here too would emit one finding per issue in it."""
        state = _state(
            [_issue(53, "Docs debt", LABELLED)],
            milestones=(*crd.TAG_TO_MILESTONE.values(), "Docs debt"),
        )
        self.assertEqual(crd.check_tag_agreement([_entry(53, "loop")], state), [])


# ── milestone vocabulary ───────────────────────────────────────────────────

class MilestoneVocabularyTest(unittest.TestCase):
    """What keeps the hardcoded `TAG_TO_MILESTONE` table from becoming fiction."""

    def test_a_renamed_milestone_breaks_the_table_and_is_reported(self):
        renamed = tuple(
            m for m in crd.TAG_TO_MILESTONE.values() if m != "Parked"
        ) + ("Parked (deferred)",)
        state = _state([_issue(53, "Loop integrity", LABELLED)], milestones=renamed)
        (finding,) = crd.check_milestone_vocabulary([], state)
        self.assertEqual(finding.check, "milestone-vocabulary")
        self.assertEqual(finding.severity, crd.SEVERITY_HARD)
        self.assertIn("`parked`", finding.message)
        self.assertIn("'Parked'", finding.message)
        self.assertIn("TAG_TO_MILESTONE", finding.message)

    def test_a_milestone_holding_labelled_work_with_no_tag_is_reported(self):
        state = _state(
            [_issue(53, "Docs debt", LABELLED)],
            milestones=(*crd.TAG_TO_MILESTONE.values(), "Docs debt"),
        )
        (finding,) = crd.check_milestone_vocabulary([], state)
        self.assertIn("'Docs debt'", finding.message)
        self.assertIn("no tag in TAG_TO_MILESTONE", finding.message)

    def test_a_milestone_holding_only_unlabelled_work_is_not_reported(self):
        """Maintenance milestones must not demand a roadmap tag they never need."""
        state = _state(
            [_issue(53, "Docs debt", UNLABELLED)],
            milestones=(*crd.TAG_TO_MILESTONE.values(), "Docs debt"),
        )
        self.assertEqual(crd.check_milestone_vocabulary([], state), [])

    def test_the_table_agreeing_with_github_is_silent(self):
        state = _state([_issue(53, "Loop integrity", LABELLED)])
        self.assertEqual(crd.check_milestone_vocabulary([], state), [])

    def test_it_reports_once_per_milestone_not_once_per_issue(self):
        state = _state(
            [_issue(n, "Docs debt", LABELLED) for n in (53, 54, 55)],
            milestones=(*crd.TAG_TO_MILESTONE.values(), "Docs debt"),
        )
        self.assertEqual(len(crd.check_milestone_vocabulary([], state)), 1)


# ── the fetch layer ────────────────────────────────────────────────────────

class FetchIssueStateTest(unittest.TestCase):
    """`fetch_issue_state` with `crd._run_gh` replaced. No process is started."""

    def test_a_successful_fetch_builds_issues_and_milestones(self):
        fake = _FakeGh(
            issue_pages=[_page([_row(53, "Loop integrity", LABELLED), _row(99)])]
        )
        with mock.patch.object(crd, "_run_gh", fake):
            state, reason = crd.fetch_issue_state()
        self.assertIsNone(reason)
        self.assertEqual(set(state.issues), {53, 99})
        self.assertEqual(state.issues[53].milestone, "Loop integrity")
        self.assertEqual(state.labelled(), {53})
        self.assertEqual(state.milestones, tuple(crd.TAG_TO_MILESTONE.values()))

    def test_pull_requests_do_not_count_as_issues(self):
        """The #60 gotcha, made structural rather than remembered.

        The milestones API's `open_issues` field **counts pull requests**. #60
        names this explicitly; #57's PR #56 is the concrete case — a pull request
        assigned to a milestone makes any count derived from an unfiltered list
        report drift that does not exist. It happens to be silent today only
        because no PR is currently milestoned.

        The filter itself is jq's (`select(.pull_request | not)` inside
        `_ISSUES_PROJECTION`), evaluated by `gh` in a process this suite never
        starts, so the hermetic guard has two halves and the docstring says so
        rather than overclaiming:

        1. the projection still carries the filter, and still derives `count`
           from the **unfiltered** `length`; and
        2. `fetch_issue_state` builds issue identity from `rows` alone — a
           milestoned pull request present in the raw page but dropped from
           `rows` never reaches the state, and produces no finding.
        """
        # (1) the projection is intact.
        self.assertIn("select(.pull_request | not)", crd._ISSUES_PROJECTION)
        self.assertIn("count: length", crd._ISSUES_PROJECTION)
        self.assertNotIn("open_issues", crd._ISSUES_PROJECTION)
        self.assertNotIn("open_issues", crd._MILESTONES_PROJECTION)

        # (2) a page whose raw length exceeds its rows — i.e. a page that held a
        # pull request milestoned to "Loop integrity" — yields only the rows.
        page = _page([_row(53, "Loop integrity", LABELLED)], count=2)
        fake = _FakeGh(issue_pages=[page])
        with mock.patch.object(crd, "_run_gh", fake):
            state, reason = crd.fetch_issue_state()
        self.assertIsNone(reason)
        self.assertEqual(set(state.issues), {53})
        self.assertNotIn(56, state.issues)
        # And the per-milestone facts come from the issues, never from a count.
        self.assertEqual(
            _network_findings([_entry(53, "loop", line_no=15)], state), []
        )

    def test_unknown_references_are_resolved_individually(self):
        fake = _FakeGh(
            issue_pages=[_page([_row(53, "Loop integrity", LABELLED)])],
            resolve={
                42: {"number": 42, "state": "closed", "is_pr": False},
                83: {"number": 83, "state": "open", "is_pr": True},
                7: {"number": 7, "state": "open", "is_pr": False},
            },
        )
        with mock.patch.object(crd, "_run_gh", fake):
            state, reason = crd.fetch_issue_state(referenced=[53, 42, 83, 7])
        self.assertIsNone(reason)
        # #83 is a merged PR in this repo and answers /issues/83 happily — the
        # `is_pr` flag is the discriminator, not the HTTP status.
        self.assertEqual(state.resolved, {7: "open", 42: "closed", 83: "missing"})
        self.assertEqual(state.unresolved, ())
        # #53 was in the list, so it cost no extra request.
        self.assertNotIn("issues/53", " ".join(fake.api_paths))

    def test_a_404_resolves_to_missing_rather_than_failing_the_fetch(self):
        """"There is no such issue" is an answer D2 wants, not a fetch failure."""
        def run(args):
            if args[:2] == ["auth", "status"]:
                return _proc(0)
            if "/issues/404" in args[1]:
                return _proc(1, stderr="gh: Not Found (HTTP 404)")
            if "/milestones" in args[1]:
                return _proc(0, json.dumps(_milestone_page()))
            return _proc(0, json.dumps(_page([])))

        with mock.patch.object(crd, "RETRY_SLEEP_SECONDS", 0), \
                mock.patch.object(crd, "_run_gh", run):
            state, reason = crd.fetch_issue_state(referenced=[404])
        self.assertIsNone(reason)
        self.assertEqual(state.resolved, {404: "missing"})

    def test_individual_resolution_is_bounded(self):
        """A badly stale file must not turn one check into a request storm."""
        referenced = list(range(300, 300 + crd.MAX_INDIVIDUAL_RESOLUTIONS + 1))
        fake = _FakeGh(issue_pages=[_page([])])
        with mock.patch.object(crd, "_run_gh", fake):
            state, reason = crd.fetch_issue_state(referenced=referenced)
        self.assertIsNone(reason)
        self.assertEqual(state.resolved, {})
        self.assertEqual(state.unresolved, tuple(referenced))
        # Not one per-issue request was made.
        self.assertEqual(
            [p for p in fake.api_paths if re.search(r"/issues/\d+", p)], []
        )


# ── pagination (R12) ───────────────────────────────────────────────────────

class PaginationTest(unittest.TestCase):
    """The page loop must terminate on the RAW page length, never on `len(rows)`.

    Verified against this repo at `per_page=20`: page 1 returned **20 raw rows of
    which 18 survived the pull-request filter**. An implementation breaking on
    `len(rows) < per_page` therefore stops after page 1 and silently drops the
    remaining 13 issues — a checker that reports PASS on two thirds of the data.
    The bug is invisible to any test that only asserts "two pages were merged",
    because the broken form merges two pages fine whenever no PR was filtered.

    (Nor may the loop be replaced by `gh api --paginate --jq '[…]'`: verified,
    it emits **one JSON array per page**, so `json.loads` raises "Extra data" and
    a working fetch is laundered into a false exit 2. `--slurp` is not the
    rescue — gh 2.87.3 rejects `--slurp` combined with `--jq`.)
    """

    def test_multi_page_response_is_accumulated(self):
        # Page 1: a FULL raw page (100) that yields only 98 rows after the PR
        # filter. This is the exact shape the live repo produced, scaled up.
        page1 = _page([_row(n) for n in range(101, 199)], count=crd.PER_PAGE)
        page2 = _page([_row(n) for n in range(201, 214)])

        # Pin the shape the regression depends on, so a future edit to these
        # literals cannot quietly turn this into the weaker "two pages" test.
        self.assertEqual(page1["count"], crd.PER_PAGE)
        self.assertLess(len(page1["rows"]), crd.PER_PAGE)
        self.assertEqual(len(page1["rows"]), 98)
        self.assertEqual(len(page2["rows"]), 13)

        fake = _FakeGh(issue_pages=[page1, page2])
        with mock.patch.object(crd, "_run_gh", fake):
            state, reason = crd.fetch_issue_state()

        self.assertIsNone(reason)
        # Breaking on the filtered length stops here, at 98.
        self.assertEqual(len(state.issues), 98 + 13)
        self.assertEqual(
            sorted(state.issues), sorted([*range(101, 199), *range(201, 214)])
        )
        # Named explicitly: page 2 is the data the broken form loses.
        self.assertTrue(set(range(201, 214)).issubset(state.issues))
        issue_pages = [
            p for p in fake.api_paths if "/issues?" in p and "/milestones" not in p
        ]
        self.assertEqual(len(issue_pages), 2, issue_pages)
        self.assertTrue(issue_pages[1].endswith("page=2"))

    def test_a_full_page_of_survivors_still_advances(self):
        """The unfiltered case: raw 100, rows 100 — must not stop either."""
        page1 = _page([_row(n) for n in range(1, crd.PER_PAGE + 1)])
        page2 = _page([_row(9001)])
        fake = _FakeGh(issue_pages=[page1, page2])
        with mock.patch.object(crd, "_run_gh", fake):
            state, reason = crd.fetch_issue_state()
        self.assertIsNone(reason)
        self.assertIn(9001, state.issues)
        self.assertEqual(len(state.issues), crd.PER_PAGE + 1)

    def test_a_single_short_page_costs_exactly_one_request(self):
        fake = _FakeGh(issue_pages=[_page([_row(53)])])
        with mock.patch.object(crd, "_run_gh", fake):
            state, reason = crd.fetch_issue_state()
        self.assertIsNone(reason)
        issue_pages = [p for p in fake.api_paths if "/issues?" in p]
        self.assertEqual(len(issue_pages), 1, issue_pages)

    def test_the_page_loop_is_bounded(self):
        """A pathological API response cannot spin the loop forever."""
        full = _page([_row(n) for n in range(1, crd.PER_PAGE + 1)])
        fake = _FakeGh(issue_pages=[full] * (crd.MAX_PAGES + 5))
        with mock.patch.object(crd, "_run_gh", fake):
            state, reason = crd.fetch_issue_state()
        self.assertIsNone(state)
        self.assertIn("too many pages", reason)
        self.assertIn(str(crd.MAX_PAGES), reason)
        issue_pages = [p for p in fake.api_paths if "/issues?" in p]
        self.assertEqual(len(issue_pages), crd.MAX_PAGES)

    def test_pagination_is_explicit_and_never_uses_the_paginate_flag(self):
        """`--paginate` emits one array per page; it must not come back."""
        fake = _FakeGh(issue_pages=[_page([_row(53)])])
        with mock.patch.object(crd, "_run_gh", fake):
            crd.fetch_issue_state()
        flat = [arg for call in fake.calls for arg in call]
        self.assertNotIn("--paginate", flat)
        self.assertNotIn("--slurp", flat)
        for path in fake.api_paths:
            self.assertIn(f"per_page={crd.PER_PAGE}", path)


# ── degradation (R2–R10) ───────────────────────────────────────────────────

class DegradationTest(unittest.TestCase):
    """Every failure becomes `(None, reason)`. **Nothing here may raise.**

    A checker that dies with a traceback teaches a reader nothing about whether
    the roadmap is correct, and R10 requires each reason to read as a *cause*
    rather than as "failed" — the caller prints it verbatim after
    "could not check — ".
    """

    def setUp(self):
        # The retry is what is under test; the five-second wait is not.
        patcher = mock.patch.object(crd, "RETRY_SLEEP_SECONDS", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _fetch(self, gh):
        with mock.patch.object(crd, "_run_gh", gh):
            return crd.fetch_issue_state(referenced=[53])

    def test_gh_missing_returns_a_reason_and_never_raises(self):
        gh = _RecordingGh(OSError(2, "No such file or directory: 'gh'"))
        state, reason = self._fetch(gh)
        self.assertIsNone(state)
        self.assertIn("gh unavailable", reason)
        self.assertIn("not installed", reason)

    def test_unauthenticated_is_a_distinct_reason_and_asks_for_nothing_else(self):
        """"install gh" and "run gh auth login" are different fixes."""
        gh = _RecordingGh(_proc(1, stderr="gh: no token"))
        state, reason = self._fetch(gh)
        self.assertIsNone(state)
        self.assertIn("not authenticated", reason)
        self.assertIn("gh auth login", reason)
        # No API call is attempted once auth is known to be missing.
        self.assertEqual(gh.api_calls, [])

    def test_an_api_error_is_retried_exactly_once(self):
        gh = _RecordingGh(_proc(0), _proc(1, stderr="HTTP 502: Bad gateway\ntrace"))
        state, reason = self._fetch(gh)
        self.assertIsNone(state)
        self.assertEqual(reason, "api error: HTTP 502: Bad gateway")
        self.assertEqual(len(gh.api_calls), 2, gh.calls)
        # Only the first line of gh's stderr reaches a public CI log.
        self.assertNotIn("trace", reason)

    def test_a_transient_error_that_clears_on_the_retry_succeeds(self):
        """One retry absorbs the common 502 rather than masking a real outage."""
        page = json.dumps(_page([_row(53, "Loop integrity", LABELLED)]))
        gh = _RecordingGh(
            _proc(0),                       # auth status
            _proc(1, stderr="HTTP 502"),    # page 1, attempt 1
            _proc(0, page),                 # page 1, attempt 2
            _proc(0, json.dumps(_milestone_page())),
        )
        state, reason = self._fetch(gh)
        self.assertIsNone(reason)
        self.assertEqual(set(state.issues), {53})

    def test_a_rate_limit_is_not_retried(self):
        """Retrying spends another request against a budget already exhausted."""
        gh = _RecordingGh(
            _proc(0),
            _proc(1, stderr="API rate limit exceeded for user ID 1234"),
        )
        state, reason = self._fetch(gh)
        self.assertIsNone(state)
        self.assertIn("rate limited", reason)
        self.assertEqual(len(gh.api_calls), 1, gh.calls)

    def test_a_rate_limit_reported_on_stdout_is_also_recognised(self):
        gh = _RecordingGh(_proc(0), _proc(1, stdout="API Rate Limit Exceeded"))
        state, reason = self._fetch(gh)
        self.assertIsNone(state)
        self.assertIn("rate limited", reason)
        self.assertEqual(len(gh.api_calls), 1)

    def test_a_timeout_during_auth_is_a_reason(self):
        gh = _RecordingGh(subprocess.TimeoutExpired(cmd=["gh"], timeout=crd.GH_TIMEOUT))
        state, reason = self._fetch(gh)
        self.assertIsNone(state)
        self.assertIn("timed out", reason)
        self.assertIn(str(crd.GH_TIMEOUT), reason)

    def test_a_timeout_during_the_api_call_is_a_reason(self):
        gh = _RecordingGh(
            _proc(0), subprocess.TimeoutExpired(cmd=["gh"], timeout=crd.GH_TIMEOUT)
        )
        state, reason = self._fetch(gh)
        self.assertIsNone(state)
        self.assertEqual(reason, f"gh timed out after {crd.GH_TIMEOUT}s")

    def test_gh_vanishing_between_the_auth_check_and_the_api_call_is_a_reason(self):
        gh = _RecordingGh(_proc(0), OSError(2, "No such file or directory: 'gh'"))
        state, reason = self._fetch(gh)
        self.assertIsNone(state)
        self.assertIn("gh unavailable", reason)

    def test_malformed_json_is_a_reason(self):
        gh = _RecordingGh(_proc(0), _proc(0, "<!doctype html><html>502</html>"))
        state, reason = self._fetch(gh)
        self.assertIsNone(state)
        self.assertIn("malformed api response", reason)

    def test_an_unexpected_response_shape_is_a_reason(self):
        """Valid JSON of the wrong shape must not be read as an empty repo."""
        gh = _RecordingGh(_proc(0), _proc(0, "[]"))
        state, reason = self._fetch(gh)
        self.assertIsNone(state)
        self.assertIn("unexpected api response shape", reason)

    def test_no_degradation_path_raises_and_every_reason_is_non_empty(self):
        """R2, stated once over every failure this layer knows how to have."""
        failures = {
            "gh missing": _RecordingGh(OSError(2, "gh")),
            "unauthenticated": _RecordingGh(_proc(1, stderr="no token")),
            "api error": _RecordingGh(_proc(0), _proc(1, stderr="HTTP 500")),
            "rate limited": _RecordingGh(_proc(0), _proc(1, stderr="rate limit")),
            "timeout": _RecordingGh(
                _proc(0), subprocess.TimeoutExpired(cmd=["gh"], timeout=1)
            ),
            "malformed": _RecordingGh(_proc(0), _proc(0, "not json")),
            "wrong shape": _RecordingGh(_proc(0), _proc(0, '{"nope": 1}')),
        }
        for label, gh in failures.items():
            with self.subTest(failure=label):
                try:
                    state, reason = self._fetch(gh)
                except Exception as exc:  # noqa: BLE001 — the assertion is "never"
                    self.fail(f"{label} raised {exc!r}; it must return a reason")
                self.assertIsNone(state)
                self.assertTrue(reason and reason.strip())
                # R10: a cause, not a verdict.
                self.assertNotEqual(reason.lower().strip(), "failed")


# ── degradation, end to end through main() ─────────────────────────────────

class DegradationExitTest(unittest.TestCase):
    """The reasons must survive to the exit code and to stderr, not just return."""

    def setUp(self):
        patcher = mock.patch.object(crd, "RETRY_SLEEP_SECONDS", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_gh_missing_exits_error_and_names_the_reason_on_stderr(self):
        gh = _RecordingGh(OSError(2, "gh"))
        with mock.patch.object(crd, "_run_gh", gh):
            rc, out, err = _run_main(["--roadmap", str(FIXTURES / "clean.md")])
        self.assertEqual(rc, crd.EXIT_ERROR, out + err)
        self.assertIn("could not check", out)
        self.assertIn("gh unavailable", err)
        # R10: never a bare traceback and never a bare "failed".
        self.assertNotIn("Traceback", err)

    def test_unauthenticated_exits_error(self):
        gh = _RecordingGh(_proc(1, stderr="gh: no token"))
        with mock.patch.object(crd, "_run_gh", gh):
            rc, out, err = _run_main(["--roadmap", str(FIXTURES / "clean.md")])
        self.assertEqual(rc, crd.EXIT_ERROR, out + err)
        self.assertIn("not authenticated", err)

    def test_a_failed_fetch_prints_no_reassuring_network_pass_lines(self):
        """Running the checks against an empty state would print five lies."""
        gh = _RecordingGh(OSError(2, "gh"))
        with mock.patch.object(crd, "_run_gh", gh):
            rc, out, _ = _run_main(["--roadmap", str(FIXTURES / "clean.md")])
        self.assertEqual(rc, crd.EXIT_ERROR)
        for name, _check in crd.NETWORK_CHECKS:
            self.assertNotIn(f"PASS  {name}", out)

    def test_json_output_carries_the_fetch_reason(self):
        gh = _RecordingGh(OSError(2, "gh"))
        with mock.patch.object(crd, "_run_gh", gh):
            rc, out, _ = _run_main(
                ["--roadmap", str(FIXTURES / "clean.md"), "--json"]
            )
        payload = json.loads(out)
        self.assertEqual(rc, crd.EXIT_ERROR)
        self.assertEqual(payload["exit"], crd.EXIT_ERROR)
        self.assertFalse(payload["offline"])
        self.assertIn("gh unavailable", payload["fetch_reason"])


# ── exit precedence (R5) ───────────────────────────────────────────────────

class NetworkExitPrecedenceTest(unittest.TestCase):
    """A definite finding outranks an unknown: drift plus a failed fetch is 1."""

    def test_offline_drift_plus_a_real_failed_fetch_exits_drift_not_error(self):
        """Through the actual degradation path, not a mocked `fetch_issue_state`."""
        gh = _RecordingGh(OSError(2, "gh"))
        with mock.patch.object(crd, "RETRY_SLEEP_SECONDS", 0), \
                mock.patch.object(crd, "_run_gh", gh):
            rc, out, err = _run_main(
                ["--roadmap", str(FIXTURES / "duplicate_reference.md")]
            )
        self.assertEqual(rc, crd.EXIT_DRIFT, out + err)
        # The unknown is still *reported*, it just does not win the exit code.
        self.assertIn("could not check", out)

    def test_network_drift_exits_drift(self):
        state = _state(
            list(_clean_state().issues.values())
            + [_issue(77, "Loop integrity", LABELLED)]
        )
        rc, out, err = _run_with_state("clean.md", state)
        self.assertEqual(rc, crd.EXIT_DRIFT, out + err)
        self.assertIn("FAIL  labelled-present", out)
        self.assertIn("#77", out)

    def test_a_hard_finding_outranks_a_co_occurring_advisory(self):
        state = _state(
            [
                _issue(43, None, LABELLED),
                _issue(53, "Loop integrity", LABELLED),
                _issue(35, "Readiness signal", LABELLED),
                _issue(10, "Cross-repo knowledge", LABELLED),
                _issue(29, None, UNLABELLED),               # advisory (D3)
                _issue(77, "Loop integrity", LABELLED),     # hard (D1)
            ]
        )
        rc, out, err = _run_with_state("clean.md", state)
        self.assertEqual(rc, crd.EXIT_DRIFT, out + err)
        self.assertIn("(advisory)", out)
        self.assertIn("FAIL  labelled-present", out)

    def test_a_fully_agreeing_state_exits_pass_with_every_check_reported(self):
        rc, out, err = _run_with_state("clean.md", _clean_state())
        self.assertEqual(rc, crd.EXIT_PASS, out + err)
        for name, _check in crd.NETWORK_CHECKS:
            self.assertIn(f"PASS  {name}", out)
        self.assertNotIn("could not check", out)

    def test_network_check_order_is_stable(self):
        names = [name for name, _ in crd.run_network_checks([], _state())]
        self.assertEqual([name for name, _ in crd.NETWORK_CHECKS], names)

    def test_every_network_check_runs_even_when_an_earlier_one_fails(self):
        """No short-circuit, for the same reason the offline half has none."""
        state = _state(
            [_issue(77, "Docs debt", LABELLED), _issue(53, "Parked", LABELLED)],
            milestones=("Loop integrity",),
        )
        results = dict(crd.run_network_checks([_entry(53, "loop")], state))
        self.assertTrue(results["labelled-present"])
        self.assertTrue(results["tag-agreement"])
        self.assertTrue(results["milestone-vocabulary"])


# ── the real ROADMAP.md: invariants only ───────────────────────────────────

class RealRoadmapTest(unittest.TestCase):
    """Invariants, never counts.

    Which issues earn a roadmap line is an owner decision that moves — the file
    went from 31 references to 24 when it was scoped to planned features, and it
    will move again. Asserting `len(entries) == N` (or `headings == 2`) would
    turn an approved editorial change into a red build, so every assertion here
    is a property that must hold for *any* correct ROADMAP.md.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = crd.DEFAULT_ROADMAP.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()
        cls.entries, cls.notes = crd.parse_roadmap(cls.text)

    def test_the_parser_finds_something(self):
        """Guards against a silently empty parse making every test below vacuous."""
        self.assertTrue(self.entries, f"no references found in {crd.DEFAULT_ROADMAP}")

    def test_offline_checks_are_clean(self):
        findings = [f for _, fs in crd.run_offline_checks(self.entries) for f in fs]
        self.assertEqual(
            [str(f) for f in findings], [], "ROADMAP.md has offline drift"
        )

    def test_at_most_one_entry_per_source_line(self):
        line_nos = [e.line_no for e in self.entries]
        self.assertEqual(sorted(line_nos), sorted(set(line_nos)))

    def test_every_entry_number_appears_in_a_wellformed_link_on_its_own_line(self):
        for entry in self.entries:
            with self.subTest(line=entry.line_no, number=entry.number):
                line = self.lines[entry.line_no - 1]
                self.assertIn(
                    f"https://github.com/{crd.REPO}/issues/{entry.number}", line
                )

    def test_every_tag_is_in_the_vocabulary(self):
        for entry in self.entries:
            if entry.tag is not None:
                with self.subTest(line=entry.line_no):
                    self.assertIn(entry.tag, crd.TAG_TO_MILESTONE)

    def test_heading_entries_carry_no_tag(self):
        for entry in self.entries:
            if entry.kind == "heading":
                self.assertIsNone(entry.tag)

    def test_every_entry_is_a_heading_or_a_bullet(self):
        self.assertEqual(
            {e.kind for e in self.entries} - {"heading", "bullet"}, set()
        )

    def test_running_offline_against_the_real_file_exits_pass(self):
        rc, out, err = _run_main(["--offline"])
        self.assertEqual(rc, crd.EXIT_PASS, out + err)


if __name__ == "__main__":
    unittest.main()
