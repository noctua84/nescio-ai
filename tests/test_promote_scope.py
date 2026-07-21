import tempfile
import unittest
from pathlib import Path

import promote_learnings as pl


class TestConceptsScope(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "memory").mkdir()
        (root / "memory" / "learning-log.md").write_text("", encoding="utf-8")
        return root

    def test_concepts_bucket_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            nom = {
                "scope": "concepts",
                "target": "concepts/async-state.md",
                "name": "async-state",
                "description": "wrap async mutations",
                "type": "concept",
                "body": "Wrap async store mutations in an action.\n",
                "source": "empirical",
                "date": "2026-07-20",
            }
            rc, summary = pl.promote([nom], repo_dir=root)
            self.assertEqual(rc, 0, summary)
            self.assertTrue((root / "memory" / "concepts" / "async-state.md").exists())


if __name__ == "__main__":
    unittest.main()
