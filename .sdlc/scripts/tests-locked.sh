#!/usr/bin/env bash
# Are tests locked in this checkout? Lets bug fixes lock their tests without anyone having to
# remember SDLC_LOCK_TESTS=1.
#
# Usage: .sdlc/scripts/tests-locked.sh [path]
#   Exit 0 and print the reason when tests are locked (and, given a path, it is a test file).
#   Exit 1 otherwise.
#
# Tests are locked when:
#   - SDLC_LOCK_TESTS=1 (set by hand): every test file; SDLC_LOCK_TESTS=0 always unlocks; or
#   - the change being worked on is a bug (changes/<slug>/bug.md exists) and this branch
#     already has its failing-test commit, `test(<slug>): …`, since it left main. Then only
#     the files that commit added or changed are locked: the build still writes new tests
#     (coverage, regression guards) in other files. Before that commit the test is still
#     being written, so it stays editable.
#
# The change is $SDLC_CHANGE, or the NNNN-name slug in the branch name (build/0003-x,
# fix/0003-x, …) or in the worktree folder's name, when changes/<slug>/ exists.
set -euo pipefail

path="${1:-}"
top="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 1
cd "$top"

is_test_path() {
  case "$1" in
    tests/*|*/tests/*|test/*|*/test/*|*/__tests__/*|e2e/*|*/e2e/*) return 0 ;;
    *.test.*|*.spec.*|test_*.py|*/test_*.py|*_test.py|*_test.go) return 0 ;;
  esac
  return 1
}

locked() {  # print why, exit 0, if the path (when given) is a test file
  if [[ -n "$path" ]] && ! is_test_path "$path"; then exit 1; fi
  echo "$1"
  exit 0
}

case "${SDLC_LOCK_TESTS:-}" in
  1) locked "SDLC_LOCK_TESTS=1 is set." ;;
  0) exit 1 ;;
esac

slug="${SDLC_CHANGE:-}"
if [[ -z "$slug" ]]; then
  for name in "$(git branch --show-current 2>/dev/null || true)" "$(basename "$top")"; do
    candidate="$(grep -oE '[0-9]{4}-[a-z0-9]+(-[a-z0-9]+)*' <<<"$name" | head -1 || true)"
    if [[ -n "$candidate" && -d "changes/$candidate" ]]; then slug="$candidate"; break; fi
  done
fi
[[ -n "$slug" && -f "changes/$slug/bug.md" ]] || exit 1

base=""
for ref in origin/main main; do
  base="$(git merge-base "$ref" HEAD 2>/dev/null)" && break
done
range="${base:+$base..}HEAD"
# The files the failing-test commit(s) touched; those, and only those, are locked.
files="$(git log --format='%H %s' "$range" 2>/dev/null \
  | awk -v s="$slug" 'index($2, "test(" s ")") == 1 {print $1}' \
  | xargs -r -n1 git diff-tree --no-commit-id --name-only -r | sort -u)"
[[ -n "$files" ]] || exit 1
why="$slug is a bug fix and its failing test is committed (test($slug): …); locked: ${files//$'\n'/, }."
if [[ -n "$path" ]]; then
  grep -qxF -- "$path" <<<"$files" || exit 1
  echo "$why"
  exit 0
fi
echo "$why"
exit 0
