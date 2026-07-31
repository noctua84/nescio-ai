"""Deep-merge helper for settings JSON.

`deep_merge(base, overlay)` overlays `overlay` onto `base` without clobbering
values already present in `base`. Used by ``install.py`` to fold the framework's
settings keys into a user's existing ``~/.claude/settings.json`` while preserving
anything the user already set.
"""

from __future__ import annotations


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
