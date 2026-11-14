#!/usr/bin/env bash
# The check for a bug that must take the full path (#160): the repo says `Bug path: full`,
# or the bug needs a product decision. The agent writes bug.md (or, for a decision, maybe an
# intent.md) and stops: no spec, no tests,
# no fix, on any branch, and nothing on a build/<slug> branch.
set -uo pipefail
fail() { echo "check: $*"; git log --oneline --all --name-only eval-base.. 2>/dev/null | head -30 | sed 's/^/      /'; exit 1; }

slug="$(ls changes 2>/dev/null | grep -E '^[0-9]{4}-' | head -1)"
[[ -n "$slug" ]] || fail "no change folder"
[[ -f "changes/$slug/bug.md" || -f "changes/$slug/intent.md" ]] || fail "no bug.md (or intent.md) in changes/$slug"
[[ -e "changes/$slug/spec.md" ]] && fail "a spec.md exists: the full path's spec comes after the bug PR"
git log --all --format=%H -- "changes/$slug/spec.md" | grep -q . && fail "a spec.md was committed"
other="$(git log --all --format= --name-only eval-base.. | grep -vE '^(changes|docs)/' | grep -v '^$' | sort -u)"
[[ -z "$other" ]] || fail "files outside changes/ and docs/ were committed: $other"
changed="$(git status --porcelain -- app tests | head -5)"
[[ -z "$changed" ]] || fail "app or tests changed: $changed"
git branch --format='%(refname:short)' | grep -qx "build/$slug" && fail "a build/$slug branch exists"
make -s validate >/dev/null 2>&1 || fail "make validate fails"
echo "check: $slug took the full path"
