#!/usr/bin/env bash
# Opens the review-learning PRs that Claude staged under /tmp/review-learnings.
#
# Reads (env): GH_TOKEN (gh and git push), PR_NUMBER, BASE_REF, REPO
#   RUNNER_TEMP (optional), GITHUB_SERVER_URL (runner-provided)
#
# Inlined into claude-review-core.yml by scripts/build_review_core.py. Edit this
# file and re-run the generator; do not edit the generated workflow.
set -euo pipefail

STAGE_DIR=/tmp/review-learnings
NOTE_DIR=.claude/memory/review-learnings
MAX_NOTES=2
MAX_BYTES=8192
SLUG_RE='^[a-z0-9]([a-z0-9-]{0,48}[a-z0-9])?$'
WORK_DIR="${RUNNER_TEMP:-/tmp}"
BOT_NAME="github-actions[bot]"
BOT_EMAIL="41898283+github-actions[bot]@users.noreply.github.com"

if [ ! -d "$STAGE_DIR" ]; then
  echo "No staged review learnings."
  exit 0
fi

case "$PR_NUMBER" in
  ''|*[!0-9]*)
    echo "::warning::Review learnings skipped: PR number '$PR_NUMBER' is not numeric."
    exit 0
    ;;
esac
if [ -z "$BASE_REF" ]; then
  echo "::warning::Review learnings skipped: base ref is empty."
  exit 0
fi

if ! git fetch --quiet origin "+refs/heads/$BASE_REF:refs/remotes/origin/$BASE_REF"; then
  echo "::warning::Review learnings skipped: could not fetch origin/$BASE_REF."
  exit 0
fi

shopt -s nullglob
# MAX_NOTES bounds the PRs opened per run; MAX_FILES bounds how
# many staged files are even looked at, so a flood of candidates
# cannot turn this step into a long loop of API calls.
MAX_FILES=10
SEEN=0
OPENED=0
for FILE in "$STAGE_DIR"/*.md; do
  SEEN=$((SEEN + 1))
  if [ "$SEEN" -gt "$MAX_FILES" ] || [ "$OPENED" -ge "$MAX_NOTES" ]; then
    echo "::warning::More review learnings staged than the limit ($MAX_NOTES per run); ignoring the rest."
    break
  fi

  SLUG=$(basename "$FILE" .md)
  # Claude chose this name and it ends up in a branch name and a
  # path: accept the narrow shape only.
  if ! [[ "$SLUG" =~ $SLUG_RE ]]; then
    echo "::warning::Review learning rejected: invalid slug '$SLUG' (need kebab-case [a-z0-9-], at most 50 chars)."
    continue
  fi
  if [ -L "$FILE" ] || [ ! -f "$FILE" ]; then
    echo "::warning::Review learning '$SLUG' rejected: not a regular file."
    continue
  fi
  if [ ! -s "$FILE" ] || [ "$(wc -c < "$FILE")" -gt "$MAX_BYTES" ]; then
    echo "::warning::Review learning '$SLUG' rejected: empty or larger than $MAX_BYTES bytes."
    continue
  fi
  if [ "$(head -n 1 "$FILE")" != "---" ]; then
    echo "::warning::Review learning '$SLUG' rejected: missing frontmatter."
    continue
  fi
  KIND=$(sed -n 's/^kind: *//p' "$FILE" | head -n 1 | tr -d '[:space:]')
  case "$KIND" in
    regression|security|architecture) ;;
    *)
      echo "::warning::Review learning '$SLUG' rejected: kind '$KIND' is not regression, security or architecture."
      continue
      ;;
  esac

  BRANCH="claude/review-learning/$PR_NUMBER-$SLUG"

  # Dedup against what is already merged on the base ...
  if git cat-file -e "origin/$BASE_REF:$NOTE_DIR/$SLUG.md" 2>/dev/null; then
    echo "Review learning '$SLUG' already exists on $BASE_REF — skipping."
    continue
  fi
  # ... and against a branch a previous push of this PR created.
  if ! REMOTE=$(git ls-remote --heads origin "refs/heads/$BRANCH"); then
    echo "::warning::Review learning '$SLUG' skipped: could not query origin for $BRANCH."
    continue
  fi
  if [ -n "$REMOTE" ]; then
    echo "Branch $BRANCH already exists — skipping."
    continue
  fi

  OPENED=$((OPENED + 1))

  # Separate worktree: the main checkout is the PR head and must
  # stay untouched. Branch off the BASE so the PR holds only the note.
  WT="$WORK_DIR/review-learning-$SLUG"
  if ! git worktree add --quiet -b "$BRANCH" "$WT" "origin/$BASE_REF"; then
    echo "::warning::Review learning '$SLUG' failed: could not create a worktree for $BRANCH."
    continue
  fi

  if ! { mkdir -p "$WT/$NOTE_DIR" \
         && cp "$FILE" "$WT/$NOTE_DIR/$SLUG.md" \
         && git -C "$WT" add -- "$NOTE_DIR/$SLUG.md" \
         && git -C "$WT" -c "user.name=$BOT_NAME" -c "user.email=$BOT_EMAIL" \
              commit --quiet -m "chore: record review learning ($SLUG)" \
         && git -C "$WT" push --quiet -u origin "$BRANCH"; }; then
    echo "::warning::Review learning '$SLUG' failed: could not commit or push $BRANCH."
    git worktree remove --force "$WT" >/dev/null 2>&1 || true
    continue
  fi

  BODY_FILE="$WORK_DIR/review-learning-$SLUG-body.md"
  {
    echo "Records a $KIND learning from PR $PR_NUMBER so future reviews of this repository watch for it."
    echo
    echo "Source PR: $GITHUB_SERVER_URL/$REPO/pull/$PR_NUMBER"
    echo
    echo "Proposed by the automated review and opened by the workflow. Read the note, edit or close it as you see fit; once merged, check 3f of every later review reads it."
  } > "$BODY_FILE"

  if gh pr create --repo "$REPO" --base "$BASE_REF" --head "$BRANCH" \
       --title "chore: record review learning ($SLUG)" --body-file "$BODY_FILE"; then
    echo "Opened review-learning PR for '$SLUG'."
  else
    echo "::warning::Review learning '$SLUG' failed: pushed $BRANCH but could not open the PR; removing the branch so a later run can retry."
    git push --quiet origin --delete "$BRANCH" || true
  fi
  git worktree remove --force "$WT" >/dev/null 2>&1 || true
done
