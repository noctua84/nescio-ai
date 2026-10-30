# Hooks

Two hooks, both wired into `~/.claude/settings.json` by `install.py`. Both are
observational — they describe what happened, never what should happen next —
and neither blocks a turn or judges it. This page describes what each one
writes, how long it stays, and how to turn it off.

## Stop — `record_stop.py`

Fires once per turn, asynchronously, as the Stop event. It appends one JSONL
line to `<$CLAUDE_CONFIG_DIR or ~/.claude>/learning-trail/<repo_key>.jsonl` and
exits — always, and fast. This file is machine-local: it is never synced and
never committed. It is the learning loop's raw, unreviewed trail; see
[the learning loop on the homepage](index.md#the-learning-loop) for how
`/harvest-memory` later distils it into `memory/`.

### What may land in the trail

Each record carries a timestamp, the session id, a `prompt_id`, the git
worktree and repository paths, the current git branch, the transcript path —
stored verbatim as a pointer and **never opened** by this hook — and a
one-line, truncated preview of the **last assistant message**. That preview is
of the assistant's own reply, not the user's prompt, and no outcome verdict
(pass/fail, clean/flagged) is ever recorded; deriving one honestly would mean
reading the full transcript, which this hook deliberately never does.

### Redaction is best-effort

The preview is checked against a fixed list of known secret shapes — OpenAI,
Stripe, GitHub, AWS, Google, npm and Slack tokens, JWTs, PEM private-key
headers, and URL-embedded credentials. On any hit, the **whole preview** is
blanked to `[redacted]` rather than partially masked; that is a deliberately
coarse trade against trying to surgically excise just the matched substring.
Matching runs before truncation, so a secret that would otherwise straddle the
cut is still caught. A secret in a shape this list does not know is **kept as
written** — this is a known-patterns filter, not a guarantee that no secret
ever reaches the trail.

### Retention is a floor, not a cap

Pruning only runs opportunistically, once a trail file grows past a size
threshold — it is never scheduled, and it never runs on every turn. When it
does run, a record is dropped only if it is **both** older than 14 days **and**
already covered by the repo's harvest watermark. Un-harvested records are kept
**regardless of age**, bounded only by an absolute ceiling on total record
count so that a trail that is never harvested still cannot grow without
bound. Malformed lines, and records whose timestamp cannot be parsed, are
always dropped. In short: nothing is guaranteed to disappear after 14 days —
that number is the earliest a record becomes eligible for pruning, not a
promise that it will be gone by then.

### Deleting or disabling it

The trail is one machine-local file plus a watermark sibling; delete or
truncate `<config>/learning-trail/<repo_key>.jsonl` and
`<config>/learning-trail/<repo_key>.watermark` directly — nothing else holds a
copy. To stop the hook firing at all, remove the `Stop` entry that
`install.py` wrote into `~/.claude/settings.json`.

## SessionStart — `harvest_nudge.py`

Fires synchronously at session start (on `startup`/`resume`, never on
`clear`/`compact`), and whatever it prints to stdout is injected as session
context. It can surface up to three independent things:

- **An unfinished harvest.** If a previous `/harvest-memory` run finished
  without stamping its watermark, a `.harvest-pending-<repo_key>` marker is
  left behind, and this hook reports it. This takes priority over the count
  nudge below for the same repo.
- **Un-harvested records.** If the number of trail records newer than the
  repo's watermark reaches `CLAUDE_HARVEST_NUDGE_THRESHOLD` (default `20`),
  the hook prints a one-line reminder to run `/harvest-memory`. Set the
  environment variable to change the threshold.
- **A fired or near-fired ADR 0002 memory trigger.** The hook shells out to
  `scripts/check_memory_triggers.py` against the current repo's `memory/` and
  prints at most two lines naming any trigger that has fired, or — only when
  none has — any trigger nearing its threshold.

Every one of these degrades to silence on its own failure (a missing marker,
an unreadable trail, a trigger-script timeout) rather than raising or
suppressing the others.

### Tuning and disabling it

Set `CLAUDE_HARVEST_NUDGE_THRESHOLD` in the environment to change the
un-harvested-record threshold; it defaults to `20` if unset or unparseable. To
stop the hook firing at all, remove the `SessionStart` entry that
`install.py` wrote into `~/.claude/settings.json`.

## Where the data lives

| What | Path | Synced? | Retention |
|---|---|---|---|
| Learning trail | `<$CLAUDE_CONFIG_DIR or ~/.claude>/learning-trail/<repo_key>.jsonl` | Never | Floor of 14 days; un-harvested records survive longer, up to an absolute record cap |
| Harvest watermark | `<config>/learning-trail/<repo_key>.watermark` | Never | Until the next harvest stamps it |
| Unfinished-harvest marker | `<config>/learning-trail/.harvest-pending-<repo_key>` | Never | Until `scripts/mark_harvested.py` or `/harvest-memory` succeeds |

## Source

- [`hooks/record_stop.py`](https://github.com/noctua84/nescio-ai/blob/main/hooks/record_stop.py)
- [`hooks/harvest_nudge.py`](https://github.com/noctua84/nescio-ai/blob/main/hooks/harvest_nudge.py)
- [`install.py`](https://github.com/noctua84/nescio-ai/blob/main/install.py) — wires both hooks into `~/.claude/settings.json`
- [Commands](commands.md#harvest-memory) — the `/harvest-memory` command that reads this trail
