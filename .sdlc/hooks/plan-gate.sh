#!/usr/bin/env bash
# PreToolUse (Edit|Write|MultiEdit|NotebookEdit): no code before the plan is committed (#44).
# Exit 2 blocks the edit and shows stderr to Claude.
#
# Claude Code's plan-mode dialog offers to leave plan mode and start implementing at once, which
# skips /sdlc-plan. This holds whichever button was pressed:
#   - On a branch or worktree named after a change (build/0003-x, plan/0003-x, …; the same
#     detection as .sdlc/scripts/tests-locked.sh, or $SDLC_CHANGE), code waits until
#     changes/<slug>/plan.md is committed. "Committed" means in HEAD: a half-written draft in
#     the working tree doesn't count.
#   - The bug fast path (#148): on build/<slug>, a bug whose bug.md and spec.md are both
#     committed may be fixed without a plan.
#   - On the default branch (main), code isn't written at all: switch to a branch first.
#   - Other branches (chore/…, fix/…, docs/…) aren't tied to a change and aren't checked.
# Always editable: changes/, docs/, top-level *.md, and anything outside the repo.
# SDLC_PLAN_GATE=0 turns the check off deliberately.
set -euo pipefail

[[ "${SDLC_PLAN_GATE:-}" == "0" ]] && exit 0
path="$(jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')"
[[ -z "$path" ]] && exit 0
root="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$root" 2>/dev/null || exit 0
top="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0

case "$path" in
  "$top"/*) rel="${path#"$top"/}" ;;
  /*) exit 0 ;;  # outside the repo: a scratch file, the person's own notes
  *) rel="$path" ;;
esac
case "$rel" in
  ../*) exit 0 ;;
  changes/* | docs/*) exit 0 ;;
  */*) ;;
  *.md) exit 0 ;;
esac

block() {
  echo "Blocked edit to $rel: $1" >&2
  exit 2
}

branch="$(git branch --show-current 2>/dev/null || true)"
[[ -n "$branch" ]] || exit 0  # detached HEAD: a CI checkout or a rebase in progress

slug="${SDLC_CHANGE:-}"
if [[ -z "$slug" ]]; then
  for name in "$branch" "$(basename "$top")"; do
    candidate="$(grep -oE '[0-9]{4}-[a-z0-9]+(-[a-z0-9]+)*' <<<"$name" | head -1 || true)"
    if [[ -n "$candidate" && -d "changes/$candidate" ]]; then slug="$candidate"; break; fi
  done
fi

committed() { git cat-file -e "HEAD:changes/$slug/$1" 2>/dev/null; }

if [[ -n "$slug" ]]; then
  committed plan.md && exit 0
  if [[ "$branch" == "build/$slug" ]] && committed bug.md && committed spec.md; then
    exit 0  # the bug fast path
  fi
  if committed spec.md; then
    block "$slug has no committed plan.md, so no code yet. Run /sdlc-plan to save the plan and open its PR; build once it merges (SDLC_PLAN_GATE=0 overrides)."
  fi
  block "$slug has no committed spec.md or plan.md, so no code yet. Run /sdlc-next to see its next step (SDLC_PLAN_GATE=0 overrides)."
fi

default="$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || true)"
default="${default#origin/}"
if [[ "$branch" == "${default:-main}" || (-z "$default" && "$branch" == master) ]]; then
  block "code isn't written on $branch. Start a branch first: build/<slug> for a planned change (/sdlc-build), or chore/… or fix/… for maintenance (SDLC_PLAN_GATE=0 overrides)."
fi
exit 0
