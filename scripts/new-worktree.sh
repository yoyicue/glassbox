#!/usr/bin/env bash
# Create a git worktree that inherits glassbox's gitignored local-only config.
#
# `git worktree add` never copies gitignored files, so a fresh worktree silently
# misses the two local-only files glassbox needs at runtime — and then degrades
# without an error:
#   - .env                                  → cfg.picokvm defaults false, so the
#       effector backend is selected as NoOp (no HID); icon backend + VLM env also
#       fall back to their defaults.
#   - glassbox/cognition/icon_backends/*.py → the AGPL omniparser drop-in plugin;
#       missing → the omniparser backend is unavailable and falls back to classical.
# Both are looked up relative to the package root, so they must live at the new
# worktree's own root. We SYMLINK them (single source of truth — edit .env once,
# every worktree sees it; the links live under gitignored paths so they can never
# be staged).
#
# This does NOT install dependencies: each worktree has its OWN .venv, so finish
# with `uv sync --extra dev` in the new worktree (plus the AGPL trio if you need
# omniparser — those are intentionally not in pyproject). See the printed hint.
#
# Usage: scripts/new-worktree.sh <dest-path> [branch]
#   <branch> existing → checked out; new name → created with -b; omitted → git's
#   default (a branch named after the dest basename).
set -euo pipefail

usage() { echo "usage: scripts/new-worktree.sh <dest-path> [branch]" >&2; exit 2; }
[ "$#" -ge 1 ] && [ -n "${1:-}" ] || usage
DEST_ARG="$1"
BRANCH="${2:-}"

# Primary checkout = the main worktree, always listed first by `git worktree list`
# (robust from any CWD inside the repo, unlike git-common-dir relative paths).
PRIMARY="$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')"
[ -n "$PRIMARY" ] || { echo "error: could not locate the primary worktree" >&2; exit 1; }

if [ -n "$BRANCH" ]; then
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git worktree add "$DEST_ARG" "$BRANCH"
  else
    git worktree add -b "$BRANCH" "$DEST_ARG"
  fi
else
  git worktree add "$DEST_ARG"
fi

DEST="$(cd "$DEST_ARG" && pwd)"  # absolutize after creation

link() {  # link <relpath>: symlink PRIMARY/<relpath> → DEST/<relpath>
  local rel="$1" src="$PRIMARY/$1" dst="$DEST/$1"
  [ -e "$src" ] || return 0
  mkdir -p "$(dirname "$dst")"
  ln -sfn "$src" "$dst"
  echo "  linked $rel"
}

echo "Linking gitignored local-only config from $PRIMARY:"
link ".env"
for f in "$PRIMARY"/glassbox/cognition/icon_backends/*.py; do
  [ -e "$f" ] || continue
  link "glassbox/cognition/icon_backends/$(basename "$f")"
done

cat <<EOF

Worktree ready: $DEST
Next — each worktree has its OWN venv, so install deps there:
  cd "$DEST" && uv sync --extra dev
  # omniparser backend also needs the AGPL runtime (intentionally not in pyproject):
  #   uv pip install ultralytics torch huggingface_hub
EOF
