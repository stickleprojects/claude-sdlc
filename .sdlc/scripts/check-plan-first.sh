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
# A change's branch without its number (build/x for changes/0007-x) fails when it has code (#185).
# A repo whose CLAUDE.md has the line `Bug path: full` turns the fast path off (#160): then a bug
# needs its plan.md too. CI passes main's CLAUDE.md in SDLC_CLAUDE_MD, so a PR can't turn the
# setting off for itself; without it, ./CLAUDE.md is read.
# A tooling change (#221, intent.md says `Kind: tooling`) has no spec, so its code may touch only
# the paths main's CLAUDE.md lists on a `Tooling paths:` line (space-separated; an entry ending in
# / is a folder). With no such line, the tooling path is off and a tooling change's code fails.
# A build PR (from build/<slug>) ships the change, so its change.toml must say done (#272). A
# folder with no change.toml passes for now.
set -uo pipefail

branch="${1:-}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
code_paths=()
while IFS= read -r path; do
  case "$path" in
    "" | changes/* | docs/*) continue ;;
    */*) ;;
    *.md) continue ;;
  esac
  code_paths+=("$path")
done
code="${code_paths[0]:-}"

slug="$(grep -oE '[0-9]{4}-[a-z0-9]+(-[a-z0-9]+)*' <<<"$branch" | head -1 || true)"
if [[ -z "$slug" || ! -d "changes/$slug" ]]; then
  # build/price-decimals for changes/0007-price-decimals: without the number nothing matches,
  # and the checks below would silently pass its code (#185).
  if [[ -n "$code" && "$branch" =~ ^(build|plan|spec|bug)/([a-z0-9]+(-[a-z0-9]+)*)$ ]]; then
    for dir in changes/[0-9][0-9][0-9][0-9]-"${BASH_REMATCH[2]}"; do
      [[ -d "$dir" ]] || continue
      echo "::error::The branch $branch leaves out the change number, so it doesn't match" \
        "${dir#changes/}. Push it as ${BASH_REMATCH[1]}/${dir#changes/} and open the PR from that."
      exit 1
    done
  fi
  echo "ok: $branch isn't a change's branch"
  exit 0
fi

require_done() {  # a build PR's change.toml says done, so merging it makes that true
  local status
  [[ "$branch" == "build/$slug" ]] || return 0
  if ! status="$(PYTHONPATH="$here/.sdlc/src" python3 -m sdlc.cli change-status "changes/$slug")"; then
    echo "::error::changes/$slug/change.toml can't be read, so its status can't be checked."
    exit 1
  fi
  [[ "$status" == done || "$status" == none ]] && return 0
  echo "::error::This PR builds $slug, but its change.toml says $status. Run" \
    "'make sync-changes CHANGE=$slug STATUS=done FIX=1' and commit it, so merging marks it done."
  exit 1
}

if [[ -z "$code" ]]; then
  echo "ok: $slug, no code changed"
  exit 0
fi
if ! kind="$(PYTHONPATH="$here/.sdlc/src" python3 -m sdlc.cli kind "changes/$slug")"; then
  echo "::error::Couldn't read the kind of change $slug (python3 -m sdlc.cli kind), so the" \
    "plan check can't run."
  exit 1
fi
if [[ "$kind" == tooling ]]; then
  allowed="$(sed -nE 's/^(- )?Tooling paths: *(.*[^[:space:]])[[:space:]]*$/\2/p' \
    "${SDLC_CLAUDE_MD:-CLAUDE.md}" 2>/dev/null | tail -1)"
  if [[ -z "$allowed" ]]; then
    echo "::error::$slug is a tooling change (Kind: tooling), but this repo's CLAUDE.md has no" \
      "'Tooling paths:' line, so the tooling path is off. Take the full path (a spec, then" \
      "the plan), or add the line on main first."
    exit 1
  fi
  read -ra prefixes <<<"$allowed"
  outside=()
  for path in "${code_paths[@]}"; do
    ok=""
    for prefix in "${prefixes[@]}"; do
      if [[ "$prefix" == */ ]]; then
        [[ "$path" == "$prefix"* ]] && ok=1
      else
        [[ "$path" == "$prefix" || "$path" == "$prefix/"* ]] && ok=1
      fi
      [[ -n "$ok" ]] && break
    done
    [[ -n "$ok" ]] || outside+=("$path")
  done
  if ((${#outside[@]})); then
    echo "::error::$slug is a tooling change (Kind: tooling), but it changes code outside" \
      "'Tooling paths: $allowed': ${outside[*]:0:3}$( ((${#outside[@]} > 3)) && echo ' …')." \
      "Move that code out of this change, or take the full path with a spec."
    exit 1
  fi
fi
if [[ -f "changes/$slug/plan.md" ]]; then
  require_done
  [[ "$kind" == tooling ]] && echo "ok: $slug is a tooling change inside 'Tooling paths: $allowed'"
  echo "ok: $slug has its plan.md"
  exit 0
fi
if [[ "$branch" == "build/$slug" && -f "changes/$slug/bug.md" && -f "changes/$slug/spec.md" ]]; then
  if grep -qE '^(- )?Bug path: *full[[:space:]]*$' "${SDLC_CLAUDE_MD:-CLAUDE.md}" 2>/dev/null; then
    echo "::error::This PR fixes bug $slug without a plan.md (the bug fast path), but this repo's" \
      "CLAUDE.md says 'Bug path: full'. Plan it with /sdlc-plan and merge the plan PR first."
    exit 1
  fi
  require_done
  echo "ok: $slug is a bug with its spec, on the fast path (#148)"
  exit 0
fi
echo "::error::This PR changes code ($code, …) for $slug, which has no plan.md yet." \
  "Save the plan with /sdlc-plan and merge its plan PR first, then build on build/$slug."
exit 1
