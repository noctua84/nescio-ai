---
name: overview
description: EXAMPLE repo memory note — copy the pattern into memory/repo/<your-repo>/ and delete EXAMPLE/
metadata:
  type: reference
---

> **This is an example.** It shows the shape of a per-repo memory note. Copy the
> pattern into `memory/repo/<your-repo>/` and delete the `EXAMPLE/` folder.

# <repo-name> — overview

What this repo is, its stack, and the handful of facts the crew needs before
touching it. Keep it **durable** (things that rarely change); regenerate volatile
lists (file inventories, full route tables) with `ls`/`grep` rather than freezing
them here where they rot.

- **Stack:** e.g. TypeScript + Node, Vite, Vitest.
- **Entry points:** where execution starts.
- **Conventions:** the non-obvious rules a newcomer would trip on.
- **Gotchas:** the traps learned the hard way.
