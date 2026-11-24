#!/usr/bin/env bash
# Which change is this copy of the code for? Prints its slug; prints nothing (exit 0) when none.
#
# Usage: .sdlc/scripts/current-change.sh    run anywhere in the checkout or worktree
#
# The plan gate, the test lock and the skills (routing.md) all ask here, so they agree (#279):
#   - $SDLC_CHANGE, when set; else
#   - the NNNN-name slug in the branch name (build/0003-x, fix/0003-x, …); else
#   - the worktree folder's name: the slug (0003-x), or the number alone (0003), which is what
#     `claude --worktree 0003` makes. Its branch, worktree-0003, carries no slug.
# A slug counts only when changes/<slug>/ exists. A number two changes share is neither.
set -euo pipefail

top="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$top"

if [[ -n "${SDLC_CHANGE:-}" ]]; then
  echo "$SDLC_CHANGE"
  exit 0
fi
folder="$(basename "$top")"
for name in "$(git branch --show-current 2>/dev/null || true)" "$folder"; do
  slug="$(grep -oE '[0-9]{4}-[a-z0-9]+(-[a-z0-9]+)*' <<<"$name" | head -1 || true)"
  if [[ -n "$slug" && -d "changes/$slug" ]]; then
    echo "$slug"
    exit 0
  fi
done
if [[ "$folder" =~ ^[0-9]{4}$ ]]; then
  shopt -s nullglob
  dirs=("changes/$folder"-*/)
  if ((${#dirs[@]} == 1)); then basename "${dirs[0]}"; fi
fi
