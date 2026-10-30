"""Tests for the hand-written reference page `docs_site/docs/hooks.md`.

Named `test_gen_reference.py` deliberately: CI collects `docs_site/test_gen_*.py`,
so a file named anything else (e.g. `test_hooks_page.py`) would be written, pass
locally and then never run again. The name is the hook into the CI pattern --
see `docs_site/test_ci_coverage.py` for the pattern itself.

Lives in `docs_site/`, NOT `tests/`: `tests/` syncs into derived instances,
which never receive `docs_site/`, so a test there importing site modules would
break `python -m unittest` for every downstream user. Same rule as
`test_gen_catalog.py` and `test_site_content.py`.

Run from the repo root:

    python -m unittest discover -s docs_site -p "test_gen_reference.py" -v

What these guard, and why each one is worth a test:

  * `hooks.md` is **hand-written** -- nothing generates it, so nothing notices
    when a constant in `hooks/record_stop.py` or `hooks/harvest_nudge.py`
    moves and the prose keeps quoting the old number. Every value assertion
    below is derived from the live module (`rs.RETENTION_DAYS`,
    `hn.PENDING_PREFIX`, `rs.redact(...)`, the parsed env-var default, ...)
    rather than from a literal copied out of the page, so a constant rename or
    a changed default fails here instead of silently making the docs wrong.
  * The two claims on this page that are *safety*-relevant are easy to
    "simplify" into falsehoods by a later editor:
      - retention is a **floor**, not a cap (a record older than
        RETENTION_DAYS is dropped only if it is ALSO at/below the harvest
        watermark -- `prune_lines`), so a bare "deleted after 14 days" would
        promise a deletion the code does not perform;
      - redaction is **best-effort** over a fixed pattern list, so any
        absolute promise ("all secrets are removed", "never contains a
        secret") would overstate `rs.SECRET_PATTERNS`.
    WordingGuardTest fails on either shape. Both guards are sentence-scoped
    and allow an absolute phrase inside an explicitly hedged sentence, which
    is how the page legitimately writes "*not* a guarantee that no secret ever
    reaches the trail".
  * A couple of behaviour tests (BehaviourBackingTest) pin the two code
    behaviours the page describes in words -- whole-preview blanking, and
    redaction running before truncation -- so the prose cannot become
    out-of-date without a local failure. `tests/test_record_stop.py` covers
    these mechanisms in depth; here they exist only as the page's backing.
  * Every source link must resolve to a file that exists in this repo. Dead
    "Source" links are the normal decay mode of a hand-written reference page.
"""

from __future__ import annotations

import inspect
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import catalog_core
import gen_catalog

_DOCS_SITE = Path(__file__).resolve().parent
_REPO_ROOT = _DOCS_SITE.parent
_PAGE = _DOCS_SITE / "docs" / "hooks.md"

# The hooks import each other by bare module name, exactly as the real hook
# runtime (and tests/test_record_stop.py) arranges it.
sys.path.insert(0, str(_REPO_ROOT / "hooks"))

# `harvest_nudge.NUDGE_THRESHOLD` is read from the environment AT IMPORT, so a
# developer who happens to have the override exported would otherwise import a
# module whose "default" is not the default. Clear it for the duration of the
# import and put it back, so the constant we compare against really is the
# shipped default.
_ENV_VAR_UNDER_TEST = "CLAUDE_HARVEST_NUDGE_THRESHOLD"
_saved_override = os.environ.pop(_ENV_VAR_UNDER_TEST, None)
try:
    import harvest_nudge as hn  # noqa: E402
    import record_stop as rs  # noqa: E402
finally:
    if _saved_override is not None:
        os.environ[_ENV_VAR_UNDER_TEST] = _saved_override


def _page() -> str:
    return _PAGE.read_text(encoding="utf-8")


def _squash(text: str) -> str:
    """One line, single-spaced -- the page may wrap a sentence anywhere."""
    return " ".join(text.split())


def _blocks(text: str) -> list[str]:
    """Split markdown into blocks: paragraph, heading, list item, table row.

    Blocking matters for the wording guards below. A plain sentence split of
    the whole squashed page glues the Source list, the table and the closing
    bullets into one giant "sentence" (list items and table rows carry no
    terminating period), so a hedge word four paragraphs away would excuse a
    false claim. Prose still wraps freely *within* a block.
    """
    out: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        starts_block = stripped.startswith(("-", "*", "|", "#", ">")) or re.match(
            r"^\d+\.\s", stripped
        )
        if not stripped or starts_block:
            if current:
                out.append(" ".join(current))
                current = []
        if stripped:
            current.append(stripped)
    if current:
        out.append(" ".join(current))
    return out


def _sentences(text: str) -> list[str]:
    """Block-scoped sentence split, for the sentence-scoped wording guards."""
    return [
        s
        for block in _blocks(text)
        for s in re.split(r"(?<=[.!?])\s+", _squash(block))
        if s.strip()
    ]


def _env_default_from_source() -> tuple[str, int]:
    """`(env var name, default)` parsed out of harvest_nudge's own source.

    Derived, not copied: the page is checked against what the module actually
    reads and actually defaults to.
    """
    src = Path(hn.__file__).read_text(encoding="utf-8")
    m = re.search(
        r"os\.environ\.get\(\s*[\"'](?P<name>[A-Z0-9_]+)[\"']\s*,\s*[\"'](?P<default>\d+)[\"']",
        src,
    )
    assert m is not None, "harvest_nudge no longer reads a defaulted env var"
    return m.group("name"), int(m.group("default"))


def _config_env_name() -> str:
    """The env var `record_stop.config_dir` consults, read off its own source."""
    src = inspect.getsource(rs.config_dir)
    m = re.search(r"os\.environ\.get\(\s*[\"'](?P<name>[A-Z0-9_]+)[\"']", src)
    assert m is not None, "record_stop.config_dir no longer reads an env var"
    return m.group("name")


def _trail_dir_name() -> str:
    """The directory name `record_stop.trail_dir` creates, observed live."""
    saved = os.environ.get("CLAUDE_CONFIG_DIR")
    with tempfile.TemporaryDirectory() as d:
        os.environ["CLAUDE_CONFIG_DIR"] = d
        try:
            return rs.trail_dir().name
        finally:
            if saved is None:
                del os.environ["CLAUDE_CONFIG_DIR"]
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = saved


def _redaction_placeholder() -> str:
    """Whatever `redact` substitutes, observed by feeding it a known shape."""
    out = rs.redact("token AKIA" + "A" * 16 + " tail")
    assert out != "token AKIA" + "A" * 16 + " tail", (
        "redact() no longer matches an AWS access key id; this helper needs a "
        "sample that SECRET_PATTERNS still recognises"
    )
    return out


class PageExistsTest(unittest.TestCase):
    def test_page_is_present_and_not_generated(self):
        self.assertTrue(_PAGE.is_file(), f"missing {_PAGE}")
        text = _page()
        self.assertNotIn(
            "Generated by",
            text,
            "hooks.md is hand-written; a generated banner means the contract "
            "of this test file changed",
        )

    def test_the_catalog_generator_never_produces_this_page(self):
        """`gen_catalog` must not claim `hooks.md` as one of its artefacts.

        The page-exists guard above only notices a banner that was *written*;
        this one closes the door one step earlier. `gen_catalog.generate`
        writes every key of `build_pages` into `docs/`, so the moment
        `hooks.md` appears in that mapping the hand-written page is
        overwritten on the next regeneration -- and `--check` starts failing
        the build over prose a human deliberately typed. The four generated
        pages are asserted by name so that a *renamed* generated page also
        has to come through this test.
        """
        pages, _ = gen_catalog.build_pages(_REPO_ROOT)
        self.assertNotIn(
            _PAGE.name,
            pages,
            f"gen_catalog.build_pages now renders {_PAGE.name}, which is "
            "hand-written; generating it would overwrite the page on the next "
            "`python docs_site/gen_catalog.py`",
        )
        self.assertEqual(
            sorted(pages),
            ["agents.md", "commands.md", "lifecycle.md", "skills.md"],
        )

    def test_page_is_wired_into_the_nav(self):
        yml = (_DOCS_SITE / "mkdocs.yml").read_text(encoding="utf-8")
        self.assertIn("hooks.md", yml, "hooks.md is not referenced by mkdocs.yml nav")


class ConstantsTest(unittest.TestCase):
    """Every number and name on the page, derived from the live modules."""

    def setUp(self):
        self.text = _page()
        self.squashed = _squash(self.text)

    def test_states_the_nudge_threshold_default(self):
        name, default = _env_default_from_source()
        self.assertEqual(
            default,
            hn.NUDGE_THRESHOLD,
            "imported NUDGE_THRESHOLD disagrees with the source default",
        )
        self.assertRegex(
            self.squashed,
            rf"defaults?[^.]{{0,20}}?`?{default}`?",
            f"page does not state the {name} default of {default}",
        )
        # And no *other* number may be presented as the default: a stale
        # "default `50`" alongside a surviving correct mention must still fail.
        stated = re.findall(r"defaults?(?:\s+to)?\s*`?(\d+)`?", self.squashed)
        self.assertTrue(stated, "page states no default value at all")
        self.assertEqual(
            {str(default)},
            set(stated),
            f"page states a default other than {default}: {sorted(set(stated))}",
        )

    def test_states_the_env_var_name(self):
        name, _ = _env_default_from_source()
        self.assertIn(name, self.text, "page does not name the threshold env var")

    def test_states_the_config_dir_env_var(self):
        self.assertIn(
            _config_env_name(),
            self.text,
            "page does not name the env var that relocates the trail",
        )

    def test_states_the_retention_days(self):
        self.assertRegex(
            self.squashed,
            rf"\b{rs.RETENTION_DAYS}\s+days\b",
            f"page does not state RETENTION_DAYS ({rs.RETENTION_DAYS})",
        )

    def test_states_the_pending_prefix(self):
        self.assertIn(
            hn.PENDING_PREFIX,
            self.text,
            f"page does not state PENDING_PREFIX ({hn.PENDING_PREFIX!r})",
        )

    def test_states_the_trail_directory_name(self):
        self.assertIn(
            _trail_dir_name(),
            self.text,
            "page does not state the learning-trail directory name",
        )

    def test_states_the_watermark_suffix(self):
        suffix = rs.watermark_path(Path("x.jsonl")).suffix  # ".watermark"
        self.assertIn(
            suffix,
            self.text,
            f"page does not mention the watermark sibling ({suffix})",
        )

    def test_states_the_redaction_placeholder(self):
        self.assertIn(
            _redaction_placeholder(),
            self.text,
            "page does not state what the preview is blanked to",
        )

    def test_mentions_the_absolute_record_ceiling(self):
        # The page states the ceiling qualitatively ("absolute record cap")
        # rather than quoting ABSOLUTE_MAX_RECORDS; what must not vanish is the
        # fact that un-harvested growth IS bounded.
        self.assertTrue(hasattr(rs, "ABSOLUTE_MAX_RECORDS"))
        self.assertRegex(
            self.squashed.lower(),
            r"(?:absolute|record)[^.]{0,40}(?:cap|ceiling)",
            "page no longer says the un-harvested trail is bounded by a cap",
        )

    def test_names_the_session_start_sources(self):
        for source in sorted(hn.NUDGE_SOURCES):
            self.assertIn(
                source,
                self.text,
                f"page does not name SessionStart source {source!r}",
            )

    def test_names_the_trigger_script_it_shells_out_to(self):
        src = Path(hn.__file__).read_text(encoding="utf-8")
        m = re.search(r"[\"'](scripts/check_memory_triggers\.py)[\"']", src) or re.search(
            r"[\"'](check_memory_triggers\.py)[\"']", src
        )
        self.assertIsNotNone(
            m, "harvest_nudge no longer references check_memory_triggers.py"
        )
        self.assertIn(
            "check_memory_triggers.py",
            self.text,
            "page does not name the trigger script the hook invokes",
        )


class WordingGuardTest(unittest.TestCase):
    """Fail on the two over-simplifications that would make the page lie."""

    #: Hedges that make a "deleted after N days" sentence honest.
    _RETENTION_HEDGES = (
        "not",
        "never",
        "nothing",
        "floor",
        "earliest",
        "only",
        "eligible",
        "regardless",
        "longer",
    )

    #: Hedges that make an absolute-sounding redaction sentence honest. Note
    #: "never"/"no" are NOT hedges here -- they are the very words an absolute
    #: promise is written with.
    _REDACTION_HEDGES = (
        "not ",
        "nothing",
        "best-effort",
        "best effort",
        "known-patterns",
        "known patterns",
        "rather than",
        "unless",
        "does not know",
    )

    def setUp(self):
        self.sentences = _sentences(_page())

    def _offenders(self, pattern: re.Pattern[str], hedges: tuple[str, ...]) -> list[str]:
        bad = []
        for sentence in self.sentences:
            low = sentence.lower()
            if pattern.search(low) and not any(h in low for h in hedges):
                bad.append(sentence)
        return bad

    def test_no_bare_retention_cap_claim(self):
        cap = re.compile(
            r"(?:deleted|removed|purged|pruned|dropped|erased|discarded|expire\w*|"
            rf"disappear\w*|gone)\b[^.]{{0,60}}?\bafter\s+{rs.RETENTION_DAYS}\s+days"
            rf"|\bafter\s+{rs.RETENTION_DAYS}\s+days\b[^.]{{0,60}}"
            r"(?:deleted|removed|purged|pruned|dropped|erased|discarded|gone)"
            rf"|\bretention\b[^.]{{0,20}}:\s*{rs.RETENTION_DAYS}\s+days\s*$"
        )
        self.assertEqual(
            [],
            self._offenders(cap, self._RETENTION_HEDGES),
            "page claims records are deleted after RETENTION_DAYS; prune_lines "
            "drops a record only when it is ALSO at/below the harvest watermark, "
            "so the number is a floor, not a cap",
        )

    def test_says_retention_is_a_floor(self):
        low = _squash(_page()).lower()
        self.assertIn(
            "floor",
            low,
            "page never says the retention window is a floor",
        )
        self.assertRegex(
            low,
            r"un-?harvested[^.]{0,80}regardless of age",
            "page no longer says un-harvested records are kept regardless of age",
        )

    def test_no_absolute_redaction_promise(self):
        absolute = re.compile(
            r"all secrets?\b"
            r"|every secret\b"
            r"|any secret[^.]{0,30}(?:is|are|will be)\s+(?:redacted|removed|stripped|masked)"
            r"|no secrets?\s+(?:ever\s+)?(?:reach|reaches|land|lands|appear|appears|enter|enters|get|gets)"
            r"|never\s+(?:contains?|reach\w*|leak\w*|land\w*|appear\w*|include[sd]?)"
            r"|(?:fully|completely|always|guaranteed)\s+redact\w*"
            r"|guarantee[sd]?\s+(?:that\s+)?no\s+secret"
            r"|100%"
        )
        self.assertEqual(
            [],
            self._offenders(absolute, self._REDACTION_HEDGES),
            "page makes an absolute redaction promise; SECRET_PATTERNS is a "
            f"fixed list of {len(rs.SECRET_PATTERNS)} known shapes and cannot "
            "guarantee that",
        )

    def test_redaction_section_is_marked_best_effort(self):
        text = _page()
        # The section that talks about redaction must carry the hedge, not just
        # some distant paragraph.
        sections = re.split(r"^#{2,}\s+", text, flags=re.MULTILINE)
        redaction_sections = [
            s for s in sections if "redact" in s.lower() or "secret" in s.lower()
        ]
        self.assertTrue(
            redaction_sections, "page no longer has a section about redaction"
        )
        self.assertTrue(
            any(
                "best-effort" in s.lower() or "best effort" in s.lower()
                for s in redaction_sections
            ),
            "no redaction section on the page describes redaction as best-effort",
        )

    def test_says_unknown_shapes_are_kept(self):
        low = _squash(_page()).lower()
        self.assertRegex(
            low,
            r"(?:does not know|not know|unknown|a shape this list)",
            "page no longer admits that a secret in an unrecognised shape "
            "survives into the trail",
        )

    def test_does_not_claim_the_transcript_is_read(self):
        low = _squash(_page()).lower()
        self.assertIn(
            "never opened",
            low,
            "page no longer states the transcript path is stored without being "
            "opened -- the hook deliberately does not read it",
        )


class BehaviourBackingTest(unittest.TestCase):
    """The page's two prose claims about behaviour, asserted against the code."""

    def test_whole_preview_is_blanked_not_partially_masked(self):
        placeholder = _redaction_placeholder()
        preview = rs.message_preview("here is my key AKIA" + "A" * 16 + " thanks")
        self.assertEqual(
            placeholder,
            preview,
            "page says the WHOLE preview is blanked; it is not",
        )

    def test_redaction_runs_before_truncation(self):
        placeholder = _redaction_placeholder()
        secret = "AKIA" + "A" * 16
        message = ("x" * (rs.PREVIEW_MAX + 50)) + " " + secret
        self.assertEqual(
            placeholder,
            rs.message_preview(message),
            "page says matching runs before truncation, so a secret past the "
            "cut is still caught",
        )

    def test_old_unharvested_record_survives_pruning(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        old = (now - timedelta(days=rs.RETENTION_DAYS * 10)).isoformat()
        line = '{"ts": "%s", "session_id": "s"}' % old
        self.assertEqual(
            [line],
            rs.prune_lines([line], now=now, watermark=None),
            "page says un-harvested records are kept regardless of age",
        )

    def test_old_harvested_record_is_pruned(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        old_dt = now - timedelta(days=rs.RETENTION_DAYS * 10)
        line = '{"ts": "%s", "session_id": "s"}' % old_dt.isoformat()
        watermark = now - timedelta(days=rs.RETENTION_DAYS * 2)
        self.assertEqual(
            [],
            rs.prune_lines([line], now=now, watermark=watermark),
            "page says a record older than the window AND harvested is dropped",
        )


class SourceLinkTest(unittest.TestCase):
    """Every link on the page resolves to something that exists."""

    _LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

    def setUp(self):
        self.links = self._LINK_RE.findall(_page())
        self.assertTrue(self.links, "page has no links at all")

    def test_repo_blob_links_point_at_existing_files(self):
        base = catalog_core.REPO_BLOB_BASE
        blob_links = [u for u in self.links if u.startswith(base)]
        self.assertTrue(
            blob_links,
            f"page has no source links under {base}; either the canonical repo "
            "base moved or the Source section lost its links",
        )
        for url in blob_links:
            rel = url[len(base) :].lstrip("/").split("#", 1)[0]
            with self.subTest(url=url):
                self.assertTrue(
                    (_REPO_ROOT / rel).exists(),
                    f"source link points at missing file: {rel}",
                )

    def test_links_the_two_hook_modules_it_documents(self):
        page = _page()
        for module in (rs, hn):
            rel = Path(module.__file__).resolve().relative_to(_REPO_ROOT).as_posix()
            with self.subTest(module=module.__name__):
                self.assertIn(
                    rel,
                    page,
                    f"page documents {module.__name__} but never links {rel}",
                )

    def test_relative_page_links_resolve(self):
        docs = _PAGE.parent
        for url in self.links:
            if "://" in url or url.startswith(("#", "mailto:")):
                continue
            target = url.split("#", 1)[0]
            if not target:
                continue
            with self.subTest(url=url):
                self.assertTrue(
                    (docs / target).exists(),
                    f"relative link points at missing page: {target}",
                )

    def test_no_external_links_outside_the_canonical_repo(self):
        for url in self.links:
            if "://" not in url:
                continue
            with self.subTest(url=url):
                self.assertTrue(
                    url.startswith(catalog_core.REPO_BLOB_BASE)
                    or url.startswith("https://github.com/noctua84/nescio-ai"),
                    f"unexpected off-site link on a reference page: {url}",
                )


if __name__ == "__main__":
    unittest.main()
