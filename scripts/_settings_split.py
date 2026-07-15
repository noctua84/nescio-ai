"""Rule-based split of a settings.json into portable vs machine-local keys.

Used by install.py when an existing (real, non-symlink) ~/.claude/settings.json
is about to be replaced by a symlink into this repo: the *unambiguously*
machine-specific keys are rescued into settings.local.json (gitignored) so they
survive the swap, while the portable/allow-list/CLAUDE.md merge stays a manual
judgment step (the adopt "copy-and-catalogue" guardrail — this module never
decides which `permissions.allow` rules are worth keeping).

Only keys with a machine-specific *signature* are moved:
  - `statusLine`                      — a command/script path that lives on this box
  - `permissions.additionalDirectories` — absolute filesystem paths
  - `extraKnownMarketplaces[*]` whose `source.source == "directory"` — a local path
  - `enabledPlugins["<plugin>@<mkt>"]` where `<mkt>` is one of those directory
    marketplaces (the plugin can't resolve without its local-path marketplace)

A github-sourced marketplace (and plugins backed by it) is portable and is left
alone. Everything else — `permissions.allow`, `model`, `effortLevel`, project
`WebFetch` domains, etc. — is left in place for manual review.
"""

from __future__ import annotations


def directory_marketplaces(settings: dict) -> set[str]:
    """Names of extraKnownMarketplaces backed by a local `directory` source."""
    out: set[str] = set()
    for name, spec in (settings.get("extraKnownMarketplaces") or {}).items():
        source = ((spec or {}).get("source") or {})
        if source.get("source") == "directory":
            out.add(name)
    return out


def classify_machine_local(settings: dict) -> dict:
    """Return the subset of `settings` that is unambiguously machine-local.

    The returned dict is shaped like a settings.local.json fragment, ready to be
    deep-merged into the existing local file. `settings` is not mutated.
    """
    machine: dict = {}
    dir_mkts = directory_marketplaces(settings)

    if "statusLine" in settings:
        machine["statusLine"] = settings["statusLine"]

    add_dirs = (settings.get("permissions") or {}).get("additionalDirectories")
    if add_dirs:
        machine.setdefault("permissions", {})["additionalDirectories"] = add_dirs

    local_mkts = {
        name: spec
        for name, spec in (settings.get("extraKnownMarketplaces") or {}).items()
        if name in dir_mkts
    }
    if local_mkts:
        machine["extraKnownMarketplaces"] = local_mkts

    local_plugins = {
        plugin: enabled
        for plugin, enabled in (settings.get("enabledPlugins") or {}).items()
        if "@" in plugin and plugin.split("@", 1)[1] in dir_mkts
    }
    if local_plugins:
        machine["enabledPlugins"] = local_plugins

    return machine


def deep_merge(base: dict, overlay: dict) -> dict:
    """Merge `overlay` into `base` without clobbering existing `base` values.

    - nested dicts merge recursively
    - lists union (order-preserving, de-duplicated)
    - scalars: `base` wins when the key already exists (the user's explicit local
      value is authoritative); otherwise `overlay` fills it in

    Returns a new dict; neither argument is mutated.
    """
    result = dict(base)
    for key, ov in overlay.items():
        if key not in result:
            result[key] = ov
            continue
        bv = result[key]
        if isinstance(bv, dict) and isinstance(ov, dict):
            result[key] = deep_merge(bv, ov)
        elif isinstance(bv, list) and isinstance(ov, list):
            merged = list(bv)
            for item in ov:
                if item not in merged:
                    merged.append(item)
            result[key] = merged
        else:
            result[key] = bv  # keep base — don't clobber the user's local value
    return result


def leftover_top_level_keys(settings: dict, machine: dict) -> list[str]:
    """Top-level keys that were NOT fully moved to the machine-local fragment.

    Reporting aid: these stay behind in the backed-up real file and may need a
    manual merge decision (notably `permissions` with its `allow` list).
    """
    out: list[str] = []
    for key in settings:
        if key not in machine:
            out.append(key)
        elif key == "permissions":
            # additionalDirectories may have moved but `allow`/others remain
            remaining = {k for k in settings["permissions"] if k != "additionalDirectories"}
            if remaining:
                out.append("permissions")
    return out
