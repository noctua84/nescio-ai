#!/usr/bin/env bash
# Prunes the staged review files before they are uploaded as an artifact: keeps
# only publishable regular files and drops anything else, plus any file that
# contains a credential-shaped string. This is hygiene for the benign and
# accidental case (plain-text credentials, links and special files stay out of a
# downloadable artifact). It is not a security boundary: the publish job treats
# the artifact as untrusted and re-checks every file itself.
#
# Reads (env): REVIEW_OUTBOX (optional; defaults to /tmp/review-outbox),
#   REVIEW_LEARNINGS (optional; defaults to /tmp/review-learnings)
#
# Inlined into claude-review-core.yml by scripts/build_review_core.py. Edit this
# file and re-run the generator; do not edit the generated workflow.
export PATH=/usr/bin:/bin
set -euo pipefail

# Identical to the filters in publish-comments.sh and open-learning-prs.sh.
SECRET_RE='(gh[opusr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-ant-[A-Za-z0-9_-]{20,})'

OUTBOX="${REVIEW_OUTBOX:-/tmp/review-outbox}"
LEARNINGS="${REVIEW_LEARNINGS:-/tmp/review-learnings}"

# The file names are Claude's choice: keep log output to a safe alphabet.
label() { printf '%s' "$(basename -- "$1")" | tr -c 'A-Za-z0-9._-' '_'; }

warn_path() {
  echo "::warning::Staged path '$(label "$1")' removed before upload: not a publishable file."
}

is_regular() { [ -f "$1" ] && [ ! -L "$1" ]; }

# keep_outbox <relative path> <full path>: is this entry publishable as it is?
keep_outbox() {
  case "$1" in
    summary.md|review.md) is_regular "$2" ;;
    findings|replies) [ -d "$2" ] && [ ! -L "$2" ] ;;
    findings/*|replies/*)
      case "${1#*/}" in
        */*|.*) return 1 ;;
        *.md) is_regular "$2" ;;
        *) return 1 ;;
      esac
      ;;
    *) return 1 ;;
  esac
}

# keep_learnings <relative path> <full path>: top-level regular *.md files only.
keep_learnings() {
  case "$1" in
    */*|.*) return 1 ;;
    *.md) is_regular "$2" ;;
    *) return 1 ;;
  esac
}

LIST=$(mktemp /tmp/scrub-staged.XXXXXX)
trap 'rm -f "$LIST"' EXIT

# prune <dir> <outbox|learnings>
prune() {
  local root="${1%/}" kind="$2" p rel rc
  if [ -z "$root" ]; then
    echo "::error::Scrub failed: staging directory path is empty."
    exit 1
  fi
  # A link is removed as a link; its target is never followed.
  if [ -L "$root" ]; then
    rm -f -- "$root"
    warn_path "$root"
    return 0
  fi
  [ -e "$root" ] || return 0
  if [ ! -d "$root" ]; then
    rm -f -- "$root"
    warn_path "$root"
    return 0
  fi
  # List first, remove afterwards: find never walks a tree it is deleting.
  find "$root" -mindepth 1 -print0 > "$LIST"
  while IFS= read -r -d '' p; do
    # Already gone with a removed parent directory.
    if [ ! -e "$p" ] && [ ! -L "$p" ]; then continue; fi
    rel="${p#"$root"/}"
    if "keep_$kind" "$rel" "$p"; then
      # Kept directories hold nothing to scan; a kept file is scanned whole.
      if [ -f "$p" ]; then
        rc=0
        LC_ALL=C grep -Eq -- "$SECRET_RE" "$p" || rc=$?
        if [ "$rc" -eq 0 ]; then
          rm -f -- "$p"
          echo "::warning::Staged file '$(label "$p")' removed before upload: it contains a credential-shaped string."
        elif [ "$rc" -ne 1 ]; then
          # Could not be scanned: do not upload what was not checked.
          rm -f -- "$p"
          warn_path "$p"
        fi
      fi
      continue
    fi
    rm -rf -- "$p"
    warn_path "$p"
  done < "$LIST"
}

prune "$OUTBOX" outbox
prune "$LEARNINGS" learnings
