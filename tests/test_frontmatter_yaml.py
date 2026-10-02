# tests/test_frontmatter_yaml.py
"""Strict YAML parsing of agent and skill frontmatter.

Claude Code silently drops agents and skills with unparseable frontmatter.
The hand-rolled line-splitting parser in test_agent_definitions.py cannot
detect YAML syntax errors (e.g., unquoted colons in scalar values).
This test parses frontmatter with a strict YAML parser to catch the bug
class: description: values with unquoted ": " patterns that break yaml.safe_load.

See ai-os#230.
"""

import re
import unittest
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Frontmatter block regex that handles both CRLF and LF line endings
FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


class TestFrontmatterYAML(unittest.TestCase):
    """Strict YAML parsing guard for agent and skill frontmatter."""

    def _load_frontmatter(self, path):
        """Extract and parse frontmatter block, returning dict with validated fields.

        Extracts the YAML frontmatter, parses it with yaml.safe_load, verifies
        structure (dict with non-empty str name and description), and returns the dict.
        """
        rel_path = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")

        # Extract frontmatter block
        match = FRONTMATTER_RE.match(text)
        self.assertTrue(
            match,
            f"{rel_path}: missing YAML frontmatter block",
        )

        frontmatter_text = match.group(1)

        # Parse with strict YAML parser
        try:
            frontmatter = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as e:
            self.fail(
                f"{rel_path}: YAML parsing failed: {e}"
            )

        # Verify structure
        self.assertIsInstance(
            frontmatter,
            dict,
            f"{rel_path}: frontmatter is not a dict",
        )

        # Verify required fields
        self.assertIn(
            "name",
            frontmatter,
            f"{rel_path}: missing 'name' field",
        )
        self.assertIsInstance(
            frontmatter.get("name"),
            str,
            f"{rel_path}: 'name' is not a string",
        )
        self.assertTrue(
            frontmatter.get("name", "").strip(),
            f"{rel_path}: 'name' is empty",
        )

        self.assertIn(
            "description",
            frontmatter,
            f"{rel_path}: missing 'description' field",
        )
        self.assertIsInstance(
            frontmatter.get("description"),
            str,
            f"{rel_path}: 'description' is not a string",
        )
        self.assertTrue(
            frontmatter.get("description", "").strip(),
            f"{rel_path}: 'description' is empty",
        )

        return frontmatter

    def test_agents_frontmatter_parse(self):
        """Parse agent frontmatter with strict YAML parser."""
        agent_files = sorted(ROOT.glob("agents/*.md"))
        self.assertTrue(agent_files, "No agent files found in agents/")

        for filepath in agent_files:
            rel_path = filepath.relative_to(ROOT).as_posix()
            with self.subTest(file=rel_path):
                frontmatter = self._load_frontmatter(filepath)

                # Agent name must match file stem
                self.assertEqual(
                    frontmatter.get("name"),
                    filepath.stem,
                    f"{rel_path}: agent name does not match file stem",
                )

    def test_skills_frontmatter_parse(self):
        """Parse skill frontmatter with strict YAML parser."""
        skill_files = sorted(ROOT.glob("skills/*/SKILL.md"))
        self.assertTrue(
            skill_files,
            "no skills/*/SKILL.md found — nothing asserted",
        )

        for filepath in skill_files:
            rel_path = filepath.relative_to(ROOT).as_posix()
            with self.subTest(file=rel_path):
                self._load_frontmatter(filepath)

    def test_yaml_error_on_unquoted_colon_in_scalar(self):
        """Regression test: unquoted colons in scalars break yaml.safe_load."""
        # This is the bug class from ai-os#230:
        # an unquoted ":" in a scalar value breaks YAML parsing.
        problematic_yaml = "name: x\ndescription: Tier — design judgment: architectural\n"

        with self.assertRaises(yaml.YAMLError):
            yaml.safe_load(problematic_yaml)


if __name__ == "__main__":
    unittest.main()
