---
name: dream
description: Review past session transcripts offline, find recurring mistakes and workflows that worked, and turn them into reviewed memory nominations or held prompt-tweak suggestions.
user-invocable: true
---

# /dream

An offline review pass between sessions. A deterministic extractor
(`scripts/dream.py`) reads this repo's past transcripts and writes a
**proposal**; you then decide, item by item, what is worth keeping. Nothing is
applied automatically — the proposal is a reading aid, not a source of truth.

The extractor makes no model call and writes only under
`<config>/dreams/<repo_key>/`, which is machine-local and never synced.

## Steps

1. **Run the extractor** from the brain or from this checkout:

   ```bash
   python scripts/dream.py                 # since the last run, else 14 days
   python scripts/dream.py --since 2026-01-01 --max-sessions 30
   python scripts/dream.py --no-stamp      # a dry run: do not advance the watermark
   ```

   It prints where the proposal landed. `--repo PATH` reviews another repo;
   `--min-sessions N` raises or lowers what counts as recurring (default 2
   distinct sessions).

2. **Read the proposal.** It lists recurring patterns (tier escalations,
   repeated tool errors, user corrections, reverts, inverted test pins), agent
   verdict counts, items to confirm, and candidate follow-ups. Treat a pattern
   as a lead: open the relevant session if the proposal alone does not say why.

3. **Decide each recurring pattern**, one of:
   - **(a) Memory note.** Draft a nomination for the harvest pipeline with
     source `empirical`, show it to the user, and only on approval feed it
     through `/harvest-memory` (`promote_learnings.py`). Never write `memory/`
     directly.
   - **(b) Agent, skill or `CLAUDE.md` change.** Write it as a proposed diff in
     the conversation only. Apply nothing without explicit user approval.
   - **(c) Drop.** One-off incidents, noise, and anything you cannot explain.

4. **Report** what you proposed under (a) and (b) and what you dropped, in a
   few lines. The watermark was already advanced by the extractor unless you
   passed `--no-stamp`.

## Privacy gate

Transcripts and the proposal are private. Before any change that is bound for
the public repo, make it generic: no private repository names, absolute paths,
usernames, hostnames, or quoted user messages. Excerpts in the proposal are
redacted and truncated, but you remain the last check.
