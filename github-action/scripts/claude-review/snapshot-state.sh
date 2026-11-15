#!/usr/bin/env bash
# Snapshots the PR's review state (issue comments, inline review comments,
# review threads, open review-learning PRs) into /tmp/review-state/ for Claude
# to READ.
#
# Reads (env): GH_TOKEN (gh), PR_NUMBER, REPO (owner/name),
#   REVIEW_STATE_DIR (optional, default /tmp/review-state; tests only)
#
# Inlined into claude-review-core.yml by scripts/build_review_core.py. Edit this
# file and re-run the generator; do not edit the generated workflow.
set -euo pipefail

case "$PR_NUMBER" in
  ''|*[!0-9]*)
    echo "::error::Review state snapshot failed: PR number '$PR_NUMBER' is not numeric."
    exit 1
    ;;
esac

OWNER="${REPO%%/*}"
NAME="${REPO#*/}"
STATE="${REVIEW_STATE_DIR:-/tmp/review-state}"

rm -rf "$STATE"
mkdir -p "$STATE"

# Issue-style PR comments, one JSON object per line.
gh api "repos/$REPO/issues/$PR_NUMBER/comments" --paginate \
  --jq '.[] | {id, user: .user.login, body}' > "$STATE/issue-comments.jsonl"

# Inline review comments, one JSON object per line.
gh api "repos/$REPO/pulls/$PR_NUMBER/comments" --paginate \
  --jq '.[] | {id, user: .user.login, body, path, line, in_reply_to_id}' > "$STATE/review-comments.jsonl"

# Review threads: resolution state plus every comment in the thread.
# owner/name are sent as raw strings (-f) so a repo named like a number or
# `true` is not type-coerced; the number is a typed Int (-F).
gh api graphql \
  -f owner="$OWNER" -f name="$NAME" -F number="$PR_NUMBER" \
  -f query='query($owner:String!,$name:String!,$number:Int!){ repository(owner:$owner,name:$name){ pullRequest(number:$number){ reviewThreads(first:100){ nodes{ id isResolved comments(first:50){ nodes{ databaseId author{ login } body } } } } } } }' \
  > "$STATE/review-threads.json"

# Open review-learning PRs (the file is empty when there are none).
gh api "repos/$REPO/pulls?state=open&per_page=100" --paginate \
  --jq '.[] | select(.head.ref | startswith("claude/review-learning/")) | .number' \
  > "$STATE/open-learning-prs.txt"

echo "Review state written to $STATE:"
wc -l "$STATE"/*
