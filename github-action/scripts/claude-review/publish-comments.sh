#!/usr/bin/env bash
# Validates the comments Claude staged under the review outbox and posts them
# (summary, review, replies, inline findings) as github-actions[bot].
#
# Reads (env): GH_TOKEN (gh), PR_NUMBER, REPO, HEAD_SHA (40-char hex)
#   REVIEW_OUTBOX (optional; defaults to /tmp/review-outbox), RUNNER_TEMP (optional)
#
# Inlined into claude-review-core.yml by scripts/build_review_core.py. Edit this
# file and re-run the generator; do not edit the generated workflow.
set -euo pipefail

OUT="${REVIEW_OUTBOX:-/tmp/review-outbox}"
WORK_DIR="${RUNNER_TEMP:-/tmp}"
# jq form of the trusted-author filter: this workflow's publisher, plus
# the login earlier versions of this template posted as.
TRUSTED_JQ='(.user.login == "github-actions[bot]" or .user.login == "claude[bot]")'
MAX_BODY=60000
MAX_REPLY=4096
MAX_FINDINGS=25
MAX_REPLIES=50
SUMMARY_MARKER='<!-- claude-pr-summary -->'
REVIEW_MARKER='<!-- claude-comprehensive-review -->'
FINDING_RE='^<!-- claude-finding: [^>]+ -->$'
# Line 2 of review.md. The merge-gate job uses the same pattern.
VERDICT_RE='^<!-- claude-verdict: (APPROVE|CHANGES_REQUESTED|COMMENT) -->$'

case "$PR_NUMBER" in
  ''|*[!0-9]*)
    echo "::error::Publish failed: PR number '$PR_NUMBER' is not numeric."
    exit 1
    ;;
esac
if ! [[ "$HEAD_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "::error::Publish failed: head SHA is not a 40-character hex string."
  exit 1
fi

if [ ! -d "$OUT" ] || [ -L "$OUT" ]; then
  echo "::warning::No review outbox at $OUT — nothing to publish."
  exit 0
fi

TMP=$(mktemp -d "$WORK_DIR/review-publish.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
shopt -s nullglob

# The file names are Claude's choice: keep log output to a safe alphabet.
label() { printf '%s' "$(basename "$1")" | tr -c 'A-Za-z0-9._-' '_'; }

# check_file <file> <max bytes> <label>
check_file() {
  if [ -L "$1" ] || [ ! -f "$1" ]; then
    echo "::warning::Staged file '$3' rejected: not a regular file."
    return 1
  fi
  if [ ! -s "$1" ]; then
    echo "::warning::Staged file '$3' rejected: empty."
    return 1
  fi
  if [ "$(wc -c < "$1")" -gt "$2" ]; then
    echo "::warning::Staged file '$3' rejected: larger than $2 bytes."
    return 1
  fi
}

# Newest issue comment by a trusted login whose body contains the marker.
# Always a fresh read: /tmp/review-state is writable by Claude.
find_comment() {
  gh api "repos/$REPO/issues/$PR_NUMBER/comments" --paginate \
    --jq ".[] | select($TRUSTED_JQ and (.body | contains(\"$1\"))) | .id" | tail -n 1
}

# publish_top <file> <marker> [line-2 regex]: edit the existing comment in
# place, or create it. With a line-2 regex (review.md only: the verdict
# the merge gate reads) a file whose line 2 does not match is rejected.
publish_top() {
  local file="$1" marker="$2" line2_re="${3:-}" lab id
  lab=$(label "$file")
  check_file "$file" "$MAX_BODY" "$lab" || return 1
  if [ "$(head -n 1 "$file")" != "$marker" ]; then
    echo "::warning::Staged file '$lab' rejected: line 1 is not $marker."
    return 1
  fi
  if [ -n "$line2_re" ]; then
    if ! [[ "$(sed -n '2p' "$file" | tr -d '\r')" =~ $line2_re ]]; then
      echo "::warning::Staged file '$lab' rejected: line 2 is not a valid verdict marker."
      return 1
    fi
  fi
  if ! id=$(find_comment "$marker"); then
    echo "::warning::Staged file '$lab' not published: could not list the existing comments."
    return 1
  fi
  # An earlier template version posted as claude[bot], and GITHUB_TOKEN
  # may not be allowed to edit that comment. The merge gate reads the
  # newest marker comment, so a fresh comment is correct.
  if [ -n "$id" ] && gh api -X PATCH "repos/$REPO/issues/comments/$id" -F body=@"$file" >/dev/null; then
    echo "Updated comment $id from '$lab'."
  else
    if [ -n "$id" ]; then
      echo "::warning::Could not edit comment $id from '$lab'; posting a new comment instead."
    fi
    gh api -X POST "repos/$REPO/issues/$PR_NUMBER/comments" -F body=@"$file" >/dev/null || return 1
    echo "Created a comment from '$lab'."
  fi
}

# parse_staged <file>: split `---` frontmatter from the body. Sets FM (the
# frontmatter lines) and writes the body to $BODY_FILE. Returns 1 if the
# frontmatter is missing or unterminated.
parse_staged() {
  local file="$1" end
  [ "$(head -n 1 "$file")" = "---" ] || return 1
  end=$(awk 'NR > 1 && $0 == "---" { print NR; exit }' "$file")
  [ -n "$end" ] || return 1
  if [ "$end" -gt 2 ]; then
    FM=$(sed -n "2,$((end - 1))p" "$file" | tr -d '\r')
  else
    FM=""
  fi
  tail -n +"$((end + 1))" "$file" > "$BODY_FILE"
}

# fm_get <key>: first `key: value` line of $FM, value trimmed.
fm_get() {
  awk -v k="$1" 'index($0, k ":") == 1 {
    v = substr($0, length(k) + 2)
    sub(/^[ \t]+/, "", v); sub(/[ \t]+$/, "", v)
    print v; exit
  }' <<<"$FM"
}

# --- Top-level comments: summary first, then the review -------------------
REVIEW_FAILED=0

if [ -e "$OUT/summary.md" ] || [ -L "$OUT/summary.md" ]; then
  publish_top "$OUT/summary.md" "$SUMMARY_MARKER" \
    || echo "::warning::The PR summary was not published."
fi

if [ -e "$OUT/review.md" ] || [ -L "$OUT/review.md" ]; then
  if ! publish_top "$OUT/review.md" "$REVIEW_MARKER" "$VERDICT_RE"; then
    # Remembered, not fatal yet: findings and replies below are still
    # published. The step fails at the very end so it is visible.
    echo "::error::The comprehensive review was staged but could not be published."
    REVIEW_FAILED=1
  fi
fi

# --- Inline findings and replies -------------------------------------------
for SUB in findings replies; do
  if [ -L "$OUT/$SUB" ]; then
    echo "::warning::Staged directory '$SUB' ignored: it is a symlink."
  fi
done
FINDING_FILES=()
REPLY_FILES=()
if [ -d "$OUT/findings" ] && [ ! -L "$OUT/findings" ]; then
  FINDING_FILES=("$OUT"/findings/*.md)
fi
if [ -d "$OUT/replies" ] && [ ! -L "$OUT/replies" ]; then
  REPLY_FILES=("$OUT"/replies/*.md)
fi

# Review comments by a trusted login, fetched fresh (JSON objects, one
# stream). Used to skip duplicate findings and to validate reply targets.
RC=""
RC_OK=0
if [ "${#FINDING_FILES[@]}" -gt 0 ] || [ "${#REPLY_FILES[@]}" -gt 0 ]; then
  if RC=$(gh api "repos/$REPO/pulls/$PR_NUMBER/comments" --paginate \
            --jq ".[] | select($TRUSTED_JQ) | {id, body}"); then
    RC_OK=1
  else
    echo "::warning::Findings and replies not published: could not list the existing review comments."
  fi
fi

SEEN_FINDINGS=""
# already_posted <first line>: a trusted review comment already carries it,
# or an earlier file in this run did.
already_posted() {
  if jq -e -s --arg l "$1" 'any(.[]; .body | contains($l))' <<<"$RC" >/dev/null; then
    return 0
  fi
  grep -Fxq -- "$1" <<<"$SEEN_FINDINGS"
}

CHANGED=""
CHANGED_OK=0
if [ "$RC_OK" -eq 1 ] && [ "${#FINDING_FILES[@]}" -gt 0 ]; then
  if CHANGED=$(gh api "repos/$REPO/pulls/$PR_NUMBER/files" --paginate --jq '.[].filename'); then
    CHANGED_OK=1
  else
    echo "::warning::Findings not published: could not list the PR's changed files."
  fi
fi

if [ "$CHANGED_OK" -eq 1 ]; then
  N=0
  for FILE in "${FINDING_FILES[@]}"; do
    N=$((N + 1))
    if [ "$N" -gt "$MAX_FINDINGS" ]; then
      echo "::warning::More findings staged than the limit ($MAX_FINDINGS per run); ignoring the rest."
      break
    fi
    LAB=$(label "$FILE")
    BODY_FILE="$TMP/finding-$N.md"
    check_file "$FILE" "$MAX_BODY" "$LAB" || continue
    if ! parse_staged "$FILE"; then
      echo "::warning::Finding '$LAB' rejected: missing or unterminated frontmatter."
      continue
    fi
    P=$(fm_get path)
    L=$(fm_get line)
    S=$(fm_get side)
    if [ -z "$P" ] || ! grep -Fxq -- "$P" <<<"$CHANGED"; then
      echo "::warning::Finding '$LAB' rejected: path is not a file changed in this PR."
      continue
    fi
    if ! [[ "$L" =~ ^[1-9][0-9]{0,6}$ ]]; then
      echo "::warning::Finding '$LAB' rejected: line is not a positive integer."
      continue
    fi
    if [ "$S" != "RIGHT" ] && [ "$S" != "LEFT" ]; then
      echo "::warning::Finding '$LAB' rejected: side is not RIGHT or LEFT."
      continue
    fi
    FIRST=$(head -n 1 "$BODY_FILE")
    if ! [[ "$FIRST" =~ $FINDING_RE ]]; then
      echo "::warning::Finding '$LAB' rejected: body line 1 is not a claude-finding marker."
      continue
    fi
    if [ "$(wc -c < "$BODY_FILE")" -gt "$MAX_BODY" ]; then
      echo "::warning::Finding '$LAB' rejected: body larger than $MAX_BODY bytes."
      continue
    fi
    if already_posted "$FIRST"; then
      echo "Finding '$LAB' already posted — skipping."
      continue
    fi
    if gh api -X POST "repos/$REPO/pulls/$PR_NUMBER/comments" \
         -f commit_id="$HEAD_SHA" -f path="$P" -F line="$L" -f side="$S" \
         -F body=@"$BODY_FILE" >/dev/null; then
      echo "Posted finding '$LAB'."
      SEEN_FINDINGS="$SEEN_FINDINGS"$'\n'"$FIRST"
    else
      echo "::warning::Finding '$LAB' could not be posted."
    fi
  done
fi

# A reply may only target a finding comment this workflow wrote on THIS PR.
if [ "$RC_OK" -eq 1 ] && [ "${#REPLY_FILES[@]}" -gt 0 ]; then
  if ! VALID_IDS=$(jq -r 'select(.body | contains("<!-- claude-finding:")) | .id' <<<"$RC"); then
    echo "::warning::Replies not published: could not read the existing finding comments."
    VALID_IDS=""
  fi
  N=0
  for FILE in "${REPLY_FILES[@]}"; do
    N=$((N + 1))
    if [ "$N" -gt "$MAX_REPLIES" ]; then
      echo "::warning::More replies staged than the limit ($MAX_REPLIES per run); ignoring the rest."
      break
    fi
    LAB=$(label "$FILE")
    BODY_FILE="$TMP/reply-$N.md"
    # The file holds frontmatter plus the body; the body limit follows.
    check_file "$FILE" "$MAX_BODY" "$LAB" || continue
    if ! parse_staged "$FILE"; then
      echo "::warning::Reply '$LAB' rejected: missing or unterminated frontmatter."
      continue
    fi
    ID=$(fm_get in_reply_to)
    if ! [[ "$ID" =~ ^[1-9][0-9]{0,17}$ ]] || ! grep -Fxq -- "$ID" <<<"$VALID_IDS"; then
      echo "::warning::Reply '$LAB' rejected: in_reply_to is not a finding comment on this PR."
      continue
    fi
    if ! grep -q '[^[:space:]]' "$BODY_FILE" || [ "$(wc -c < "$BODY_FILE")" -gt "$MAX_REPLY" ]; then
      echo "::warning::Reply '$LAB' rejected: body is empty or larger than $MAX_REPLY bytes."
      continue
    fi
    if gh api -X POST "repos/$REPO/pulls/$PR_NUMBER/comments/$ID/replies" \
         -F body=@"$BODY_FILE" >/dev/null; then
      echo "Posted reply '$LAB' to comment $ID."
    else
      echo "::warning::Reply '$LAB' could not be posted."
    fi
  done
fi

if [ "$REVIEW_FAILED" -ne 0 ]; then
  exit 1
fi
