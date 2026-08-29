import tempfile
import unittest
from pathlib import Path

import wiki_index


def _note(dir_path, fname, name, desc):
    (dir_path / fname).write_text(
        f"---\nname: {name}\ndescription: {desc}\ntype: concept\n---\nbody\n",
        encoding="utf-8",
    )


def _write_bytes(path, text, *, crlf=False):
    """Write `text` with line endings under exact control.

    `Path.write_text` translates "\\n" to os.linesep, which on Windows would
    silently make every fixture CRLF and hide the very thing the line-ending
    tests are about. Normalise to LF first, then expand only when asked.
    """
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    path.write_bytes(data.encode("utf-8"))


def _index(root):
    return root / "MEMORY.md"


# --- Scenario builders -------------------------------------------------------
# Shared by the per-row tests and by the "--check never writes" sweep, so the
# two can never drift apart.

def _setup_prose_above_block(root):
    _note(root, "a.md", "alpha", "first")
    _write_bytes(
        _index(root),
        "# Orientation\n\nprose\n\n" + wiki_index.render_block("- [stale](zz.md) — old"),
    )


def _setup_prose_below_block(root):
    _note(root, "a.md", "alpha", "first")
    _write_bytes(
        _index(root),
        wiki_index.render_block("- [stale](zz.md) — old") + "\n## Hand notes\n\nprose\n",
    )


def _setup_markerless_line_identical(root):
    _note(root, "b.md", "beta", "second")
    _note(root, "a.md", "alpha", "first")
    _write_bytes(_index(root), "- [alpha](a.md) — first\n- [beta](b.md) — second\n")


def _setup_markerless_reordered(root):
    _note(root, "b.md", "beta", "second")
    _note(root, "a.md", "alpha", "first")
    _write_bytes(_index(root), "- [beta](b.md) — second\n- [alpha](a.md) — first\n")


def _setup_start_here_annotation(root):
    _note(root, "auth-model.md", "auth model", "how auth works")
    _note(root, "sessions.md", "sessions", "session handling")
    _write_bytes(
        _index(root),
        "- [START HERE — read before touching sessions](auth-model.md)"
        " — ask Markus first\n",
    )


def _setup_adr_bullets_only(root):
    """The `ai-os#138` `repo/soulsgate-payment` shape: bullets, zero prose."""
    _note(root, "a.md", "alpha", "first")
    (root / "adr").mkdir(exist_ok=True)
    _note(root / "adr", "0001-x.md", "0001 x", "a decision")
    _write_bytes(
        _index(root),
        "- [alpha](a.md) — first\n- [ADR 0001](adr/0001-x.md) — a decision\n",
    )


def _setup_curated_prose(root):
    _note(root, "a.md", "a", "d")
    _write_bytes(_index(root), "# Index\n\nHand-written orientation.\n\n- [a](a.md) — d\n")


def _setup_append_full_overlap(root):
    _note(root, "a.md", "alpha", "first")
    _note(root, "b.md", "beta", "second")
    _write_bytes(_index(root), "# Index\n\n- [alpha](a.md)\n- [beta](b.md)\n")


def _setup_append_partial_overlap(root):
    _note(root, "a.md", "alpha", "first")
    _note(root, "b.md", "beta", "second")
    _note(root, "c.md", "gamma", "third")
    _write_bytes(_index(root), "# Index\n\nOnly one is curated:\n\n- [alpha](a.md)\n")


def _setup_append_no_overlap(root):
    _note(root, "a.md", "alpha", "first")
    _note(root, "b.md", "beta", "second")
    _note(root, "c.md", "gamma", "third")
    _write_bytes(_index(root), "# Index\n\nHand-written orientation, no links.\n")


def _setup_missing_end_marker(root):
    _note(root, "a.md", "alpha", "first")
    _write_bytes(
        _index(root),
        f"# Index\n\n{wiki_index.GENERATED_BEGIN}\n\n- [alpha](a.md) — first\n",
    )


def _setup_missing_begin_marker(root):
    _note(root, "a.md", "alpha", "first")
    _write_bytes(
        _index(root),
        f"# Index\n\n- [alpha](a.md) — first\n\n{wiki_index.GENERATED_END}\n",
    )


def _setup_reversed_markers(root):
    _note(root, "a.md", "alpha", "first")
    _write_bytes(
        _index(root),
        f"{wiki_index.GENERATED_END}\n\n- [alpha](a.md) — first\n\n"
        f"{wiki_index.GENERATED_BEGIN}\n",
    )


def _setup_duplicate_begin_markers(root):
    _note(root, "a.md", "alpha", "first")
    _write_bytes(
        _index(root),
        f"{wiki_index.GENERATED_BEGIN}\n\n{wiki_index.GENERATED_BEGIN}\n\n"
        f"- [alpha](a.md) — first\n\n{wiki_index.GENERATED_END}\n",
    )


def _setup_duplicate_end_markers(root):
    _note(root, "a.md", "alpha", "first")
    _write_bytes(
        _index(root),
        f"{wiki_index.GENERATED_BEGIN}\n\n- [alpha](a.md) — first\n\n"
        f"{wiki_index.GENERATED_END}\n\n{wiki_index.GENERATED_END}\n",
    )


def _setup_empty_folder(root):
    (root / ".gitkeep").write_text("", encoding="utf-8")


def _setup_emptied_folder(root):
    _write_bytes(_index(root), wiki_index.render_block("- [alpha](a.md) — first"))


def _setup_crlf_pure_generated(root):
    _note(root, "a.md", "alpha", "first")
    _write_bytes(_index(root), "- [alpha](a.md) — first\n", crlf=True)


def _setup_crlf_prose_above_block(root):
    _note(root, "a.md", "alpha", "first")
    _write_bytes(_index(root), "# Orientation\n\nprose\n\n", crlf=True)
    with _index(root).open("ab") as fh:
        fh.write(wiki_index.render_block("- [stale](zz.md) — old").encode("utf-8"))


# Matrix row 20: every case 1-17 must be write-free under --check, malformed
# included. (label, builder, expected rc).
_CHECK_CASES = [
    ("prose above block", _setup_prose_above_block, 1),
    ("prose below block", _setup_prose_below_block, 1),
    ("marker-less line-identical", _setup_markerless_line_identical, 1),
    ("marker-less reordered", _setup_markerless_reordered, 1),
    ("START HERE annotation", _setup_start_here_annotation, 1),
    ("adr bullets only", _setup_adr_bullets_only, 1),
    ("curated prose", _setup_curated_prose, 1),
    ("append full overlap", _setup_append_full_overlap, 1),
    ("append partial overlap", _setup_append_partial_overlap, 1),
    ("append no overlap", _setup_append_no_overlap, 1),
    ("missing end marker", _setup_missing_end_marker, 2),
    ("missing begin marker", _setup_missing_begin_marker, 2),
    ("reversed markers", _setup_reversed_markers, 2),
    ("duplicate begin markers", _setup_duplicate_begin_markers, 2),
    ("duplicate end markers", _setup_duplicate_end_markers, 2),
    ("empty folder", _setup_empty_folder, 0),
    ("emptied folder", _setup_emptied_folder, 1),
]


class TestBuildIndex(unittest.TestCase):
    def test_lines_from_frontmatter(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _note(root, "b.md", "beta", "second")
            _note(root, "a.md", "alpha", "first")
            self.assertEqual(
                wiki_index.build_index(root),
                "- [alpha](a.md) — first\n- [beta](b.md) — second\n",
            )


class TestRegenerate(unittest.TestCase):
    def test_check_flags_stale(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _note(root, "a.md", "alpha", "first")
            rc, _ = wiki_index.regenerate(root, check=True)
            self.assertEqual(rc, 1)

    def test_write_then_check_clean(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _note(root, "a.md", "alpha", "first")
            rc, _ = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            index = root / "MEMORY.md"
            # The generated bullet now lives inside the owned block rather than
            # being the whole file, so assert containment plus both markers.
            written = index.read_text(encoding="utf-8", newline="")
            self.assertIn("- [alpha](a.md) — first", written)
            self.assertIn(wiki_index.GENERATED_BEGIN, written)
            self.assertIn(wiki_index.GENERATED_END, written)
            rc2, _ = wiki_index.regenerate(root, check=True)
            self.assertEqual(rc2, 0)
            # Idempotency on bytes — a read_text comparison would normalise away
            # a CRLF regression (#83/#84).
            before = index.read_bytes()
            rc3, _ = wiki_index.regenerate(root)
            self.assertEqual(rc3, 0)
            self.assertEqual(index.read_bytes(), before)


class TestPreservationAroundBlock(unittest.TestCase):
    """Matrix rows 1-2 — content outside the markers survives byte-for-byte."""

    def test_prose_above_block_is_preserved_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_prose_above_block(root)
            rc, _ = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            data = _index(root).read_bytes()
            self.assertTrue(data.startswith("# Orientation\n\nprose\n\n".encode("utf-8")))
            self.assertIn("- [alpha](a.md) — first".encode("utf-8"), data)
            self.assertNotIn(b"zz.md", data)

    def test_prose_below_block_is_preserved_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_prose_below_block(root)
            rc, _ = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            data = _index(root).read_bytes()
            self.assertTrue(data.endswith(b"\n## Hand notes\n\nprose\n"))
            self.assertIn("- [alpha](a.md) — first".encode("utf-8"), data)
            self.assertNotIn(b"zz.md", data)


class TestMarkerlessMigration(unittest.TestCase):
    """Matrix rows 3-6 — the line-identity predicate (D6)."""

    def test_line_identical_file_migrates_without_warning(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_markerless_line_identical(root)
            rc, summary = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            expected = wiki_index.render_block(
                "- [alpha](a.md) — first\n- [beta](b.md) — second"
            ).encode("utf-8")
            self.assertEqual(_index(root).read_bytes(), expected)
            self.assertFalse([line for line in summary if "⚠" in line], summary)

    def test_reordered_generated_lines_migrate_in_generator_order(self):
        # The documented, accepted loss: the predicate is a set test, so a file
        # of nothing but generated lines comes back in generator order.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_markerless_reordered(root)
            rc, summary = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            expected = wiki_index.render_block(
                "- [alpha](a.md) — first\n- [beta](b.md) — second"
            ).encode("utf-8")
            self.assertEqual(_index(root).read_bytes(), expected)
            self.assertFalse([line for line in summary if "⚠" in line], summary)

    def test_start_here_annotation_is_not_replaceable(self):
        # A shape regex passes this line and a target-containment check passes
        # `auth-model.md`, so shape matching would flatten the human's warning.
        # Line identity is what catches it.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_start_here_annotation(root)
            rc, summary = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            data = _index(root).read_bytes()
            self.assertTrue(
                data.startswith(
                    "- [START HERE — read before touching sessions](auth-model.md)"
                    " — ask Markus first\n".encode("utf-8")
                )
            )
            self.assertNotIn("- [auth model](auth-model.md)".encode("utf-8"), data)
            self.assertIn(
                "- [sessions](sessions.md) — session handling".encode("utf-8"), data
            )
            self.assertTrue([line for line in summary if "⚠ appended" in line], summary)

    def test_adr_bullets_without_prose_are_not_replaceable(self):
        # The real `ai-os#138` `repo/soulsgate-payment` shape: no prose at all.
        # It survives only because `adr/0001-x.md` is a target a non-recursive
        # walk never emits, so one line fails membership.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_adr_bullets_only(root)
            rc, summary = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            data = _index(root).read_bytes()
            self.assertTrue(
                data.startswith(
                    "- [alpha](a.md) — first\n"
                    "- [ADR 0001](adr/0001-x.md) — a decision\n".encode("utf-8")
                )
            )
            self.assertIn(wiki_index.ALL_LINKED_BODY.encode("utf-8"), data)
            self.assertTrue([line for line in summary if "⚠ appended" in line], summary)

    def test_curated_prose_appends_and_warns(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_curated_prose(root)
            original = _index(root).read_bytes()
            rc, summary = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            self.assertTrue(_index(root).read_bytes().startswith(original))
            self.assertTrue([line for line in summary if "⚠ appended" in line], summary)


class TestDedupe(unittest.TestCase):
    """Matrix rows 8-11 — D13/D14 de-duplication against preserved text."""

    def test_append_full_overlap_uses_all_linked_placeholder(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_append_full_overlap(root)
            rc, _ = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            text = _index(root).read_text(encoding="utf-8", newline="")
            self.assertIn(wiki_index.ALL_LINKED_BODY, text)
            self.assertEqual(text.count("](a.md)"), 1)
            self.assertEqual(text.count("](b.md)"), 1)

    def test_append_partial_overlap_lists_only_unlinked_notes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_append_partial_overlap(root)
            rc, _ = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            text = _index(root).read_text(encoding="utf-8", newline="")
            body = text.split(wiki_index.GENERATED_BEGIN, 1)[1]
            self.assertNotIn("](a.md)", body)
            self.assertIn("- [beta](b.md) — second", body)
            self.assertIn("- [gamma](c.md) — third", body)
            self.assertEqual(text.count("](a.md)"), 1)

    def test_append_no_overlap_lists_all_notes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_append_no_overlap(root)
            rc, _ = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            body = _index(root).read_text(encoding="utf-8", newline="").split(
                wiki_index.GENERATED_BEGIN, 1
            )[1]
            self.assertIn("- [alpha](a.md) — first", body)
            self.assertIn("- [beta](b.md) — second", body)
            self.assertIn("- [gamma](c.md) — third", body)

    def test_splice_path_dedupes_too(self):
        # D14's regression guard. Run 2 takes the splice path; if de-duplication
        # were wired only into the append path it would put the full note list
        # back and the bytes would differ.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_append_partial_overlap(root)
            rc1, _ = wiki_index.regenerate(root)
            self.assertEqual(rc1, 0)
            after_first = _index(root).read_bytes()
            rc2, _ = wiki_index.regenerate(root)
            self.assertEqual(rc2, 0)
            self.assertEqual(_index(root).read_bytes(), after_first)
            text = after_first.decode("utf-8")
            body = text.split(wiki_index.GENERATED_BEGIN, 1)[1]
            self.assertNotIn("](a.md)", body)
            self.assertEqual(body.count("](b.md)"), 1)
            self.assertEqual(body.count("](c.md)"), 1)


class TestMalformedMarkers(unittest.TestCase):
    """Matrix rows 12-15 — D7 refuses rather than guessing the block's extent."""

    def _assert_refuses(self, setup, *, runs=1):
        # The tempdir must outlive every run, so the loop lives inside it —
        # regenerate() on a vanished directory returns rc 0, not rc 2, and would
        # make a second run outside this block pass for the wrong reason.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            setup(root)
            before = _index(root).read_bytes()
            for run in range(1, runs + 1):
                with self.subTest(run=run):
                    rc, summary = wiki_index.regenerate(root)
                    self.assertEqual(rc, 2)
                    self.assertEqual(_index(root).read_bytes(), before)
                    self.assertTrue(
                        [line for line in summary if "⚠ malformed" in line], summary
                    )

    def test_missing_end_marker_refuses_and_never_duplicates(self):
        # The precedent bug: `compute_readiness.compose()` falls to its append
        # branch here and re-appends its block on every single run.
        self._assert_refuses(_setup_missing_end_marker, runs=2)

    def test_compose_returns_none_on_begin_marker_without_end(self):
        text = f"# Index\n\n{wiki_index.GENERATED_BEGIN}\n\n- [alpha](a.md) — first\n"
        new_text, disposition = wiki_index.compose(
            text, wiki_index.render_block("- [alpha](a.md) — first"), replaceable=False
        )
        self.assertIsNone(new_text)
        self.assertTrue(disposition.startswith("malformed:"), disposition)

    def test_missing_begin_marker_refuses(self):
        self._assert_refuses(_setup_missing_begin_marker)

    def test_reversed_markers_refuse(self):
        self._assert_refuses(_setup_reversed_markers)

    def test_duplicate_begin_markers_refuse(self):
        self._assert_refuses(_setup_duplicate_begin_markers)

    def test_duplicate_end_markers_refuse(self):
        self._assert_refuses(_setup_duplicate_end_markers)


class TestEmptyFolders(unittest.TestCase):
    """Matrix rows 16-17 — D15."""

    def test_empty_folder_creates_no_index_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_empty_folder(root)
            rc, summary = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            self.assertFalse(_index(root).exists())
            self.assertTrue(
                [line for line in summary if "skipped (no notes)" in line], summary
            )

    def test_emptied_folder_keeps_file_and_writes_no_notes_body(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_emptied_folder(root)
            rc, _ = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            self.assertTrue(_index(root).exists())
            text = _index(root).read_text(encoding="utf-8", newline="")
            self.assertIn(wiki_index.NO_NOTES_BODY, text)
            self.assertNotIn("](a.md)", text)


class TestIdempotency(unittest.TestCase):
    """Matrix row 18 — run twice, compare bytes."""

    def _assert_idempotent(self, setup):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            setup(root)
            rc1, _ = wiki_index.regenerate(root)
            self.assertEqual(rc1, 0)
            after_first = _index(root).read_bytes()
            rc2, _ = wiki_index.regenerate(root)
            self.assertEqual(rc2, 0)
            self.assertEqual(_index(root).read_bytes(), after_first)
            rc3, _ = wiki_index.regenerate(root, check=True)
            self.assertEqual(rc3, 0)
            self.assertEqual(_index(root).read_bytes(), after_first)

    def test_idempotent_prose_above_block(self):
        self._assert_idempotent(_setup_prose_above_block)

    def test_idempotent_prose_below_block(self):
        self._assert_idempotent(_setup_prose_below_block)

    def test_idempotent_markerless_line_identical(self):
        self._assert_idempotent(_setup_markerless_line_identical)

    def test_idempotent_curated_prose_append(self):
        self._assert_idempotent(_setup_curated_prose)

    def test_idempotent_append_partial_overlap(self):
        self._assert_idempotent(_setup_append_partial_overlap)


class TestLineEndings(unittest.TestCase):
    """Matrix row 19 — D10. CRLF on disk stays CRLF where it was preserved."""

    def test_crlf_pure_generated_file_migrates(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_crlf_pure_generated(root)
            rc, _ = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            expected = wiki_index.render_block("- [alpha](a.md) — first").encode("utf-8")
            self.assertEqual(_index(root).read_bytes(), expected)
            rc2, _ = wiki_index.regenerate(root, check=True)
            self.assertEqual(rc2, 0)

    def test_crlf_prose_above_block_keeps_its_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _setup_crlf_prose_above_block(root)
            rc, _ = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            data = _index(root).read_bytes()
            self.assertTrue(data.startswith(b"# Orientation\r\n\r\nprose\r\n\r\n"), data)
            self.assertIn("- [alpha](a.md) — first".encode("utf-8"), data)
            # Mixed endings are expected exactly once; run 2 reads the LF block
            # back, renders LF, and compares equal.
            rc2, _ = wiki_index.regenerate(root, check=True)
            self.assertEqual(rc2, 0)
            rc3, _ = wiki_index.regenerate(root)
            self.assertEqual(rc3, 0)
            self.assertEqual(_index(root).read_bytes(), data)


class TestCheckNeverWrites(unittest.TestCase):
    """Matrix row 20 — `--check` writes nothing, in every case including malformed."""

    def test_check_writes_nothing_in_any_case(self):
        for label, setup, expected_rc in _CHECK_CASES:
            with self.subTest(case=label):
                with tempfile.TemporaryDirectory() as d:
                    root = Path(d)
                    setup(root)
                    existed = _index(root).exists()
                    before = _index(root).read_bytes() if existed else None
                    rc, _ = wiki_index.regenerate(root, check=True)
                    self.assertEqual(rc, expected_rc)
                    self.assertEqual(_index(root).exists(), existed)
                    if existed:
                        self.assertEqual(_index(root).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
