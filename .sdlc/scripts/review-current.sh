#!/usr/bin/env bash
# Mark a pushed commit the Claude review hasn't seen as not reviewed (#46).
#
# Usage: .sdlc/scripts/review-current.sh <pr-number> <head-sha>
#
# The review posts a `claude-review` commit status on each commit it reviews, and main requires
# it, so nobody merges on a stale review. Without auto-merge, a push doesn't start a review, so
# the new commit has no status and GitHub would only show "Expected". This puts a pending status there
# (nothing failed, and pending blocks the merge too, #277) that says why and what to do: "Not reviewed: 2 commits since the review of abc1234. Add the
# review label." Adding the label (.sdlc/scripts/request-review.sh does it after a skill's push) runs
# the review, which replaces it. A review still running on an older commit of the PR can't count
# any more, so it's cancelled (best effort).
#
# Every push counts, docs and sketches too: any commit after the review needs a new one. The
# exception is a push that only merges the base branch in, such as GitHub's Update branch
# (#182): each commit since the review is a merge of the reviewed chain with a commit on the base
# branch, and its tree is exactly what git's own merge of those two gives, so the merge added
# nothing of its own, and main's changes it brings in touch none of the files the PR changes. The
# review then still holds, and the status is a success naming it. A conflict resolved by hand
# or a change slipped into the merge gives a different tree, and still needs a review. So does
# a merge that brings in changes to a file the PR changes too: git can merge two rewordings of
# the same rule cleanly, and only a review sees that they clash. (Comparing diffs doesn't work: their context lines change whenever the
# base edits a line next to the PR's, as on #192 and #193.)
# A commit that already has a `claude-review` status (a review is running on it, or one ran) is
# left alone. Exits 0 unless it can't read or post, so the push's other checks are unaffected.
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
#      HEAD_REF  the PR's branch, to find the review runs to cancel. Unset: none are cancelled.
#      BASE_REF  the PR's base branch, as origin/<BASE_REF> in this checkout with the PR's
#                history (fetch-depth: 0). Unset or unreadable: every push needs a review.
#      SDLC_REVIEW_CARRY_FORWARD  `off`: every push needs a review, base merges too (the repo
#                variable of that name; anything else, or unset, carries a review forward).
set -uo pipefail

pr="${1:-}" head="${2:-}"
[[ "$pr" =~ ^[0-9]+$ && "$head" =~ ^[0-9a-f]{40}$ ]] || { sed -n '2,23p' "$0" >&2; exit 2; }
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
reviewed="" since=0 at=-1
for ((i = ${#shas[@]} - 1; i >= 0; i--)); do
  if [[ "$(state_of "${shas[i]}")" == success ]]; then reviewed="${shas[i]}" at=$i; break; fi
  since=$((since + 1))
done

# Is <commit> a merge of <prev> with a commit on the base branch that adds nothing of its own?
# Needs the PR's history and origin/<BASE_REF> (fetch-depth: 0) and git 2.38+ for merge-tree;
# anything git can't answer counts as "no", so the push needs a review.
overlap=""
base_merge_only() {
  local commit="$1" prev="$2" parents merged file
  read -r -a parents <<<"$(git rev-list --parents -n 1 "$commit" 2>/dev/null)"
  ((${#parents[@]} == 3)) && [[ "${parents[1]}" == "$prev" ]] || return 1
  git merge-base --is-ancestor "${parents[2]}" "origin/$BASE_REF" 2>/dev/null || return 1
  merged="$(git merge-tree --write-tree "$prev" "${parents[2]}" 2>/dev/null)" || return 1
  [[ "$merged" == "$(git rev-parse "$commit^{tree}" 2>/dev/null)" ]] || return 1
  # What the merge brought in from the base, against the files the reviewed PR changes.
  while IFS= read -r file; do
    [[ -n "$file" ]] && grep -qxF -- "$file" <<<"$pr_files" && { overlap="$file"; return 1; }
  done < <(git diff --name-only "$prev" "$commit" 2>/dev/null)
  return 0
}
if [[ -n "$reviewed" && -n "${BASE_REF:-}" && "${SDLC_REVIEW_CARRY_FORWARD:-}" != off ]] \
  && ((since > 0)); then
  pr_files="$(git diff --name-only "$(git merge-base "origin/$BASE_REF" "$reviewed" 2>/dev/null)" \
    "$reviewed" 2>/dev/null)"
  prev="$reviewed" carried=1
  for ((i = at + 1; i < ${#shas[@]}; i++)); do
    base_merge_only "${shas[i]}" "$prev" || { carried=""; break; }
    prev="${shas[i]}"
  done
  if [[ -n "$carried" && "$prev" == "$head" ]]; then
    description="The Claude review of ${reviewed:0:7} still holds: only $BASE_REF was merged in, adding nothing of its own"
    gh api "repos/$repo/statuses/$head" --silent -f state=success -f context=claude-review \
      -f description="${description:0:140}" || { echo "review-current: can't post the status" >&2; exit 1; }
    echo "review-current: ${head:0:7}: $description"
    exit 0
  fi
fi

if [[ -n "$overlap" ]]; then
  description="Not reviewed: $BASE_REF changed ${overlap##*/} too, which this PR changes. Add the review label"
elif [[ -n "$reviewed" ]]; then
  s=""; ((since == 1)) || s="s"
  description="Not reviewed: $since commit$s since the review of ${reviewed:0:7}. Add the review label"
else
  description="Not reviewed yet: add the review label to run the Claude review"
fi
gh api "repos/$repo/statuses/$head" --silent -f state=pending -f context=claude-review \
  -f description="${description:0:140}" || { echo "review-current: can't post the status" >&2; exit 1; }
echo "review-current: ${head:0:7}: $description"

# Cancel the reviews of older commits, unless a newer push came in: its review isn't older.
[[ -n "${HEAD_REF:-}" ]] || exit 0
[[ "$(gh api "repos/$repo/pulls/$pr" --jq .head.sha 2>/dev/null)" == "$head" ]] || exit 0
export HEAD_REF REPO="$repo" HEAD="$head"
stale="$(gh api "repos/$repo/actions/workflows/sdlc-claude-review.yml/runs?event=pull_request&per_page=50" \
  --jq '.workflow_runs[] | select(.status != "completed" and .head_branch == env.HEAD_REF
    and .head_repository.full_name == env.REPO and .head_sha != env.HEAD) | .id' 2>/dev/null)" || stale=""
while IFS= read -r id; do
  [[ -n "$id" ]] || continue
  if gh api -X POST "repos/$repo/actions/runs/$id/cancel" --silent 2>/dev/null; then
    echo "review-current: cancelled run $id, a review of an older commit"
  else
    echo "review-current: couldn't cancel run $id, a review of an older commit"
  fi
done <<<"$stale"
exit 0
