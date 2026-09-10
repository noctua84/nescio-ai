# tests/test_theme_common.py
"""Unit tests for `scripts/_theme_common.py`, the theme classifier.

The classifier—``detect_theme``, ``theme_representatives``, ``desynced_agents``
—is a two-consumer fact extracted from ``apply_theme.py`` so that
``sync_from_upstream.py`` can consult it without importing the renderer. These
tests pin the classifier at its new home and verify it stays a re-export in
``apply_theme.py``, not a fork.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import _theme_common  # noqa: E402
import apply_theme  # noqa: E402


def _make_charter(name_value: str | None) -> str:
    """A minimal agent charter with an optional ``name:`` frontmatter field.

    Args:
        name_value: The value to set for ``name:`` in frontmatter, or None
                    to omit the field entirely (simulating a file with no name).

    Returns:
        The charter text with YAML frontmatter.
    """
    if name_value is None:
        return "# a charter with no frontmatter\n"
    return f"""---
name: {name_value}
description: test agent
---
# {name_value}

test charter
"""


class ThemeRepresentativesTest(unittest.TestCase):
    """Tests for ``theme_representatives`` and ``detect_theme``."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.agents_dir = Path(self._tmp.name) / "agents"
        self.agents_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_zero_representatives_yields_empty_dict(self):
        """An empty agents/ directory has no theme evidence."""
        result = _theme_common.theme_representatives(self.agents_dir)
        self.assertEqual(result, {})

    def test_zero_representatives_detect_returns_none(self):
        """detect_theme returns None when no representatives exist."""
        result = _theme_common.detect_theme(self.agents_dir)
        self.assertIsNone(result)

    def test_one_representative_functional_detected(self):
        """When only planner.md exists, theme is detected as 'functional'."""
        (self.agents_dir / "planner.md").write_text(_make_charter("planner"))
        reps = _theme_common.theme_representatives(self.agents_dir)
        self.assertEqual(reps, {"functional": "planner.md"})
        self.assertEqual(_theme_common.detect_theme(self.agents_dir), "functional")

    def test_one_representative_philosophers_detected(self):
        """When only plato.md exists, theme is detected as 'philosophers'."""
        (self.agents_dir / "plato.md").write_text(_make_charter("plato"))
        reps = _theme_common.theme_representatives(self.agents_dir)
        self.assertEqual(reps, {"philosophers": "plato.md"})
        self.assertEqual(_theme_common.detect_theme(self.agents_dir), "philosophers")

    def test_both_representatives_yields_two_entries(self):
        """When both representatives exist, theme_representatives returns both."""
        (self.agents_dir / "planner.md").write_text(_make_charter("planner"))
        (self.agents_dir / "plato.md").write_text(_make_charter("plato"))
        reps = _theme_common.theme_representatives(self.agents_dir)
        self.assertEqual(reps, {
            "functional": "planner.md",
            "philosophers": "plato.md",
        })

    def test_both_representatives_detect_returns_none(self):
        """When both representatives exist, detect_theme returns None (ambiguous)."""
        (self.agents_dir / "planner.md").write_text(_make_charter("planner"))
        (self.agents_dir / "plato.md").write_text(_make_charter("plato"))
        result = _theme_common.detect_theme(self.agents_dir)
        self.assertIsNone(result)


class DesyncedAgentsTest(unittest.TestCase):
    """Tests for ``desynced_agents``."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.agents_dir = Path(self._tmp.name) / "agents"
        self.agents_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_synced_agent_is_absent(self):
        """An agent whose name: matches its filename is not in the result."""
        (self.agents_dir / "planner.md").write_text(_make_charter("planner"))
        result = _theme_common.desynced_agents(self.agents_dir)
        self.assertEqual(result, [])

    def test_single_desynced_agent_is_present(self):
        """An agent whose name: differs from filename is in the result."""
        (self.agents_dir / "planner.md").write_text(_make_charter("plato"))
        result = _theme_common.desynced_agents(self.agents_dir)
        self.assertEqual(result, [("planner.md", "plato")])

    def test_multiple_desynced_agents_sorted(self):
        """Multiple desynced agents are returned sorted by filename."""
        (self.agents_dir / "alpha.md").write_text(_make_charter("beta"))
        (self.agents_dir / "gamma.md").write_text(_make_charter("delta"))
        (self.agents_dir / "synced.md").write_text(_make_charter("synced"))
        result = _theme_common.desynced_agents(self.agents_dir)
        self.assertEqual(result, [
            ("alpha.md", "beta"),
            ("gamma.md", "delta"),
        ])

    def test_no_frontmatter_is_not_reported(self):
        """A `.md` with no frontmatter block at all is not a charter.

        This is the T14 regression: `agents/README.md`, plain documentation
        with no `---` fences, must not be reported by `desynced_agents` —
        it was never claiming to be an agent, so its presence is not an
        inconsistency. Before the fix, `_frontmatter_name` collapsed "no
        frontmatter" and "frontmatter with no `name:` key" into the same
        `None`, and this file was reported exactly like a broken charter.
        """
        (self.agents_dir / "README.md").write_text(_make_charter(None))
        result = _theme_common.desynced_agents(self.agents_dir)
        self.assertEqual(result, [])

    def test_no_frontmatter_arbitrary_filename_is_not_reported(self):
        """Same as above, for a non-README doc-shaped filename.

        Pins that the exemption is about the *content* (no frontmatter
        fences), not a special case for the literal name `README.md`.
        """
        (self.agents_dir / "notes.md").write_text(_make_charter(None))
        result = _theme_common.desynced_agents(self.agents_dir)
        self.assertEqual(result, [])

    def test_no_name_key_in_frontmatter_is_reported(self):
        """A charter *with* frontmatter but no `name:` key is a broken charter.

        Unlike the no-frontmatter case, a file that opens a `---` block is
        claiming to be a charter — and one that claims it without a `name:`
        genuinely fails to load, so it must still be reported.
        """
        (self.agents_dir / "unnamed.md").write_text("""---
description: test
tools: []
---
# test
""")
        result = _theme_common.desynced_agents(self.agents_dir)
        self.assertEqual(result, [("unnamed.md", None)])

    def test_no_name_key_message_does_not_contain_python_none(self):
        """`desync_reason(None)` must not leak Python's `None` repr.

        `None` here means "the frontmatter block has no `name:` key", not
        a value the charter actually declared — printing `declares
        \\`name: None\\`` would read as if the charter wrote that literally,
        and any `apply_theme.py` command suggested alongside it could not
        fix a missing key anyway.
        """
        message = _theme_common.desync_reason(None)
        self.assertNotIn("None", message)

    # -- audit Serious #2: entries the oracle cannot read are not charters ---

    def test_non_utf8_file_is_skipped_not_raised(self):
        """A `.md` that is not UTF-8 text is not a charter; it must not raise.

        `desynced_agents` runs on every sync since the desync warning moved
        above the theme classification — including the untheme'd path whose
        contract is "today's behaviour exactly". A Latin-1 scratch note in
        `agents/` used to escape as a `UnicodeDecodeError` from a classifier
        that was never going to classify it anyway.
        """
        (self.agents_dir / "planner.md").write_text(_make_charter("planner"))
        (self.agents_dir / "notes.md").write_bytes(b"caf\xe9 notes\n")
        self.assertEqual(_theme_common.desynced_agents(self.agents_dir), [])

    def test_non_utf8_file_does_not_hide_a_real_desync(self):
        """The skip is per entry: a broken charter next to it is still found."""
        (self.agents_dir / "planner.md").write_text(_make_charter("plato"))
        (self.agents_dir / "notes.md").write_bytes(b"caf\xe9 notes\n")
        self.assertEqual(_theme_common.desynced_agents(self.agents_dir),
                         [("planner.md", "plato")])

    def test_directory_named_like_a_charter_is_skipped(self):
        """A directory named `x.md` matches the glob but is not a file.

        Reading it raises `PermissionError` (Windows) or `IsADirectoryError`
        (POSIX) — both `OSError` — and either one crashed the sync.
        """
        (self.agents_dir / "planner.md").write_text(_make_charter("planner"))
        (self.agents_dir / "x.md").mkdir()
        self.assertEqual(_theme_common.desynced_agents(self.agents_dir), [])


class ReExportPinTest(unittest.TestCase):
    """Tests that _theme_common symbols are re-exported from apply_theme."""

    def test_detect_theme_is_reexported(self):
        """apply_theme.detect_theme is the same object as _theme_common.detect_theme."""
        self.assertIs(
            apply_theme.detect_theme,
            _theme_common.detect_theme,
            "detect_theme must be re-exported, not copied"
        )

    def test_theme_representatives_is_reexported(self):
        """apply_theme.theme_representatives is the same object."""
        self.assertIs(
            apply_theme.theme_representatives,
            _theme_common.theme_representatives,
            "theme_representatives must be re-exported, not copied"
        )

    def test_desynced_agents_is_reexported(self):
        """apply_theme.desynced_agents is the same object."""
        self.assertIs(
            apply_theme.desynced_agents,
            _theme_common.desynced_agents,
            "desynced_agents must be re-exported, not copied"
        )

    def test_theme_representatives_constant_is_reexported(self):
        """apply_theme.THEME_REPRESENTATIVES is the same object."""
        self.assertIs(
            apply_theme.THEME_REPRESENTATIVES,
            _theme_common.THEME_REPRESENTATIVES,
            "THEME_REPRESENTATIVES constant must be re-exported, not copied"
        )


class RendererNotInClassifierTest(unittest.TestCase):
    """Tests that _theme_common does not include renderer functions.

    The renderer (``_mappings``, ``_transform``, ``apply_theme``) deliberately
    stayed behind in ``apply_theme.py``. Importing it on an unthemed instance
    would break the guarantee that unthemed instances execute literally today's
    code path without touching the cosmetic module.
    """

    def test_apply_theme_not_in_classifier(self):
        """_theme_common does not define apply_theme function."""
        self.assertFalse(
            hasattr(_theme_common, "apply_theme"),
            "_theme_common must not define apply_theme—the renderer stays in apply_theme.py"
        )

    def test_mappings_not_in_classifier(self):
        """_theme_common does not define _mappings function."""
        self.assertFalse(
            hasattr(_theme_common, "_mappings"),
            "_theme_common must not define _mappings—the renderer stays in apply_theme.py"
        )

    def test_transform_not_in_classifier(self):
        """_theme_common does not define _transform function."""
        self.assertFalse(
            hasattr(_theme_common, "_transform"),
            "_theme_common must not define _transform—the renderer stays in apply_theme.py"
        )


if __name__ == "__main__":
    unittest.main()
