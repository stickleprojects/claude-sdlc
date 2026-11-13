#!/usr/bin/env bash
# Is this branch documentation only? (#140) The framework repo's `make check` skips the test
# suite when it is. Framework-only: never synced to consumers, which keep their own `check`.
#
# Usage: scripts/docs-only.sh [base]    base defaults to origin/main
#   exit 0, printing why: every changed path is documentation; skip the tests
#   exit 1, printing why: run everything (a code change, no changes, or no diff to go on)
#
# The branch is compared from its merge base with `base` to the working tree, untracked files
# included, so a local run before committing sees the same change CI will. Documentation is
# what no test reads:
#   - docs/**, except docs/release-notes/ (the release tests read those);
#   - a *.md file at the top level (readme.md, CLAUDE.md).
# Everything else is code, .sdlc/**/*.md included: skills, templates, prompts and REVIEW.md
# are what the tests check. When unsure, run everything.
set -uo pipefail

base="${1:-origin/main}"
full() {
  echo "$1"
  exit 1
}

git rev-parse --verify --quiet "$base^{commit}" >/dev/null || full "can't find $base to compare with"
merge_base="$(git merge-base "$base" HEAD 2>/dev/null)" || full "no merge base with $base (a shallow clone?)"
tracked="$(git diff --name-only "$merge_base" 2>/dev/null)" || full "can't list the files changed since $base"
untracked="$(git ls-files --others --exclude-standard 2>/dev/null)" || full "can't list untracked files"
changed="$(printf '%s\n%s\n' "$tracked" "$untracked" | sed '/^$/d')"
[[ -n "$changed" ]] || full "nothing changed since $base"

n=0
while IFS= read -r path; do
  case "$path" in
    docs/release-notes/*) full "$path changed (the release tests read release notes)" ;;
    docs/*) ;;
    */*) full "$path changed" ;;
    *.md) ;;
    *) full "$path changed" ;;
  esac
  ((n += 1))
done <<<"$changed"
if ((n == 1)); then
  echo "only documentation changed since $base (1 file)"
else
  echo "only documentation changed since $base ($n files)"
fi
