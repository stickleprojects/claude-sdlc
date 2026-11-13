#!/usr/bin/env bash
# The check for a bug that should take the fast path (#148, #160), run in the eval's consumer
# after the agent stops. It holds the agent to what .sdlc/docs/bug-fast-path.md promises:
# one branch with the bug report, its spec, failing tests committed before the fix, no plan;
# CI's title and plan checks pass; and once merged, `make next` shows the bug done.
set -uo pipefail
fail() { echo "check: $*"; git log --oneline --all 2>/dev/null | head -20 | sed 's/^/      /'; exit 1; }

slug="$(ls changes 2>/dev/null | grep -E '^[0-9]{4}-' | head -1)"
[[ -n "$slug" ]] || fail "no change folder"
dir="changes/$slug"
branch="$(git branch --show-current)"
[[ "$branch" == "build/$slug" ]] || fail "on '$branch', not build/$slug"
for f in bug.md spec.md; do
  git cat-file -e "HEAD:$dir/$f" 2>/dev/null || fail "$dir/$f isn't committed on the branch"
done
for f in plan.md build.md; do
  git cat-file -e "HEAD:$dir/$f" 2>/dev/null && fail "$dir/$f exists: the fast path has no plan"
done

test_sha="$(git log --format=%H -E --grep="^test\($slug\)" main..HEAD | tail -1)"
fix_sha="$(git log --format=%H -E --grep="^fix\($slug\)" main..HEAD | head -1)"
[[ -n "$test_sha" ]] || fail "no test($slug): commit"
[[ -n "$fix_sha" ]] || fail "no fix($slug): commit"
git merge-base --is-ancestor "$test_sha" "$fix_sha" || fail "the fix comes before the failing tests"
git diff --name-only "$test_sha^" "$test_sha" | grep -q '^app/' && fail "the test commit changes app/ too"

# Failing first, proven by running them: the tests at the test commit fail, at HEAD they pass.
tree="$(mktemp -d)"
git worktree add -q --detach "$tree" "$test_sha" || fail "can't check out the test commit"
if (cd "$tree" && make -s test >/dev/null 2>&1); then
  git worktree remove --force "$tree"
  fail "the tests at the test($slug) commit pass: they don't show the bug"
fi
git worktree remove --force "$tree"
make -s check >/dev/null 2>&1 || fail "make check fails at HEAD"
python3 -c 'import sys; sys.path.insert(0, "."); from app.prices import format_price as f; sys.exit(f(150) != "$1.50")' \
  || fail "150 cents still doesn't show as \$1.50"

# What CI checks on the PR.
files="$(git diff --name-only main...HEAD)"
[[ -s pr-title.txt ]] || fail "no pr-title.txt"
title="$(head -1 pr-title.txt)"
.sdlc/scripts/check-pr-title.sh "$title" <<<"$files" >/dev/null || fail "CI's title check refuses '$title'"
.sdlc/scripts/check-plan-first.sh "build/$slug" <<<"$files" >/dev/null || fail "CI's plan check refuses it"

# Merged the way GitHub merges it, `make next` shows the bug fixed.
git checkout -q main
git merge -q --no-ff -m "Merge pull request #1 from o/build/$slug" "build/$slug" || fail "merge failed"
make -s next | grep -qF "$slug	spec	done	fixed on the fast path" || fail "make next: $(make -s next)"
echo "check: $slug took the fast path"
