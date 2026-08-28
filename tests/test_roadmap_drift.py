# tests/test_roadmap_drift.py — the offline half of scripts/check_roadmap_drift.py.
"""Tests for the parser, the offline checks, and the exit convention.

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
"""

import contextlib
import io
import json
import shutil
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
