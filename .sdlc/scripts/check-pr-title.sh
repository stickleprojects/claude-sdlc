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
#
# The bug fast path (#148, #154) is the exception: one PR carries a bug's bug.md, its spec.md
# (and a plan.md, if it has one), the failing tests and the fix. Merging it ships the fix, so
# it's titled `fix(<slug>): …`, which puts it under Bug fixes in the release notes. That holds
# only when every gate artifact it changes is that change's bug.md, spec.md or plan.md, bug.md
# is one of them, and the PR also changes code (anything but changes/, docs/ and top-level *.md,
# as in check-plan-first.sh).
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
scope="${BASH_REMATCH[2]#(}"
scope="${scope%)}"

files="$(cat)"
gate_files="$(grep -E '^changes/[^/]+/(intent|bug|spec|plan)\.md$' <<<"$files" || true)"
gates="$(sed -nE 's#^changes/[^/]+/(intent|bug|spec|plan)\.md$#\1#p' <<<"$gate_files" | sort -u | paste -sd ' ' -)"

# The fast path: only one change's bug.md (always), spec.md and plan.md, plus code.
fast_path_slug() {
  local slug
  slug="$(sed -nE 's#^changes/([^/]+)/bug\.md$#\1#p' <<<"$gate_files" | head -1)"
  [[ -n "$slug" ]] || return 1
  grep -qvE "^changes/$slug/(bug|spec|plan)\.md$" <<<"$gate_files" && return 1
  grep -vE '^(changes/|docs/)' <<<"$files" | grep -qvE '^[^/]+\.md$' || return 1
  echo "$slug"
}

if [[ -n "$gates" && "$type" == fix ]] && slug="$(fast_path_slug)" && [[ "$scope" == "$slug" ]]; then
  echo "ok: $title (the bug fast path for $slug)"
  exit 0
fi
if [[ -n "$gates" && " $gates " != *" $type "* ]]; then
  if slug="$(fast_path_slug)"; then
    echo "::error::This PR carries $slug's bug report, spec and fix (the bug fast path), so" \
      "title it 'fix($slug): <summary>'."
    echo "Got: $title"
    exit 1
  fi
  artifacts="$(sed -E 's/([a-z]+)/\1.md/g; s/ /, /g' <<<"$gates")"
  echo "::error::This PR changes a gate artifact ($artifacts), so its type must say so:" \
    "use ${gates// / or }, e.g. '${gates%% *}(<slug>): <summary>'."
  echo "Got: $title"
  exit 1
fi
echo "ok: $title"
