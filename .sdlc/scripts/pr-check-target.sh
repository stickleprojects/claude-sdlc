#!/usr/bin/env bash
# Which make target a PR's `check` runs (#244): $SDLC_PR_CHECK_TARGET, or `check`.
#
# Usage: .sdlc/scripts/pr-check-target.sh     prints the target; run from the repo root
#
# A project with a slow `make check` can give PRs a lighter tier (`make check-pr`, say) by
# setting the repo variable SDLC_PR_CHECK_TARGET. sdlc-ci.yml and sdlc-check-after-review.yml
# run that target on a PR. A push to main still runs `make check FULL=1`, and `make check`
# stays the full check everywhere else (the build, the verifier, the pre-PR rule).
#
# The value must be a plain make target name, and the Makefile must define it: a typo fails
# here, naming the variable, rather than as make's "No rule to make target". The workflows pass
# it through `env`, never `${{ }}` in the script, so it can't inject shell.
set -euo pipefail

target="${SDLC_PR_CHECK_TARGET:-check}"
if ! [[ "$target" =~ ^[a-z][a-z0-9-]*$ ]]; then
  echo "::error::SDLC_PR_CHECK_TARGET is '$target', which isn't a make target name" \
    "(lower-case letters, digits and -). Fix the repo variable, or delete it to run 'check'." >&2
  exit 1
fi
# make's database, without running anything: -q runs no recipes, -p prints the rules.
db="$(make -pRrq 2>/dev/null || true)"
if ! grep -qE "^${target}:" <<<"$db"; then
  echo "::error::SDLC_PR_CHECK_TARGET is '$target', but the Makefile has no '$target' target." \
    "Add it, or delete the repo variable to run 'check'." >&2
  exit 1
fi
echo "$target"
