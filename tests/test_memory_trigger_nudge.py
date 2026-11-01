import contextlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hooks import memory_trigger_nudge  # noqa: E402


# ---- the ADR 0002 memory-trigger reminder ------------------------------


@contextlib.contextmanager
def _patched(obj, name, value):
    """Temporarily set ``obj.name`` to ``value``, restoring it afterwards.

    Manual save/restore rather than ``unittest.mock``, matching this file's
    existing idiom (see the ``NUDGE_THRESHOLD`` save/restore above).
    """
    missing = object()
    saved = getattr(obj, name, missing)
    setattr(obj, name, value)
    try:
        yield
    finally:
        if saved is missing:
            delattr(obj, name)
        else:
            setattr(obj, name, saved)


class _FakeRun:
    """Stand-in for ``subprocess.run``: records calls, returns a canned result.

    This is the boundary the trigger reminder is tested across. The real
    ``check_memory_triggers.py`` is a 1500-line transcript-capable reporter; the
    failure paths below (timeout, undefined return code, malformed stdout)
    cannot be provoked through it, and the hook's whole contract is what it does
    with those answers.
    """

    def __init__(self, *, returncode=0, stdout="", raises=None):
        self.returncode = returncode
        self.stdout = stdout
        self.raises = raises
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, "")


def _trigger(name, verdict, *, headline="", can_fire=True):
    """One entry of the payload's ``triggers`` list, shaped like the script's."""
    return {
        "trigger": name,
        "verdict": verdict,
        "reason": None,
        "can_fire": can_fire,
        "headline": headline,
        "detail": [],
    }


def _payload(*triggers, corpus_notes=12, directory_notes=None, limits=None):
    """A ``--skip-transcripts --json`` payload, shaped like the real script's.

    Only the keys the hook reads are modelled; the real payload carries more
    (``scan``, ``exit``, ``memory_root``...) and the hook must not need them.
    Every name here is invented — no fixture mirrors a real corpus.
    """
    return {
        "memory_root": "/fixture/memory",
        "corpus_notes": corpus_notes,
        "directory_notes": (
            {"alpha": 7, "beta": 5} if directory_notes is None else directory_notes
        ),
        "limits": ({"directory": 100, "corpus": 500} if limits is None else limits),
        "triggers": list(triggers),
    }


def _clear_payload(**kwargs):
    """Nothing to say: both size triggers clear, T3/T4 unknown (the real shape)."""
    return _payload(
        _trigger("t1-directory-size", "clear"),
        _trigger("t2-corpus-size", "clear"),
        _trigger("t3-unrouted-harvest", "unknown"),
        _trigger("t4-index-bypass", "unknown", can_fire=False),
        **kwargs,
    )


class TriggerLineRenderingTest(unittest.TestCase):
    """What the hook says about a payload — the pure rendering layer."""

    def test_fired_t2_names_the_trigger_its_count_and_its_threshold(self):
        lines = memory_trigger_nudge._fired_lines(
            _payload(_trigger("t2-corpus-size", "FIRED"), corpus_notes=512)
        )
        self.assertEqual(len(lines), 1)
        self.assertIn("FIRED", lines[0])
        self.assertIn("T2", lines[0])
        self.assertIn("ADR 0002", lines[0])
        self.assertIn("512", lines[0])  # the measured count
        self.assertIn("500", lines[0])  # the threshold it is measured against

    def test_fired_t1_names_the_largest_directory_count_and_the_threshold(self):
        lines = memory_trigger_nudge._fired_lines(
            _payload(
                _trigger("t1-directory-size", "FIRED"),
                directory_notes={"alpha": 118, "beta": 4},
            )
        )
        self.assertEqual(len(lines), 1)
        self.assertIn("FIRED", lines[0])
        self.assertIn("T1", lines[0])
        self.assertIn("118", lines[0])
        self.assertIn("100", lines[0])

    def test_fired_t3_reports_the_scripts_own_headline(self):
        # T3 has no numeric pair in the payload's structured fields, so the
        # headline is the only thing that can carry the finding.
        lines = memory_trigger_nudge._fired_lines(
            _payload(
                _trigger(
                    "t3-unrouted-harvest",
                    "FIRED",
                    headline="3 harvest nomination(s) could not be routed",
                )
            )
        )
        self.assertEqual(len(lines), 1)
        self.assertIn("T3", lines[0])
        self.assertIn("3 harvest nomination(s) could not be routed", lines[0])

    def test_clear_payload_produces_no_lines(self):
        self.assertEqual(memory_trigger_nudge._fired_lines(_clear_payload()), [])
        self.assertEqual(memory_trigger_nudge._near_threshold_lines(_clear_payload()), [])

    def test_t4_is_never_named_even_when_the_payload_claims_it_fired(self):
        # With --skip-transcripts T4 is always `unknown` with can_fire=False, so
        # this payload is impossible in production. It is forced anyway: ADR 0004's
        # guarantee is that `unknown` must never read as a finding *or* as
        # `clear`, and pinning it against the data rather than against the
        # producer means a future T4 that could fire cannot leak a bypass rate
        # into session context without someone deciding that it should.
        forced = _payload(
            _trigger("t4-index-bypass", "FIRED", headline="bypass rate 99%"),
            _trigger("t1-directory-size", "clear"),
            _trigger("t2-corpus-size", "clear"),
        )
        self.assertEqual(memory_trigger_nudge._fired_lines(forced), [])
        rendered = "\n".join(
            memory_trigger_nudge._fired_lines(forced)
            + memory_trigger_nudge._near_threshold_lines(forced)
        )
        for needle in ("t4", "T4", "bypass", "99"):
            self.assertNotIn(needle, rendered)

    def test_unknown_verdicts_are_never_rendered(self):
        # T3 `unknown` means "no tally was ever recorded", which is precisely not
        # the same as zero unrouted learnings. Rendering it either way would be a
        # claim the payload does not support.
        unknown = _payload(
            _trigger("t3-unrouted-harvest", "unknown", headline="no unrouted tally"),
            _trigger("t4-index-bypass", "unknown", can_fire=False),
        )
        self.assertEqual(memory_trigger_nudge._fired_lines(unknown), [])
        self.assertEqual(memory_trigger_nudge._near_threshold_lines(unknown), [])

    def test_two_line_budget_holds_when_more_triggers_fire_than_fit(self):
        everything = _payload(
            _trigger("t1-directory-size", "FIRED"),
            _trigger("t2-corpus-size", "FIRED"),
            _trigger("t3-unrouted-harvest", "FIRED", headline="2 unrouted"),
            corpus_notes=512,
            directory_notes={"alpha": 118, "beta": 101},
        )
        lines = memory_trigger_nudge._fired_lines(everything)
        self.assertEqual(len(lines), 2)
        # The two findings that carry numbers are kept; the third is dropped,
        # not merged into one of them.
        self.assertIn("T1", lines[0])
        self.assertIn("T2", lines[1])
        self.assertNotIn("2 unrouted", "\n".join(lines))

    def test_missing_triggers_key_renders_nothing(self):
        payload = {
            "corpus_notes": 12,
            "directory_notes": {"alpha": 7},
            "limits": {"directory": 100, "corpus": 500},
        }
        self.assertEqual(memory_trigger_nudge._fired_lines(payload), [])

    def test_triggers_that_is_not_a_list_renders_nothing(self):
        payload = _clear_payload()
        payload["triggers"] = {"t2-corpus-size": "FIRED"}
        self.assertEqual(memory_trigger_nudge._fired_lines(payload), [])

    def test_non_dict_trigger_entries_are_skipped_not_fatal(self):
        payload = _payload(corpus_notes=512)
        payload["triggers"] = [
            "t2-corpus-size",
            None,
            7,
            ["t2-corpus-size", "FIRED"],
            _trigger("t2-corpus-size", "FIRED"),
        ]
        lines = memory_trigger_nudge._fired_lines(payload)
        self.assertEqual(len(lines), 1)
        self.assertIn("512", lines[0])
        # ...and a list of nothing but junk says nothing at all.
        payload["triggers"] = ["t2-corpus-size", None, 7]
        self.assertEqual(memory_trigger_nudge._fired_lines(payload), [])

    def test_missing_limits_suppress_the_line_rather_than_guessing(self):
        # A line naming a count without the threshold it was measured against
        # would be noise, so the whole line is dropped.
        payload = _payload(_trigger("t2-corpus-size", "FIRED"), corpus_notes=512)
        del payload["limits"]
        self.assertEqual(memory_trigger_nudge._fired_lines(payload), [])
        self.assertEqual(memory_trigger_nudge._near_threshold_lines(payload), [])

    def test_near_threshold_reports_proximity_with_its_percentage(self):
        lines = memory_trigger_nudge._near_threshold_lines(
            _clear_payload(directory_notes={"alpha": 95, "beta": 3})
        )
        self.assertEqual(len(lines), 1)
        self.assertIn("nearing threshold", lines[0])
        self.assertIn("T1", lines[0])
        self.assertIn("95", lines[0])
        self.assertIn("100", lines[0])

    def test_near_threshold_boundary_is_the_declared_fraction(self):
        limit = 100
        at = int(limit * memory_trigger_nudge.NEAR_THRESHOLD_FRACTION)
        self.assertEqual(at, 90, "this test's arithmetic assumes a 0.9 fraction")
        self.assertEqual(
            len(
                memory_trigger_nudge._near_threshold_lines(
                    _clear_payload(directory_notes={"alpha": at})
                )
            ),
            1,
        )
        self.assertEqual(
            memory_trigger_nudge._near_threshold_lines(
                _clear_payload(directory_notes={"alpha": at - 1})
            ),
            [],
        )
        # The same boundary for the corpus, against its own (different) limit.
        self.assertEqual(
            len(memory_trigger_nudge._near_threshold_lines(_clear_payload(corpus_notes=450))),
            1,
        )
        self.assertEqual(
            memory_trigger_nudge._near_threshold_lines(_clear_payload(corpus_notes=449)), []
        )

    def test_near_threshold_tolerates_a_zero_limit(self):
        # The percentage divides by the limit; a zero limit must not raise
        # inside a SessionStart hook.
        self.assertEqual(
            memory_trigger_nudge._near_threshold_lines(
                _clear_payload(
                    corpus_notes=10,
                    directory_notes={"alpha": 10},
                    limits={"directory": 0, "corpus": 0},
                )
            ),
            [],
        )


class TriggerPayloadBoundaryTest(unittest.TestCase):
    """``_trigger_payload`` across the subprocess boundary — every failure is None.

    ``subprocess.run`` is faked rather than invoking the real script: these are
    the answers the real script cannot be made to give on demand, and they are
    exactly the ones that must degrade to silence.
    """

    SCRIPT = Path("nowhere") / "check_memory_triggers.py"

    def _payload_via(self, run):
        with _patched(memory_trigger_nudge.subprocess, "run", run):
            return memory_trigger_nudge._trigger_payload(
                Path("fixture") / "memory", self.SCRIPT
            )

    def test_return_code_1_is_success_not_failure(self):
        # THE regression this feature lives or dies on. check_memory_triggers.py
        # defines EXIT_FIRED = 1, so "a trigger fired" IS the non-zero-rc case.
        # Reading non-zero as failure — the obvious reading — turns the whole
        # reminder into a permanent no-op that nothing else would ever report.
        body = json.dumps(
            _payload(_trigger("t2-corpus-size", "FIRED"), corpus_notes=512)
        )
        payload = self._payload_via(_FakeRun(returncode=1, stdout=body))
        self.assertIsNotNone(payload)
        self.assertEqual(payload["corpus_notes"], 512)

    def test_return_code_0_is_also_accepted(self):
        payload = self._payload_via(
            _FakeRun(returncode=0, stdout=json.dumps(_clear_payload()))
        )
        self.assertIsNotNone(payload)

    def test_accepted_return_codes_match_the_scripts_own_exit_constants(self):
        # The hook does not import scripts/ (see the PENDING_PREFIX pin above),
        # so the accepted return codes are duplicated knowledge. Pin them against
        # the definitions so renumbering the script's exits cannot silently make a
        # fired trigger look like an error — or an error look like a finding.
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import check_memory_triggers  # noqa: E402

        self.assertEqual(check_memory_triggers.EXIT_PASS, 0)
        self.assertEqual(check_memory_triggers.EXIT_FIRED, 1)
        self.assertEqual(check_memory_triggers.EXIT_ERROR, 2)
        body = json.dumps(_clear_payload())
        for rc in (check_memory_triggers.EXIT_PASS, check_memory_triggers.EXIT_FIRED):
            self.assertIsNotNone(
                self._payload_via(_FakeRun(returncode=rc, stdout=body)),
                f"rc {rc} is a defined verdict and must be parsed",
            )
        self.assertIsNone(
            self._payload_via(
                _FakeRun(returncode=check_memory_triggers.EXIT_ERROR, stdout=body)
            ),
            "EXIT_ERROR must not be read as a verdict",
        )

    def test_undefined_return_code_is_silent(self):
        self.assertIsNone(
            self._payload_via(
                _FakeRun(returncode=3, stdout=json.dumps(_clear_payload()))
            )
        )

    def test_timeout_is_silent(self):
        self.assertIsNone(
            self._payload_via(
                _FakeRun(
                    raises=subprocess.TimeoutExpired(
                        cmd=["python"], timeout=memory_trigger_nudge.TRIGGER_TIMEOUT
                    )
                )
            )
        )

    def test_oserror_launching_the_interpreter_is_silent(self):
        self.assertIsNone(
            self._payload_via(_FakeRun(raises=OSError("no such executable")))
        )

    def test_malformed_json_is_silent(self):
        self.assertIsNone(self._payload_via(_FakeRun(stdout="{not json")))
        self.assertIsNone(self._payload_via(_FakeRun(stdout="")))

    def test_json_that_is_not_an_object_is_silent(self):
        self.assertIsNone(self._payload_via(_FakeRun(stdout="[1, 2, 3]")))
        self.assertIsNone(self._payload_via(_FakeRun(stdout="null")))

    def test_the_subprocess_call_skips_transcripts_and_targets_the_given_memory(self):
        run = _FakeRun(stdout=json.dumps(_clear_payload()))
        with _patched(memory_trigger_nudge.subprocess, "run", run):
            memory_trigger_nudge._trigger_payload(Path("fixture") / "memory", self.SCRIPT)
        self.assertEqual(len(run.calls), 1)
        argv, kwargs = run.calls[0]
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1], str(self.SCRIPT))
        # --skip-transcripts is not optional: the full T4 scan takes minutes and
        # must never run inside a SessionStart hook.
        self.assertIn("--skip-transcripts", argv)
        self.assertIn("--json", argv)
        self.assertEqual(
            argv[argv.index("--memory-root") + 1], str(Path("fixture") / "memory")
        )
        # A pathological tree must not hang session start.
        self.assertEqual(kwargs["timeout"], memory_trigger_nudge.TRIGGER_TIMEOUT)
        self.assertGreater(memory_trigger_nudge.TRIGGER_TIMEOUT, 0)


class TriggerMessageTest(unittest.TestCase):
    """``trigger_message``/``trigger_nudge``: resolution, gating, degradation."""

    def _with_config(self, d):
        saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = d
        return saved

    def _restore_config(self, saved):
        if saved is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = saved

    @contextlib.contextmanager
    def _repo_with_memory(self):
        """Yield a fixture repo root that owns an (empty) ``memory/`` directory."""
        with tempfile.TemporaryDirectory() as work:
            (Path(work) / "memory").mkdir()
            yield work

    def test_framework_root_owns_the_trigger_script(self):
        # scripts/ is never symlinked into ~/.claude/; the hook reaches the
        # script through the hooks/ symlink's resolved parent instead. If this
        # stops holding, every trigger reminder goes silent and nothing says so.
        root = memory_trigger_nudge._framework_root()
        self.assertEqual(root, Path(memory_trigger_nudge.__file__).resolve().parent.parent)
        self.assertTrue((root / "scripts" / "check_memory_triggers.py").is_file())

    def test_fired_trigger_is_surfaced_for_this_repos_memory(self):
        run = _FakeRun(
            returncode=1,
            stdout=json.dumps(
                _payload(_trigger("t2-corpus-size", "FIRED"), corpus_notes=512)
            ),
        )
        with self._repo_with_memory() as work:
            with _patched(memory_trigger_nudge.subprocess, "run", run):
                msg = memory_trigger_nudge.trigger_message(work)
        self.assertIn("FIRED", msg)
        self.assertIn("512", msg)
        # The memory root handed to the script is this repo's, not the
        # framework's — the framework's own memory/ would report the same handful
        # of notes in every repo on the machine.
        argv = run.calls[0][0]
        self.assertEqual(
            argv[argv.index("--memory-root") + 1], str(Path(work) / "memory")
        )
        self.assertNotIn(str(memory_trigger_nudge._framework_root() / "memory"), argv)

    def test_clear_corpus_says_nothing(self):
        run = _FakeRun(stdout=json.dumps(_clear_payload()))
        with self._repo_with_memory() as work:
            with _patched(memory_trigger_nudge.subprocess, "run", run):
                self.assertEqual(memory_trigger_nudge.trigger_message(work), "")

    def test_output_is_at_most_two_lines(self):
        run = _FakeRun(
            returncode=1,
            stdout=json.dumps(
                _payload(
                    _trigger("t1-directory-size", "FIRED"),
                    _trigger("t2-corpus-size", "FIRED"),
                    _trigger("t3-unrouted-harvest", "FIRED", headline="2 unrouted"),
                    corpus_notes=512,
                    directory_notes={"alpha": 118, "beta": 101},
                )
            ),
        )
        with self._repo_with_memory() as work:
            with _patched(memory_trigger_nudge.subprocess, "run", run):
                msg = memory_trigger_nudge.trigger_message(work)
        self.assertEqual(len(msg.splitlines()), 2)

    def test_a_fired_trigger_suppresses_the_near_threshold_note(self):
        # A FIRED trigger already implies "near the threshold"; printing both
        # would spend the whole two-line budget saying one thing twice.
        run = _FakeRun(
            returncode=1,
            stdout=json.dumps(
                _payload(
                    _trigger("t2-corpus-size", "FIRED"),
                    corpus_notes=512,
                    directory_notes={"alpha": 95},
                )
            ),
        )
        with self._repo_with_memory() as work:
            with _patched(memory_trigger_nudge.subprocess, "run", run):
                msg = memory_trigger_nudge.trigger_message(work)
        self.assertIn("FIRED", msg)
        self.assertNotIn("nearing threshold", msg)

    def test_near_threshold_is_surfaced_when_nothing_fired(self):
        run = _FakeRun(stdout=json.dumps(_clear_payload(directory_notes={"alpha": 95})))
        with self._repo_with_memory() as work:
            with _patched(memory_trigger_nudge.subprocess, "run", run):
                msg = memory_trigger_nudge.trigger_message(work)
        self.assertIn("nearing threshold", msg)
        self.assertIn("95", msg)

    def test_silent_when_memory_dir_is_absent(self):
        run = _FakeRun(
            stdout=json.dumps(_payload(_trigger("t2-corpus-size", "FIRED")))
        )
        with tempfile.TemporaryDirectory() as work:
            with _patched(memory_trigger_nudge.subprocess, "run", run):
                self.assertEqual(memory_trigger_nudge.trigger_message(work), "")
        # A repo with no brain has no triggers — and the script is never even run.
        self.assertEqual(run.calls, [])

    def test_silent_when_the_trigger_script_is_missing(self):
        # A copy-install, or a relocated framework, must produce silence rather
        # than an error line in every session's context.
        run = _FakeRun(
            stdout=json.dumps(_payload(_trigger("t2-corpus-size", "FIRED")))
        )
        with self._repo_with_memory() as work, tempfile.TemporaryDirectory() as fake:
            with _patched(memory_trigger_nudge, "_framework_root", lambda: Path(fake)):
                with _patched(memory_trigger_nudge.subprocess, "run", run):
                    self.assertEqual(memory_trigger_nudge.trigger_message(work), "")
        self.assertEqual(run.calls, [])

    def test_silent_on_every_subprocess_failure(self):
        failures = [
            _FakeRun(raises=subprocess.TimeoutExpired(cmd=["python"], timeout=5)),
            _FakeRun(raises=OSError("boom")),
            _FakeRun(returncode=2, stdout=json.dumps(_clear_payload())),
            _FakeRun(stdout="{not json"),
            _FakeRun(stdout="[1, 2, 3]"),
        ]
        with self._repo_with_memory() as work:
            for run in failures:
                with self.subTest(case=str(run.raises or run.returncode)):
                    with _patched(memory_trigger_nudge.subprocess, "run", run):
                        self.assertEqual(memory_trigger_nudge.trigger_message(work), "")

    def test_source_gating_matches_the_rest_of_the_hook(self):
        calls = []

        def fake_payload(memory_root, script):
            calls.append((memory_root, script))
            return _payload(_trigger("t2-corpus-size", "FIRED"), corpus_notes=512)

        with tempfile.TemporaryDirectory() as cfg, self._repo_with_memory() as work:
            saved = self._with_config(cfg)
            try:
                with _patched(memory_trigger_nudge, "_trigger_payload", fake_payload):
                    for source in ("clear", "compact", "", None, "unknown-source"):
                        self.assertEqual(
                            memory_trigger_nudge.trigger_nudge({"source": source, "cwd": work}),
                            "",
                        )
                    # Not even consulted on a gated source: no subprocess cost.
                    self.assertEqual(calls, [])
                    for source in ("startup", "resume"):
                        self.assertIn(
                            "FIRED",
                            memory_trigger_nudge.trigger_nudge(
                                {"source": source, "cwd": work}
                            ),
                        )
                    self.assertEqual(len(calls), 2)
            finally:
                self._restore_config(saved)


class TriggerEndToEndTest(unittest.TestCase):
    """One run against the real ``check_memory_triggers.py``, on an invented tree.

    Everything else fakes the subprocess boundary. This exists so the two sides
    cannot drift apart unnoticed: it pins the real script's JSON key names, its
    ``limits`` shape, and — the part that matters most — that a genuinely fired
    trigger exits **1** and the hook still prints it.
    """

    @contextlib.contextmanager
    def _fixture_tree(self, notes):
        """Yield a repo root whose ``memory/fixture-topic/`` holds ``notes`` notes."""
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = os.environ.get("CLAUDE_CONFIG_DIR")
            os.environ["CLAUDE_CONFIG_DIR"] = cfg
            try:
                topic = Path(work) / "memory" / "fixture-topic"
                topic.mkdir(parents=True)
                for i in range(notes):
                    (topic / f"note-{i:03d}.md").write_text(
                        f"# fixture note {i}\n", encoding="utf-8"
                    )
                yield work
            finally:
                if saved is None:
                    os.environ.pop("CLAUDE_CONFIG_DIR", None)
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = saved

    def test_fired_t1_is_reported_from_a_real_run(self):
        limit = 100  # DIR_NOTE_LIMIT; one directory at the limit fires T1 (rc 1)
        with self._fixture_tree(limit) as work:
            msg = memory_trigger_nudge.trigger_message(work)
        self.assertIn("FIRED", msg)
        self.assertIn("T1", msg)
        self.assertIn(str(limit), msg)
        self.assertLessEqual(len(msg.splitlines()), 2)
        # T3 is `unknown` on a fresh tree (no tally was ever recorded) and T4 is
        # `unknown` by construction; neither may appear as a finding.
        self.assertNotIn("T3", msg)
        self.assertNotIn("T4", msg)

    def test_a_small_real_tree_says_nothing(self):
        with self._fixture_tree(3) as work:
            self.assertEqual(memory_trigger_nudge.trigger_message(work), "")


if __name__ == "__main__":
    unittest.main()
