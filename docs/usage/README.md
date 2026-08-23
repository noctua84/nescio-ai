# Token-usage toolkit

Small, disposable scripts used to work out where a Claude Code token budget
actually goes. They parse local session transcripts, aggregate the spend, and
render it as a static report. The findings from one run of this drove a round
of agent/prompt cleanup in this repo.

## What this measures

`~/.claude/projects/*/*.jsonl` are the session transcripts Claude Code writes
locally — one line per event (assistant turns, tool calls, tool results).
Each assistant turn carries a token-usage record (input, output, cache write,
cache read, thinking tokens). These scripts dedupe those records by
`requestId` and aggregate them by day, by project, by model, and by position
within a session, then apply a weighting that approximates API-relative cost
(cache reads &times;0.1, cache writes &times;1.25, output &times;5) so the
totals reflect spend, not just raw token count.

- `scan.py` — first-pass aggregate scan; prints a summary to stdout.
- `deep.py` — deeper scan; writes `data.json`.
- `build.py` — renders `dashboard.html` from a set of figures (currently
  hardcoded from a specific scan — re-derive them by hand from a fresh
  `data.json` if you want the dashboard to reflect a new run).
- `data.json` — the aggregate scan output consumed for analysis.
- `dashboard.html` — the rendered report.

## Regenerating

```
python deep.py    # scans ~/.claude/projects, writes data.json
python build.py   # renders dashboard.html
```

Run both from this directory (or use `deep.py -o <path>` to write elsewhere).

## Anonymization

`data.json` groups spend by project directory, and the raw project key is a
slug derived from the transcript's local folder path (e.g.
`C--Users-<you>-code-some-app`) — it embeds your OS username and
every local repo name touched. **`deep.py` anonymizes this by default**,
replacing each slug with a stable pseudonym (`project-01`, `project-02`, ...)
assigned in descending order of weighted spend, so the relative shape of the
data survives without exposing what any of it actually is.

Pass `--raw` to keep the real slugs for local-only inspection. **Output
produced with `--raw` must never be committed** — it identifies your machine
and your private project names. The committed `data.json` in this directory
was produced without `--raw`; before committing a refreshed version, re-run
the acceptance checks described in the repo's contribution docs (grep for
your own username/paths, then `python scripts/scrub_check.py`).

## A note on stability

The transcript JSONL format is internal to Claude Code and not a documented,
versioned API. Field names, event shapes, and even which fields carry token
usage have changed before and can change again on any Claude Code release.
Treat these scripts as disposable: if a new release breaks them, the fix is
to re-inspect a sample transcript and adjust the parsing, not to assume the
old field names still apply.
