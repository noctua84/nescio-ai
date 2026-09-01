# Redraw the crew diagram for the full 17-agent roster

## Objective
The crew diagram draws 10 of 17 agents and its caption claims "nine specialists".
`docs_site/gen_catalog.py` independently claims 11 agents in 5 buckets, so
`docs_site/docs/agents.md` is stale and `docs_site` tests are RED on this branch.
Make one true roster reach both surfaces, and add a detector so it cannot drift again.

## Roster (17 = orchestrator + 16 specialists)
| Bucket | Agents |
|---|---|
| Coordinate | orchestrator |
| Discover | scout, explore, librarian, vision |
| Plan and challenge | planner, validator, advisor, critic |
| Build | builder, builder-standard, builder-simple |
| Document | doc-researcher, doc-writer |
| Verify | test-writer, qa-guard, reviewer |

## Task 1 — catalog
`docs_site/gen_catalog.py:75` AGENT_GROUPS -> the table above (adds a `Document`
bucket between Build and Verify; lifecycle order comment updated to match).
Regenerate `docs_site/docs/agents.md` via gen_catalog.py. Do not hand-edit it.

## Task 2 — diagram
`brand/make_diagrams.py` `diagram_crew()`: 6 groups, headings = the six bucket
names above (upper-cased, as today). Layout 3 columns x 2 bands. Caption count
derived from the groups list, not hardcoded. Regenerate + copy tokenised source.

## Task 3 — detector
`docs_site/test_site_content.py`: assert the diagram's roster == agents/*.md
minus orchestrator, and its headings == gen_catalog AGENT_GROUPS titles minus
Coordinate.

## Out of scope (reported, not done)
- CI runs only `tests/`; docs_site/ and brand/ never execute. Spawned task.
- docs/design/docs-site-mockup.html: frozen point-in-time snapshot (its own
  line 311 says so). Left untouched, deliberately.

## Verify
PYTHONPATH=scripts py -3.13 -m unittest discover -s tests
py -3.13 -m unittest discover -s docs_site
