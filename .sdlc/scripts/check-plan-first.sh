#!/usr/bin/env bash
# CI's half of "no code before the plan" (#44): the hook (.sdlc/hooks/plan-gate.sh) can be
# turned off or bypassed with a shell write, so the PR check holds the rule as well.
#
# Usage: .sdlc/scripts/check-plan-first.sh <head branch>   the PR's changed files on stdin
#   Run from the PR's checkout (the merge commit), so the tree holds what main and the branch
#   have between them.
#
# A PR from a branch named after a change (build/0003-x, plan/0003-x, …, when changes/<slug>/
# exists) that changes code must have changes/<slug>/plan.md in its tree: committed on the
# branch, or merged to main before it. The bug fast path (#148) is the exception: on
# build/<slug>, a bug whose bug.md and spec.md are in the tree may be fixed without a plan.
# Code is anything but changes/, docs/ and top-level *.md. Other branches aren't checked.
# A repo whose CLAUDE.md has the line `Bug path: full` turns the fast path off (#160): then a bug
# needs its plan.md too. CI passes main's CLAUDE.md in SDLC_CLAUDE_MD, so a PR can't turn the
# setting off for itself; without it, ./CLAUDE.md is read.
set -uo pipefail

branch="${1:-}"
slug="$(grep -oE '[0-9]{4}-[a-z0-9]+(-[a-z0-9]+)*' <<<"$branch" | head -1 || true)"
if [[ -z "$slug" || ! -d "changes/$slug" ]]; then
  echo "ok: $branch isn't a change's branch"
  exit 0
fi

code=""
while IFS= read -r path; do
  case "$path" in
    "" | changes/* | docs/*) continue ;;
    */*) ;;
    *.md) continue ;;
  esac
  code="$path"
  break
done

if [[ -z "$code" ]]; then
  echo "ok: $slug, no code changed"
  exit 0
fi
if [[ -f "changes/$slug/plan.md" ]]; then
  echo "ok: $slug has its plan.md"
  exit 0
fi
if [[ "$branch" == "build/$slug" && -f "changes/$slug/bug.md" && -f "changes/$slug/spec.md" ]]; then
  if grep -qE '^(- )?Bug path: *full[[:space:]]*$' "${SDLC_CLAUDE_MD:-CLAUDE.md}" 2>/dev/null; then
    echo "::error::This PR fixes bug $slug without a plan.md (the bug fast path), but this repo's" \
      "CLAUDE.md says 'Bug path: full'. Plan it with /sdlc-plan and merge the plan PR first."
    exit 1
  fi
  echo "ok: $slug is a bug with its spec, on the fast path (#148)"
  exit 0
fi
echo "::error::This PR changes code ($code, …) for $slug, which has no plan.md yet." \
  "Save the plan with /sdlc-plan and merge its plan PR first, then build on build/$slug."
exit 1
