import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
sys.path.insert(0, str(ROOT / "scripts"))
import record_stop as rs  # noqa: E402
import _trail_scope as scope  # noqa: E402
import begin_harvest  # noqa: E402

EARLY = "2026-07-10T06:00:00+00:00"
MID = "2026-07-11T09:30:00+00:00"
LATE = "2026-07-12T08:00:00+00:00"
# Far enough ahead that it is in the future whenever this suite runs. Stands in
# for one turn written while the machine's clock was running fast.
FUTURE = "2126-01-01T00:00:00+00:00"


class BeginHarvestTest(unittest.TestCase):
    def _with_config(self, d):
        saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = d
        return saved

    def _restore_config(self, saved):
        if saved is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = saved

    def _seed_trail(self, name, lines):
        """Create ``<name>.jsonl`` in the trail dir from raw ``lines``."""
        p = rs.trail_dir() / f"{name}.jsonl"
        p.write_text("".join(ln + "\n" for ln in lines), encoding="utf-8")
        return p

    def _rec(self, ts, repo_root):
        return json.dumps({"ts": ts, "git_root": repo_root, "repo_root": repo_root})

    def _run(self, argv):
        """Run main() capturing stdout; return (rc, stdout)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = begin_harvest.main(argv)
        return rc, out.getvalue()

    @contextlib.contextmanager
    def _world(self):
        """cfg + a subject repo and an unrelated one, each with its own trail.

        Yields ``(base, repo, other, trails)``. ``current_repo_root`` is pinned to
        the subject repo so the default scope resolves without touching git.
        """
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as d:
            saved = self._with_config(cfg)
            try:
                base = Path(d)
                repo = base / "proj"
                other = base / "elsewhere"
                repo.mkdir()
                other.mkdir()
                trails = {
                    "own": self._seed_trail(
                        rs.repo_key(repo.as_posix()),
                        [self._rec(MID, repo.as_posix())],
                    ),
                    "other": self._seed_trail(
                        rs.repo_key(other.as_posix()),
                        [self._rec(LATE, other.as_posix())],
                    ),
                }
                with mock.patch.object(
                    scope, "current_repo_root", return_value=repo
                ):
                    yield base, repo, other, trails
            finally:
                self._restore_config(saved)

    def _read_json(self, out_dir):
        return json.loads((Path(out_dir) / "read.json").read_text(encoding="utf-8"))

    # ---- the file itself -------------------------------------------------

    def test_writes_read_json_at_out_dir_and_round_trips(self):
        with self._world() as (base, repo, other, trails):
            out = base / "staging"
            rc, stdout = self._run(["--out", str(out)])
            self.assertEqual(rc, 0)
            path = out / "read.json"
            self.assertTrue(path.is_file())
            data = self._read_json(out)
            self.assertEqual(data["version"], 1)
            self.assertIn(str(path.resolve()), stdout)

    def test_default_out_dir_is_a_timestamped_staging_dir(self):
        with self._world() as (base, repo, other, trails):
            fake_repo_dir = base / "checkout"
            with mock.patch.object(begin_harvest, "REPO_DIR", fake_repo_dir):
                rc, _ = self._run([])
            self.assertEqual(rc, 0)
            staged = sorted((fake_repo_dir / "eval" / "learnings").iterdir())
            self.assertEqual(len(staged), 1)
            # `%Y%m%dT%H%M%S` — sortable and colon-free for Windows.
            self.assertRegex(staged[0].name, r"^\d{8}T\d{6}$")
            self.assertTrue((staged[0] / "read.json").is_file())

    def test_cli_path_reads_sys_argv(self):
        # `main(None)` is the `__main__` path. Regression: parsing `[]` there
        # instead of deferring to argparse silently ignored every flag the
        # operator typed — including `--repo`, whose whole purpose is to be an
        # explicit, recorded widening of scope.
        with self._world() as (base, repo, other, trails):
            out = base / "staging"
            argv = ["begin_harvest.py", "--out", str(out), "--repo", str(other)]
            with mock.patch.object(sys, "argv", argv):
                rc, _ = self._run(None)
            self.assertEqual(rc, 0)
            data = self._read_json(out)
            self.assertEqual(
                sorted(data["repos"]),
                sorted([repo.as_posix(), other.as_posix()]),
            )

    def test_read_at_is_iso_and_timezone_aware(self):
        with self._world() as (base, repo, other, trails):
            out = base / "staging"
            rc, stdout = self._run(["--out", str(out)])
            self.assertEqual(rc, 0)
            data = self._read_json(out)
            parsed = datetime.fromisoformat(data["read_at"])
            self.assertIsNotNone(parsed.tzinfo)
            # The read-time is the first thing on stdout, for the operator to copy.
            self.assertEqual(stdout.splitlines()[0], data["read_at"])

    # ---- scope: the regression this script exists for --------------------

    def test_unrelated_repos_trail_is_absent(self):
        with self._world() as (base, repo, other, trails):
            out = base / "staging"
            self._run(["--out", str(out)])
            data = self._read_json(out)
            names = [t["trail"] for t in data["trails"]]
            self.assertIn(trails["own"].name, names)
            self.assertNotIn(trails["other"].name, names)
            self.assertEqual(data["repos"], [repo.as_posix()])

    def test_repo_flag_adds_a_second_repos_trails(self):
        with self._world() as (base, repo, other, trails):
            out = base / "staging"
            rc, _ = self._run(["--out", str(out), "--repo", str(other)])
            self.assertEqual(rc, 0)
            data = self._read_json(out)
            names = {t["trail"] for t in data["trails"]}
            self.assertEqual(names, {trails["own"].name, trails["other"].name})
            self.assertEqual(
                sorted(data["repos"]),
                sorted([repo.as_posix(), other.as_posix()]),
            )

    def test_trail_entry_names_the_basename_only(self):
        with self._world() as (base, repo, other, trails):
            out = base / "staging"
            self._run(["--out", str(out)])
            (entry,) = self._read_json(out)["trails"]
            self.assertEqual(entry["trail"], trails["own"].name)
            self.assertNotIn("/", entry["trail"])
            self.assertNotIn("\\", entry["trail"])
            self.assertEqual(entry["repo_root"], repo.as_posix())

    def test_subject_repo_with_no_trails_is_reported_and_still_succeeds(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as d:
            saved = self._with_config(cfg)
            try:
                base = Path(d)
                repo = base / "untouched"
                repo.mkdir()
                rs.trail_dir()  # the dir exists, it just holds nothing for us
                with mock.patch.object(
                    scope, "current_repo_root", return_value=repo
                ):
                    rc, stdout = self._run(["--out", str(base / "staging")])
                self.assertEqual(rc, 0)
                data = self._read_json(base / "staging")
                self.assertEqual(data["trails"], [])
                self.assertEqual(data["repos"], [repo.as_posix()])
                self.assertIn("no learning-trails", stdout)
                self.assertIn("stamp nothing", stdout)
            finally:
                self._restore_config(saved)

    # ---- max_ts / records ------------------------------------------------

    def test_max_ts_is_the_true_max_when_records_are_out_of_order(self):
        with self._world() as (base, repo, other, trails):
            # Concurrent worktrees (and a stepped clock) leave the newest record
            # anywhere in the file, so the tail must not be trusted.
            trails["own"].write_text(
                "".join(
                    self._rec(ts, repo.as_posix()) + "\n"
                    for ts in (MID, LATE, EARLY)
                ),
                encoding="utf-8",
            )
            out = base / "staging"
            self._run(["--out", str(out)])
            (entry,) = self._read_json(out)["trails"]
            self.assertEqual(entry["records"], 3)
            self.assertEqual(
                datetime.fromisoformat(entry["max_ts"]),
                datetime.fromisoformat(LATE),
            )

    def test_zero_record_trail_is_listed_with_null_max_ts(self):
        with self._world() as (base, repo, other, trails):
            trails["own"].write_text("", encoding="utf-8")
            out = base / "staging"
            self._run(["--out", str(out)])
            (entry,) = self._read_json(out)["trails"]
            self.assertEqual(entry["trail"], trails["own"].name)
            self.assertEqual(entry["records"], 0)
            self.assertIsNone(entry["max_ts"])

    def test_unparseable_ts_is_excluded_from_max_but_still_counted(self):
        with self._world() as (base, repo, other, trails):
            trails["own"].write_text(
                self._rec(MID, repo.as_posix()) + "\n"
                + json.dumps(
                    {"ts": "whenever", "repo_root": repo.as_posix()}
                ) + "\n",
                encoding="utf-8",
            )
            out = base / "staging"
            self._run(["--out", str(out)])
            (entry,) = self._read_json(out)["trails"]
            self.assertEqual(entry["records"], 2)
            self.assertEqual(
                datetime.fromisoformat(entry["max_ts"]),
                datetime.fromisoformat(MID),
            )

    def test_only_unparseable_ts_yields_null_max_ts(self):
        with self._world() as (base, repo, other, trails):
            trails["own"].write_text(
                json.dumps({"ts": "nope", "repo_root": repo.as_posix()}) + "\n",
                encoding="utf-8",
            )
            out = base / "staging"
            self._run(["--out", str(out)])
            (entry,) = self._read_json(out)["trails"]
            self.assertEqual(entry["records"], 1)
            self.assertIsNone(entry["max_ts"])

    def test_malformed_line_does_not_crash_and_is_not_counted(self):
        with self._world() as (base, repo, other, trails):
            trails["own"].write_text(
                self._rec(MID, repo.as_posix()) + "\n"
                + "{not json at all\n"
                + "\n"
                + self._rec(LATE, repo.as_posix()) + "\n",
                encoding="utf-8",
            )
            out = base / "staging"
            rc, _ = self._run(["--out", str(out)])
            self.assertEqual(rc, 0)
            (entry,) = self._read_json(out)["trails"]
            self.assertEqual(entry["records"], 2)
            self.assertEqual(
                datetime.fromisoformat(entry["max_ts"]),
                datetime.fromisoformat(LATE),
            )

    def test_naive_ts_is_read_as_utc_rather_than_raising(self):
        # Comparing a naive datetime against an aware one raises TypeError; the
        # pruner reads naive as UTC and so must this.
        with self._world() as (base, repo, other, trails):
            trails["own"].write_text(
                self._rec("2026-07-13T00:00:00", repo.as_posix()) + "\n"
                + self._rec(LATE, repo.as_posix()) + "\n",
                encoding="utf-8",
            )
            out = base / "staging"
            rc, _ = self._run(["--out", str(out)])
            self.assertEqual(rc, 0)
            (entry,) = self._read_json(out)["trails"]
            self.assertEqual(entry["records"], 2)
            self.assertEqual(
                datetime.fromisoformat(entry["max_ts"]),
                datetime.fromisoformat("2026-07-13T00:00:00+00:00"),
            )

    # ---- the read-time clamp ---------------------------------------------

    def test_future_dated_record_is_clamped_to_the_read_time(self):
        # The regression. One clock-skewed record used to carry the watermark
        # with it: for as long as the skew, every genuinely new record lands
        # at-or-below the watermark, so `harvest_nudge` reports nothing,
        # `compute_readiness` counts nothing un-harvested, and the Stop-hook
        # pruner deletes records nobody read.
        with self._world() as (base, repo, other, trails):
            trails["own"].write_text(
                "".join(
                    self._rec(ts, repo.as_posix()) + "\n" for ts in (MID, FUTURE)
                ),
                encoding="utf-8",
            )
            out = base / "staging"
            rc, _ = self._run(["--out", str(out)])
            self.assertEqual(rc, 0)
            data = self._read_json(out)
            (entry,) = data["trails"]
            self.assertEqual(entry["records"], 2)
            # Bounded by the read-time, not by the future record.
            self.assertEqual(entry["max_ts"], data["read_at"])
            self.assertLess(
                datetime.fromisoformat(entry["max_ts"]),
                datetime.fromisoformat(FUTURE),
            )

    def test_records_entirely_in_the_past_are_not_clamped(self):
        # The clamp is a ceiling, not a rewrite: the ordinary case must be
        # untouched, or every watermark would collapse onto the read-time and
        # over-claim exactly the way the manifest exists to prevent.
        with self._world() as (base, repo, other, trails):
            trails["own"].write_text(
                "".join(
                    self._rec(ts, repo.as_posix()) + "\n" for ts in (MID, LATE)
                ),
                encoding="utf-8",
            )
            out = base / "staging"
            rc, stdout = self._run(["--out", str(out)])
            self.assertEqual(rc, 0)
            (entry,) = self._read_json(out)["trails"]
            self.assertEqual(
                datetime.fromisoformat(entry["max_ts"]),
                datetime.fromisoformat(LATE),
            )
            self.assertNotIn("clamped", stdout)

    def test_clamp_is_reported_on_stdout(self):
        # A future-dated record is a real anomaly on this machine. Correcting it
        # silently would hide the thing the operator needs to go fix.
        with self._world() as (base, repo, other, trails):
            trails["own"].write_text(
                self._rec(FUTURE, repo.as_posix()) + "\n", encoding="utf-8"
            )
            out = base / "staging"
            rc, stdout = self._run(["--out", str(out)])
            self.assertEqual(rc, 0)
            (line,) = [ln for ln in stdout.splitlines() if "clamped" in ln]
            self.assertIn(trails["own"].name, line)
            self.assertIn(FUTURE, line)

    def test_clamp_uses_one_read_at_across_every_trail(self):
        # Each trail is bounded against the same captured instant, so the
        # manifest's `read_at` and every `max_ts` in it describe one moment
        # rather than a spread of `now()` calls.
        with self._world() as (base, repo, other, trails):
            for key, root in (("own", repo), ("other", other)):
                trails[key].write_text(
                    self._rec(FUTURE, root.as_posix()) + "\n", encoding="utf-8"
                )
            out = base / "staging"
            rc, _ = self._run(["--out", str(out), "--repo", str(other)])
            self.assertEqual(rc, 0)
            data = self._read_json(out)
            self.assertEqual(len(data["trails"]), 2)
            self.assertEqual(
                {t["max_ts"] for t in data["trails"]}, {data["read_at"]}
            )

    # ---- library surface -------------------------------------------------

    def test_scan_trail_on_a_missing_file_degrades_to_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(
                begin_harvest.scan_trail(Path(d) / "nope.jsonl"), (0, None, None)
            )

    def test_scan_trail_clamps_to_the_read_at_it_is_given(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            p.write_text(
                self._rec(EARLY, "C:/p/repo") + "\n"
                + self._rec(FUTURE, "C:/p/repo") + "\n",
                encoding="utf-8",
            )
            records, max_ts, clamped_from = begin_harvest.scan_trail(
                p, datetime.fromisoformat(LATE)
            )
            self.assertEqual(records, 2)
            self.assertEqual(datetime.fromisoformat(max_ts), datetime.fromisoformat(LATE))
            self.assertEqual(
                datetime.fromisoformat(clamped_from), datetime.fromisoformat(FUTURE)
            )

    def test_scan_trail_defaults_to_clamping_against_now(self):
        # The default is a bound, never "no bound": an unclamped max is the
        # failure the parameter exists to prevent, so omitting it must not
        # re-open it.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            p.write_text(self._rec(FUTURE, "C:/p/repo") + "\n", encoding="utf-8")
            _, max_ts, clamped_from = begin_harvest.scan_trail(p)
            self.assertLess(
                datetime.fromisoformat(max_ts), datetime.fromisoformat(FUTURE)
            )
            self.assertEqual(clamped_from, FUTURE)


if __name__ == "__main__":
    unittest.main()
