#!/usr/bin/env bash
# Check a PR title: conventional-commit form, and a type that says which gate artifact it changes.
#
# Usage: .sdlc/scripts/check-pr-title.sh <title>      the PR's changed files on stdin, one per line
#
# Titles drive the version (scripts/next-version.sh) and the release notes, so they follow the
# convention: `type: summary`, `type(scope): summary`, `type!: summary` for a breaking change.
# And a PR that changes a gate artifact says so in its type (#46), so the merge record shows
# that an intent, bug, spec or plan was accepted, not hidden under `docs:` or `feat:`:
#   changes/<slug>/intent.md -> intent   bug.md -> bug   spec.md -> spec   plan.md -> plan
# A PR that changes several of them may use any of their types. build.md isn't a gate artifact.
set -uo pipefail

title="${1:-}"
types='feat|fix|docs|chore|ci|refactor|test|perf|build|revert|intent|bug|spec|plan'
if ! [[ "$title" =~ ^($types)(\([a-z0-9-]+\))?!?:\ .+ ]]; then
  echo "::error::PR title must look like 'type: summary' or 'type!: summary' (breaking)."
  echo "Types: ${types//|/, }. feat bumps the minor version, ! marks a breaking change."
  echo "Got: $title"
  exit 1
fi
type="${BASH_REMATCH[1]}"

gates="$(sed -nE 's#^changes/[^/]+/(intent|bug|spec|plan)\.md$#\1#p' | sort -u | paste -sd ' ' -)"
if [[ -n "$gates" && " $gates " != *" $type "* ]]; then
  artifacts="$(sed -E 's/([a-z]+)/\1.md/g; s/ /, /g' <<<"$gates")"
  echo "::error::This PR changes a gate artifact ($artifacts), so its type must say so:" \
    "use ${gates// / or }, e.g. '${gates%% *}(<slug>): <summary>'."
  echo "Got: $title"
  exit 1
fi
echo "ok: $title"
