#!/usr/bin/env bash
# Does this branch need the scenario tests (tests/test_scenario.py)? The framework repo's
# `make check` leaves those slow tests out of a PR unless it does: they install the framework
# into a consumer repo, so any change to what's synced, installed or run there needs them
# before merge, not only on main afterwards. Framework-only: never synced to consumers.
#
# Usage: scripts/scenario-needed.sh [base]    base defaults to origin/main
#   exit 0, printing why: run the scenario tests
#   exit 1, printing why: every changed path is one they can't be affected by; leave them out
#
# Compared like scripts/docs-only.sh: from the merge base with `base` to the working tree,
# untracked files included. The scenario tests can't be affected by:
#   - docs/** and a top-level *.md file (documentation);
#   - tests/** other than the scenario tests themselves, their fixtures and conftest.py.
# Everything else (.sdlc/, .github/, .claude/, scripts/, pyproject.toml, uv.lock, Makefile...)
# needs them. When unsure, run them.
set -uo pipefail

base="${1:-origin/main}"
needed() {
  echo "$1"
  exit 0
}

git rev-parse --verify --quiet "$base^{commit}" >/dev/null || needed "can't find $base to compare with"
merge_base="$(git merge-base "$base" HEAD 2>/dev/null)" || needed "no merge base with $base (a shallow clone?)"
tracked="$(git diff --name-only "$merge_base" 2>/dev/null)" || needed "can't list the files changed since $base"
untracked="$(git ls-files --others --exclude-standard 2>/dev/null)" || needed "can't list untracked files"
changed="$(printf '%s\n%s\n' "$tracked" "$untracked" | sed '/^$/d')"
[[ -n "$changed" ]] || needed "nothing changed since $base"

while IFS= read -r path; do
  case "$path" in
    tests/test_scenario.py | tests/conftest.py | tests/fixtures/*) needed "$path changed" ;;
    docs/* | tests/*) ;;
    */*) needed "$path changed" ;;
    *.md) ;;
    *) needed "$path changed" ;;
  esac
done <<<"$changed"
echo "only documentation and other tests changed since $base"
exit 1
