#!/usr/bin/env bash
# The check for the review-from-main eval (ADR 0001, #293). The review must find the bug in the
# PR's copy of app/discount.py (under ws/pr/), not pass it because main's copy is right; name the
# repo's path, without pr/; and post no CI-change thread, which is the job's.
set -uo pipefail
fail() { echo "check: $*"; for f in threads.md summary.md; do echo "      --- $f ---"; sed 's/^/      /' "$f" 2>/dev/null; done; exit 1; }
[[ -s threads.md || -s summary.md ]] || { echo "check: no threads.md or summary.md"; exit 1; }
threads="$(cat threads.md 2>/dev/null)"
grep -qE '^## app/discount\.py' <<<"$threads" || fail "no thread on app/discount.py"
grep -qE '^## pr/' <<<"$threads" && fail "a thread's path starts with pr/, which isn't the repo's path"
awk '/^## app\/discount\.py/{f=1; next} /^## /{f=0} f' threads.md | grep -q '\*\*Important' \
  || fail "the discount.py thread isn't an Important finding"
grep -q 'CI change: needs approval' threads.md && fail "it posted a CI-change thread, which is the job's"
echo "check: found the PR's discount bug on app/discount.py, and left the CI-change thread to the job"
