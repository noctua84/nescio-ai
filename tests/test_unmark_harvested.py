"""Reverting a bad global harvest stamp (`scripts/unmark_harvested.py`).

The fixture mirrors `tests/test_mark_harvested.py`: a temp `CLAUDE_CONFIG_DIR`
holds a synthetic learning-trail dir, so nothing here can reach the real
`~/.claude/learning-trail`.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
sys.path.insert(0, str(ROOT / "scripts"))
import record_stop as rs  # noqa: E402
import harvest_nudge  # noqa: E402
import unmark_harvested  # noqa: E402

# The bad stamp, and an equal instant written in a different offset.
STAMP = "2026-08-20T11:30:14.126690+00:00"
STAMP_OTHER_OFFSET = "2026-08-20T13:30:14.126690+02:00"
OTHER_STAMP = "2026-08-19T09:00:00+00:00"

BEFORE_STAMP = "2026-08-19T10:00:00+00:00"
AFTER_STAMP = "2026-08-21T10:00:00+00:00"


class UnmarkHarvestedTest(unittest.TestCase):
    # ---- fixture ---------------------------------------------------------

    def _with_config(self, d):
        saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = d
        return saved

    def _restore_config(self, saved):
        if saved is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = saved

    def _seed_trail(self, name, *, git_root=None, timestamps=()):
        """Create `<name>.jsonl` with one record per entry in ``timestamps``.

        Every record names ``git_root`` so `_trail_scope` can attribute the trail.
        A trail with no timestamps is written empty.
        """
        path = rs.trail_dir() / f"{name}.jsonl"
        lines = []
        for ts in timestamps:
            lines.append(
                json.dumps({"ts": ts, "git_root": git_root, "repo_root": git_root})
            )
        path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
        return path

    def _stamp(self, trail, value):
        """Write a raw watermark value beside ``trail``; return the watermark path."""
        wm = rs.watermark_path(trail)
        wm.write_text(value, encoding="utf-8")
        return wm

    def _run(self, argv):
        """Run main() capturing both streams; return (rc, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = unmark_harvested.main(argv)
        return rc, out.getvalue(), err.getvalue()

    @contextlib.contextmanager
    def _world(self):
        """cfg + four trails: the kept repo, its worktree, a victim, a stranger.

        Yields ``(paths, trails, watermarks)`` where ``paths`` names the repo
        roots on disk, ``trails`` maps a label to its ``*.jsonl`` and
        ``watermarks`` to its ``*.watermark``.
        """
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as d:
            saved = self._with_config(cfg)
            try:
                # Resolved, because that is what the real world records: a
                # `git_root` comes out of git already canonical, and a
                # `--keep-repo` is resolved before it is compared. An
                # unresolved temp path (Windows can hand out an 8.3 short form)
                # would make the fixture disagree with both.
                base = Path(d).resolve()
                kept = base / "holo-mind"
                kept_wt = kept / ".claude" / "worktrees" / "feature"
                victim = base / "soulsgate-ui"
                stranger = base / "elsewhere"
                for p in (kept, kept_wt, victim, stranger):
                    p.mkdir(parents=True)

                trails = {
                    "kept": self._seed_trail(
                        rs.repo_key(kept.as_posix()),
                        git_root=kept.as_posix(),
                        timestamps=[BEFORE_STAMP] * 3,
                    ),
                    "kept_wt": self._seed_trail(
                        "kept-worktree",
                        git_root=kept_wt.as_posix(),
                        timestamps=[BEFORE_STAMP] * 2,
                    ),
                    "victim": self._seed_trail(
                        rs.repo_key(victim.as_posix()),
                        git_root=victim.as_posix(),
                        timestamps=[BEFORE_STAMP] * 25,
                    ),
                    "stranger": self._seed_trail(
                        rs.repo_key(stranger.as_posix()),
                        git_root=stranger.as_posix(),
                        timestamps=[BEFORE_STAMP] * 4,
                    ),
                }
                watermarks = {
                    "kept": self._stamp(trails["kept"], STAMP),
                    "kept_wt": self._stamp(trails["kept_wt"], STAMP),
                    "victim": self._stamp(trails["victim"], STAMP),
                    "stranger": self._stamp(trails["stranger"], OTHER_STAMP),
                }
                paths = {"kept": kept, "victim": victim, "stranger": stranger}
                yield paths, trails, watermarks
            finally:
                self._restore_config(saved)

    # ---- dry run is the default -----------------------------------------

    def test_dry_run_is_the_default_and_deletes_nothing(self):
        with self._world() as (_, _, watermarks):
            rc, out, _ = self._run(["--stamp", STAMP])
            self.assertEqual(rc, 0)
            for label, wm in watermarks.items():
                self.assertTrue(wm.is_file(), f"dry run deleted {label}")
            self.assertIn("DRY RUN", out)
            self.assertIn("nothing has been deleted", out)

    def test_dry_run_prints_the_exact_apply_command(self):
        with self._world() as (paths, _, _):
            _, out, _ = self._run(
                ["--stamp", STAMP, "--keep-repo", str(paths["kept"])]
            )
            expected = (
                f"python scripts/unmark_harvested.py --stamp {STAMP} "
                f"--keep-repo {paths['kept'].as_posix()} --apply"
            )
            self.assertIn(expected, out)

    def test_dry_run_reports_returning_records_and_nudge_revival(self):
        with self._world() as (paths, _, _):
            _, out, _ = self._run(
                ["--stamp", STAMP, "--keep-repo", str(paths["kept"])]
            )
            # The victim trail's 25 records all sit at/below the stamp.
            self.assertIn("25 record(s) return to un-harvested", out)
            self.assertIn("(un-harvested now 0 -> 25)", out)
            self.assertIn("nudge REVIVED", out)
            self.assertIn(str(harvest_nudge.NUDGE_THRESHOLD), out)
            # Grouped under the owning repo.
            self.assertIn(paths["victim"].as_posix(), out)

    def test_dry_run_counts_exempt_watermarks_separately(self):
        with self._world() as (paths, _, _):
            _, out, _ = self._run(
                ["--stamp", STAMP, "--keep-repo", str(paths["kept"])]
            )
            self.assertIn("1 would be DELETED, 2 exempt via --keep-repo", out)

    # ---- --apply ---------------------------------------------------------

    def test_apply_deletes_matching_and_leaves_others_intact(self):
        with self._world() as (_, trails, watermarks):
            rc, out, _ = self._run(["--stamp", STAMP, "--apply"])
            self.assertEqual(rc, 0)
            self.assertFalse(watermarks["kept"].exists())
            self.assertFalse(watermarks["kept_wt"].exists())
            self.assertFalse(watermarks["victim"].exists())
            # Different stamp: never a candidate.
            self.assertTrue(watermarks["stranger"].is_file())
            self.assertEqual(
                rs.read_watermark(watermarks["stranger"]),
                datetime.fromisoformat(OTHER_STAMP),
            )
            self.assertIn("APPLIED", out)
            self.assertIn("3 watermark(s) deleted", out)
            for wm in (watermarks["kept"], watermarks["victim"]):
                self.assertIn(wm.name, out)

    def test_apply_never_touches_jsonl_files(self):
        with self._world() as (_, trails, _):
            before = {
                label: path.read_text(encoding="utf-8")
                for label, path in trails.items()
            }
            rc, _, _ = self._run(["--stamp", STAMP, "--apply"])
            self.assertEqual(rc, 0)
            for label, path in trails.items():
                self.assertTrue(path.is_file(), f"{label}.jsonl was deleted")
                self.assertEqual(path.read_text(encoding="utf-8"), before[label])

    def test_apply_returns_zero(self):
        with self._world():
            rc, _, _ = self._run(["--stamp", STAMP, "--apply"])
            self.assertEqual(rc, 0)

    # ---- --keep-repo -----------------------------------------------------

    def test_keep_repo_exempts_the_repo_and_its_worktree_trails(self):
        with self._world() as (paths, _, watermarks):
            rc, out, _ = self._run(
                ["--stamp", STAMP, "--keep-repo", str(paths["kept"]), "--apply"]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(watermarks["kept"].is_file())
            self.assertTrue(
                watermarks["kept_wt"].is_file(),
                "a worktree trail of the kept repo was deleted",
            )
            self.assertFalse(watermarks["victim"].exists())
            self.assertIn("1 watermark(s) deleted", out)
            self.assertIn("2 exempt via --keep-repo", out)

    def test_keep_repo_given_as_a_relative_path_still_exempts(self):
        # `belongs_to_repo` compares posix strings for equality, so an
        # un-normalised --keep-repo matches nothing. Standing in the repo you
        # mean to protect and typing `.` (or `../<repo>`) is the most natural
        # thing there is, and it used to put that repo back in the delete set.
        with self._world() as (paths, _, watermarks):
            cwd = os.getcwd()
            os.chdir(paths["kept"])
            try:
                rc, out, err = self._run(["--stamp", STAMP, "--keep-repo", ".", "--apply"])
            finally:
                os.chdir(cwd)
            self.assertEqual(rc, 0, err)
            self.assertTrue(watermarks["kept"].is_file(), "--keep-repo . did not exempt")
            self.assertTrue(watermarks["kept_wt"].is_file())
            self.assertFalse(watermarks["victim"].exists())
            self.assertIn("2 exempt via --keep-repo", out)

    def test_keep_repo_given_as_a_parent_relative_path_still_exempts(self):
        with self._world() as (paths, _, watermarks):
            cwd = os.getcwd()
            os.chdir(paths["victim"])  # a sibling of the kept repo
            try:
                rc, out, err = self._run(
                    ["--stamp", STAMP, "--keep-repo", f"../{paths['kept'].name}", "--apply"]
                )
            finally:
                os.chdir(cwd)
            self.assertEqual(rc, 0, err)
            self.assertTrue(watermarks["kept"].is_file())
            self.assertTrue(watermarks["kept_wt"].is_file())
            self.assertIn("2 exempt via --keep-repo", out)

    def test_keep_repo_with_a_trailing_slash_still_exempts(self):
        with self._world() as (paths, _, watermarks):
            rc, out, err = self._run(
                ["--stamp", STAMP, "--keep-repo", paths["kept"].as_posix() + "/", "--apply"]
            )
            self.assertEqual(rc, 0, err)
            self.assertTrue(watermarks["kept"].is_file())
            self.assertIn("2 exempt via --keep-repo", out)

    def test_keep_repo_with_native_separators_still_exempts(self):
        with self._world() as (paths, _, watermarks):
            rc, out, err = self._run(
                ["--stamp", STAMP, "--keep-repo", str(paths["kept"]), "--apply"]
            )
            self.assertEqual(rc, 0, err)
            self.assertTrue(watermarks["kept"].is_file())
            self.assertIn("2 exempt via --keep-repo", out)

    # ---- an unmatched --keep-repo is refused, never ignored ---------------

    def test_keep_repo_matching_no_trail_refuses_apply_and_deletes_nothing(self):
        with self._world() as (paths, _, watermarks):
            bogus = paths["kept"].parent / "not-a-repo-here"
            rc, out, err = self._run(
                ["--stamp", STAMP, "--keep-repo", str(bogus), "--apply"]
            )
            self.assertEqual(rc, 1)
            for label, wm in watermarks.items():
                self.assertTrue(wm.is_file(), f"a refused run deleted {label}")
            self.assertIn("REFUSED", err)
            self.assertIn("nothing has been deleted", err)
            # Names both what was typed and what it resolved to.
            self.assertIn(str(bogus), err)
            self.assertIn(bogus.resolve().as_posix(), err)
            self.assertNotIn("APPLIED", out)

    def test_keep_repo_matching_no_trail_warns_in_the_dry_run(self):
        with self._world() as (paths, _, watermarks):
            bogus = paths["kept"].parent / "not-a-repo-here"
            rc, out, _ = self._run(["--stamp", STAMP, "--keep-repo", str(bogus)])
            self.assertEqual(rc, 0)
            self.assertIn("WARNING", out)
            self.assertIn("--keep-repo matched no trail", out)
            self.assertIn("--apply will REFUSE", out)
            self.assertIn(bogus.resolve().as_posix(), out)
            for wm in watermarks.values():
                self.assertTrue(wm.is_file())

    def test_a_kept_repo_holding_only_another_stamp_is_not_an_error(self):
        # It exempts nothing — correctly — but the tool can see it, so refusing
        # would be a false alarm.
        with self._world() as (paths, _, watermarks):
            rc, out, err = self._run(
                ["--stamp", STAMP, "--keep-repo", str(paths["stranger"]), "--apply"]
            )
            self.assertEqual(rc, 0, err)
            self.assertNotIn("REFUSED", err)
            self.assertIn("APPLIED", out)
            self.assertTrue(watermarks["stranger"].is_file())

    def test_apply_command_carries_the_resolved_keep_repo(self):
        # Following the printed command must reproduce the dry run exactly —
        # re-emitting the typed relative path would delete what it protected.
        with self._world() as (paths, _, _):
            cwd = os.getcwd()
            os.chdir(paths["kept"])
            try:
                _, out, _ = self._run(["--stamp", STAMP, "--keep-repo", "."])
            finally:
                os.chdir(cwd)
            expected = (
                f"python scripts/unmark_harvested.py --stamp {STAMP} "
                f"--keep-repo {paths['kept'].resolve().as_posix()} --apply"
            )
            self.assertIn(expected, out)
            self.assertNotIn("--keep-repo . --apply", out)

    def test_unmatched_keep_roots_ignores_stamp_and_reports_input_order(self):
        with self._world() as (paths, _, _):
            missing_a = paths["kept"].parent / "ghost-a"
            missing_b = paths["kept"].parent / "ghost-b"
            self.assertEqual(
                unmark_harvested.unmatched_keep_roots(
                    rs.trail_dir(),
                    [missing_a, paths["kept"].resolve(), missing_b],
                ),
                [missing_a, missing_b],
            )

    def test_resolve_keep_root_absolutises_without_requiring_existence(self):
        resolved = unmark_harvested.resolve_keep_root("./no/such/repo")
        self.assertTrue(resolved.is_absolute())
        self.assertFalse(resolved.exists())

    def test_keep_repo_is_repeatable(self):
        with self._world() as (paths, _, watermarks):
            rc, _, _ = self._run(
                [
                    "--stamp", STAMP,
                    "--keep-repo", str(paths["kept"]),
                    "--keep-repo", str(paths["victim"]),
                    "--apply",
                ]
            )
            self.assertEqual(rc, 0)
            for label in ("kept", "kept_wt", "victim", "stranger"):
                self.assertTrue(watermarks[label].is_file(), label)

    # ---- stamp matching --------------------------------------------------

    def test_equal_instant_in_another_offset_still_matches(self):
        with self._world() as (_, _, watermarks):
            rc, _, _ = self._run(["--stamp", STAMP_OTHER_OFFSET, "--apply"])
            self.assertEqual(rc, 0)
            self.assertFalse(watermarks["victim"].exists())
            self.assertTrue(watermarks["stranger"].is_file())

    def test_watermark_written_in_another_offset_still_matches(self):
        # The reverse direction: the stored value is spelled differently.
        with self._world() as (_, trails, watermarks):
            self._stamp(trails["stranger"], STAMP_OTHER_OFFSET)
            rc, _, _ = self._run(["--stamp", STAMP, "--apply"])
            self.assertEqual(rc, 0)
            self.assertFalse(watermarks["stranger"].exists())

    def test_different_timestamp_is_never_a_candidate(self):
        with self._world() as (_, _, watermarks):
            rc, out, _ = self._run(["--stamp", STAMP])
            self.assertEqual(rc, 0)
            self.assertIn("1 watermark(s) hold a different stamp", out)
            self.assertTrue(watermarks["stranger"].is_file())

    def test_naive_stamp_is_read_as_utc(self):
        with self._world() as (_, _, watermarks):
            rc, _, _ = self._run(["--stamp", "2026-08-20T11:30:14.126690", "--apply"])
            self.assertEqual(rc, 0)
            self.assertFalse(watermarks["victim"].exists())

    # ---- degraded inputs -------------------------------------------------

    def test_unparseable_watermark_is_skipped_and_reported(self):
        with self._world() as (_, trails, watermarks):
            self._stamp(trails["stranger"], "whenever")
            rc, out, _ = self._run(["--stamp", STAMP])
            self.assertEqual(rc, 0)
            self.assertIn("does not parse as ISO8601", out)
            self.assertIn("never a candidate", out)
            self.assertIn(watermarks["stranger"].name, out)
            self.assertTrue(watermarks["stranger"].is_file())

    def test_unparseable_watermark_is_not_deleted_by_apply(self):
        with self._world() as (_, trails, watermarks):
            self._stamp(trails["stranger"], "whenever")
            rc, _, _ = self._run(["--stamp", STAMP, "--apply"])
            self.assertEqual(rc, 0)
            self.assertTrue(watermarks["stranger"].is_file())
            self.assertEqual(
                watermarks["stranger"].read_text(encoding="utf-8"), "whenever"
            )

    def test_trail_with_no_watermark_is_a_no_op(self):
        with self._world() as (_, trails, _):
            lonely = self._seed_trail(
                "lonely", git_root="/tmp/lonely", timestamps=[BEFORE_STAMP]
            )
            rc, out, _ = self._run(["--stamp", STAMP])
            self.assertEqual(rc, 0)
            self.assertIn("1 trail(s) have no watermark at all", out)
            rc, _, _ = self._run(["--stamp", STAMP, "--apply"])
            self.assertEqual(rc, 0)
            self.assertTrue(lonely.is_file())
            self.assertFalse(rs.watermark_path(lonely).exists())

    def test_no_matching_watermark_reports_and_returns_zero(self):
        with self._world() as (_, _, watermarks):
            rc, out, _ = self._run(["--stamp", "2020-01-01T00:00:00+00:00"])
            self.assertEqual(rc, 0)
            self.assertIn("nothing to revert", out)
            for wm in watermarks.values():
                self.assertTrue(wm.is_file())

    def test_empty_trail_dir_returns_zero(self):
        with tempfile.TemporaryDirectory() as cfg:
            saved = self._with_config(cfg)
            try:
                rs.trail_dir()  # create it, empty
                rc, out, _ = self._run(["--stamp", STAMP])
                self.assertEqual(rc, 0)
                self.assertIn("nothing to revert", out)
            finally:
                self._restore_config(saved)

    # ---- record counting -------------------------------------------------

    def test_straddling_trail_counts_only_records_at_or_below_the_stamp(self):
        with self._world() as (paths, trails, _):
            # 6 old (return to un-harvested) + 4 new (already un-harvested).
            self._seed_trail(
                rs.repo_key(paths["victim"].as_posix()),
                git_root=paths["victim"].as_posix(),
                timestamps=[BEFORE_STAMP] * 6 + [AFTER_STAMP] * 4,
            )
            _, out, _ = self._run(["--stamp", STAMP])
            self.assertIn("6 record(s) return to un-harvested", out)
            self.assertIn("(un-harvested now 4 -> 10)", out)

    def test_record_exactly_at_the_stamp_returns_to_unharvested(self):
        # `_is_unharvested` is strictly-newer-than, so ts == watermark is harvested.
        with self._world() as (paths, _, _):
            self._seed_trail(
                rs.repo_key(paths["victim"].as_posix()),
                git_root=paths["victim"].as_posix(),
                timestamps=[STAMP],
            )
            _, out, _ = self._run(["--stamp", STAMP])
            self.assertIn("1 record(s) return to un-harvested", out)

    def test_unparseable_records_are_reported_not_counted(self):
        with self._world() as (paths, trails, _):
            trails["victim"].write_text(
                json.dumps({"ts": BEFORE_STAMP, "repo_root": paths["victim"].as_posix()})
                + "\n{ not json\n"
                + json.dumps({"ts": "whenever", "repo_root": paths["victim"].as_posix()})
                + "\n",
                encoding="utf-8",
            )
            _, out, _ = self._run(["--stamp", STAMP])
            self.assertIn("1 record(s) return to un-harvested", out)
            self.assertIn("2 unparseable record(s) ignored", out)

    def test_nudge_not_claimed_revived_below_the_threshold(self):
        with self._world() as (paths, _, _):
            self._seed_trail(
                rs.repo_key(paths["victim"].as_posix()),
                git_root=paths["victim"].as_posix(),
                timestamps=[BEFORE_STAMP] * 3,
            )
            _, out, _ = self._run(["--stamp", STAMP])
            self.assertNotIn("nudge REVIVED", out)
            self.assertIn("below the nudge threshold", out)
            self.assertIn("0 nudge(s) revived", out)

    # ---- argparse surface ------------------------------------------------

    def test_missing_stamp_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as ctx:
                unmark_harvested.main([])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--stamp", err.getvalue())

    def test_malformed_stamp_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as ctx:
                unmark_harvested.main(["--stamp", "not-a-timestamp"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--stamp", err.getvalue())

    # ---- library surface -------------------------------------------------

    def test_parse_stamp_defaults_naive_to_utc(self):
        self.assertEqual(
            unmark_harvested.parse_stamp("2026-08-20T11:30:14.126690"),
            datetime(2026, 8, 20, 11, 30, 14, 126690, tzinfo=timezone.utc),
        )

    def test_parse_stamp_rejects_garbage(self):
        with self.assertRaises(Exception):
            unmark_harvested.parse_stamp("nope")

    def test_delete_watermarks_tolerates_a_file_that_vanished(self):
        with self._world() as (_, _, watermarks):
            findings = unmark_harvested.scan(
                rs.trail_dir(), unmark_harvested.parse_stamp(STAMP), []
            )
            candidates = [
                f for f in findings if f.status == unmark_harvested.CANDIDATE
            ]
            self.assertEqual(len(candidates), 3)
            # Race: one candidate disappears between scan and delete.
            candidates[0].watermark.unlink()
            deleted, raced, failed = unmark_harvested.delete_watermarks(findings)
            self.assertEqual(len(deleted), 2)
            self.assertEqual(len(raced), 1)
            self.assertEqual(failed, [])

    def test_apply_reports_a_race_as_not_an_error(self):
        # The window is between scan and unlink, so the race is injected there:
        # a watermark that was already absent when the scan ran is classified
        # `no-watermark` instead and never reaches the delete loop.
        real_scan = unmark_harvested.scan

        def scan_then_race(trail_dir, stamp, keep_roots):
            findings = real_scan(trail_dir, stamp, keep_roots)
            for finding in findings:
                if finding.status == unmark_harvested.CANDIDATE:
                    finding.watermark.unlink()
                    break
            return findings

        with self._world() as (_, _, watermarks):
            with mock.patch.object(unmark_harvested, "scan", scan_then_race):
                rc, out, _ = self._run(["--stamp", STAMP, "--apply"])
            self.assertEqual(rc, 0)
            self.assertIn("already gone", out)
            self.assertIn("not an error", out)
            self.assertIn("1 already gone", out)
            self.assertIn("2 watermark(s) deleted", out)
            self.assertIn("0 failed", out)

    def test_docstring_states_the_indefinite_retention_cost(self):
        doc = unmark_harvested.__doc__ or ""
        self.assertIn("indefinitely", doc)
        self.assertIn("14", doc)
        self.assertIn("500", doc)

    def test_scan_on_a_missing_trail_dir_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "nope"
            self.assertEqual(
                unmark_harvested.scan(
                    missing, unmark_harvested.parse_stamp(STAMP), []
                ),
                [],
            )

    def test_trail_with_no_records_is_still_a_candidate(self):
        # An empty trail has no repo to attribute, but its watermark still holds
        # the bad stamp and still suppresses nothing — remove it anyway.
        with tempfile.TemporaryDirectory() as cfg:
            saved = self._with_config(cfg)
            try:
                trail = self._seed_trail("empty", timestamps=[])
                wm = self._stamp(trail, STAMP)
                rc, out, _ = self._run(["--stamp", STAMP])
                self.assertEqual(rc, 0)
                self.assertIn(unmark_harvested.UNATTRIBUTED, out)
                rc, _, _ = self._run(["--stamp", STAMP, "--apply"])
                self.assertEqual(rc, 0)
                self.assertFalse(wm.exists())
                self.assertTrue(trail.is_file())
            finally:
                self._restore_config(saved)

    def test_recent_records_are_unaffected_by_the_revert_math(self):
        # Sanity check on the sign of the comparison: a record newer than the
        # stamp is already un-harvested and must not be double-counted.
        with self._world() as (paths, _, _):
            future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
            self._seed_trail(
                rs.repo_key(paths["victim"].as_posix()),
                git_root=paths["victim"].as_posix(),
                timestamps=[future],
            )
            _, out, _ = self._run(["--stamp", STAMP])
            self.assertIn("0 record(s) return to un-harvested", out)
            self.assertIn("(un-harvested now 1 -> 1)", out)


if __name__ == "__main__":
    unittest.main()
