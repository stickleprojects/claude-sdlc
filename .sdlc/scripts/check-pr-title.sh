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
#
# A build PR that amends its plan (#174) is the other exception, only when the repo variable
# SDLC_BUILD_AMENDS_PLAN is `on`: a feat or fix PR may carry one change's plan.md and spec.md with
# its code when its body lists them under a `## Plan changes` heading. A person still approves
# them, in the review's "Plan changes: needs approval" thread (descopes-decided.sh).
#
# A tooling change (#221) is the third: one PR carries a change's intent.md (whose `Kind: tooling`
# line the tree holds) and plan.md with its code, and no spec. Merging it ships tooling, not a
# feature or a fix, so it's titled `chore(<slug>): …` or `ci(<slug>): …`. Which paths its code
# may touch is check-plan-first.sh's job. Run from the PR's checkout, so the tree has intent.md.
#
# Env: SDLC_BUILD_AMENDS_PLAN (`on` or anything else), SDLC_PR_BODY_FILE (the PR's body).
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

# A tooling PR: only one change's intent.md and plan.md, plus code, and the change's intent says
# `Kind: tooling` (read by the sdlc tool, so a commented-out example doesn't count). Prints the slug.
tooling_slug() {
  local slug here
  slug="$(sed -nE 's#^changes/([^/]+)/(intent|plan)\.md$#\1#p' <<<"$gate_files" | sort -u)"
  [[ -n "$slug" && "$slug" != *$'\n'* ]] || return 1
  grep -qvE "^changes/$slug/(intent|plan)\.md$" <<<"$gate_files" && return 1
  grep -vE '^(changes/|docs/)' <<<"$files" | grep -qvE '^[^/]+\.md$' || return 1
  [[ -d "changes/$slug" ]] || return 1
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  [[ "$(PYTHONPATH="$here/.sdlc/src" python3 -m sdlc.cli kind "changes/$slug" 2>/dev/null)" == tooling ]] \
    || return 1
  echo "$slug"
}

# A build PR amending its plan: one change's spec.md and plan.md, plus code. Prints the slug.
amended_slug() {
  local slug
  [[ "${SDLC_BUILD_AMENDS_PLAN:-}" == on ]] || return 1
  slug="$(sed -nE 's#^changes/([^/]+)/(spec|plan)\.md$#\1#p' <<<"$gate_files" | sort -u)"
  [[ -n "$slug" && "$slug" != *$'\n'* ]] || return 1
  grep -qvE "^changes/$slug/(spec|plan)\.md$" <<<"$gate_files" && return 1
  grep -vE '^(changes/|docs/)' <<<"$files" | grep -qvE '^[^/]+\.md$' || return 1
  echo "$slug"
}
plan_changes_listed() {
  [[ -n "${SDLC_PR_BODY_FILE:-}" && -f "$SDLC_PR_BODY_FILE" ]] \
    && grep -qiE '^##+ *Plan changes' "$SDLC_PR_BODY_FILE"
}

if [[ -n "$gates" ]] && slug="$(tooling_slug)"; then
  if [[ ( "$type" == chore || "$type" == ci ) && "$scope" == "$slug" ]]; then
    echo "ok: $title (the tooling path for $slug)"
    exit 0
  fi
  echo "::error::This PR carries $slug's intent, plan and code (the tooling path, Kind: tooling)," \
    "so title it 'chore($slug): <summary>' or 'ci($slug): <summary>'."
  echo "Got: $title"
  exit 1
fi
if [[ -n "$gates" && ( "$type" == feat || "$type" == fix ) ]] && slug="$(amended_slug)"; then
  if plan_changes_listed; then
    echo "ok: $title (a build PR amending $slug's plan, SDLC_BUILD_AMENDS_PLAN)"
    exit 0
  fi
  echo "::error::This PR amends $slug's plan or spec with its code. List each amendment under a" \
    "'## Plan changes' heading in the PR body, or move them to a plan or spec PR."
  echo "Got: $title"
  exit 1
fi
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
