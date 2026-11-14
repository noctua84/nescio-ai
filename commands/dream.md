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

   It prints where the proposal landed and writes a JSON sidecar next to it
   with every signal seen, for step 2. `--repo PATH` reviews another repo;
   `--min-sessions N` raises or lowers what counts as recurring (default 2
   distinct sessions).

2. **Check earlier lessons first:**

   ```bash
   python scripts/dream.py --compare
   ```

   For each note linked in an earlier dream (step 4), this compares how often
   its signal showed up in the dreams before the note landed and after it.
   `--ledger PATH` points at the brain's `memory/learning-log.md` when you run
   from a checkout that has none. In that case the link date stands in and the
   output says so. Act on the verdict:
   - `working`, `too early`, `no baseline`: nothing to do.
   - `unclear`: mention it, take no action.
   - `ineffective` (the signal did not drop): list the note as a **removal or
     rewrite candidate** in your report. Retire or supersede it only through
     `/harvest-memory` and only on user approval, as with any memory change.
     One verdict is not proof (usage mix shifts), so say how many sessions it
     rests on.

3. **Read the proposal.** It lists recurring patterns (tier escalations,
   repeated tool errors, user corrections, reverts, inverted test pins), agent
   verdict counts, items to confirm, and candidate follow-ups. Treat a pattern
   as a lead: open the relevant session if the proposal alone does not say why.

4. **Decide each recurring pattern**, one of:
   - **(a) Memory note.** Draft a nomination for the harvest pipeline with
     source `empirical`, show it to the user, and only on approval feed it
     through `/harvest-memory` (`promote_learnings.py`). Never write `memory/`
     directly.

     After it is promoted, **link the note to the signal** that prompted it,
     so later dreams can tell whether it worked. Take the note's 12-hex hash
     from its new ledger line in `memory/learning-log.md`
     (`- <date> | <target> | <hash12> | promoted: <name>`). Take the signal id
     from the `[sig <id>]` at the end of the pattern's line in the proposal.

     ```bash
     python scripts/dream.py --link <hash12> <sig-id>
     ```

     Link only notes that answer one recurring signal. A note that is not
     about a signal, or a pattern you dropped, gets no link. Linking the same
     pair again changes nothing.
   - **(b) Agent, skill or `CLAUDE.md` change.** Write it as a proposed diff in
     the conversation only. Apply nothing without explicit user approval.
   - **(c) Drop.** One-off incidents, noise, and anything you cannot explain.

5. **Report** what you proposed under (a) and (b) and what you dropped, in a
   few lines, together with the notes you linked and any `ineffective` notes
   from step 2. The watermark was already advanced by the extractor unless you
   passed `--no-stamp`.

## Privacy gate

Transcripts and the proposal are private. Before any change that is bound for
the public repo, make it generic: no private repository names, absolute paths,
usernames, hostnames, or quoted user messages. Excerpts in the proposal are
redacted and truncated, but you remain the last check.
