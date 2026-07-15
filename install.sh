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
    echo "  ! source missing, skipping: $src"
    return
  fi
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    echo "  ! $dst exists and is not a symlink — back it up and rerun, skipping."
    return
  fi
  ln -sfn "$src" "$dst"
  echo "  linked $dst -> $src"
}

link "$REPO_DIR/CLAUDE.md"   "$CLAUDE_DIR/CLAUDE.md"
link "$REPO_DIR/memory"      "$CLAUDE_DIR/memory"
link "$REPO_DIR/skills"      "$CLAUDE_DIR/skills"
link "$REPO_DIR/agents"      "$CLAUDE_DIR/agents"
link "$REPO_DIR/commands"    "$CLAUDE_DIR/commands"
link "$REPO_DIR/hooks"       "$CLAUDE_DIR/hooks"
link "$REPO_DIR/settings.json" "$CLAUDE_DIR/settings.json"

if [ ! -f "$REPO_DIR/settings.local.json" ]; then
  cp "$REPO_DIR/settings.local.json.example" "$REPO_DIR/settings.local.json"
  echo "  created $REPO_DIR/settings.local.json from template (gitignored, edit freely)"
fi
link "$REPO_DIR/settings.local.json" "$CLAUDE_DIR/settings.local.json"

if [ ! -f "$REPO_DIR/CLAUDE.local.md" ]; then
  cp "$REPO_DIR/CLAUDE.local.md.example" "$REPO_DIR/CLAUDE.local.md"
  echo "  created $REPO_DIR/CLAUDE.local.md from template (gitignored, edit freely)"
fi
link "$REPO_DIR/CLAUDE.local.md" "$CLAUDE_DIR/CLAUDE.local.md"

echo "Done. Restart Claude Code / Desktop to pick up changes."
