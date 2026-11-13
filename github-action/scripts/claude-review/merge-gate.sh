#!/usr/bin/env bash
# Submits a formal PR review (REQUEST_CHANGES / APPROVE / COMMENT) from the
# verdict on line 2 of the workflow's own Comprehensive Review comment;
# fails closed when it is missing.
#
# Reads (env): GH_TOKEN (gh), PR_NUMBER, REPO
#
# Inlined into claude-review-core.yml by scripts/build_review_core.py. Edit this
# file and re-run the generator; do not edit the generated workflow.
set -euo pipefail

# Must match the publish step's TRUSTED_JQ exactly: the gate may only
# trust the logins that step publishes (and edits) review comments as.
TRUSTED_JQ='(.user.login == "github-actions[bot]" or .user.login == "claude[bot]")'
VERDICT_RE='^<!-- claude-verdict: (APPROVE|CHANGES_REQUESTED|COMMENT) -->$'

# The newest Comprehensive Review comment by a trusted login, across ALL
# pages. `--paginate` runs --jq once per page, so the matches are streamed
# one JSON string per line (@json keeps a multi-line body on one line)
# and the last line overall is the newest comment.
LAST_REVIEW_JSON=$(gh api "repos/$REPO/issues/$PR_NUMBER/comments" --paginate \
  --jq ".[] | select($TRUSTED_JQ and (.body | contains(\"<!-- claude-comprehensive-review -->\"))) | .body | @json" | tail -n 1)
REVIEW_BODY=""
if [ -n "$LAST_REVIEW_JSON" ]; then
  REVIEW_BODY=$(printf '%s' "$LAST_REVIEW_JSON" | jq -r .)
fi

if [ -z "$REVIEW_BODY" ]; then
  echo "No Comprehensive Review comment from the review workflow — submitting REQUEST_CHANGES (fail-closed)."
  VERDICT="CHANGES_REQUESTED"
  FAIL_CLOSED_REASON="Claude review did not complete (no Comprehensive Review comment from the review workflow). Re-run it manually: Actions → \"Claude Code Review\" → Run workflow (enter this PR number), or apply the \`skip-claude-review\` label if this is a chore PR that does not need an automated review."
else
  # The verdict is read ONLY from line 2 (the publish step enforces
  # that position); a marker anywhere else in the body is ignored.
  VERDICT_LINE=$(printf '%s\n' "$REVIEW_BODY" | sed -n '2p' | tr -d '\r')
  VERDICT=""
  if [[ "$VERDICT_LINE" =~ $VERDICT_RE ]]; then
    VERDICT="${BASH_REMATCH[1]}"
  fi

  if [ -z "${VERDICT:-}" ]; then
    echo "No verdict marker on line 2 of the Comprehensive Review — submitting REQUEST_CHANGES (fail-closed)."
    VERDICT="CHANGES_REQUESTED"
    FAIL_CLOSED_REASON="Claude review comment was found but the verdict marker (\`<!-- claude-verdict: ... -->\`) is missing or is not on line 2. The review may have terminated mid-step (e.g., hit max turns before Step 6). Re-run it manually: Actions → \"Claude Code Review\" → Run workflow (enter this PR number), or apply the \`skip-claude-review\` label if this is a chore PR."
  fi
fi

echo "Parsed verdict: $VERDICT"

case "$VERDICT" in
  CHANGES_REQUESTED)
    EVENT="REQUEST_CHANGES"
    DESIRED_STATE="CHANGES_REQUESTED"
    if [ -n "${FAIL_CLOSED_REASON:-}" ]; then
      BODY="$FAIL_CLOSED_REASON"
    else
      BODY="Blocking until the findings in the Comprehensive Review comment above are addressed."
    fi
    ;;
  APPROVE)
    EVENT="APPROVE"
    DESIRED_STATE="APPROVED"
    BODY="All prior findings addressed. See the Comprehensive Review comment above for the current assessment."
    ;;
  COMMENT)
    EVENT="COMMENT"
    DESIRED_STATE="COMMENTED"
    BODY="Minor suggestions only — see the Comprehensive Review comment above. Not blocking."
    ;;
  *)
    echo "Unknown verdict: $VERDICT — skipping."
    exit 0
    ;;
esac

BOT_LOGIN="github-actions[bot]"

# Clear any stale fail-closed block.
#
# GitHub auto-dismisses a prior CHANGES_REQUESTED only when the same
# author later submits an APPROVE — NOT on a COMMENT. Without this,
# a fail-closed block from a run that never completed (transient API
# or quota failure) outlives the successful review that superseded
# it, leaving the PR blocked by a review of a run that never
# happened. COMMENT ("minor suggestions, not blocking") is the
# common good outcome, so this is not a corner case.
#
# Runs BEFORE the idempotency exit below so a re-run also heals a PR
# that is already in the desired state but still carries the block.
# Non-fatal: this script runs under `set -e`, so an unguarded
# dismissal failure would abort before the verdict is submitted.
# Note this block still RUNS for APPROVE — it is a no-op only because
# GitHub has already auto-dismissed those reviews, so STALE_IDS comes
# back empty and the loop body never executes. Same for PRs that
# carry no block.
if [ "$EVENT" != "REQUEST_CHANGES" ]; then
  # Non-fatal: an unguarded substitution would abort under `set -e`,
  # killing the job before the verdict is submitted — worse than the
  # stale block this clears. On failure STALE_IDS is empty and the
  # loop is a no-op. stderr is left visible for debugging.
  STALE_IDS=$(gh api "repos/$REPO/pulls/$PR_NUMBER/reviews" --paginate \
    --jq "[.[] | select(.user.login == \"$BOT_LOGIN\" and .state == \"CHANGES_REQUESTED\")] | .[].id" || true)
  for RID in $STALE_IDS; do
    if gh api "repos/$REPO/pulls/$PR_NUMBER/reviews/$RID/dismissals" \
      -X PUT \
      -f message="Superseded by a newer Claude review verdict ($VERDICT)." >/dev/null; then
      echo "Dismissed stale fail-closed CHANGES_REQUESTED review $RID."
    else
      echo "WARNING: could not dismiss stale review $RID — continuing so the verdict is still submitted."
    fi
  done
fi

PRIOR_STATE=$(gh api "repos/$REPO/pulls/$PR_NUMBER/reviews" --paginate \
  --jq "[.[] | select(.user.login == \"$BOT_LOGIN\")] | last | .state // \"NONE\"")

echo "Prior bot review state: $PRIOR_STATE"
echo "Desired state:          $DESIRED_STATE"

if [ "$PRIOR_STATE" = "$DESIRED_STATE" ]; then
  echo "Already in desired state — no new review submitted."
  exit 0
fi

gh api "repos/$REPO/pulls/$PR_NUMBER/reviews" \
  -X POST \
  -f event="$EVENT" \
  -f body="$BODY"

echo "Submitted $EVENT review on PR #$PR_NUMBER."
