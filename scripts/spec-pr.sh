#!/usr/bin/env bash
# One spec PR per change, for .github/workflows/spec-from-intent.yml.
#
# Usage: scripts/spec-pr.sh pending
#          Print each change folder that needs a spec: it has intent.md or bug.md, has no
#          spec.md here, and has no open PR from its branch spec/<slug>. A change whose spec PR
#          is already open is skipped, so a second run never regenerates (and makes stale) a
#          spec someone is reviewing.
#        scripts/spec-pr.sh open <change-dir>...
#          For each folder with a generated spec.md: commit it alone on spec/<slug> (from the
#          current commit), push, open a PR named after the slug, and close any older
#          run-numbered spec PR (spec/<digits>) that carried the same change as superseded.
#          Then scripts/auto-merge.sh turns on auto-merge where the repo opted in (#89).
#
# Env: GITHUB_REPOSITORY (owner/name); gh must be authenticated (GH_TOKEN in Actions).
# A GitHub API error stops the script: guessing "no open PR" would open a duplicate.
set -euo pipefail

repo="${GITHUB_REPOSITORY:?set GITHUB_REPOSITORY=owner/name}"
owner="${repo%%/*}"

open_pr_from() {  # the open PR's number for branch $1, or nothing
  gh api "repos/$repo/pulls?state=open&head=$owner:$1" --jq '.[0].number // empty'
}

pending() {
  local d slug n
  for d in changes/*/; do
    d="${d%/}"
    [[ -f "$d/intent.md" || -f "$d/bug.md" ]] || continue
    [[ -f "$d/spec.md" ]] && continue
    slug="${d#changes/}"
    n="$(open_pr_from "spec/$slug")"
    if [[ -n "$n" ]]; then
      echo "skip $d: spec PR #$n is already open" >&2
      continue
    fi
    echo "$d"
  done
}

close_superseded() {  # $1 = change dir, $2 = new PR number
  local old
  for old in $(gh api "repos/$repo/pulls?state=open&per_page=100" \
    --jq '.[] | select(.head.ref | test("^spec/[0-9]+$")) | .number'); do
    if gh api "repos/$repo/pulls/$old/files?per_page=100" --jq '.[].filename' | grep -qxF "$1/spec.md"; then
      gh api "repos/$repo/issues/$old/comments" --silent \
        -f body="Superseded by #$2, which carries the spec for \`$1\` on its own branch."
      gh api -X PATCH "repos/$repo/pulls/$old" --silent -f state=closed
      echo "closed #$old (superseded by #$2)"
    fi
  done
}

open_prs() {
  local base d slug kind branch n
  base="$(git rev-parse HEAD)"
  if [[ -n "${SDLC_AGENT_APP_SLUG:-}" ]]; then
    # Commit as the agent's App identity, whose token opens the PR.
    local bot="$SDLC_AGENT_APP_SLUG[bot]" id
    id="$(gh api "users/$bot" --jq .id)"
    git config user.name "$bot"
    git config user.email "$id+$bot@users.noreply.github.com"
  else
    git config user.name "github-actions[bot]"
    git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  fi
  for d in "$@"; do
    if [[ ! -f "$d/spec.md" ]]; then
      echo "no spec produced for $d" >&2
      continue
    fi
    slug="${d#changes/}"
    kind=intent
    [[ -f "$d/bug.md" ]] && kind=bug
    branch="spec/$slug"
    git switch -q -C "$branch" "$base"
    git add -- "$d/spec.md"
    git commit -q -m "spec($slug): generate from accepted $kind"
    # The branch may be left over from a closed PR; this run's spec replaces it.
    git push -q -f -u origin "$branch"
    n="$(gh api "repos/$repo/pulls" -f title="spec($slug): generate from accepted $kind" \
      -f head="$branch" -f base=main \
      -f body="Generated spec for \`$d\` from its accepted \`$kind.md\`. Product owner: review it (\`/pr <this PR>\` in Claude Code) and resolve any flagged policy concerns. — Claude (spec)" \
      --jq .number)"
    echo "opened #$n for $d"
    # Now, while the PR is new: GitHub refuses auto-merge once it's approved and green.
    "$(dirname "$0")/auto-merge.sh" "$n" || true
    close_superseded "$d" "$n"
  done
}

case "${1:-}" in
  pending) pending ;;
  open) shift; open_prs "$@" ;;
  *) sed -n '2,17p' "$0" >&2; exit 2 ;;
esac
