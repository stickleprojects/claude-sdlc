#!/usr/bin/env bash
# Mark a pushed commit the Claude review hasn't seen as not reviewed (#46).
#
# Usage: .sdlc/scripts/review-current.sh <pr-number> <head-sha>
#
# The review posts a `claude-review` commit status on each commit it reviews, and main requires
# it, so nobody merges on a stale review. Without auto-merge, a push doesn't start a review, so
# the new commit has no status and GitHub would only show "Expected". This puts a failure there
# that says why and what to do: "Not reviewed: 2 commits since the review of abc1234. Add the
# review label." Adding the label (.sdlc/scripts/request-review.sh does it after a skill's push) runs
# the review, which replaces the failure.
#
# Every push counts, docs and sketches too: any commit after the review needs a new one.
# A commit that already has a `claude-review` status (a review is running on it, or one ran) is
# left alone. Exits 0 unless it can't read or post, so the push's other checks are unaffected.
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
set -uo pipefail

pr="${1:-}" head="${2:-}"
[[ "$pr" =~ ^[0-9]+$ && "$head" =~ ^[0-9a-f]{40}$ ]] || { sed -n '2,17p' "$0" >&2; exit 2; }
repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
[[ -n "$repo" ]] || { echo "review-current: can't tell which repo this is" >&2; exit 1; }

# The newest `claude-review` state on a commit (statuses come newest first), or empty.
state_of() {
  gh api "repos/$repo/commits/$1/statuses" --paginate \
    --jq '[.[] | select(.context == "claude-review")][0].state // empty'
}

current="$(state_of "$head")" || { echo "review-current: can't read $head's statuses" >&2; exit 1; }
if [[ -n "$current" ]]; then
  echo "review-current: ${head:0:7} already has a claude-review status ($current); leaving it"
  exit 0
fi

commits="$(gh api "repos/$repo/pulls/$pr/commits" --paginate --jq '.[].sha')" \
  || { echo "review-current: can't list PR #$pr's commits" >&2; exit 1; }
# Newest first: the PR's commits come oldest first. (No `tac`: macOS doesn't have it.)
shas=()
while IFS= read -r sha; do [[ -n "$sha" ]] && shas+=("$sha"); done <<<"$commits"
reviewed="" since=0
for ((i = ${#shas[@]} - 1; i >= 0; i--)); do
  if [[ "$(state_of "${shas[i]}")" == success ]]; then reviewed="${shas[i]}"; break; fi
  since=$((since + 1))
done

if [[ -n "$reviewed" ]]; then
  s=""; ((since == 1)) || s="s"
  description="Not reviewed: $since commit$s since the review of ${reviewed:0:7}. Add the review label"
else
  description="Not reviewed yet: add the review label to run the Claude review"
fi
gh api "repos/$repo/statuses/$head" --silent -f state=failure -f context=claude-review \
  -f description="$description" || { echo "review-current: can't post the status" >&2; exit 1; }
echo "review-current: ${head:0:7}: $description"
