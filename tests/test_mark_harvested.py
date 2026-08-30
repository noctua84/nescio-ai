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
import mark_harvested  # noqa: E402

AT = "2026-07-12T08:00:00+00:00"
AFTER_AT = "2026-07-12T08:05:00+00:00"
BEFORE_AT = "2026-07-11T23:00:00+00:00"
NEWER = "2026-07-13T09:00:00+00:00"


class MarkHarvestedTest(unittest.TestCase):
    def _with_config(self, d):
        saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = d
        return saved

    def _restore_config(self, saved):
        if saved is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = saved

    def _seed_trails(self, names):
        """Create empty *.jsonl trail files; return their paths."""
        td = rs.trail_dir()
        paths = []
        for name in names:
            p = td / f"{name}.jsonl"
            p.write_text("{}\n", encoding="utf-8")
            paths.append(p)
        return paths

    def _seed_trail(self, name, git_root=None):
        """Create one trail; its first record names ``git_root`` when given."""
        p = rs.trail_dir() / f"{name}.jsonl"
        body = ""
        if git_root is not None:
            body = json.dumps(
                {"ts": AT, "git_root": git_root, "repo_root": git_root}
            ) + "\n"
        p.write_text(body, encoding="utf-8")
        return p

    def _read_manifest(self, d, trails, *, version=1, name="read.json", raw=None):
        """Write a read manifest into ``d``; return its path.

        ``trails`` is a list of (trail_path, max_ts) pairs, or an already-shaped
        list of entry dicts. ``raw`` short-circuits everything and writes the
        given text verbatim, for the malformed cases.
        """
        p = Path(d) / name
        if raw is not None:
            p.write_text(raw, encoding="utf-8")
            return p
        entries = []
        for item in trails:
            if isinstance(item, dict):
                entries.append(item)
                continue
            trail, max_ts = item
            entries.append(
                {
                    "trail": Path(trail).name if not isinstance(trail, str) else trail,
                    "repo_root": "C:/repo/proj",
                    "records": 3,
                    "max_ts": max_ts,
                }
            )
        payload = {
            "version": version,
            "read_at": AFTER_AT,
            "repos": ["C:/repo/proj"],
            "trails": entries,
        }
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return p

    def _receipt(self, d, **overrides):
        """Write a promotion receipt into ``d``; return its path."""
        payload = {
            "version": 1,
            "manifest": "eval/learnings/20260712T080000Z/manifest.json",
            "promoted": 3,
            "skipped": 0,
            "targets": ["repo/proj/foo.md"],
            "written_at": AFTER_AT,
        }
        payload.update(overrides)
        p = Path(d) / "receipt.json"
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return p

    def _run(self, argv):
        """Run main() capturing both streams; return (rc, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = mark_harvested.main(argv)
        return rc, out.getvalue(), err.getvalue()

    @contextlib.contextmanager
    def _scoped_world(self):
        """cfg + four trails on disk: the repo's own, a worktree, a sibling, a stranger.

        Yields ``(dir, trails)`` where ``trails`` maps a label to its trail path
        and ``dir`` is a scratch dir for manifests and receipts. Only the trails a
        manifest names may ever be stamped — the other three exist precisely so a
        test can assert their watermarks stay absent.
        """
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as d:
            saved = self._with_config(cfg)
            try:
                base = Path(d)
                repo = base / "proj"
                sibling = base / "proj-docs"
                stranger = base / "elsewhere"
                worktree = repo / ".claude" / "worktrees" / "feature"
                sibling.mkdir()
                stranger.mkdir()
                worktree.mkdir(parents=True)
                trails = {
                    "own": self._seed_trail(rs.repo_key(str(repo))),
                    "worktree": self._seed_trail("wt", worktree.as_posix()),
                    "sibling": self._seed_trail(
                        rs.repo_key(str(sibling)), sibling.as_posix()
                    ),
                    "stranger": self._seed_trail("other", stranger.as_posix()),
                }
                yield d, trails
            finally:
                self._restore_config(saved)

    @contextlib.contextmanager
    def _in_dir(self, path):
        """Run the body with the process cwd at ``path``.

        main()'s marker is keyed on the repo containing the *process* cwd, so a
        test about cross-repo marker scope has to actually stand somewhere.
        """
        saved = os.getcwd()
        os.chdir(path)
        try:
            yield
        finally:
            os.chdir(saved)

    def _assert_unstamped(self, trails, *labels):
        for label in labels:
            self.assertFalse(
                rs.watermark_path(trails[label]).exists(),
                f"a watermark was written for {label} ({trails[label].name})",
            )

    # ---- library surface -------------------------------------------------

    def test_stamp_watermark_writes_paired_file(self):
        with tempfile.TemporaryDirectory() as cfg:
            saved = self._with_config(cfg)
            try:
                (trail,) = self._seed_trails(["repoA"])
                ts = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)
                wm = mark_harvested.stamp_watermark(trail, ts)
                self.assertEqual(wm, rs.watermark_path(trail))
                self.assertTrue(wm.is_file())
                self.assertEqual(rs.read_watermark(wm), ts)
            finally:
                self._restore_config(saved)

    def test_mark_trails_harvested_stamps_only_what_it_is_given(self):
        with tempfile.TemporaryDirectory() as cfg:
            saved = self._with_config(cfg)
            try:
                a, b = self._seed_trails(["repoA", "repoB"])
                ts = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)
                written = mark_harvested.mark_trails_harvested([a], now=ts)
                self.assertEqual(written, [rs.watermark_path(a)])
                self.assertTrue(rs.watermark_path(a).is_file())
                self.assertFalse(rs.watermark_path(b).exists())
            finally:
                self._restore_config(saved)

    def test_no_global_stamping_helper_survives(self):
        # The machine-global sweep IS the bug; the function must not exist to be
        # re-wired by a future caller.
        self.assertFalse(hasattr(mark_harvested, "mark_all_harvested"))

    # ---- CLI: stamping from the manifest ---------------------------------

    def test_stamps_exactly_the_manifest_trails_each_at_its_own_max_ts(self):
        with self._scoped_world() as (d, trails):
            manifest = self._read_manifest(
                d,
                [
                    (trails["own"].name, AT),
                    (trails["worktree"].name, NEWER),
                ],
            )
            rc, out, err = self._run(["--read", str(manifest)])
            self.assertEqual(rc, 0, err)
            self.assertEqual(
                rs.read_watermark(rs.watermark_path(trails["own"])),
                datetime.fromisoformat(AT),
            )
            self.assertEqual(
                rs.read_watermark(rs.watermark_path(trails["worktree"])),
                datetime.fromisoformat(NEWER),
            )
            self.assertIn("read manifest", out)
            self.assertIn("stamped for 2 trail(s)", out)

    def test_trail_on_disk_but_absent_from_manifest_is_never_stamped(self):
        # The core regression: one repo's harvest must not mark another's records
        # as reviewed.
        with self._scoped_world() as (d, trails):
            manifest = self._read_manifest(d, [(trails["own"].name, AT)])
            rc, _, err = self._run(["--read", str(manifest)])
            self.assertEqual(rc, 0, err)
            self.assertTrue(rs.watermark_path(trails["own"]).is_file())
            self._assert_unstamped(trails, "worktree", "sibling", "stranger")

    def test_null_max_ts_is_skipped_and_reported(self):
        with self._scoped_world() as (d, trails):
            manifest = self._read_manifest(
                d, [(trails["own"].name, None), (trails["worktree"].name, AT)]
            )
            rc, out, err = self._run(["--read", str(manifest)])
            self.assertEqual(rc, 0, err)
            self._assert_unstamped(trails, "own")
            self.assertTrue(rs.watermark_path(trails["worktree"]).is_file())
            self.assertIn("skipped", err)
            self.assertIn("max_ts", err)
            self.assertIn("1 skipped", out)

    def test_manifest_naming_a_nonexistent_trail_warns_and_stamps_the_rest(self):
        with self._scoped_world() as (d, trails):
            manifest = self._read_manifest(
                d, [("ghost.jsonl", AT), (trails["own"].name, AT)]
            )
            rc, out, err = self._run(["--read", str(manifest)])
            self.assertEqual(rc, 0, err)
            self.assertIn("ghost.jsonl", err)
            self.assertIn("absent from disk", err)
            self.assertTrue(rs.watermark_path(trails["own"]).is_file())
            self.assertIn("stamped for 1 trail(s)", out)

    def test_never_moves_a_watermark_backward(self):
        with self._scoped_world() as (d, trails):
            newer = datetime.fromisoformat(NEWER)
            rs.write_watermark(rs.watermark_path(trails["own"]), newer)
            manifest = self._read_manifest(d, [(trails["own"].name, AT)])
            rc, out, err = self._run(["--read", str(manifest)])
            self.assertEqual(rc, 0, err)
            self.assertEqual(
                rs.read_watermark(rs.watermark_path(trails["own"])), newer
            )
            self.assertIn("unchanged", err)
            self.assertIn("1 unchanged", out)

    def test_equal_watermark_is_left_unchanged(self):
        with self._scoped_world() as (d, trails):
            at = datetime.fromisoformat(AT)
            rs.write_watermark(rs.watermark_path(trails["own"]), at)
            manifest = self._read_manifest(d, [(trails["own"].name, AT)])
            rc, out, _ = self._run(["--read", str(manifest)])
            self.assertEqual(rc, 0)
            self.assertEqual(rs.read_watermark(rs.watermark_path(trails["own"])), at)
            self.assertIn("1 unchanged", out)

    def test_older_watermark_is_advanced(self):
        with self._scoped_world() as (d, trails):
            rs.write_watermark(
                rs.watermark_path(trails["own"]), datetime.fromisoformat(BEFORE_AT)
            )
            manifest = self._read_manifest(d, [(trails["own"].name, AT)])
            rc, _, _ = self._run(["--read", str(manifest)])
            self.assertEqual(rc, 0)
            self.assertEqual(
                rs.read_watermark(rs.watermark_path(trails["own"])),
                datetime.fromisoformat(AT),
            )

    def test_trail_name_with_a_path_separator_is_not_resolved(self):
        # A manifest is a file; it must not be able to steer the stamp at a
        # watermark outside the trail dir.
        #
        # Two shapes, because they take different routes and only one of them is
        # platform-independent. "../escape.jsonl" is rejected by _trail_name on
        # both platforms (Path(...).name strips the "../"). A Windows absolute
        # path is the divergent case: on Windows _trail_name rejects it the same
        # way, but on Linux a backslash is an ordinary filename character, so the
        # whole string IS its own basename and survives into the join — landing
        # inside trail_dir as a literal name, where is_file() is False and it is
        # skipped. Either way nothing outside trail_dir is written; that is what
        # the assertions below establish, rather than assuming one platform's
        # route.
        with self._scoped_world() as (d, trails):
            manifest = self._read_manifest(
                d,
                [
                    ("../escape.jsonl", AT),
                    ("C:\\Windows\\x.jsonl", AT),
                    (trails["own"].name, AT),
                ],
            )
            rc, out, _ = self._run(["--read", str(manifest)])
            self.assertEqual(rc, 0)
            td = Path(rs.trail_dir())
            self.assertFalse((td.parent / "escape.watermark").exists())
            self.assertFalse(Path("C:/Windows/x.watermark").exists())
            self.assertTrue(rs.watermark_path(trails["own"]).is_file())
            # The only watermark anywhere in the trail dir is the declared one.
            self.assertEqual(
                sorted(p.name for p in td.glob("*.watermark")),
                [rs.watermark_path(trails["own"]).name],
            )
            self.assertIn("stamped for 1 trail(s)", out)

    # ---- CLI: a future max_ts -------------------------------------------

    def test_future_max_ts_is_clamped_to_now(self):
        # Defence in depth against a clock-skewed record or a hand-edited
        # manifest: a watermark in the future claims coverage of records that do
        # not exist yet, and record_stop's prune would delete them unread.
        with self._scoped_world() as (d, trails):
            future = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()
            manifest = self._read_manifest(d, [(trails["own"].name, future)])
            before = datetime.now(timezone.utc)
            rc, out, err = self._run(["--read", str(manifest)])
            after = datetime.now(timezone.utc)
            self.assertEqual(rc, 0, err)
            stamped = rs.read_watermark(rs.watermark_path(trails["own"]))
            self.assertGreaterEqual(stamped, before)
            self.assertLessEqual(stamped, after)
            self.assertIn("clamped", err)
            self.assertIn(trails["own"].name, err)
            self.assertIn("stamped for 1 trail(s)", out)

    def test_past_max_ts_is_not_clamped(self):
        with self._scoped_world() as (d, trails):
            manifest = self._read_manifest(d, [(trails["own"].name, AT)])
            rc, _, err = self._run(["--read", str(manifest)])
            self.assertEqual(rc, 0, err)
            self.assertNotIn("clamped", err)
            self.assertEqual(
                rs.read_watermark(rs.watermark_path(trails["own"])),
                datetime.fromisoformat(AT),
            )

    # ---- CLI: refusals ---------------------------------------------------

    def _assert_refused(self, argv, needle, *, read_arg=None):
        """rc 0, banner on stderr, zero watermarks written, marker dropped."""
        with self._scoped_world() as (d, trails):
            rc, out, err = self._run(argv)
            self.assertEqual(rc, 0, err)
            self.assertIn("refusing to stamp", err)
            self.assertIn(needle, err)
            self.assertIn("re-run", err.lower())
            self.assertIn("mark_harvested.py --read", err)
            self.assertEqual(out, "")
            self._assert_unstamped(trails, *trails.keys())
            marker = mark_harvested.pending_path()
            self.assertTrue(marker.is_file(), "refusal left no pending marker")
            data = json.loads(marker.read_text(encoding="utf-8"))
            self.assertIn("reason", data)
            self.assertIn("at", data)
            self.assertIn("cwd", data)
            self.assertEqual(data["read"], read_arg)

    def test_refuses_without_read_manifest(self):
        self._assert_refused([], "no --read manifest given")

    def test_refuses_missing_manifest_file(self):
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "nope.json"
            self._assert_refused(
                ["--read", str(missing)], "not readable", read_arg=str(missing)
            )

    def test_refuses_malformed_manifest_json(self):
        with tempfile.TemporaryDirectory() as d:
            bad = self._read_manifest(d, [], raw="{not json")
            self._assert_refused(
                ["--read", str(bad)], "not valid JSON", read_arg=str(bad)
            )

    def test_refuses_manifest_that_is_not_an_object(self):
        with tempfile.TemporaryDirectory() as d:
            arr = self._read_manifest(d, [], raw="[1, 2, 3]")
            self._assert_refused(
                ["--read", str(arr)], "not a JSON object", read_arg=str(arr)
            )

    def test_refuses_unknown_manifest_version(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._read_manifest(d, [("a.jsonl", AT)], version=2)
            self._assert_refused(["--read", str(m)], "is not 1", read_arg=str(m))

    def test_refuses_manifest_without_a_trails_list(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._read_manifest(
                d, [], raw=json.dumps({"version": 1, "trails": "nope"})
            )
            self._assert_refused(["--read", str(m)], "no 'trails' list", read_arg=str(m))

    def test_refuses_manifest_with_an_empty_trails_list(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._read_manifest(d, [])
            self._assert_refused(
                ["--read", str(m)], "no usable trails", read_arg=str(m)
            )

    def test_refuses_manifest_whose_entries_are_all_unusable(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._read_manifest(
                d,
                [{"repo_root": "x", "max_ts": AT}, {"trail": 7}, "not-a-dict"],
                raw=json.dumps(
                    {
                        "version": 1,
                        "trails": [
                            {"repo_root": "x", "max_ts": AT},
                            {"trail": 7},
                            "not-a-dict",
                        ],
                    }
                ),
            )
            self._assert_refused(
                ["--read", str(m)], "no usable trails", read_arg=str(m)
            )

    # ---- CLI: the pending marker ----------------------------------------

    def test_marker_is_cleared_after_a_successful_stamp(self):
        with self._scoped_world() as (d, trails):
            mark_harvested.write_pending("earlier refusal", None)
            self.assertTrue(mark_harvested.pending_path().is_file())
            manifest = self._read_manifest(d, [(trails["own"].name, AT)])
            rc, _, err = self._run(["--read", str(manifest)])
            self.assertEqual(rc, 0, err)
            self.assertFalse(mark_harvested.pending_path().exists())

    def test_clear_pending_is_a_no_op_when_absent(self):
        with tempfile.TemporaryDirectory() as cfg:
            saved = self._with_config(cfg)
            try:
                mark_harvested.clear_pending()  # must not raise
                self.assertFalse(mark_harvested.pending_path().exists())
            finally:
                self._restore_config(saved)

    def test_marker_name_is_keyed_per_repo(self):
        with tempfile.TemporaryDirectory() as cfg, \
                tempfile.TemporaryDirectory() as a, \
                tempfile.TemporaryDirectory() as b:
            saved = self._with_config(cfg)
            try:
                pa = mark_harvested.pending_path(a)
                pb = mark_harvested.pending_path(b)
                self.assertNotEqual(pa, pb)
                for p in (pa, pb):
                    self.assertTrue(p.name.startswith(mark_harvested.PENDING_PREFIX))
                    self.assertEqual(p.parent, rs.trail_dir())
                # ...and it is the same identity record_stop uses for the trail.
                self.assertEqual(
                    pa.name,
                    mark_harvested.PENDING_PREFIX + rs.repo_key(rs.git_root(a)),
                )
            finally:
                self._restore_config(saved)

    def test_each_repos_marker_is_independent_and_clearing_is_scoped(self):
        with tempfile.TemporaryDirectory() as cfg, \
                tempfile.TemporaryDirectory() as a, \
                tempfile.TemporaryDirectory() as b:
            saved = self._with_config(cfg)
            try:
                mark_harvested.write_pending("A refused", "a/read.json", cwd=a)
                mark_harvested.write_pending("B refused", "b/read.json", cwd=b)
                pa = mark_harvested.pending_path(a)
                pb = mark_harvested.pending_path(b)
                self.assertTrue(pa.is_file())
                self.assertTrue(pb.is_file())
                self.assertEqual(
                    json.loads(pa.read_text(encoding="utf-8"))["read"], "a/read.json"
                )
                self.assertEqual(
                    json.loads(pb.read_text(encoding="utf-8"))["read"], "b/read.json"
                )
                mark_harvested.clear_pending(a)
                self.assertFalse(pa.exists())
                self.assertTrue(pb.is_file(), "clearing A's marker removed B's")
            finally:
                self._restore_config(saved)

    def test_a_successful_stamp_does_not_clear_another_repos_marker(self):
        # The regression this whole branch exists to prevent, in marker form: a
        # machine-global marker meant repo B's successful harvest deleted repo A's
        # still-unread warning, so A's records stayed un-harvested AND unmentioned.
        with self._scoped_world() as (d, trails):
            with tempfile.TemporaryDirectory() as repo_a:
                mark_harvested.write_pending("A's harvest refused", None, cwd=repo_a)
                marker_a = mark_harvested.pending_path(repo_a)
                self.assertTrue(marker_a.is_file())
                manifest = self._read_manifest(d, [(trails["own"].name, AT)])
                with self._in_dir(d):  # stamping from a different repo entirely
                    rc, _, err = self._run(["--read", str(manifest)])
                    self.assertEqual(rc, 0, err)
                    # ...which did clear its own (absent) marker, not A's.
                    self.assertFalse(mark_harvested.pending_path(d).exists())
                self.assertTrue(
                    marker_a.is_file(),
                    "another repo's successful stamp erased this repo's marker",
                )
                self.assertEqual(
                    json.loads(marker_a.read_text(encoding="utf-8"))["reason"],
                    "A's harvest refused",
                )

    # ---- CLI: an I/O error part-way through the stamping loop ------------

    def test_io_error_mid_stamp_reports_and_leaves_the_marker_standing(self):
        # stamp_watermark can raise OSError (ENOSPC, permissions, an AV file lock
        # on Windows). Letting it escape gave a traceback and a non-zero exit at
        # the end of a harvest whose notes and ledger were already written — and
        # left no marker, so the SessionStart net never fired for this class.
        with self._scoped_world() as (d, trails):
            order = [trails["own"], trails["worktree"], trails["sibling"]]
            manifest = self._read_manifest(d, [(t.name, AT) for t in order])
            real_write = rs.write_watermark
            calls = {"n": 0}

            def flaky(path, ts):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise OSError(28, "No space left on device")
                return real_write(path, ts)

            with self._in_dir(d):
                mark_harvested.write_pending("earlier refusal", None)
                with mock.patch.object(rs, "write_watermark", flaky):
                    rc, out, err = self._run(["--read", str(manifest)])
                marker = mark_harvested.pending_path()
                self.assertTrue(
                    marker.is_file(), "a partial stamp cleared the pending marker"
                )
                data = json.loads(marker.read_text(encoding="utf-8"))

            self.assertEqual(rc, 0, err)
            self.assertEqual(calls["n"], 3)  # the loop kept going after the failure
            # Reported honestly, on both streams.
            self.assertIn("FAILED to stamp", err)
            self.assertIn(trails["worktree"].name, err)
            self.assertIn("No space left on device", err)
            self.assertIn("1 FAILED", out)
            self.assertIn("stamped for 2 trail(s)", out)
            # No rollback: the two that landed are genuinely declared-and-read.
            self.assertTrue(rs.watermark_path(trails["own"]).is_file())
            self.assertTrue(rs.watermark_path(trails["sibling"]).is_file())
            self.assertFalse(rs.watermark_path(trails["worktree"]).exists())
            # The marker now describes the failure, and names the manifest so the
            # hook can tell the operator what to re-run.
            self.assertIn("could not be stamped", data["reason"])
            self.assertIn(trails["worktree"].name, data["reason"])
            self.assertEqual(data["read"], str(manifest))

    def test_a_fully_successful_stamp_still_clears_the_marker(self):
        # The guard above must not turn every run into a pending one.
        with self._scoped_world() as (d, trails):
            manifest = self._read_manifest(
                d, [(trails["own"].name, AT), (trails["sibling"].name, AT)]
            )
            with self._in_dir(d):
                mark_harvested.write_pending("earlier refusal", None)
                rc, out, err = self._run(["--read", str(manifest)])
                self.assertEqual(rc, 0, err)
                self.assertFalse(mark_harvested.pending_path().exists())
            self.assertNotIn("FAILED", out)
            self.assertNotIn("FAILED", err)

    # ---- CLI: the advisory receipt --------------------------------------

    def test_receipt_with_zero_promotions_still_stamps_and_warns(self):
        with self._scoped_world() as (d, trails):
            manifest = self._read_manifest(d, [(trails["own"].name, AT)])
            receipt = self._receipt(d, promoted=0)
            rc, out, err = self._run(
                ["--read", str(manifest), "--receipt", str(receipt)]
            )
            self.assertEqual(rc, 0, err)
            self.assertIn("0 promotions", err)
            self.assertIn("WARNING", err)
            self.assertNotIn("refusing to stamp", err)
            self.assertEqual(
                rs.read_watermark(rs.watermark_path(trails["own"])),
                datetime.fromisoformat(AT),
            )

    def test_malformed_receipt_still_stamps_and_warns(self):
        with self._scoped_world() as (d, trails):
            manifest = self._read_manifest(d, [(trails["own"].name, AT)])
            bad = Path(d) / "receipt.json"
            bad.write_text("{not json", encoding="utf-8")
            rc, _, err = self._run(["--read", str(manifest), "--receipt", str(bad)])
            self.assertEqual(rc, 0, err)
            self.assertIn("WARNING", err)
            self.assertTrue(rs.watermark_path(trails["own"]).is_file())

    def test_missing_receipt_file_still_stamps_and_warns(self):
        with self._scoped_world() as (d, trails):
            manifest = self._read_manifest(d, [(trails["own"].name, AT)])
            missing = Path(d) / "no-such-receipt.json"
            rc, _, err = self._run(
                ["--read", str(manifest), "--receipt", str(missing)]
            )
            self.assertEqual(rc, 0, err)
            self.assertIn("not readable", err)
            self.assertTrue(rs.watermark_path(trails["own"]).is_file())

    def test_valid_receipt_is_silent(self):
        with self._scoped_world() as (d, trails):
            manifest = self._read_manifest(d, [(trails["own"].name, AT)])
            receipt = self._receipt(d)
            rc, _, err = self._run(
                ["--read", str(manifest), "--receipt", str(receipt)]
            )
            self.assertEqual(rc, 0, err)
            self.assertNotIn("WARNING", err)

    def test_no_receipt_is_silent(self):
        with self._scoped_world() as (d, trails):
            manifest = self._read_manifest(d, [(trails["own"].name, AT)])
            rc, _, err = self._run(["--read", str(manifest)])
            self.assertEqual(rc, 0, err)
            self.assertNotIn("WARNING", err)

    # ---- receipt validator, directly ------------------------------------

    def test_check_receipt_accepts_valid_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(mark_harvested.check_receipt(str(self._receipt(d))))

    def test_check_receipt_without_a_path_is_silent(self):
        self.assertIsNone(mark_harvested.check_receipt(None))

    def test_check_receipt_flags_boolean_promoted(self):
        with tempfile.TemporaryDirectory() as d:
            warning = mark_harvested.check_receipt(str(self._receipt(d, promoted=True)))
            self.assertIsNotNone(warning)
            self.assertIn("no integer 'promoted'", warning)

    def test_check_receipt_flags_unknown_version(self):
        with tempfile.TemporaryDirectory() as d:
            warning = mark_harvested.check_receipt(str(self._receipt(d, version=2)))
            self.assertIsNotNone(warning)
            self.assertIn("is not 1", warning)

    def test_check_receipt_ignores_the_manifest_field_entirely(self):
        # Recorded verbatim as the operator typed it: relative, backslashed, or
        # simply gone. None of that may matter.
        with tempfile.TemporaryDirectory() as d:
            r = self._receipt(d, manifest="..\\eval\\learnings\\nope\\manifest.json")
            self.assertIsNone(mark_harvested.check_receipt(str(r)))


if __name__ == "__main__":
    unittest.main()
