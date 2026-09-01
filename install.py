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
                                   <name>.pre-adopt-<ts>.bak, then symlink it into
                                   the repo. settings.json and CLAUDE.md are not
                                   symlinked — they're integrated per the --settings
                                   / --claude-md consent choice (see install_settings
                                   / install_claude_md).
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

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from scripts import adopt_existing_config
from scripts._adopt_common import is_done, sha8, parse_ledger
from scripts._settings_merge import deep_merge

REPO_DIR = Path(__file__).resolve().parent
CLAUDE_DIR = Path.home() / ".claude"

# Repo path -> target name under ~/.claude. NOTE: settings.json and CLAUDE.md are
# deliberately NOT symlinked. settings.json is generated as a real, merged file by
# install_settings() (Claude Code ignores ~/.claude/settings.local.json, and
# user-scope hooks must live in ~/.claude/settings.json, which is machine-specific
# and not synced). CLAUDE.md is handled by install_claude_md() per a consent choice
# (import the framework's into / replace / skip the user's ~/.claude/CLAUDE.md).
LINKS = [
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

CLAUDEMD_CHOICES = ("import", "replace", "skip")

# Selectable top-level parts of the framework settings.json -> the key(s) each maps to.
PART_KEYS: dict[str, tuple[str, ...]] = {
    "agent": ("agent",),
    "permissions": ("permissions",),
    "plugins": ("enabledPlugins",),
}
# Keyword shorthands (kept for backward compatibility).
SETTINGS_KEYWORDS: dict[str, frozenset[str]] = {
    "full": frozenset(PART_KEYS),
    "minimal": frozenset({"agent"}),
    "skip": frozenset(),
}


def parse_settings_value(value: str) -> frozenset[str]:
    """Parse a --settings value into a set of parts (empty set == skip).

    Accepts EITHER a keyword (full|minimal|skip) OR a comma-list of parts
    (agent, permissions, plugins). Raises ValueError on an unknown token or a
    keyword mixed with parts (e.g. "full,agent").
    """
    v = value.strip().lower()
    if v in SETTINGS_KEYWORDS:
        return SETTINGS_KEYWORDS[v]
    tokens = [t.strip() for t in v.split(",") if t.strip()]
    if not tokens:
        return frozenset()
    unknown = [t for t in tokens if t not in PART_KEYS]
    if unknown:
        raise ValueError(
            f"unknown settings part(s): {', '.join(unknown)} — expected the "
            f"keyword full|minimal|skip or a comma-list of {'|'.join(PART_KEYS)}"
        )
    return frozenset(tokens)


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
    """Create/replace a symlink dst -> src. Returns True on success.

    Idempotent: if dst is already a symlink pointing at src, it is left
    untouched (no destructive unlink/recreate on a re-run).

    Restore-on-failure: when an existing symlink must be replaced, its current
    target is captured first; if the recreate raises OSError (e.g. Windows
    without Developer Mode), the previous symlink is restored so a failed
    install never destroys a previously-working link (issue #31).
    """
    old_target: str | None = None
    if dst.is_symlink():
        try:
            current = os.readlink(dst)
        except OSError:
            current = None
        # Already pointing where we want -> no-op; skip the destructive path.
        # Compare the resolved target (Path.resolve normalizes the Windows
        # extended-length "\\?\" prefix that os.readlink can return).
        already_linked = False
        if current is not None:
            try:
                already_linked = dst.resolve() == src.resolve()
            except OSError:
                already_linked = False
        if already_linked:
            if dry_run:
                print(f"  would leave {dst} -> {src} (already linked)")
            else:
                print(f"  already linked {dst} -> {src}")
            return True
        old_target = current
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
        # Best-effort restore of the symlink we just removed, so a failed
        # recreate never leaves the target missing where a working link stood.
        if not dry_run and old_target is not None:
            try:
                os.symlink(old_target, dst,
                           target_is_directory=Path(old_target).is_dir())
                print(f"  restored previous symlink {dst} -> {old_target}")
            except OSError as restore_err:
                print(f"    ! WARNING: could not restore previous symlink "
                      f"{dst} -> {old_target}: {restore_err}")
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


def resolve_settings_choice(cli_value: str | None) -> frozenset[str]:
    """Return the selected settings parts (empty set == skip). Ask every time.

    A keyword (full|minimal|skip) or a comma-list of parts
    (agent,permissions,plugins). Non-interactive runs must pass --settings.
    """
    if cli_value is not None:
        return parse_settings_value(cli_value)  # ValueError -> handled in main()
    if not sys.stdin.isatty():
        print("  ! Non-interactive install: pass --settings.", file=sys.stderr)
        print("    keyword: full (agent+permissions+plugins) | minimal (agent) | skip", file=sys.stderr)
        print("    or a comma-list of parts: agent,permissions,plugins", file=sys.stderr)
        sys.exit(2)
    print("\nIntegrate this framework's settings into ~/.claude/settings.json?")
    print("  (deep-merged over your file — your other keys and allow-list are kept)")
    print("  full     agent + permissions + plugins   (recommended) + hooks")
    print("  minimal  agent entrypoint only + hooks")
    print("  custom   choose parts individually")
    print("  skip     change nothing")
    while True:
        ans = input("  choose [full/minimal/custom/skip] (default full): ").strip().lower()
        if ans == "":
            return SETTINGS_KEYWORDS["full"]
        if ans in SETTINGS_KEYWORDS:
            return SETTINGS_KEYWORDS[ans]
        if ans == "custom":
            return _prompt_custom_parts()
        print("    please type one of: full, minimal, custom, skip")


def _prompt_custom_parts() -> frozenset[str]:
    """Per-part [Y/n] prompts (each defaults to Yes). Returns the selected parts."""
    questions = [
        ("agent", "adopt agent entrypoint?"),
        ("permissions", "adopt permissions allow-list?"),
        ("plugins", "adopt plugins?"),
    ]
    selected = {
        part for part, q in questions
        if input(f"    {q} [Y/n]: ").strip().lower() in ("", "y", "yes")
    }
    return frozenset(selected)


def install_settings(parts: frozenset[str], dry_run: bool) -> None:
    """Write ~/.claude/settings.json as a REAL, merged file for the selected parts.

    `parts` is a subset of PART_KEYS (empty == skip). The overlay is the framework
    settings.json restricted to the selected parts' keys, deep-merged OVER any
    existing user settings so adopted keys win while the user's other keys and
    allow-list are preserved. Hooks are wired separately, after this.
    """
    target = CLAUDE_DIR / "settings.json"
    if not parts:
        print("  settings: skip — leaving ~/.claude/settings.json unchanged")
        return

    if target.is_symlink():
        if dry_run:
            print(f"  settings: would replace the repo symlink at {target} with a real merged file")
        else:
            target.unlink()

    existing = load_json(target)
    fw = load_json(REPO_DIR / "settings.json")
    overlay = {k: fw[k] for part in parts for k in PART_KEYS[part] if k in fw}
    merged = deep_merge(overlay, existing)  # overlay (framework) wins; user's extras kept

    label = ",".join(sorted(parts))
    if dry_run:
        print(f"  settings: would write {target} — parts {label} "
              f"(keys: {', '.join(sorted(overlay)) or 'none'})")
        return
    target.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    print(f"  settings: wrote {target} (parts: {label})")


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


def resolve_claudemd_choice(cli_choice: str | None) -> str:
    """Return 'import' | 'replace' | 'skip'. Ask every time — never a silent default.

    A non-interactive run must pass --claude-md, mirroring resolve_settings_choice
    so an unattended install can't quietly pick for the user.
    """
    if cli_choice:
        return cli_choice
    if not sys.stdin.isatty():
        print("  ! Non-interactive install: pass --claude-md {import,replace,skip}.", file=sys.stderr)
        print("    import  = your ~/.claude/CLAUDE.md @-imports the framework's (keeps your own);", file=sys.stderr)
        print("    replace = symlink the framework's CLAUDE.md as your global (backs up an existing one);", file=sys.stderr)
        print("    skip    = leave ~/.claude/CLAUDE.md untouched.", file=sys.stderr)
        sys.exit(2)
    print("\nHow should this framework's CLAUDE.md integrate with ~/.claude/CLAUDE.md?")
    print("  import   your ~/.claude/CLAUDE.md @-imports the framework's (keeps your own additions)")
    print("  replace  symlink the framework's CLAUDE.md as your global (backs up an existing one)")
    print("  skip     leave ~/.claude/CLAUDE.md untouched")
    while True:
        ans = input("  choose [import/replace/skip]: ").strip().lower()
        if ans in CLAUDEMD_CHOICES:
            return ans
        print("    please type one of: import, replace, skip")


def install_claude_md(choice: str, dry_run: bool) -> None:
    """Integrate the framework's CLAUDE.md with ~/.claude/CLAUDE.md per the choice.

    Only one user-scope CLAUDE.md is read, so composition is via Claude Code's
    `@path` import mechanism (documented + reliable at user scope — unlike the
    ignored settings.local.json):

      import   ~/.claude/CLAUDE.md becomes a REAL file whose first line is
               `@<repo>/CLAUDE.md` (the framework brief, resolved live) with the
               user's own instructions preserved below. Idempotent.
      replace  symlink ~/.claude/CLAUDE.md -> the repo's CLAUDE.md (an existing
               real file is backed up first). The framework brief IS the global.
      skip     leave ~/.claude/CLAUDE.md untouched.
    """
    target = CLAUDE_DIR / "CLAUDE.md"
    repo_md = REPO_DIR / "CLAUDE.md"
    import_line = f"@{repo_md}"

    if choice == "skip":
        print("  CLAUDE.md: skip — leaving ~/.claude/CLAUDE.md unchanged")
        return

    if choice == "replace":
        if is_conflict(target):  # a real file — preserve it before symlinking
            backup(target, datetime.now().strftime("%Y%m%d-%H%M%S"), dry_run)
        symlink(repo_md, target, dry_run)
        return

    # choice == "import"
    existing = ""
    if target.is_symlink():
        # An older installer symlinked this into the repo; become a real file that
        # imports it instead, so the user can keep their own lines below.
        if dry_run:
            print(f"  CLAUDE.md: would replace the repo symlink at {target} with a real importing file")
        else:
            target.unlink()
    elif target.is_file():
        existing = target.read_text(encoding="utf-8")

    if import_line in existing:
        print(f"  CLAUDE.md: {target} already imports the framework — nothing to do")
        return

    if existing.strip():
        new_text = f"{import_line}\n\n{existing}"
    else:
        new_text = (
            f"{import_line}\n\n"
            "# Your instructions\n\n"
            "# Add your own global instructions below; they load alongside the import above.\n"
        )
    if dry_run:
        print(f"  CLAUDE.md: would add `{import_line}` to {target} (import)")
        return
    target.write_text(new_text, encoding="utf-8")
    print(f"  CLAUDE.md: wrote {target} importing the framework (import)")


def _norm_path(p: str) -> str:
    """Case/separator-insensitive path key for comparing wired hook paths.

    ``os.path.normcase`` folds case and separators on Windows (so ``C:\\x`` and
    ``c:/x`` compare equal); ``normpath`` collapses redundant ``.``/``//``
    segments on every platform. Together they stop a re-run from double-wiring a
    hook whose stored path merely differs in spelling.
    """
    return os.path.normcase(os.path.normpath(p))


def _hook_group(matcher: str | None, entries: list) -> dict:
    """Build a hooks group, with ``matcher`` serialised ahead of ``hooks``.

    ``None`` omits the key entirely rather than writing ``"matcher": null`` —
    that is the shape the event-scoped hooks (Stop, SessionStart) have always
    produced, and re-ordering or padding it would churn every user's
    settings.json on the next install for no behavioural gain.
    """
    group: dict = {}
    if matcher is not None:
        group["matcher"] = matcher
    group["hooks"] = entries
    return group


def _wire_command_hook(
    config_dir: Path,
    *,
    event_name: str,
    script_name: str,
    use_async: bool,
    dry_run: bool,
    matcher: str | None = None,
) -> None:
    """Inject a global command hook for ``event_name`` into ~/.claude/settings.json.

    Claude Code does not expand ${CLAUDE_CONFIG_DIR}, ~, or $HOME inside a hook
    command/args, so a user-level hook must be wired with an install-time
    resolved absolute path. The interpreter is the running Python
    (``sys.executable``) and the script is the symlinked
    ``<config_dir>/hooks/<script_name>``.

    The write goes into ~/.claude/settings.json — the only user-scope settings
    file Claude Code reads (settings.local.json is ignored at user scope). That
    file is generated as a real, machine-local file (never symlinked into the
    repo), so the resolved absolute paths stay off the synced tree. Existing keys
    are preserved (raw load + merge, so ``_comment_*`` docs survive) and the
    injection is idempotent.

    A wired hook's identity is the *pair* (script path, compared
    path-normalized, plus the containing group's ``matcher``), because
    ``matcher`` is a property of the group, not of the entry. So a repeated run
    (including ``--relink``) that finds an ``event_name`` entry referencing this
    script *inside a group whose matcher agrees* is a no-op. It is re-wired in
    place, never duplicated and never silently skipped, when either half has
    drifted: the recorded interpreter ``command`` (e.g. a Python upgrade moved
    ``sys.executable``) or the group's ``matcher``. Both are fixed in one pass.
    Comparing on the script path alone was the older behaviour and it was wrong:
    adding a matcher to an already-wired hook printed "already wired" and left
    the old unscoped entry in place, still firing on every tool call.

    ``matcher`` scopes a tool-event hook (``PreToolUse``/``PostToolUse``) to the
    tools it cares about; ``None`` emits a bare ``{"hooks": [...]}`` group, which
    is what event-scoped hooks (``Stop``, ``SessionStart``) want. A tool-scoped
    hook wired without one fires on *every* tool call, which on a synchronous
    hook is a latency tax on the whole session. The comparison is deliberately
    narrow: an absent ``matcher`` key and an explicit ``null`` both mean "no
    matcher", and anything else must match exactly. ``"*"`` and ``""`` are *not*
    folded into "absent" — how Claude Code reads those is its business, and
    guessing would make two differently-scoped hooks compare equal.

    Re-scoping mutates the group in place only when our entry is its sole
    occupant. A group shared with other hooks is left alone and our entry is
    moved out into a correctly-matched group of its own, since rewriting a
    shared group's ``matcher`` would silently re-scope somebody else's hook.
    That move appends the new group at the end of the event's list, so our hook
    now runs *after* the ones it used to sit beside — immaterial for ``Stop``,
    but observable on a ``SessionStart``-style event whose hooks' stdout is
    concatenated into the session context in list order.

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

    def matching_entry(group: object) -> tuple[dict, dict] | None:
        """Return (group, entry) for the entry in `group` referencing our script.

        The *group* comes back with the entry because `matcher` lives on the
        group, not the entry — a bare entry cannot answer whether the hook is
        scoped the way we asked for.
        """
        if not isinstance(group, dict):
            return None
        for entry in group.get("hooks", []) or []:
            if not isinstance(entry, dict):
                continue
            args = entry.get("args") or []
            if isinstance(args, list) and any(
                isinstance(a, str) and _norm_path(a) == norm_script for a in args
            ):
                return group, entry
            cmd = entry.get("command")
            if isinstance(cmd, str) and _norm_path(cmd) == norm_script:
                return group, entry
        return None

    found = [
        m for m in (matching_entry(group) for group in group_list) if m is not None
    ]
    # Several groups may reference our script (a settings.json edited by hand, or
    # left behind by the older matcher-blind wiring). Prefer one already scoped
    # the way we want, so a correct wiring stays a no-op; otherwise take the
    # first, which gets re-scoped below rather than duplicated alongside.
    existing_group, existing = next(
        ((g, e) for g, e in found if g.get("matcher") == matcher),
        found[0] if found else (None, None),
    )

    if existing is not None:
        # Already wired for this script. Leave it untouched unless the recorded
        # interpreter drifted (e.g. sys.executable moved after a Python upgrade)
        # or the group's matcher no longer matches what we were asked to wire —
        # either way re-point it in place so nothing stale or wrongly-scoped
        # lingers. Both are repaired in the same pass.
        interpreter_ok = existing.get("command") == interpreter
        matcher_ok = existing_group.get("matcher") == matcher
        if interpreter_ok and matcher_ok:
            print(f"  {event_name} hook already wired in {local_path} — leaving it")
            return
        drift = [
            label for label, ok in (("interpreter", interpreter_ok),
                                    ("matcher", matcher_ok)) if not ok
        ]
        reason = " and ".join(drift) + " changed"
        if dry_run:
            print(f"  would re-wire {event_name} hook in {local_path} ({reason}):")
            if not interpreter_ok:
                print(f"      {existing.get('command')} -> {interpreter}")
            if not matcher_ok:
                print(f"      matcher {existing_group.get('matcher')!r} -> {matcher!r}")
            return
        existing["command"] = interpreter
        args = existing.get("args")
        if not (isinstance(args, list) and any(
            isinstance(a, str) and _norm_path(a) == norm_script for a in args
        )):
            existing["args"] = [script_str]
        if not matcher_ok:
            siblings = [e for e in existing_group.get("hooks") or [] if e is not existing]
            if siblings:
                # The group carries other hooks too. Rewriting its matcher would
                # silently re-scope those, so move our entry out into a group of
                # its own and leave theirs exactly as it was.
                existing_group["hooks"] = siblings
                group_list.append(_hook_group(matcher, [existing]))
            else:
                # Sole occupant: re-scope in place, rebuilding the key order so
                # `matcher` still serialises ahead of `hooks`. Any other keys the
                # group carries are preserved.
                rest = {k: v for k, v in existing_group.items() if k != "matcher"}
                existing_group.clear()
                existing_group.update(_hook_group(matcher, rest.pop("hooks", [])))
                existing_group.update(rest)
        hooks[event_name] = group_list
        settings["hooks"] = hooks
        local_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        print(f"  re-wired {event_name} hook in {local_path} ({reason}): "
              f"{interpreter} {script_str}")
        return

    entry: dict = {
        "type": "command",
        "command": interpreter,
        "args": [script_str],
    }
    if use_async:
        entry["async"] = True
    block = _hook_group(matcher, [entry])

    if dry_run:
        suffix = " (async)" if use_async else ""
        scope = "" if matcher is None else f" [matcher: {matcher}]"
        print(f"  would wire {event_name} hook into {local_path}:")
        print(f"      {interpreter} {script_str}{suffix}{scope}")
        return

    group_list.append(block)
    hooks[event_name] = group_list
    settings["hooks"] = hooks
    local_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"  wired {event_name} hook into {local_path}: {interpreter} {script_str}")


def wire_stop_hook(config_dir: Path, *, dry_run: bool) -> None:
    """Wire the global Stop hook (``record_stop.py``, async) into ~/.claude/settings.json."""
    _wire_command_hook(
        config_dir,
        event_name="Stop",
        script_name="record_stop.py",
        use_async=True,
        dry_run=dry_run,
    )


def wire_sessionstart_hook(config_dir: Path, *, dry_run: bool) -> None:
    """Wire the global SessionStart hook (``harvest_nudge.py``) into ~/.claude/settings.json.

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


def do_relink(stamp: str, dry_run: bool, ledger: dict, parts: frozenset[str], claudemd_choice: str) -> int:
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
    install_settings(parts, dry_run)
    install_claude_md(claudemd_choice, dry_run)
    if parts and (dry_run or hooks_linked):
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

    adopt_existing_config.main()


def do_default(dry_run: bool, ledger: dict, parts: frozenset[str], claudemd_choice: str) -> int:
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
        install_settings(parts, dry_run)
        install_claude_md(claudemd_choice, dry_run)
        # Hooks live in ~/.claude/settings.json now; wire them only if the hooks/
        # symlink is in place and the user didn't skip settings integration.
        if parts and hooks_linked:
            wire_stop_hook(CLAUDE_DIR, dry_run=dry_run)
            wire_sessionstart_hook(CLAUDE_DIR, dry_run=dry_run)
        elif parts:
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
    ap.add_argument("--settings", default=None, metavar="full|minimal|skip|part,part",
                    help="settings.json integration: keyword (full|minimal|skip) or a "
                         "comma-list of parts (agent,permissions,plugins) "
                         "(prompted if omitted; required when non-interactive)")
    ap.add_argument("--claude-md", choices=CLAUDEMD_CHOICES, default=None,
                    help="CLAUDE.md integration: import | replace | skip "
                         "(prompted if omitted; required when non-interactive)")
    args = ap.parse_args(argv)

    print(f"Repo:   {REPO_DIR}")
    print(f"Target: {CLAUDE_DIR}")
    if args.dry_run:
        print("(dry run — no changes will be made)")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ledger = parse_ledger()

    try:
        parts = resolve_settings_choice(args.settings)
    except ValueError as e:
        print(f"error: --settings: {e}", file=sys.stderr)
        raise SystemExit(2)
    claudemd_choice = resolve_claudemd_choice(args.claude_md)
    if args.relink:
        return do_relink(stamp, args.dry_run, ledger, parts, claudemd_choice)
    return do_default(args.dry_run, ledger, parts, claudemd_choice)


if __name__ == "__main__":
    sys.exit(main())
