#!/usr/bin/env bash
# Setup for the re-review eval (#160): a git repo in ./rereview whose first commit has the spec
# an earlier review saw, then a commit that covers exactly what that review's thread listed and
# rewords R2. earlier-threads.json is that review's thread, as `gh api …/pulls/N/comments`
# returns it, pointing at the first commit.
set -euo pipefail
src="evals/fixtures/clause-one-pass/rereview"
mkdir -p rereview/changes/0001-hero-docs
cd rereview
git init -q -b main
git config user.name eval
git config user.email eval@example.invalid
cp "../$src/spec-before.md" changes/0001-hero-docs/spec.md
git add -A && git commit -q -m "spec(0001-hero-docs): first draft"
before="$(git rev-parse HEAD)"
cp "../$src/spec-after.md" changes/0001-hero-docs/spec.md
git commit -qam "spec(0001-hero-docs): cover the clauses the review listed; R2 adds the error case"
sed "s/SHA_BEFORE/$before/" "../$src/earlier-threads.json" > earlier-threads.json
