#!/usr/bin/env bash
# Did a push to main change only docs? (#240) With the repo variable SDLC_MAIN_DOCS_SKIP=on,
# sdlc-ci.yml then runs `make validate` on main instead of `make check FULL=1`.
#
# Usage: .sdlc/scripts/main-docs-only.sh <before> <after>    the push's two commits
#   exit 0, printing why: every changed path is docs, so validate is enough
#   exit 1, printing why: run everything (code changed, nothing to compare, or the diff
#                         can't be read)
#
# Docs are what no build or test reads: docs/**, changes/** (intents, specs, plans, build
# plans, which `make validate` checks) and a *.md file at the top level. Everything else is
# code, nested *.md included, the same split as check-plan-first.sh. A squash merge and a merge
# commit are judged the same way, from <before> to <after>. When unsure, run everything: the
# full run on main is the safety net that catches what a PR's lighter check missed.
set -uo pipefail

before="${1:-}"
after="${2:-}"
full() {
  echo "$1"
  exit 1
}

[[ "$before" =~ ^[0-9a-f]{7,40}$ && "$after" =~ ^[0-9a-f]{7,40}$ ]] \
  || full "no commits to compare ('$before'..'$after'): run everything"
[[ "$before" =~ ^0+$ ]] && full "the push has no earlier commit: run everything"
git cat-file -e "$before^{commit}" 2>/dev/null || full "can't find $before (a shallow clone?): run everything"
changed="$(git diff --name-only "$before" "$after" 2>/dev/null)" \
  || full "can't list the files changed in $before..$after: run everything"
[[ -n "$changed" ]] || full "nothing changed in $before..$after: run everything"

n=0
while IFS= read -r path; do
  n=$((n + 1))
  case "$path" in
    changes/* | docs/*) continue ;;
    */*) ;;
    *.md) continue ;;
  esac
  full "$path is code: run everything"
done <<<"$changed"
echo "docs only: $n file(s) in docs/, changes/ or top-level *.md, so make validate is enough"
