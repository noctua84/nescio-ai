#!/usr/bin/env bash
# Makes the review always run with the base branch's Claude configuration: each
# listed Claude configuration path is dropped from the checked-out PR head and,
# where the base branch has it, restored from there.
#
# Reads (env): BASE_REF (the PR's base branch)
# Run from the checkout root, after the PR head is checked out. No network and no
# token: it uses the remote-tracking ref the full-history checkout already holds.
#
# Inlined into claude-review-core.yml by scripts/build_review_core.py. Edit this
# file and re-run the generator; do not edit the generated workflow.
set -euo pipefail

BASE_REF="${BASE_REF-}"

if [ -z "$BASE_REF" ] || ! git check-ref-format --branch "$BASE_REF" >/dev/null 2>&1; then
  echo "::error::Base branch restore failed: the base branch name is empty or not a valid branch name."
  exit 1
fi

BASE="refs/remotes/origin/$BASE_REF"
if ! git rev-parse --verify --quiet "$BASE^{commit}" >/dev/null; then
  echo "::error::Base branch restore failed: the base branch was not found in the checkout."
  exit 1
fi

PATHS=(.claude .mcp.json .claude.json .gitmodules .ripgreprc CLAUDE.md CLAUDE.local.md .husky)

for P in "${PATHS[@]}"; do
  present=0
  if [ -e "$P" ] || [ -L "$P" ] || [ -n "$(git ls-files -- "$P")" ]; then
    present=1
  fi

  # Remove from the index and the work tree. rm does not follow a symlink
  # operand: a link is removed as a link.
  git rm -r -q --cached --ignore-unmatch -- "$P"
  rm -rf -- "$P"

  # ls-tree rather than `cat-file -e "$BASE:$P"`: no "ref:path" argument, which
  # Git Bash on Windows rewrites as a path list.
  if [ -n "$(git ls-tree --name-only "$BASE" -- "$P")" ]; then
    # --attr-source: the base branch's attributes decide any conversion, not the
    # .gitattributes of the checked-out PR head (git 2.40 or newer).
    git --attr-source="$BASE" checkout "$BASE" -- "$P"
    echo "restored $P from the base branch"
  elif [ "$present" = 1 ]; then
    echo "removed $P (not on the base branch)"
  fi
done
