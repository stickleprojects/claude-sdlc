#!/usr/bin/env bash
# Which files that set CI's rules does a PR change? (ADR 0001, #293)
#
# Usage: .sdlc/scripts/ci-changes.sh <base> <head> [--digest]
#        .sdlc/scripts/ci-changes.sh --filter    paths on stdin; prints those on the list
#
# Prints, one per line, each file on the approval list that changed between <base> and <head>'s
# merge base and <head>: added, changed, deleted, or either side of a rename. The list:
#   - everything under .github/ (workflows, actions, dependabot.yml, CODEOWNERS, actions.lock);
#   - .sdlc/hooks/**, the agent's guardrails;
#   - .claude/settings.json, which wires those hooks in;
#   - uv.lock.
# They decide what runs in CI, with what permissions, who approves and what the agent may do. A
# change to one gets a `CI change: needs approval` thread on the PR, and only a person's
# `Approved: <name>, <date>` reply settles it (descopes-decided.sh).
#
# --digest prints one hash of those files' diff instead, so a new thread can be posted when the
# change differs from the one a person approved. It prints nothing when no file on the list
# changed. --filter is for a caller that has the PR's file list but not its commits
# (auto-merge.sh).
#
# Reads only git objects: it runs nothing from either commit, so it's safe on a PR's head.
# Exits 0 (with an empty list when nothing on the list changed), 2 on bad usage, 3 when git
# can't compare the two commits.
set -uo pipefail

on_the_list() {  # stdin: paths; stdout: those on the list. -z: NUL-ended in and out
  local path delim=$'\n' end='\n'
  [[ "${1:-}" == -z ]] && delim='' end='\0'
  while IFS= read -r -d "$delim" path || [[ -n "$path" ]]; do
    case "$path" in
      .github/* | .sdlc/hooks/* | .claude/settings.json | uv.lock) printf "%s$end" "$path" ;;
    esac
  done
}

if [[ "${1:-}" == --filter && $# -eq 1 ]]; then
  on_the_list
  exit 0
fi

base="${1:-}"
head="${2:-}"
mode="${3:-}"
[[ -n "$base" && -n "$head" && ( -z "$mode" || "$mode" == --digest ) ]] \
  || { sed -n '2,24p' "$0" >&2; exit 2; }

fork="$(git merge-base "$base" "$head" 2>/dev/null)" \
  || { echo "ci-changes: can't find where $head forked from $base" >&2; exit 3; }
# -z: without it git quotes a name with unusual characters, and the quoted name would miss the list.
changed="$(mktemp)"
trap 'rm -f "$changed"' EXIT
git diff --no-renames --name-only -z "$fork" "$head" > "$changed" 2>/dev/null \
  || { echo "ci-changes: can't compare $fork with $head" >&2; exit 3; }

mapfile -t -d '' files < <(on_the_list -z < "$changed")

((${#files[@]})) || exit 0
if [[ "$mode" == --digest ]]; then
  diff="$(git --literal-pathspecs diff --no-renames "$fork" "$head" -- "${files[@]}")" \
    || { echo "ci-changes: can't diff $fork with $head" >&2; exit 3; }
  sha256sum <<<"$diff" | cut -c1-16
else
  printf '%s\n' "${files[@]}"
fi
