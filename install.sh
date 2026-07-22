#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"

echo "Repo:   $REPO_DIR"
echo "Target: $CLAUDE_DIR"
mkdir -p "$CLAUDE_DIR"

link() {
  local src="$1" dst="$2"
  if [ ! -e "$src" ]; then
    echo "  ! source missing, skipping: $src"; return
  fi
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    echo "  ! $dst exists and is not a symlink — back it up and rerun, skipping."; return
  fi
  ln -sfn "$src" "$dst"
  echo "  linked $dst -> $src"
}

# Symlink the config Claude Code reads at user scope. settings.json is NOT
# symlinked here: it needs a consent step + machine-specific hooks (absolute
# paths), which install.py handles — see the note below.
link "$REPO_DIR/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"
link "$REPO_DIR/memory"    "$CLAUDE_DIR/memory"
link "$REPO_DIR/skills"    "$CLAUDE_DIR/skills"
link "$REPO_DIR/agents"    "$CLAUDE_DIR/agents"
link "$REPO_DIR/commands"  "$CLAUDE_DIR/commands"
link "$REPO_DIR/hooks"     "$CLAUDE_DIR/hooks"

# Remove dead user-scope .local symlinks an older installer may have created —
# Claude Code does NOT read ~/.claude/settings.local.json or ~/.claude/CLAUDE.local.md.
for dead in settings.local.json CLAUDE.local.md; do
  if [ -L "$CLAUDE_DIR/$dead" ]; then
    rm -f "$CLAUDE_DIR/$dead"
    echo "  removed dead symlink $CLAUDE_DIR/$dead (ignored by Claude Code)"
  fi
done

echo ""
echo "Symlinks done. settings.json + the learning-loop hooks must live in"
echo "~/.claude/settings.json (Claude Code ignores user-scope .local files), and"
echo "adopting settings needs a consent step — run:"
echo "    python install.py --settings minimal   # or: full | skip"
echo "Then restart Claude Code / Desktop to pick up the changes."
