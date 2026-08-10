# settings.json per-part selection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `install.py` adopt a chosen subset of the framework's `settings.json` parts (`agent` / `permissions` / `plugins`) instead of only all-or-`agent`-or-nothing.

**Architecture:** Introduce a `PART_KEYS` map and a pure `parse_settings_value()` parser. `resolve_settings_choice()` returns a `frozenset[str]` of parts (empty = skip). `install_settings(parts, …)` builds the overlay from just those parts' keys and runs the existing `deep_merge` (unchanged). CLI keywords `full|minimal|skip` are preserved as aliases. Hook-wiring gates on "any part selected."

**Tech Stack:** Python 3.13+, standard library only. Tests: `unittest` (run via `python -m unittest discover -s tests -p "test_*.py"`).

## Global Constraints
- **Standard library only** — `install.py` has zero dependencies; keep it that way.
- **Python 3.13+** (`requires-python = ">=3.13"`).
- **Backward-compatible:** `--settings full|minimal|skip` must behave byte-identically to today (`full` = all parts, `minimal` = `agent`, `skip` = none).
- **Idempotent** and **dry-run-able**: every write path prints under `--dry-run` and changes nothing; re-running yields an identical file.
- **Non-destructive:** the existing `deep_merge` is reused untouched; the user's other keys and allow-list are preserved.
- **No silent default in non-interactive mode:** a run with no TTY and no `--settings` still exits 2 with help.
- Scope is **A1 only**: no CLAUDE.md changes, no MCP part.

---

### Task 1: Parts map + pure `parse_settings_value` parser

**Files:**
- Modify: `install.py` (add near `SETTINGS_CHOICES`, ~line 67)
- Test: `tests/test_install.py`

**Interfaces:**
- Produces: `PART_KEYS: dict[str, tuple[str, ...]]`; `SETTINGS_KEYWORDS: dict[str, frozenset[str]]`; `parse_settings_value(value: str) -> frozenset[str]` (raises `ValueError` on an unknown token or a keyword mixed with parts; empty/whitespace → empty set).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_install.py  (new class; ROOT/sys.path setup already present in this file)
import install  # noqa: E402

class ParseSettingsValueTest(unittest.TestCase):
    def test_keywords(self):
        self.assertEqual(install.parse_settings_value("full"),
                         frozenset({"agent", "permissions", "plugins"}))
        self.assertEqual(install.parse_settings_value("minimal"), frozenset({"agent"}))
        self.assertEqual(install.parse_settings_value("skip"), frozenset())

    def test_part_list(self):
        self.assertEqual(install.parse_settings_value("agent,plugins"),
                         frozenset({"agent", "plugins"}))
        self.assertEqual(install.parse_settings_value(" agent , plugins "),
                         frozenset({"agent", "plugins"}))
        self.assertEqual(install.parse_settings_value("plugins,plugins"),
                         frozenset({"plugins"}))

    def test_empty_is_skip(self):
        self.assertEqual(install.parse_settings_value(""), frozenset())
        self.assertEqual(install.parse_settings_value("  "), frozenset())

    def test_unknown_token_raises(self):
        with self.assertRaises(ValueError):
            install.parse_settings_value("bogus")

    def test_keyword_mixed_with_parts_raises(self):
        with self.assertRaises(ValueError):
            install.parse_settings_value("full,agent")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_install.ParseSettingsValueTest -v`
Expected: FAIL/ERROR — `module 'install' has no attribute 'parse_settings_value'`.

- [ ] **Step 3: Implement the parser**

Add after the existing `SETTINGS_CHOICES = ("full", "minimal", "skip")` line (~67):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_install.ParseSettingsValueTest -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add install.py tests/test_install.py
git commit -m "feat(install): add PART_KEYS + parse_settings_value parser"
```

---

### Task 2: `resolve_settings_choice` returns a parts set (+ interactive `custom`)

**Files:**
- Modify: `install.py` — `resolve_settings_choice` (159-181)
- Test: `tests/test_install.py`

**Interfaces:**
- Consumes: `parse_settings_value`, `SETTINGS_KEYWORDS` (Task 1).
- Produces: `resolve_settings_choice(cli_value: str | None) -> frozenset[str]` — returns the selected parts; propagates `ValueError` from a bad CLI value; `sys.exit(2)` when non-interactive with no `--settings`. `_prompt_custom_parts() -> frozenset[str]` (per-part `[Y/n]`, default Y).

- [ ] **Step 1: Write the failing tests**

```python
class ResolveSettingsChoiceTest(unittest.TestCase):
    def test_cli_keyword(self):
        self.assertEqual(install.resolve_settings_choice("full"),
                         frozenset({"agent", "permissions", "plugins"}))
        self.assertEqual(install.resolve_settings_choice("skip"), frozenset())

    def test_cli_part_list(self):
        self.assertEqual(install.resolve_settings_choice("agent,plugins"),
                         frozenset({"agent", "plugins"}))

    def test_cli_bad_value_raises(self):
        with self.assertRaises(ValueError):
            install.resolve_settings_choice("nope")

    def test_interactive_default_full(self, ):
        # blank input at the top prompt -> full (all three)
        with mock.patch("builtins.input", side_effect=[""]), \
             mock.patch("sys.stdin.isatty", return_value=True):
            self.assertEqual(install.resolve_settings_choice(None),
                             frozenset({"agent", "permissions", "plugins"}))

    def test_interactive_custom(self):
        # custom -> agent yes (blank), permissions no, plugins yes
        with mock.patch("builtins.input", side_effect=["custom", "", "n", "y"]), \
             mock.patch("sys.stdin.isatty", return_value=True):
            self.assertEqual(install.resolve_settings_choice(None),
                             frozenset({"agent", "plugins"}))
```
(Add `from unittest import mock` at the top of the test file if not present.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_install.ResolveSettingsChoiceTest -v`
Expected: FAIL — current `resolve_settings_choice` returns a str / has no `custom`.

- [ ] **Step 3: Rewrite `resolve_settings_choice`**

Replace the body of `resolve_settings_choice` (159-181) with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_install.ResolveSettingsChoiceTest -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add install.py tests/test_install.py
git commit -m "feat(install): resolve_settings_choice returns parts set + custom flow"
```

---

### Task 3: `install_settings(parts, dry_run)` builds the overlay from selected parts

**Files:**
- Modify: `install.py` — `install_settings` (184-214)
- Test: `tests/test_install.py`

**Interfaces:**
- Consumes: `PART_KEYS` (Task 1); resolved parts set (Task 2); existing `deep_merge`, `load_json`, `CLAUDE_DIR`, `REPO_DIR`.
- Produces: `install_settings(parts: frozenset[str], dry_run: bool) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
class InstallSettingsPartsTest(unittest.TestCase):
    def _setup(self, tmp):
        # Fake framework settings.json with all three parts.
        fw = {"agent": "orchestrator",
              "permissions": {"allow": ["Bash(git status:*)"]},
              "enabledPlugins": {"p@x": True}}
        repo = Path(tmp) / "repo"; (repo).mkdir()
        (repo / "settings.json").write_text(json.dumps(fw), encoding="utf-8")
        claude = Path(tmp) / "claude"; claude.mkdir()
        return repo, claude

    def test_only_selected_parts_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, claude = self._setup(tmp)
            with mock.patch.object(install, "REPO_DIR", repo), \
                 mock.patch.object(install, "CLAUDE_DIR", claude):
                install.install_settings(frozenset({"agent", "plugins"}), dry_run=False)
                out = json.loads((claude / "settings.json").read_text())
            self.assertEqual(out.get("agent"), "orchestrator")
            self.assertIn("enabledPlugins", out)
            self.assertNotIn("permissions", out)  # not selected

    def test_unselected_permissions_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, claude = self._setup(tmp)
            (claude / "settings.json").write_text(
                json.dumps({"permissions": {"allow": ["Bash(mine:*)"]}, "mykey": 1}),
                encoding="utf-8")
            with mock.patch.object(install, "REPO_DIR", repo), \
                 mock.patch.object(install, "CLAUDE_DIR", claude):
                install.install_settings(frozenset({"agent"}), dry_run=False)
                out = json.loads((claude / "settings.json").read_text())
            self.assertEqual(out["permissions"]["allow"], ["Bash(mine:*)"])  # untouched
            self.assertEqual(out["mykey"], 1)  # user key preserved
            self.assertEqual(out["agent"], "orchestrator")

    def test_empty_parts_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, claude = self._setup(tmp)
            with mock.patch.object(install, "REPO_DIR", repo), \
                 mock.patch.object(install, "CLAUDE_DIR", claude):
                install.install_settings(frozenset(), dry_run=False)
            self.assertFalse((claude / "settings.json").exists())

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, claude = self._setup(tmp)
            with mock.patch.object(install, "REPO_DIR", repo), \
                 mock.patch.object(install, "CLAUDE_DIR", claude):
                install.install_settings(frozenset({"agent"}), dry_run=True)
            self.assertFalse((claude / "settings.json").exists())
```
(Ensure `import json, tempfile` and `from pathlib import Path` are available in the test file — they are used elsewhere in it.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_install.InstallSettingsPartsTest -v`
Expected: FAIL — `install_settings` still takes a `choice` string.

- [ ] **Step 3: Rewrite `install_settings`**

Replace the signature and body (184-214). Keep the symlink-unlink and docstring intent:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_install.InstallSettingsPartsTest -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add install.py tests/test_install.py
git commit -m "feat(install): install_settings builds overlay from selected parts"
```

---

### Task 4: Wire it end-to-end (argparse, main, call sites, hook-gating)

**Files:**
- Modify: `install.py` — argparse `--settings` (~638), `main()` (~654), `do_default` (569, call at 601, gates at 605/608), `do_relink` (486, call at 543, gate at 545). Remove `SETTINGS_CHOICES` usages superseded by `SETTINGS_KEYWORDS`.
- Test: `tests/test_install.py` (+ update any existing test in `tests/test_install.py`/`tests/test_install_hooks.py` that calls `install_settings`/`resolve_settings_choice` with the old string API).

**Interfaces:**
- Consumes: `resolve_settings_choice` (Task 2), `install_settings` (Task 3).
- Produces: `--settings` accepts a free string; `main()` converts a bad value to exit 2; `do_default`/`do_relink` take `parts: frozenset[str]` and gate hooks on `if parts:`.

- [ ] **Step 1: Write the failing test (end-to-end parse → write; bad value → exit 2)**

```python
class SettingsCliIntegrationTest(unittest.TestCase):
    def test_part_list_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = {"agent": "orchestrator",
                  "permissions": {"allow": ["Bash(x:*)"]},
                  "enabledPlugins": {"p@x": True}}
            repo = Path(tmp) / "repo"; repo.mkdir()
            (repo / "settings.json").write_text(json.dumps(fw), encoding="utf-8")
            claude = Path(tmp) / "claude"; claude.mkdir()
            with mock.patch.object(install, "REPO_DIR", repo), \
                 mock.patch.object(install, "CLAUDE_DIR", claude):
                parts = install.resolve_settings_choice("agent,plugins")
                install.install_settings(parts, dry_run=False)
                out = json.loads((claude / "settings.json").read_text())
            self.assertEqual(set(out), {"agent", "enabledPlugins"})

    def test_bad_settings_value_exits_2(self):
        # main() must convert a ValueError from --settings into exit code 2.
        with mock.patch.object(sys, "argv", ["install.py", "--settings", "bogus",
                                             "--claude-md", "skip", "--dry-run"]):
            with self.assertRaises(SystemExit) as cm:
                install.main()
            self.assertEqual(cm.exception.code, 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_install.SettingsCliIntegrationTest -v`
Expected: FAIL — argparse still restricts `--settings` to `choices`; `main()` doesn't catch `ValueError`.

- [ ] **Step 3: Apply the wiring changes**

1. argparse (~638): drop `choices=SETTINGS_CHOICES`, accept a free string:
```python
ap.add_argument("--settings", default=None, metavar="full|minimal|skip|part,part",
                help="settings.json integration: keyword (full|minimal|skip) or a "
                     "comma-list of parts (agent,permissions,plugins)")
```
2. `main()` (~654): wrap resolution to convert a bad value to exit 2:
```python
    try:
        parts = resolve_settings_choice(args.settings)
    except ValueError as e:
        print(f"error: --settings: {e}", file=sys.stderr)
        raise SystemExit(2)
```
   Pass `parts` where `choice` was passed to `do_default`/`do_relink`.
3. `do_default` / `do_relink`: rename the `choice: str` parameter to `parts: frozenset[str]`; change `install_settings(choice, dry_run)` → `install_settings(parts, dry_run)`; change every hook-gate `if choice != "skip":` → `if parts:` (do_relink ~545; do_default ~605 and ~608). Hooks wire whenever any part is selected (preserves full/minimal wiring; skip stays no-hooks).
4. Remove the now-unused `SETTINGS_CHOICES` constant if nothing else references it (grep first: `grep -n SETTINGS_CHOICES install.py`); otherwise leave it. `SETTINGS_KEYWORDS`/`PART_KEYS` are the source of truth.

- [ ] **Step 4: Run the full suite to verify green (and fix any old-API test callers)**

Run: `python -m unittest discover -s tests -p "test_*.py" 2>&1 | grep -E "^(OK|FAILED|Ran )|ERROR:|FAIL:"`
Expected: OK. If any pre-existing test calls `install_settings("full", …)` or expects a str from `resolve_settings_choice`, update it to the parts API (e.g. `install_settings(frozenset({"agent"}), …)`).

- [ ] **Step 5: Commit**

```bash
git add install.py tests/test_install.py tests/test_install_hooks.py
git commit -m "feat(install): wire per-part --settings end-to-end + gate hooks on any part"
```

---

### Task 5: Document `--settings` parts in the README

**Files:**
- Modify: `README.md` — the `settings.json` bullet block (~61-69) and the unattended note (~85-86).

**Interfaces:** none (docs only).

- [ ] **Step 1: Update the README**

In the `**settings.json** — `full | minimal | skip`:` block, add the parts syntax and an example. Replace the intro line and add a line after the three bullets:

```markdown
**`settings.json`** — a keyword (`full | minimal | skip`) **or a comma-list of parts** (`agent,permissions,plugins`):

- **full** — the whole `settings.json` (agent + permissions + plugins) + hooks
- **minimal** — only `agent: orchestrator` (+ the learning-loop hooks)
- **skip** — change nothing
- **parts** — adopt a subset, e.g. `--settings agent,plugins` keeps your own permissions while adding the entrypoint and plugins (deep-merged; your other keys and allow-list are preserved)
```

In the unattended-install sentence (~85-86), change
`Pass \`--settings full|minimal|skip\``
to
`Pass \`--settings full|minimal|skip|<parts>\``.

- [ ] **Step 2: Verify the docs render / match behavior**

Run: `grep -n "agent,plugins" README.md`
Expected: the example line is present. Eyeball the block for consistency with the installed help text.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document --settings per-part selection"
```

---

## Self-Review

**Spec coverage:** parts selection (Tasks 1–3), keyword back-compat (Task 1 tests + preserved in `SETTINGS_KEYWORDS`), interactive `custom` default-Y (Task 2), overlay-from-parts + deep_merge preserved (Task 3), empty=skip (Tasks 1–3), CLI free-string + exit-2 on bad value (Task 4), non-interactive still exits 2 (Task 2), hooks gating mapped to non-empty parts (Task 4), README (Task 5). MCP-as-a-part and CLAUDE.md/A2 are explicitly out of scope. ✅ no gaps.

**Placeholder scan:** every step has concrete code/commands; no TBD/TODO. ✅

**Type consistency:** `parse_settings_value` / `resolve_settings_choice` / `install_settings` all use `frozenset[str]` of parts; `PART_KEYS` keys (`agent`/`permissions`/`plugins`) match `SETTINGS_KEYWORDS` and the parser tokens; `install_settings(parts, dry_run)` matches the call sites updated in Task 4. ✅

**One decision to surface at review:** hook-wiring is gated on "any part selected" (`if parts:`). This preserves `full`/`minimal` → hooks and `skip` → no hooks exactly, but means a custom selection of, say, only `permissions` also wires the learning-loop hooks. If hooks should instead be their own independent toggle, that's a small follow-up — flagged, not silently decided.
