"""The `units` payload shape: add, supersede, legacy-import (#180 stage 1).

**Gating test 2 of 2, and it stands on its own fixtures.** Its sibling
`tests/test_promote_learnings_body_shape.py` certifies that the `body` shape
still replaces byte-identically; that proves nothing about the path below, and
treating it as coverage here was the specific trap #180's staged plan exists to
avoid. Every fixture in this file exercises code that does not exist on
`origin/main` at d72376a, so every test here fails there and passes on the
branch that adds it.

What is pinned, and where the requirement comes from:

  * **Rendering** — one marker pair, one `<!-- unit:<hash12> -->` anchor per
    unit, the unit's text, then its own `[Source: ... -- date]` line
    (ADR 0007 Decision 2, D2/D3/D7).
  * **Insertion order, not precedence order** (D4). A `user override` unit
    submitted after an `agent inference` one renders *second*. The point is the
    git diff: precedence-sorted rendering would rewrite the block from its
    first line, and the diff is the review gate.
  * **Supersession removes text** (D1), and for the `people` and `feedback`
    buckets that is a hard erasure requirement rather than a preference --
    tested explicitly, by asserting the retracted text is absent from the whole
    file rather than merely moved or commented out.
  * **The ledger decision.** A superseded unit keeps its `promoted:` line,
    gains a `superseded:` event line, and its hash **stays in the dedup set**,
    so re-submitting retracted text is refused. Recorded as an event rather
    than inferred from a line's absence.
  * **Legacy import** (D6). A managed block with no anchors parses as exactly
    one `legacy` unit, lazily, on its next promotion -- and its hash joins to
    the ledger line the old `body`-path promotion already wrote.
  * **Append-only ledger on this path.** `_prune_target_lines` is `body`-only;
    one line per unit is the correct shape here.

Hermetic throughout, in the house style of `tests/test_promote_learnings.py`.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import promote_learnings as pl  # noqa: E402
from _learning_common import parse_ledger  # noqa: E402

LEDGER_SEED = "# Learning log\n\nSeed intro.\n\n## Entries\n"

TARGET = "feedback/sample-learning.md"

FIRST = "The first learning, promoted on its own."
SECOND = "The second learning, added later."
REPLACEMENT = "The corrected learning that replaces the first."

H_FIRST = pl.content_hash12(FIRST)
H_SECOND = pl.content_hash12(SECOND)
H_REPLACEMENT = pl.content_hash12(REPLACEMENT)


def _seed_repo(repo: Path) -> Path:
    memory = repo / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    ledger = memory / "learning-log.md"
    if not ledger.exists():
        ledger.write_text(LEDGER_SEED, encoding="utf-8")
    return ledger


def _unit(text, *, source="empirical", date="2026-07-12", supersedes=None) -> dict:
    unit = {"text": text, "source": source, "date": date}
    if supersedes is not None:
        unit["supersedes"] = supersedes
    return unit


def _nom(units, **over) -> dict:
    base = {
        "scope": "feedback",
        "target": TARGET,
        "name": "feedback-sample-learning",
        "description": "A one-line description.",
        "type": "feedback",
        "units": units,
        "source": "empirical",
        "date": "2026-07-12",
    }
    base.update(over)
    return base


def _ledger_lines(ledger: Path, target: str = TARGET) -> list[str]:
    return [
        ln
        for ln in ledger.read_text(encoding="utf-8").splitlines()
        if ln.startswith("- ") and target in ln
    ]


class UnitRenderingTest(unittest.TestCase):
    """Anchor, text and per-unit provenance, inside one marker pair."""

    def test_fresh_note_renders_one_anchored_unit(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            rc, summary = pl.promote([_nom([_unit(FIRST)])], repo_dir=repo)
            self.assertEqual(rc, 0, summary)

            note = repo / "memory" / TARGET
            self.assertEqual(
                note.read_text(encoding="utf-8"),
                "---\n"
                "name: feedback-sample-learning\n"
                "description: A one-line description.\n"
                "type: feedback\n"
                "---\n"
                f"{pl.PROMOTED_BEGIN}\n"
                f"<!-- unit:{H_FIRST} -->\n"
                f"{FIRST}\n"
                "[Source: empirical — 2026-07-12]\n"
                f"{pl.PROMOTED_END}\n",
            )
            # One ledger line, keyed by the UNIT's hash -- not the whole
            # nomination's -- so a retrieved passage joins back to it (D8).
            self.assertEqual(
                _ledger_lines(ledger),
                [
                    f"- 2026-07-12 | {TARGET} | {H_FIRST} "
                    f"| promoted: feedback-sample-learning"
                ],
            )

    def test_units_render_in_insertion_order_not_precedence_order(self):
        # D4. `PRIORITY` ranks `user override` highest, so a precedence sort
        # would hoist the second unit to the top of the block. It must not.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            rc, summary = pl.promote(
                [
                    _nom([
                        _unit(FIRST, source="agent inference", date="2026-07-10"),
                        _unit(SECOND, source="user override", date="2026-07-12"),
                    ])
                ],
                repo_dir=repo,
            )
            self.assertEqual(rc, 0, summary)

            text = (repo / "memory" / TARGET).read_text(encoding="utf-8")
            self.assertLess(text.index(FIRST), text.index(SECOND))
            self.assertIn(
                f"<!-- unit:{H_FIRST} -->\n"
                f"{FIRST}\n"
                "[Source: agent inference — 2026-07-10]\n"
                "\n"
                f"<!-- unit:{H_SECOND} -->\n"
                f"{SECOND}\n"
                "[Source: user override — 2026-07-12]\n",
                text,
            )

    def test_a_later_promotion_appends_and_leaves_the_first_unit_in_place(self):
        # The diff-minimality property D4 exists to protect: everything above
        # the new unit is unchanged, so the review diff is the new unit.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            note = repo / "memory" / TARGET

            pl.promote([_nom([_unit(FIRST)])], repo_dir=repo)
            before = note.read_text(encoding="utf-8")

            rc, summary = pl.promote(
                [
                    _nom(
                        [_unit(SECOND, source="user override", date="2026-07-13")],
                        date="2026-07-13",
                    )
                ],
                repo_dir=repo,
            )
            self.assertEqual(rc, 0, summary)
            after = note.read_text(encoding="utf-8")

            head = before.split(f"{pl.PROMOTED_END}\n")[0]
            self.assertTrue(after.startswith(head), after)
            self.assertIn(f"<!-- unit:{H_SECOND} -->", after)

    def test_parse_then_render_is_a_fixed_point(self):
        # Rendering normalises trailing blank lines, so the round trip has to
        # settle in one step or every promotion would rewrite the whole block.
        units = [
            pl.Unit(
                hash12=H_FIRST, text=FIRST, source="empirical", date="2026-07-12"
            ),
            pl.Unit(
                hash12=H_SECOND,
                text=SECOND,
                source="user override",
                date="2026-07-13",
                legacy=True,
            ),
        ]
        block = pl.render_units_block(units)
        reparsed = pl.parse_block_units(pl._BLOCK.inner(block))
        self.assertEqual(reparsed, units)
        self.assertEqual(pl.render_units_block(reparsed), block)

    def test_fenced_unit_anchor_in_prose_is_not_a_unit_boundary(self):
        # The outer pair's #102/#121 failure class, one level down: a block
        # whose prose documents the anchor shape inside a fenced example must
        # not have that example read as a boundary.
        inner = (
            "A single legacy unit whose prose documents the anchor:\n"
            "\n"
            "```\n"
            "<!-- unit:0123456789ab -->\n"
            "```\n"
            "[Source: empirical — 2026-07-01]\n"
        )
        units = pl.parse_block_units(inner)
        self.assertEqual(len(units), 1, units)
        self.assertTrue(units[0].legacy)
        self.assertIn("<!-- unit:0123456789ab -->", units[0].text)


class SupersessionTest(unittest.TestCase):
    """D1: the superseded unit's text leaves the rendered block."""

    def _promote_then_supersede(self, repo, *, scope="feedback", target=TARGET):
        _seed_repo(repo)
        rc, summary = pl.promote(
            [_nom([_unit(FIRST)], scope=scope, target=target)], repo_dir=repo
        )
        self.assertEqual(rc, 0, summary)
        rc, summary = pl.promote(
            [
                _nom(
                    [
                        _unit(
                            REPLACEMENT,
                            date="2026-07-13",
                            supersedes=[H_FIRST],
                        )
                    ],
                    scope=scope,
                    target=target,
                    date="2026-07-13",
                )
            ],
            repo_dir=repo,
        )
        self.assertEqual(rc, 0, summary)
        return rc, summary

    def test_superseded_text_is_omitted_from_the_rendered_block(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            rc, summary = self._promote_then_supersede(repo)
            text = (repo / "memory" / TARGET).read_text(encoding="utf-8")

            self.assertNotIn(FIRST, text)
            self.assertNotIn(H_FIRST, text)
            self.assertIn(REPLACEMENT, text)
            self.assertIn(f"<!-- unit:{H_REPLACEMENT} -->", text)
            self.assertTrue(
                any("-1 superseded" in s for s in summary), summary
            )

    def test_people_bucket_supersession_removes_the_text_from_the_file(self):
        # A hard requirement, not a preference: a `people` note is a dated,
        # attributed sequence of observations about an identifiable individual,
        # and supersession is the only erasure path `memory/CONVENTIONS.md`
        # leaves open. Demoting or commenting the text out would not satisfy
        # it, so this asserts absence from the WHOLE file.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            target = "people/a-person.md"
            self._promote_then_supersede(repo, scope="people", target=target)
            text = (repo / "memory" / target).read_text(encoding="utf-8")

            self.assertNotIn(FIRST, text)
            # Nor any fragment of it, and nor commented out.
            self.assertNotIn("first learning", text.lower())
            self.assertNotIn(f"<!-- unit:{H_FIRST}", text)
            self.assertIn(REPLACEMENT, text)

    def test_feedback_bucket_supersession_removes_the_text_from_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            target = "feedback/about-someone.md"
            self._promote_then_supersede(repo, scope="feedback", target=target)
            text = (repo / "memory" / target).read_text(encoding="utf-8")

            self.assertNotIn(FIRST, text)
            self.assertNotIn("first learning", text.lower())
            self.assertNotIn(f"<!-- unit:{H_FIRST}", text)
            self.assertIn(REPLACEMENT, text)

    def test_supersession_is_recorded_as_a_ledger_event(self):
        # The open decision #180 asked to be made and stated: supersession is
        # an explicit ledger verb, not an inference from a missing line. Both
        # lines survive -- the promotion happened AND the retraction happened.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            self._promote_then_supersede(repo)
            lines = _ledger_lines(ledger)

            self.assertIn(
                f"- 2026-07-12 | {TARGET} | {H_FIRST} "
                f"| promoted: feedback-sample-learning",
                lines,
            )
            self.assertIn(
                f"- 2026-07-13 | {TARGET} | {H_FIRST} "
                f"| superseded: feedback-sample-learning",
                lines,
            )
            self.assertIn(
                f"- 2026-07-13 | {TARGET} | {H_REPLACEMENT} "
                f"| promoted: feedback-sample-learning",
                lines,
            )

    def test_parse_ledger_still_returns_its_documented_shape(self):
        # `parse_ledger`'s contract has to keep working for every current
        # caller: `{hash12: (date, target)}`, one entry per hash, last line
        # wins. The superseded hash stays present -- that IS the dedup
        # decision -- and reports the supersession date and the same target.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            self._promote_then_supersede(repo)

            parsed = parse_ledger(ledger)
            self.assertIn(H_FIRST, parsed)
            self.assertEqual(parsed[H_FIRST], ("2026-07-13", TARGET))
            self.assertEqual(parsed[H_REPLACEMENT], ("2026-07-13", TARGET))

    def test_resubmitting_superseded_text_is_refused_as_already_promoted(self):
        # The consequence of keeping the hash in the dedup set, asserted rather
        # than left as a surprise. It *was* promoted; silently re-adding text a
        # human retracted is the worse failure.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            self._promote_then_supersede(repo)
            note = repo / "memory" / TARGET
            before = note.read_text(encoding="utf-8")

            rc, summary = pl.promote(
                [_nom([_unit(FIRST, date="2026-07-20")], date="2026-07-20")],
                repo_dir=repo,
            )
            self.assertEqual(rc, 0, summary)
            self.assertTrue(any("skip (dedup)" in s for s in summary), summary)
            self.assertEqual(note.read_text(encoding="utf-8"), before)

    def test_the_units_path_never_prunes_the_targets_ledger_lines(self):
        # Append-only here, unlike the `body` path. One line per unit is the
        # correct shape, and pruning the target would delete the per-unit
        # history supersession exists to keep.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            self._promote_then_supersede(repo)
            self.assertEqual(len(_ledger_lines(ledger)), 3)


class SupersessionPrecedenceTest(unittest.TestCase):
    """Supersession is the one operation here that deletes, so it is gated."""

    def _seed_first(self, repo, *, source, date="2026-07-12"):
        _seed_repo(repo)
        rc, summary = pl.promote(
            [_nom([_unit(FIRST, source=source, date=date)], source=source, date=date)],
            repo_dir=repo,
        )
        self.assertEqual(rc, 0, summary)

    def _supersede_with(self, repo, *, source, date="2026-07-13"):
        return pl.promote(
            [
                _nom(
                    [
                        _unit(
                            REPLACEMENT,
                            source=source,
                            date=date,
                            supersedes=[H_FIRST],
                        )
                    ],
                    source=source,
                    date=date,
                )
            ],
            repo_dir=repo,
        )

    def test_agent_inference_cannot_erase_a_user_override(self):
        # `memory/CONVENTIONS.md`'s stated purpose for the precedence rule:
        # "without it, an `agent inference` could silently clobber a `user
        # override`". Both units render; the operator sees a warning.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            self._seed_first(repo, source="user override")
            rc, summary = self._supersede_with(repo, source="agent inference")
            self.assertEqual(rc, 0, summary)

            text = (repo / "memory" / TARGET).read_text(encoding="utf-8")
            self.assertIn(FIRST, text)
            self.assertIn(REPLACEMENT, text)
            self.assertTrue(
                any("refused to supersede" in s and H_FIRST in s for s in summary),
                summary,
            )

    def test_user_override_erases_an_agent_inference(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            self._seed_first(repo, source="agent inference")
            rc, summary = self._supersede_with(repo, source="user override")
            self.assertEqual(rc, 0, summary)

            text = (repo / "memory" / TARGET).read_text(encoding="utf-8")
            self.assertNotIn(FIRST, text)
            self.assertIn(REPLACEMENT, text)

    def test_same_source_refinement_erases_its_own_earlier_unit(self):
        # Mirrors the `body` path's same-source branch: a source correcting its
        # own learning is allowed even at equal priority and the same date.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            self._seed_first(repo, source="empirical", date="2026-07-12")
            rc, summary = self._supersede_with(repo, source="empirical", date="2026-07-12")
            self.assertEqual(rc, 0, summary)
            self.assertNotIn(
                FIRST, (repo / "memory" / TARGET).read_text(encoding="utf-8")
            )

    def test_an_unmatched_supersedes_hash_warns_and_removes_nothing(self):
        # A hash that matches no anchor means the retraction silently did not
        # happen, which in the `people`/`feedback` buckets is an unmet erasure
        # obligation. It must be loud.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            rc, summary = pl.promote(
                [_nom([_unit(FIRST, supersedes=["aaaaaaaaaaaa"])])], repo_dir=repo
            )
            self.assertEqual(rc, 0, summary)
            self.assertTrue(
                any(
                    "aaaaaaaaaaaa" in s and "NOTHING WAS REMOVED" in s
                    for s in summary
                ),
                summary,
            )
            self.assertIn(
                FIRST, (repo / "memory" / TARGET).read_text(encoding="utf-8")
            )


class LegacyImportTest(unittest.TestCase):
    """D6: an un-anchored managed block imports as one `legacy` unit, lazily."""

    LEGACY_BODY = "The merged legacy body.\n\nA second paragraph of it."
    H_LEGACY = pl.content_hash12(LEGACY_BODY)

    def _legacy_note(self) -> str:
        return (
            "---\n"
            "name: feedback-sample-learning\n"
            "description: An older one-line description.\n"
            "type: feedback\n"
            "owner: a-human\n"
            "---\n"
            "# Hand-written heading\n"
            "\n"
            "Prose above the block that must survive.\n"
            "\n"
            f"{pl.PROMOTED_BEGIN}\n"
            f"{self.LEGACY_BODY}\n"
            "[Source: empirical — 2026-07-01]\n"
            f"{pl.PROMOTED_END}\n"
            "\n"
            "## Hand-written tail\n"
            "\n"
            "More prose below the block.\n"
        )

    def test_a_block_with_no_anchors_parses_as_one_legacy_unit(self):
        inner = pl._BLOCK.inner(
            f"{pl.PROMOTED_BEGIN}\n"
            f"{self.LEGACY_BODY}\n"
            "[Source: empirical — 2026-07-01]\n"
            f"{pl.PROMOTED_END}\n"
        )
        units = pl.parse_block_units(inner)
        self.assertEqual(
            units,
            [
                pl.Unit(
                    hash12=self.H_LEGACY,
                    text=self.LEGACY_BODY,
                    source="empirical",
                    date="2026-07-01",
                    legacy=True,
                )
            ],
        )

    def test_the_legacy_units_hash_joins_to_its_existing_ledger_line(self):
        # The old `body`-path promotion hashed exactly this text, so the
        # anchor the import writes resolves to the ledger line that is already
        # there -- no orphan anchor, and no duplicate ledger entry.
        self.assertEqual(self.H_LEGACY, pl.content_hash12(self.LEGACY_BODY))

        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            # Promote the legacy body through the OLD shape first, exactly as
            # the un-migrated harvest command would.
            rc, summary = pl.promote(
                [
                    {
                        "scope": "feedback",
                        "target": TARGET,
                        "name": "feedback-sample-learning",
                        "description": "An older one-line description.",
                        "type": "feedback",
                        "body": self.LEGACY_BODY,
                        "source": "empirical",
                        "date": "2026-07-01",
                    }
                ],
                repo_dir=repo,
            )
            self.assertEqual(rc, 0, summary)
            self.assertEqual(len(_ledger_lines(ledger)), 1)

            # Now a `units` nomination against it: the legacy block imports.
            rc, summary = pl.promote([_nom([_unit(SECOND)])], repo_dir=repo)
            self.assertEqual(rc, 0, summary)

            text = (repo / "memory" / TARGET).read_text(encoding="utf-8")
            self.assertIn(f"<!-- unit:{self.H_LEGACY} legacy -->", text)
            # Two lines: the original promotion, and the new unit. The import
            # itself adds none, because its hash already resolves.
            lines = _ledger_lines(ledger)
            self.assertEqual(len(lines), 2, lines)
            self.assertTrue(any(self.H_LEGACY in ln for ln in lines))
            self.assertTrue(any(H_SECOND in ln for ln in lines))

    def test_import_preserves_the_legacy_text_and_the_hand_written_prose(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            note = repo / "memory" / TARGET
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(self._legacy_note(), encoding="utf-8")

            rc, summary = pl.promote([_nom([_unit(SECOND)])], repo_dir=repo)
            self.assertEqual(rc, 0, summary)

            self.assertEqual(
                note.read_text(encoding="utf-8"),
                "---\n"
                "name: feedback-sample-learning\n"
                "description: A one-line description.\n"
                "type: feedback\n"
                "owner: a-human\n"
                "---\n"
                "# Hand-written heading\n"
                "\n"
                "Prose above the block that must survive.\n"
                "\n"
                f"{pl.PROMOTED_BEGIN}\n"
                f"<!-- unit:{self.H_LEGACY} legacy -->\n"
                f"{self.LEGACY_BODY}\n"
                "[Source: empirical — 2026-07-01]\n"
                "\n"
                f"<!-- unit:{H_SECOND} -->\n"
                f"{SECOND}\n"
                "[Source: empirical — 2026-07-12]\n"
                f"{pl.PROMOTED_END}\n"
                "\n"
                "## Hand-written tail\n"
                "\n"
                "More prose below the block.\n",
            )

    def test_an_imported_legacy_unit_can_then_be_superseded(self):
        # The retraction path #180 put on the must-not-break list, reached
        # through the import: the legacy body's own provenance gates it, so an
        # `empirical` unit can retire an `empirical` legacy body.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            note = repo / "memory" / TARGET
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(self._legacy_note(), encoding="utf-8")

            rc, summary = pl.promote(
                [
                    _nom(
                        [_unit(REPLACEMENT, supersedes=[self.H_LEGACY])],
                    )
                ],
                repo_dir=repo,
            )
            self.assertEqual(rc, 0, summary)
            text = note.read_text(encoding="utf-8")
            self.assertNotIn(self.LEGACY_BODY, text)
            self.assertIn(REPLACEMENT, text)
            # The hand-written prose outside the block is untouched either way.
            self.assertIn("Prose above the block that must survive.", text)
            self.assertIn("More prose below the block.", text)

    def test_a_marker_less_note_migrates_and_gains_an_anchored_block(self):
        # The `migrated` disposition on this path: a legacy note with no
        # managed block at all. Nothing is parsed as a unit (there is no
        # block), and the existing prose is preserved below the new one.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            note = repo / "memory" / TARGET
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(
                "---\nname: x\ndescription: y\ntype: feedback\n---\n"
                "Hand-written, never promotion-owned.\n",
                encoding="utf-8",
            )
            rc, summary = pl.promote([_nom([_unit(FIRST)])], repo_dir=repo)
            self.assertEqual(rc, 0, summary)

            text = note.read_text(encoding="utf-8")
            self.assertIn(f"<!-- unit:{H_FIRST} -->", text)
            self.assertIn("Hand-written, never promotion-owned.", text)
            self.assertLess(
                text.index(pl.PROMOTED_END),
                text.index("Hand-written, never promotion-owned."),
            )


class UnitsValidationTest(unittest.TestCase):
    """Phase 1 refusals. Nothing on disk, rc 1, and the reason named."""

    def _reject(self, nom):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            before = ledger.read_text(encoding="utf-8")
            rc, summary = pl.promote([nom], repo_dir=repo)
            self.assertEqual(rc, 1, summary)
            self.assertEqual(ledger.read_text(encoding="utf-8"), before)
            self.assertFalse((repo / "memory" / TARGET).exists())
            return summary

    def test_empty_units_list_is_rejected(self):
        summary = self._reject(_nom([]))
        self.assertTrue(any("non-empty JSON list" in s for s in summary), summary)

    def test_a_unit_missing_its_text_is_rejected(self):
        summary = self._reject(
            _nom([{"source": "empirical", "date": "2026-07-12"}])
        )
        self.assertTrue(
            any("unit #0" in s and "text" in s for s in summary), summary
        )

    def test_a_unit_missing_its_own_date_is_rejected(self):
        # D7: per-unit provenance is required. Inheriting the nomination's
        # would silently backdate and re-attribute the unit.
        unit = _unit(FIRST)
        del unit["date"]
        summary = self._reject(_nom([unit]))
        self.assertTrue(
            any("unit #0" in s and "date" in s for s in summary), summary
        )

    def test_a_unit_with_an_invalid_source_is_rejected(self):
        summary = self._reject(_nom([_unit(FIRST, source="vibes")]))
        self.assertTrue(
            any("unit #0" in s and "invalid source" in s for s in summary), summary
        )

    def test_a_non_list_supersedes_is_rejected(self):
        summary = self._reject(_nom([_unit(FIRST, supersedes=H_SECOND)]))
        self.assertTrue(
            any("must be a JSON list" in s for s in summary), summary
        )

    def test_a_supersedes_hash_that_cannot_match_is_rejected_not_warned(self):
        summary = self._reject(_nom([_unit(FIRST, supersedes=["NOTAHASH"])]))
        self.assertTrue(
            any("not a 12-hex unit hash" in s for s in summary), summary
        )

    def test_a_unit_that_is_not_an_object_is_rejected(self):
        summary = self._reject(_nom(["just a string"]))
        self.assertTrue(
            any("must be a JSON object" in s for s in summary), summary
        )

    def test_a_malformed_units_nomination_leaves_an_earlier_one_unwritten(self):
        # Phase 1 validates everything before writing anything, so a bad unit
        # in nomination two must not leave nomination one on disk.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            before = ledger.read_text(encoding="utf-8")
            rc, summary = pl.promote(
                [_nom([_unit(FIRST)]), _nom([_unit(SECOND, source="vibes")])],
                repo_dir=repo,
            )
            self.assertEqual(rc, 1, summary)
            self.assertEqual(ledger.read_text(encoding="utf-8"), before)
            self.assertFalse((repo / "memory" / TARGET).exists())


class UnitsRefusalTest(unittest.TestCase):
    """Per-nomination skips: one bad file must not discard the good ones."""

    def test_malformed_block_markers_skip_the_nomination_and_keep_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            note = repo / "memory" / TARGET
            note.parent.mkdir(parents=True, exist_ok=True)
            orphan = (
                "---\nname: x\ndescription: y\ntype: feedback\n---\n"
                f"{pl.PROMOTED_BEGIN}\n"
                "An orphan begin marker with no end.\n"
            )
            note.write_text(orphan, encoding="utf-8")

            rc, summary = pl.promote([_nom([_unit(FIRST)])], repo_dir=repo)
            self.assertEqual(rc, 0, summary)
            self.assertTrue(
                any("skip (malformed markers)" in s for s in summary), summary
            )
            # Byte-identical: the refusal is a refusal to write, not a guess.
            self.assertEqual(note.read_text(encoding="utf-8"), orphan)

    def test_dry_run_writes_no_note_and_no_ledger_line(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            before = ledger.read_text(encoding="utf-8")

            rc, summary = pl.promote(
                [_nom([_unit(FIRST)])], repo_dir=repo, dry_run=True
            )
            self.assertEqual(rc, 0, summary)
            self.assertFalse((repo / "memory" / TARGET).exists())
            self.assertEqual(ledger.read_text(encoding="utf-8"), before)
            self.assertTrue(any("would write" in s for s in summary), summary)

    def test_dry_run_dedups_within_one_manifest(self):
        # Nothing is appended during a preview, so `parse_ledger` cannot see an
        # earlier would-write; the in-run set has to.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            rc, summary = pl.promote(
                [_nom([_unit(FIRST)]), _nom([_unit(FIRST)])],
                repo_dir=repo,
                dry_run=True,
            )
            self.assertEqual(rc, 0, summary)
            self.assertTrue(any("skip (dedup)" in s for s in summary), summary)
            self.assertIn("[dry-run] promoted 1, skipped 1", summary)

    def test_a_unit_already_in_the_block_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            pl.promote([_nom([_unit(FIRST)])], repo_dir=repo)
            rc, summary = pl.promote(
                [_nom([_unit(FIRST), _unit(SECOND)])], repo_dir=repo
            )
            self.assertEqual(rc, 0, summary)
            text = (repo / "memory" / TARGET).read_text(encoding="utf-8")
            self.assertEqual(text.count(f"<!-- unit:{H_FIRST} -->"), 1)
            self.assertEqual(text.count(f"<!-- unit:{H_SECOND} -->"), 1)


if __name__ == "__main__":
    unittest.main()
