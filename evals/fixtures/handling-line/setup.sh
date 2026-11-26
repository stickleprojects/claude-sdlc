#!/usr/bin/env bash
# Setup for the handling-line evals (#289): a repo with `Change tracking: issues` in ./handling,
# on branch fix/greeting-space (PR 41), whose one commit fixes a missing space and adds its
# test. Usage: setup.sh clean|unexplained, the PR body to use: one that links its issue and says
# how it was tested (nothing to find), or "Small fix." (an Important finding: no issue, no
# explanation).
set -euo pipefail
variant="${1:?usage: setup.sh clean|unexplained}"
src="evals/fixtures/handling-line"
mkdir -p handling/app handling/tests
cd handling
git init -q -b main
git config user.name eval
git config user.email eval@example.invalid
cp "../$src/CLAUDE.md" CLAUDE.md
touch app/__init__.py
cp "../$src/greet_old.py" app/greet.py
git add -A && git commit -q -m "feat: greet a visitor by name"
git switch -q -c fix/greeting-space
cp "../$src/greet_new.py" app/greet.py
cp "../$src/test_greet.txt" tests/test_greet.py  # .txt: ruff would lint it here
git add -A && git commit -q -m "fix: a space after the greeting's comma"
cp "../$src/pr-body-$variant.md" pr-body.md
echo '[]' > .review-threads.json
