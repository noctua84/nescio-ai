# tests/test_sync_theme_hygiene.py
"""Hygiene pins for the theme-aware overlay sync (issue #133, task T10).

`scripts/sync_from_upstream.py`'s themed branch materialises upstream's
`agents/` into a temp directory and runs `scripts/apply_theme.py`'s renderer
over it before comparing. That machinery has five separate ways to leak or
misbehave that the *contract* tests (empty plan, correct triple) do not touch
at all, because none of them change what is added/updated/deleted:

* W1 — the renderer is chatty, and every word of it describes a temp
  directory the operator has never heard of. It must never reach the sync's
  own stdout/stderr on success, and on failure `main()`'s own framing must
  come first.
* R2's replacement — the materialised root must hold nothing but `agents/`,
  so the renderer's word-level transform can never reach
  `scripts/_crew_common.py`'s `PAIRS` table.
* The temp directory itself must not outlive the call, on the success path
  and on the `rc != 0` refusal path alike.
* W2/W3 — `--diff` on a themed instance must not raise, must report exactly
  one `net-new:` footer, and must annotate renamed agents with where they
  came from.
* R6, arriving through a new door — a CRLF themed dest holding the same
  themed text as the freshly rendered upstream must not read as changed.

Theme-agnostic throughout (this repo may itself be on either theme when the
suite runs — see `tests/test_agent_definitions.py:118-141` for the pattern
this module copies) and reads nothing under `.github/`.
"""

import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_theme  # noqa: E402
import sync_from_upstream as sfu  # noqa: E402

AGENTS_DIR = ROOT / "agents"


def _make_instance(root: Path, theme: str) -> Path:
    """installer + a real copy of `agents/`, converged onto `theme`.

    Seeded from this repo's own `agents/` rather than a synthetic fixture so
    the renderer runs over the real eleven-file roster, matching the shape of
    `ApplyThemeRoundTripTest` (`tests/test_apply_theme.py:79-93`). Theme is
    *read off the tree first and only converged if it disagrees*: this repo
    may itself be shipped on either theme (`tests` is inside
    `FRAMEWORK_PATHS`), so assuming a starting theme would assert this repo's
    own state rather than a property of the framework.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "install.py").write_text("# installer\n", encoding="utf-8")
    agents_dir = root / "agents"
    agents_dir.mkdir(parents=True)
    for src in AGENTS_DIR.glob("*.md"):
        (agents_dir / src.name).write_bytes(src.read_bytes())
    if apply_theme.detect_theme(agents_dir) != theme:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = apply_theme.apply_theme(agents_dir, theme)
        assert rc == 0, f"fixture setup: could not converge onto {theme!r}"
    return root


def _make_crewless_upstream(root: Path) -> Path:
    """A checkout with neither theme representative present.

    This is the bootstrap-case fixture from `tests/test_sync_from_upstream.py`
    (`_make_checkout`), reused here for a different purpose: materialising it
    into a theme makes the renderer's own `apply_theme` call return 2
    ("could not detect the crew"), which is what the render-refusal (P2)
    hygiene tests in this module need to exercise.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "install.py").write_text("# installer\n", encoding="utf-8")
    (root / "agents").mkdir(parents=True)
    (root / "agents" / "explore.md").write_text("explore\n", encoding="utf-8")
    return root


def _tempdir_recorder():
    """A drop-in replacement for `tempfile.TemporaryDirectory` that records
    every path it hands out.

    Patched onto `sync_from_upstream`'s `tempfile` reference so a test can
    assert on the materialised root's path *after* the `with` block that owns
    it inside `main()` has exited and cleaned it up — the thing under test is
    that cleanup, not the directory's contents.
    """
    recorded: list[str] = []

    class _Recording(tempfile.TemporaryDirectory):
        def __enter__(self):
            name = super().__enter__()
            recorded.append(name)
            return name

    return _Recording, recorded


class RendererOutputCaptureTest(unittest.TestCase):
    """W1: the renderer's own chatter must never reach the sync's own streams.

    Verified directly against `apply_theme`: a normal philosophers render
    emits thirteen `renamed X -> Y` / `switched crew` lines on stdout, and
    when the materialised copy is missing a themed agent's functional source
    — a genuine upstream deletion, reproduced below by removing
    `agents/qa-guard.md` from upstream before the sync runs — the renderer
    also writes an `expected ... not found` line on stderr. Every one of
    those lines describes `scripts/apply_theme.py`'s own private temp copy of
    upstream, a directory the operator syncing `dest` has never heard of, so
    none of it may survive `main()`'s themed branch on a successful run.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = _make_instance(base / "upstream", "functional")
        self.dst = _make_instance(base / "dest", "philosophers")
        # A genuine upstream deletion, so the renderer also writes to stderr
        # (verified in the plan's spike: "after upstream deletes qa-guard.md
        # -> deleted=['agents/cato.md']").
        (self.up / "agents" / "qa-guard.md").unlink()

    def tearDown(self):
        self._tmp.cleanup()

    def test_renderer_chatter_never_reaches_mains_own_streams(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst)])
        self.assertEqual(rc, 0, err.getvalue())

        combined = out.getvalue() + "\n" + err.getvalue()
        for phrase in ("renamed ", "switched crew", "would update refs in",
                       "expected ", "not found"):
            self.assertNotIn(phrase, combined, f"renderer chatter {phrase!r} leaked")

        # The deletion itself must still be reported — capture discards the
        # renderer's *own* narration of it, not the sync's.
        self.assertIn("cato.md", out.getvalue())


class RenderFailureFramingTest(unittest.TestCase):
    """W1, the failure half: `main()`'s framing line must precede the
    renderer's captured text it quotes.

    The refusal itself (a non-zero `rc` from the materialising `apply_theme`
    call) is T9's to cover; this only pins the *ordering*. Without the
    framing line first, the operator would see a bare error about a
    `/tmp/...` path they never asked for, with no account of which
    `--upstream` produced it.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        # Neither planner.md nor plato.md: theme_representatives(upstream) is
        # {}, so step 2's themed-upstream guard passes, and materialisation
        # proceeds to call apply_theme over a crewless copy, which returns 2
        # with "could not detect the crew".
        self.up = _make_crewless_upstream(base / "upstream")
        self.dst = _make_instance(base / "dest", "philosophers")

    def tearDown(self):
        self._tmp.cleanup()

    def test_mains_framing_line_precedes_the_captured_renderer_text(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst)])
        self.assertEqual(rc, 2)

        stderr_text = err.getvalue()
        framing_idx = stderr_text.find("could not render upstream's crew")
        renderer_idx = stderr_text.find("could not detect the crew")
        self.assertNotEqual(framing_idx, -1, stderr_text)
        self.assertNotEqual(renderer_idx, -1, stderr_text)
        self.assertLess(framing_idx, renderer_idx,
                         "main()'s framing must appear before the quoted renderer text")
        # The framing line is what tells the operator which --upstream this is about.
        self.assertIn(str(self.up), stderr_text)


class MaterialisedRootScopeTest(unittest.TestCase):
    """R2's replacement: the temp root the renderer runs over holds only
    `agents/`, so the theme transform can never reach
    `scripts/_crew_common.py`'s `PAIRS` table.

    Transforming `PAIRS` into `[("plato", "plato"), ...]` would make
    `themed_name` the identity and make the theme permanently unrevertable in
    every instance that syncs it afterwards — the rejected lens design needed
    a thirteen-file audit to rule this out. Here it is unreachable by
    construction: `main()` only ever `shutil.copytree`s `upstream/agents`
    into the temp root, so `scripts/` is never present for the renderer to
    reach at all. This test pins that structural fact by running a themed
    `--apply` against an upstream that *does* carry
    `scripts/_crew_common.py`, and checking the applied copy in `dest` is
    byte-identical to upstream's — i.e. it travelled through the plain,
    untransformed `others` half of the sync, not through the renderer.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = _make_instance(base / "upstream", "functional")
        self.dst = _make_instance(base / "dest", "philosophers")
        self.crew_common_bytes = (ROOT / "scripts" / "_crew_common.py").read_bytes()
        (self.up / "scripts").mkdir(parents=True, exist_ok=True)
        (self.up / "scripts" / "_crew_common.py").write_bytes(self.crew_common_bytes)

    def tearDown(self):
        self._tmp.cleanup()

    def test_scripts_crew_common_survives_a_themed_apply_untransformed(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])
        self.assertEqual(rc, 0, err.getvalue())

        dst_bytes = (self.dst / "scripts" / "_crew_common.py").read_bytes()
        self.assertEqual(dst_bytes, self.crew_common_bytes)
        # PAIRS itself, untouched: still maps functional names to philosopher
        # ones, not to themselves.
        self.assertIn(b'("planner", "plato")', dst_bytes)


class TempDirLifetimeTest(unittest.TestCase):
    """The materialised temp directory must not survive the call — on the
    success path and on the render-failure refusal path alike.

    `main()`'s `with tempfile.TemporaryDirectory() as tmp:` block spans plan
    -> diff -> apply on success, and is exited via an early `return 2` on
    refusal; both are ordinary context-manager exits, but this pins the
    observable consequence rather than trusting the `with` statement's own
    contract.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def test_temp_dir_does_not_survive_a_successful_run(self):
        base = Path(self._tmp.name)
        up = _make_instance(base / "upstream", "functional")
        dst = _make_instance(base / "dest", "philosophers")

        recorder_cls, recorded = _tempdir_recorder()
        with patch.object(sfu.tempfile, "TemporaryDirectory", recorder_cls):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = sfu.main(["--upstream", str(up), "--dest", str(dst)])
        self.assertEqual(rc, 0, err.getvalue())
        self.assertEqual(len(recorded), 1, "expected exactly one materialised temp root")
        self.assertFalse(Path(recorded[0]).exists(),
                          f"temp root {recorded[0]} survived a successful main()")

    def test_temp_dir_does_not_survive_a_render_refusal(self):
        base = Path(self._tmp.name)
        up = _make_crewless_upstream(base / "upstream")
        dst = _make_instance(base / "dest", "philosophers")

        recorder_cls, recorded = _tempdir_recorder()
        with patch.object(sfu.tempfile, "TemporaryDirectory", recorder_cls):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = sfu.main(["--upstream", str(up), "--dest", str(dst)])
        self.assertEqual(rc, 2)
        self.assertEqual(len(recorded), 1, "expected exactly one materialised temp root")
        self.assertFalse(Path(recorded[0]).exists(),
                          f"temp root {recorded[0]} survived a refused main()")


class DiffOnThemedInstanceTest(unittest.TestCase):
    """W2/W3: `--diff` against a themed instance with a pending update.

    `render_diff` must not raise — a `FileNotFoundError` here was a confirmed
    defect of the rejected (lens-based) design, resolving plan strings
    against the wrong root; it is now impossible because every plan string
    names a real file either under the materialised temp root or under the
    real upstream. The paths the rendered diff actually names must be
    exactly the plan's (normalised to POSIX, since the plan itself is
    OS-native), and the two per-root `render_diff` calls (`summary=False`
    each) must combine into **exactly one** `net-new:` footer, not two.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = _make_instance(base / "upstream", "functional")
        self.dst = _make_instance(base / "dest", "philosophers")
        # A real, theme-invariant content change: explore.md keeps its
        # filename under every theme, so this is an unambiguous single-entry
        # "updated" fixture.
        explore = self.up / "agents" / "explore.md"
        explore.write_text(
            explore.read_text(encoding="utf-8") + "\n<!-- upstream edit -->\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _plan_paths(stdout_text: str) -> set[str]:
        paths = set()
        for line in stdout_text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("+ add", "~ update", "- delete")):
                item = stripped.split(None, 2)[-1]
                paths.add(Path(item).as_posix())
        return paths

    def test_diff_does_not_raise_and_reports_exactly_one_net_new_footer(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--diff"])
        self.assertEqual(rc, 0)

        text = out.getvalue()
        self.assertEqual(text.count("net-new:"), 1, text)

    def test_diff_paths_match_the_plan_exactly(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--diff"])
        self.assertEqual(rc, 0)
        text = out.getvalue()

        plan_paths = self._plan_paths(text)
        self.assertTrue(plan_paths, f"fixture produced no pending change:\n{text}")

        # A text UPDATED entry names its path only in the unified-diff header
        # (`--- a/<posix> (current)`); `~ UPDATED  <posix>` is the binary-file
        # branch, which this fixture does not exercise but which a general
        # extraction should still cover.
        diff_paths = (
            set(re.findall(r"^--- a/(\S+) \(current\)$", text, re.MULTILINE))
            | set(re.findall(r"^~ UPDATED\s+(\S+)$", text, re.MULTILINE))
            | set(re.findall(r"^\+\+\+ ADDED\s+(\S+)", text, re.MULTILINE))
            | set(re.findall(r"^--- DELETED\s+(\S+)", text, re.MULTILINE))
        )
        self.assertEqual(plan_paths, diff_paths)


class ProvenanceHeaderTest(unittest.TestCase):
    """W3: an updated *renamed* agent's diff header names the upstream file
    it came from; an updated *theme-invariant* agent's header does not.

    Display-only (no correctness depends on it — see `render_diff`'s
    docstring), but exercised end to end through `main()` so a drift in how
    `prov` is built (its POSIX-keying in particular — a
    `str(Path(...))`-built key would silently never match on Windows) shows
    up here rather than only in a unit test of `render_diff` itself.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = _make_instance(base / "upstream", "functional")
        self.dst = _make_instance(base / "dest", "philosophers")
        for name in ("planner.md", "explore.md"):
            p = self.up / "agents" / name
            p.write_text(p.read_text(encoding="utf-8") + "\n<!-- upstream edit -->\n",
                          encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_renamed_agent_gets_provenance_unrenamed_agent_does_not(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--diff"])
        self.assertEqual(rc, 0)

        text = out.getvalue()
        self.assertIn("b/agents/plato.md (upstream agents/planner.md, themed)", text)
        self.assertIn("b/agents/explore.md (upstream)", text)
        # And not the other way around.
        self.assertNotIn("b/agents/explore.md (upstream agents", text)


class CrlfThemedDestTest(unittest.TestCase):
    """R6, arriving through a new door: a CRLF themed dest holding the same
    themed *text* as the freshly rendered upstream must read as not updated.

    This holds because `_files_equal` is completely untouched by the theme
    feature, and because the materialised temp copy is written by
    `shutil.copy2` (upstream's bytes verbatim) and the existing renderer's
    `newline=""` writes (which preserve whatever line ending the source
    already had) — nothing in the themed path introduces a newline
    translation `_files_equal` doesn't already normalise away. Pinned anyway,
    because it is the exact failure mode `LineEndingTest`
    (`tests/test_sync_from_upstream.py:165-268`) exists for, arriving at the
    same comparison through the new materialisation door rather than the old
    direct one.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = _make_instance(base / "upstream", "functional")
        self.dst = _make_instance(base / "dest", "philosophers")

    def tearDown(self):
        self._tmp.cleanup()

    def test_crlf_themed_dest_with_identical_text_is_not_reported_updated(self):
        # dest's plato.md already holds the canonical themed rendering of the
        # same real agents/ source upstream was seeded from (apply_theme is
        # deterministic and round-trip-safe — see ApplyThemeRoundTripTest),
        # so rewriting it with CRLF line endings and nothing else isolates
        # exactly the newline-only difference under test.
        plato = self.dst / "agents" / "plato.md"
        original_text = plato.read_text(encoding="utf-8")
        plato.write_bytes(original_text.replace("\n", "\r\n").encode("utf-8"))

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst)])
        self.assertEqual(rc, 0)
        self.assertIn("framework already in sync", out.getvalue())
        self.assertNotIn("plato.md", out.getvalue())


if __name__ == "__main__":
    unittest.main()
