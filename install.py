#!/usr/bin/env python3
"""Cross-platform installer for this claude-config repo.

Symlinks the repo into ~/.claude so edits here take effect immediately, and
creates the machine-local template files if they're missing. Works on macOS,
Linux, and Windows (Windows symlinks need Developer Mode or an elevated
terminal — see the note printed on failure).

An existing *symlink* target is always replaced. An existing *real* file/dir is
a **conflict** and is never overwritten silently:

    python install.py             detect conflicts; auto-stage any not-yet-adopted
                                   ones into eval/adopt/ for review with /adopt-config
    python install.py --relink     back up each conflicting real file to
                                   <name>.pre-adopt-<ts>.bak, then symlink. For a
                                   conflicting settings.json, first rescue the
                                   unambiguously machine-specific keys into
                                   settings.local.json (rule-based split).
    python install.py --dry-run    preview any of the above without writing

The content merge itself (which `allow` rules / CLAUDE.md lines are worth
keeping) stays a human/AI judgment step — see the /adopt-config skill. This
script only automates the mechanical envelope around it.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
CLAUDE_DIR = Path.home() / ".claude"

sys.path.insert(0, str(REPO_DIR / "scripts"))
from _adopt_common import is_done, parse_ledger, sha8  # noqa: E402
from _settings_split import deep_merge  # noqa: E402

# Repo path -> target name under ~/.claude. NOTE: settings.json is deliberately
# NOT symlinked — it's generated as a real, merged file by install_settings()
# (Claude Code ignores ~/.claude/settings.local.json, and user-scope hooks must
# live in ~/.claude/settings.json, which is machine-specific, not synced).
LINKS = [
    ("CLAUDE.md", "CLAUDE.md"),
    ("memory", "memory"),
    ("skills", "skills"),
    ("agents", "agents"),
    ("commands", "commands"),
    ("hooks", "hooks"),
]

# No user-scope template files: Claude Code does not read ~/.claude/settings.local.json
# or ~/.claude/CLAUDE.local.md (both are project-scope-only). Settings + hooks go
# into ~/.claude/settings.json (see install_settings); old dead .local symlinks are
# cleaned up by cleanup_dead_user_local().
TEMPLATES: list[tuple[str, str]] = []

SETTINGS_CHOICES = ("full", "minimal", "skip")


def is_conflict(dst: Path) -> bool:
    """A real (non-symlink) file/dir sitting where we want a symlink."""
    return dst.exists() and not dst.is_symlink()


def can_symlink(directory: Path) -> bool:
    """Probe whether this process may create a symlink inside `directory`.

    Windows only grants symlink creation with Developer Mode or an elevated
    shell; `--relink` backs up real files *before* linking, so probing up front
    lets us refuse without moving anything when the link would fail anyway.
    """
    probe = directory / ".install-symlink-probe"
    try:
        if probe.is_symlink() or probe.exists():
            probe.unlink()
    except OSError:
        pass
    try:
        probe.symlink_to(directory, target_is_directory=True)
    except OSError:
        return False
    try:
        probe.unlink()
    except OSError:
        pass
    return True


def symlink(src: Path, dst: Path, dry_run: bool) -> bool:
    """Create/replace a symlink dst -> src. Returns True on success."""
    if dst.is_symlink():
        if not dry_run:
            dst.unlink()  # replace existing symlink (mirrors `ln -sfn`)
    try:
        if dry_run:
            print(f"  would link {dst} -> {src}")
        else:
            dst.symlink_to(src, target_is_directory=src.is_dir())
            print(f"  linked {dst} -> {src}")
        return True
    except OSError as e:
        print(f"  ! failed to symlink {dst} -> {src}: {e}")
        if platform.system() == "Windows":
            print("    On Windows, symlinks require Developer Mode (Settings > Privacy &")
            print("    security > For developers) or running this terminal as Administrator.")
        return False


def backup(dst: Path, stamp: str, dry_run: bool) -> Path:
    """Move a real file/dir aside to <name>.pre-adopt-<stamp>.bak. Never deletes."""
    dest = dst.with_name(f"{dst.name}.pre-adopt-{stamp}.bak")
    if dry_run:
        print(f"  would back up {dst} -> {dest}")
    else:
        shutil.move(str(dst), str(dest))
        print(f"  backed up {dst} -> {dest}")
    return dest


def load_json(path: Path) -> dict:
    """Parse a JSON file, tolerating missing/comment-annotated files."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ! could not parse {path} ({e}); treating as empty")
        return {}
    if not isinstance(data, dict):
        return {}
    # Drop template annotation keys (the *.example files carry _comment* docs).
    return {k: v for k, v in data.items() if not k.startswith("_comment") and not k.endswith("_example")}


def ensure_from_template(real: Path, template: Path, dry_run: bool) -> None:
    if real.exists():
        return
    if not template.exists():
        print(f"  ! template missing, cannot create {real}: {template}")
        return
    if dry_run:
        print(f"  would create {real} from template {template.name}")
        return
    shutil.copy(template, real)
    print(f"  created {real} from template (gitignored, edit freely)")


def resolve_settings_choice(cli_choice: str | None) -> str:
    """Return 'full' | 'minimal' | 'skip'. Ask every time — never a silent default.

    A non-interactive run must pass --settings, so an unattended install can't
    quietly pick for the user.
    """
    if cli_choice:
        return cli_choice
    if not sys.stdin.isatty():
        print("  ! Non-interactive install: pass --settings {full,minimal,skip}.", file=sys.stderr)
        print("    full = adopt the whole settings.json (default agent + permissions +", file=sys.stderr)
        print("    plugins) + hooks;  minimal = set agent=orchestrator (+ hooks);", file=sys.stderr)
        print("    skip = change ~/.claude/settings.json not at all.", file=sys.stderr)
        sys.exit(2)
    print("\nIntegrate this framework's settings into ~/.claude/settings.json?")
    print("  full     adopt the whole settings.json (default agent + permissions + plugins) + hooks")
    print("  minimal  set only agent=orchestrator, plus the learning-loop hooks")
    print("  skip     change nothing (the crew won't be your default agent)")
    while True:
        ans = input("  choose [full/minimal/skip]: ").strip().lower()
        if ans in SETTINGS_CHOICES:
            return ans
        print("    please type one of: full, minimal, skip")


def install_settings(choice: str, dry_run: bool) -> None:
    """Write ~/.claude/settings.json as a REAL, merged file per the consent choice.

    Claude Code ignores ~/.claude/settings.local.json, so user-scope settings AND
    hooks must live in ~/.claude/settings.json. We generate it as a real file
    (never a symlink into the repo — machine-specific hook paths must not be
    committed/synced), deep-merging the chosen framework keys OVER any existing
    user settings so the adopted keys win while the user's other keys and
    allow-list are preserved. Hooks are wired separately, after this.
    """
    target = CLAUDE_DIR / "settings.json"
    if choice == "skip":
        print("  settings: skip — leaving ~/.claude/settings.json unchanged")
        return

    if target.is_symlink():
        # An older installer symlinked this into the repo; we manage a real file now.
        if dry_run:
            print(f"  settings: would replace the repo symlink at {target} with a real merged file")
        else:
            target.unlink()

    existing = load_json(target)  # {} if absent / just-unlinked symlink
    overlay = {"agent": "orchestrator"} if choice == "minimal" else load_json(REPO_DIR / "settings.json")
    merged = deep_merge(overlay, existing)  # overlay (framework) wins; user's extras kept

    if dry_run:
        print(f"  settings: would write {target} — {choice} ({', '.join(sorted(overlay)) or 'no keys'})")
        return
    target.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    print(f"  settings: wrote {target} ({choice})")


def cleanup_dead_user_local(dry_run: bool) -> None:
    """Remove the user-scope *.local files an older installer symlinked into
    ~/.claude — Claude Code never read them (they are project-scope-only). A real
    (non-symlink) file is left in place but flagged, so we never delete user data.
    """
    for name in ("settings.local.json", "CLAUDE.local.md"):
        p = CLAUDE_DIR / name
        if p.is_symlink():
            if dry_run:
                print(f"  cleanup: would remove dead symlink {p} (Claude Code ignores user-scope .local files)")
            else:
                p.unlink()
                print(f"  cleanup: removed dead symlink {p} (ignored by Claude Code)")
        elif p.is_file():
            print(f"  note: {p} is ignored by Claude Code (user-scope .local files aren't read) — safe to delete.")


def _norm_path(p: str) -> str:
    """Case/separator-insensitive path key for comparing wired hook paths.

    ``os.path.normcase`` folds case and separators on Windows (so ``C:\\x`` and
    ``c:/x`` compare equal); ``normpath`` collapses redundant ``.``/``//``
    segments on every platform. Together they stop a re-run from double-wiring a
    hook whose stored path merely differs in spelling.
    """
    return os.path.normcase(os.path.normpath(p))


def _wire_command_hook(
    config_dir: Path,
    *,
    event_name: str,
    script_name: str,
    use_async: bool,
    dry_run: bool,
) -> None:
    """Inject a global command hook for ``event_name`` into settings.local.json.

    Claude Code does not expand ${CLAUDE_CONFIG_DIR}, ~, or $HOME inside a hook
    command/args, so a user-level hook must be wired with an install-time
    resolved absolute path. The interpreter is the running Python
    (``sys.executable``) and the script is the symlinked
    ``<config_dir>/hooks/<script_name>``.

    The write goes into settings.local.json (machine-local, gitignored) — never
    the committed settings.json — because the resolved paths are machine
    specific. Existing keys are preserved (raw load + merge, so ``_comment_*``
    docs survive) and the injection is idempotent: a repeated run (including
    ``--relink``) that finds an ``event_name`` entry already referencing this
    script path — compared path-normalized — is a no-op, unless the recorded
    interpreter ``command`` has drifted from the current ``sys.executable`` (e.g.
    a Python upgrade), in which case it is re-wired in place rather than
    duplicated.

    The wired entry carries ``"async": True`` only when ``use_async`` is set;
    otherwise the ``async`` key is omitted entirely.

    Skipped as a no-op if the resolved script does not exist on disk (except
    under ``--dry-run``), so we never wire a hook to a script the ``hooks/``
    symlink failed to create.
    """
    interpreter = sys.executable
    script = config_dir / "hooks" / script_name
    script_str = str(script)
    norm_script = _norm_path(script_str)

    if not dry_run and not script.exists():
        print(f"  skipping {event_name} hook: {script} does not exist "
              "(hooks link not created) — nothing wired")
        return

    local_path = config_dir / "settings.json"
    # Read the raw JSON (not the comment-stripping load_json) so unrelated keys,
    # including the _comment_* guidance seeded in the template, survive the write.
    settings: dict = {}
    if local_path.exists():
        try:
            data = json.loads(local_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                settings = data
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ! could not parse {local_path} ({e}); treating as empty")

    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    group_list = hooks.get(event_name)
    if not isinstance(group_list, list):
        group_list = []

    def matching_entry(group: object) -> dict | None:
        """Return the entry in `group` that references our script (path-normalized)."""
        if not isinstance(group, dict):
            return None
        for entry in group.get("hooks", []) or []:
            if not isinstance(entry, dict):
                continue
            args = entry.get("args") or []
            if isinstance(args, list) and any(
                isinstance(a, str) and _norm_path(a) == norm_script for a in args
            ):
                return entry
            cmd = entry.get("command")
            if isinstance(cmd, str) and _norm_path(cmd) == norm_script:
                return entry
        return None

    existing = next(
        (e for e in (matching_entry(group) for group in group_list) if e is not None),
        None,
    )

    if existing is not None:
        # Already wired for this script. Leave it untouched unless the recorded
        # interpreter drifted (e.g. sys.executable moved after a Python upgrade),
        # in which case re-point it in place so no stale interpreter lingers.
        if existing.get("command") == interpreter:
            print(f"  {event_name} hook already wired in {local_path} — leaving it")
            return
        if dry_run:
            print(f"  would re-wire {event_name} hook in {local_path} (interpreter changed):")
            print(f"      {existing.get('command')} -> {interpreter}")
            return
        existing["command"] = interpreter
        args = existing.get("args")
        if not (isinstance(args, list) and any(
            isinstance(a, str) and _norm_path(a) == norm_script for a in args
        )):
            existing["args"] = [script_str]
        hooks[event_name] = group_list
        settings["hooks"] = hooks
        local_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        print(f"  re-wired {event_name} hook in {local_path}: {interpreter} {script_str}")
        return

    entry: dict = {
        "type": "command",
        "command": interpreter,
        "args": [script_str],
    }
    if use_async:
        entry["async"] = True
    block = {"hooks": [entry]}

    if dry_run:
        suffix = " (async)" if use_async else ""
        print(f"  would wire {event_name} hook into {local_path}:")
        print(f"      {interpreter} {script_str}{suffix}")
        return

    group_list.append(block)
    hooks[event_name] = group_list
    settings["hooks"] = hooks
    local_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"  wired {event_name} hook into {local_path}: {interpreter} {script_str}")


def wire_stop_hook(config_dir: Path, *, dry_run: bool) -> None:
    """Wire the global Stop hook (``record_stop.py``, async) into settings.local.json."""
    _wire_command_hook(
        config_dir,
        event_name="Stop",
        script_name="record_stop.py",
        use_async=True,
        dry_run=dry_run,
    )


def wire_sessionstart_hook(config_dir: Path, *, dry_run: bool) -> None:
    """Wire the global SessionStart hook (``harvest_nudge.py``) into settings.local.json.

    Synchronous (no ``async`` key): its stdout is injected as session context, so
    it must run to completion before the session proceeds.
    """
    _wire_command_hook(
        config_dir,
        event_name="SessionStart",
        script_name="harvest_nudge.py",
        use_async=False,
        dry_run=dry_run,
    )


def do_relink(stamp: str, dry_run: bool, ledger: dict, choice: str) -> int:
    """Back up each conflicting real target and symlink it into the repo."""
    # Refuse before touching anything if we can't create symlinks — otherwise we'd
    # back up real files and then fail to link them, leaving ~/.claude half-broken.
    if not dry_run and not can_symlink(CLAUDE_DIR):
        print(f"  ! cannot create symlinks in {CLAUDE_DIR} — nothing was changed.")
        if platform.system() == "Windows":
            print("    Enable Developer Mode (Settings > Privacy & security > For")
            print("    developers) or run this terminal as Administrator, then re-run.")
        return 1

    template_srcs = {REPO_DIR / real for real, _ in TEMPLATES}
    for real, template in TEMPLATES:
        ensure_from_template(REPO_DIR / real, REPO_DIR / template, dry_run)

    all_targets = [(REPO_DIR / s, CLAUDE_DIR / d) for s, d in LINKS]
    all_targets += [(REPO_DIR / real, CLAUDE_DIR / real) for real, _ in TEMPLATES]

    hooks_dst = CLAUDE_DIR / "hooks"
    hooks_linked = False
    relinked = 0
    failed = 0
    for src, dst in all_targets:
        if not is_conflict(dst):
            continue
        # Warn if we're relinking something never run through adoption.
        if src.exists() and not is_done(sha8(dst), ledger):
            print(f"  ! {dst} is not recorded as adopted in the ledger — backing up and")
            print("    linking anyway; make sure you merged anything worth keeping first.")
        # A template source may not exist on disk yet in a dry run (ensure_from_template
        # only prints "would create"); treat it as present so the preview is accurate.
        if not src.exists() and not (dry_run and src in template_srcs):
            print(f"  ! repo source missing for {dst}: {src} — skipping")
            continue
        backup_path = backup(dst, stamp, dry_run)
        if symlink(src, dst, dry_run):
            relinked += 1
            if dst == hooks_dst:
                hooks_linked = True
        elif not dry_run:
            # Symlink failed after the file was already moved aside; put it back
            # so a mid-run failure never leaves the target missing.
            shutil.move(str(backup_path), str(dst))
            print(f"  restored {dst} from backup after symlink failure")
            failed += 1

    # The hooks target may not have been a conflict (already a valid symlink) —
    # in that case it was skipped above but is still correctly in place, so treat
    # it as linked if the symlink resolves to an existing record_stop.py.
    if not hooks_linked and not is_conflict(hooks_dst):
        if hooks_dst.is_symlink() and (hooks_dst / "record_stop.py").exists():
            hooks_linked = True

    # Only wire the hook when the hooks/ link specifically is (or would be) in
    # place; otherwise we'd reference a record_stop.py that never got linked and,
    # worse, leave a real settings.local.json blocking future installs.
    cleanup_dead_user_local(dry_run)
    install_settings(choice, dry_run)
    if choice != "skip" and (dry_run or hooks_linked):
        wire_stop_hook(CLAUDE_DIR, dry_run=dry_run)
        wire_sessionstart_hook(CLAUDE_DIR, dry_run=dry_run)

    if dry_run:
        print(f"\nWould relink {relinked} target(s). Backups kept as *.pre-adopt-*.bak.")
    elif relinked:
        print(f"\nRelinked {relinked} target(s). Backups kept as *.pre-adopt-*.bak.")
    elif failed:
        print(f"\n{failed} target(s) could not be linked; originals were left in place.")
    else:
        print("\nNo real-file conflicts to relink.")
    return 1 if failed and not relinked else 0


def stage_conflicts(dry_run: bool) -> None:
    """Delegate to the adopt scan so conflicts land in eval/adopt/ for review."""
    if dry_run:
        print("  would run scripts/adopt_existing_config.py to stage conflicts for review")
        return
    import adopt_existing_config
    adopt_existing_config.main()


def do_default(dry_run: bool, ledger: dict, choice: str) -> int:
    """Link safe targets; detect conflicts and route them to staging or --relink."""
    if not dry_run:
        CLAUDE_DIR.mkdir(parents=True, exist_ok=True)

    conflicts: list[Path] = []
    hooks_linked = False

    for src_name, dst_name in LINKS:
        src, dst = REPO_DIR / src_name, CLAUDE_DIR / dst_name
        if not src.exists():
            print(f"  ! source missing, skipping: {src}")
            continue
        if is_conflict(dst):
            conflicts.append(dst)
            continue
        linked = symlink(src, dst, dry_run)
        if dst_name == "hooks":
            hooks_linked = linked

    for real_name, template_name in TEMPLATES:
        real = REPO_DIR / real_name
        ensure_from_template(real, REPO_DIR / template_name, dry_run)
        dst = CLAUDE_DIR / real_name
        if is_conflict(dst):
            conflicts.append(dst)
            continue
        if real.exists():
            symlink(real, dst, dry_run)

    if not conflicts:
        cleanup_dead_user_local(dry_run)
        install_settings(choice, dry_run)
        # Hooks live in ~/.claude/settings.json now; wire them only if the hooks/
        # symlink is in place and the user didn't skip settings integration.
        if choice != "skip" and hooks_linked:
            wire_stop_hook(CLAUDE_DIR, dry_run=dry_run)
            wire_sessionstart_hook(CLAUDE_DIR, dry_run=dry_run)
        elif choice != "skip":
            print("  skipping hooks: hooks/ link was not created")
        print("Done. Restart Claude Code / Desktop to pick up changes.")
        return 0

    undone = [c for c in conflicts if not is_done(sha8(c), ledger)]
    adopted = [c for c in conflicts if is_done(sha8(c), ledger)]

    print(f"\n{len(conflicts)} existing real file(s) block symlinking:")
    for c in conflicts:
        tag = "adopted" if c in adopted else "needs review"
        print(f"  - {c}  [{tag}]")

    if undone:
        print("\nStaging the not-yet-adopted ones for review:")
        stage_conflicts(dry_run)
        print("\nNext: review with /adopt-config (merge what's worth keeping), then run")
        print("  python install.py --relink")
    else:
        print("\nAll conflicts are already adopted into the repo. Finish the swap with:")
        print("  python install.py --relink")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Install this claude-config repo into ~/.claude.")
    ap.add_argument("--relink", action="store_true",
                    help="back up conflicting real files and symlink them")
    ap.add_argument("--dry-run", action="store_true",
                    help="preview actions without writing anything")
    ap.add_argument("--settings", choices=SETTINGS_CHOICES, default=None,
                    help="settings.json integration: full | minimal | skip "
                         "(prompted if omitted; required when non-interactive)")
    args = ap.parse_args(argv)

    print(f"Repo:   {REPO_DIR}")
    print(f"Target: {CLAUDE_DIR}")
    if args.dry_run:
        print("(dry run — no changes will be made)")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ledger = parse_ledger()

    choice = resolve_settings_choice(args.settings)
    if args.relink:
        return do_relink(stamp, args.dry_run, ledger, choice)
    return do_default(args.dry_run, ledger, choice)


if __name__ == "__main__":
    sys.exit(main())
