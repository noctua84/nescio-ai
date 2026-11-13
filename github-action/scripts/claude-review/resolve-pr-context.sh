#!/usr/bin/env bash
# Resolves the PR under review (number, title, author, refs, SHAs, today's date)
# and publishes them as step outputs for later steps.
#
# Reads (env): GH_TOKEN (gh), PR_NUMBER (the workflow input)
#   GITHUB_REPOSITORY and GITHUB_OUTPUT (runner-provided)
#
# Inlined into claude-review-core.yml by scripts/build_review_core.py. Edit this
# file and re-run the generator; do not edit the generated workflow.
# Inputs arrive via env; nothing is interpolated into run:.
if ! [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]]; then
  echo "::error::pr_number must be a positive integer"
  exit 1
fi
META=$(gh api "repos/$GITHUB_REPOSITORY/pulls/$PR_NUMBER" \
  --jq '{title, user: .user.login, base_ref: .base.ref, base_sha: .base.sha, head_ref: .head.ref, head_sha: .head.sha}')
{
  echo "number=$PR_NUMBER"
  echo "title=$(echo "$META" | jq -r .title)"
  echo "user=$(echo "$META" | jq -r .user)"
  echo "base_ref=$(echo "$META" | jq -r .base_ref)"
  echo "base_sha=$(echo "$META" | jq -r .base_sha)"
  echo "head_ref=$(echo "$META" | jq -r .head_ref)"
  echo "head_sha=$(echo "$META" | jq -r .head_sha)"
  # Claude has no date tool in its allow-list; hand it the date
  # for the learning-note frontmatter (Step 4b).
  echo "today=$(date -u +%F)"
} >> "$GITHUB_OUTPUT"
