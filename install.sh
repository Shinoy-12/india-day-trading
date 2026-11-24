#!/bin/sh
# Copy each trader-in-* skill into ~/.claude/skills, with the shared India files beside it.
set -e
DEST="${1:-$HOME/.claude/skills}"
HERE="$(cd "$(dirname "$0")" && pwd)"
for d in "$HERE"/skills/trader-in-*; do
  n="$(basename "$d")"
  mkdir -p "$DEST/$n"
  cp -R "$d"/. "$DEST/$n/"
  cp "$HERE"/shared/*.py "$HERE"/shared/*.json "$DEST/$n/"
  echo "installed $n"
done
