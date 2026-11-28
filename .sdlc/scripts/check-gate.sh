#!/usr/bin/env bash
# May `make check` run on a PR's head yet? (SDLC_CHECK_AFTER_REVIEW, #163)
#
# Usage: .sdlc/scripts/check-gate.sh <pr-number> <head-sha> [--force]
#
# With SDLC_CHECK_AFTER_REVIEW on, a PR's `check` waits for a clean Claude review: one whose
# `claude-review` status on the head is success and that leaves no open Important thread. A
# review that asks for changes means another push, so a `check` run on this one would be
# wasted, and on a runner that runs one job at a time it would hold up the review as well.
# A green `claude-review` alone isn't clean: it says the review posted and each Important
# finding has its thread (#130), not that there are none.
#
# Prints one line, and .github/workflows/sdlc-check-after-review.yml acts on its first word:
#   run              run `make check` now
#   wait <reason>    not yet; the `check` status on the head is set to pending with the reason
#   skip <reason>    nothing to do: the PR is closed, the head is stale, or `check` already
#                    ran, is running or is queued on this head
# --force (the `check` label) runs it whatever the review says, unless the head is stale.
# Before saying `run` it claims the head (#237): `check` goes to pending "make check is queued",
# linked to this workflow run, so another gate on the same head (an approval and its Descope
# decisions run come together) skips rather than starting a second job that cancels the first.
# The claim holds only while that run is still going: once it's over, a later gate may run.
# Exits 0 with a decision, 2 on bad arguments, 3 when GitHub can't be read or written.
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
#      REVIEW_BOT (default: github-actions[bot],claude[bot]): the reviewer's logins, comma-separated.
#        The review posts with the job's token (ADR 0001); claude[bot] covers earlier reviews.
#      GITHUB_RUN_ID, GITHUB_SERVER_URL (set by Actions): the run the claim links to.
set -uo pipefail

pr="${1:-}" head="${2:-}" force="${3:-}"
[[ "$pr" =~ ^[0-9]+$ && "$head" =~ ^[0-9a-f]{40}$ && "$force" =~ ^(--force)?$ ]] \
  || { sed -n '2,27p' "$0" >&2; exit 2; }
repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
[[ "$repo" == */* ]] || { echo "check-gate: can't tell which repo this is" >&2; exit 3; }
bots="${REVIEW_BOT:-github-actions[bot],claude[bot]}"
# As JSON arrays for jq: the REST logins, and GraphQL's, which drop an App's [bot] suffix.
bots_json="[$(sed -E 's/[^,]+/"&"/g' <<<"$bots")]"
logins_json="${bots_json//\[bot\]/}"
RUNNING="make check is running"
QUEUED="make check is queued"

fail() { echo "check-gate: $1" >&2; exit 3; }

pull="$(gh api "repos/$repo/pulls/$pr" --jq '[.state, .head.sha] | join(" ")')" \
  || fail "can't read PR #$pr"
read -r state current <<<"$pull"
[[ "$state" == open ]] || { echo "skip PR #$pr is $state"; exit 0; }
[[ "$current" == "$head" ]] || { echo "skip a newer push (${current:0:7}) replaced ${head:0:7}"; exit 0; }

# The newest status of a context on the head (statuses come newest first): "state description".
latest() {
  gh api "repos/$repo/commits/$head/statuses" --paginate \
    --jq "[.[] | select(.context == \"$1\")][0] | select(. != null) | \"\(.state) \(.description // \"\")\""
}
check="$(latest check)" || fail "can't read the statuses of ${head:0:7}"
case "$check" in
  success* | failure* | error*) [[ -n "$force" ]] || { echo "skip check already ran on ${head:0:7}"; exit 0; } ;;
  "pending $RUNNING"*) [[ -n "$force" ]] || { echo "skip check is already running on ${head:0:7}"; exit 0; } ;;
  "pending $QUEUED"*)
    if [[ -z "$force" ]]; then
      # The claim's link names the gate run that made it. A run that's over and left the claim
      # behind (its job was cancelled before it started) no longer holds the head.
      url="$(gh api "repos/$repo/commits/$head/statuses" --paginate \
        --jq '[.[] | select(.context == "check")][0].target_url // ""')" \
        || fail "can't read the statuses of ${head:0:7}"
      claimer="$(sed -nE 's#.*/actions/runs/([0-9]+).*#\1#p' <<<"$url")"
      if [[ -n "$claimer" ]]; then
        run_state="$(gh api "repos/$repo/actions/runs/$claimer" --jq .status)" \
          || fail "can't read run $claimer"
        [[ "$run_state" == completed ]] \
          || { echo "skip check is already queued on ${head:0:7} (run $claimer)"; exit 0; }
      fi
    fi
    ;;
esac

# Claim the head for this run's make-check job, then say run.
go() {
  local link=()
  [[ -z "${GITHUB_RUN_ID:-}" ]] \
    || link=(-f target_url="${GITHUB_SERVER_URL:-https://github.com}/$repo/actions/runs/$GITHUB_RUN_ID")
  gh api "repos/$repo/statuses/$head" --silent -f state=pending -f context=check \
    -f description="$QUEUED: if it never starts, add the check label" "${link[@]}" \
    || fail "can't set the check status on ${head:0:7}"
  echo run
  exit 0
}
[[ -z "$force" ]] || go

wait_for() {
  local reason
  reason="$(cut -c1-140 <<<"$1")"
  gh api "repos/$repo/statuses/$head" --silent -f state=pending -f context=check \
    -f description="$reason" || fail "can't set the check status on ${head:0:7}"
  echo "wait $reason"
  exit 0
}

review="$(latest claude-review)" || fail "can't read the statuses of ${head:0:7}"
case "$review" in
  "") wait_for "Waiting for the Claude review" ;;
  "pending Not reviewed"*) wait_for "Waiting for a clean Claude review: ${review#* }" ;;
  pending*) wait_for "Waiting for the Claude review, which is running" ;;
  success*) ;;
  *) wait_for "Waiting for a clean Claude review: ${review#* }" ;;
esac

# Unresolved threads the reviewer started with **Important, not the job's CI-change thread
# (as .sdlc/scripts/review-findings.sh).
query='query($owner: String!, $name: String!, $pr: Int!, $endCursor: String) {
  repository(owner: $owner, name: $name) { pullRequest(number: $pr) {
    reviewThreads(first: 100, after: $endCursor) {
      pageInfo { hasNextPage endCursor }
      nodes { isResolved comments(first: 1) { nodes { author { login } body } } } } } } }'
threads="$(gh api graphql --paginate -f query="$query" -F owner="${repo%%/*}" \
  -F name="${repo#*/}" -F pr="$pr" --jq "
    .data.repository.pullRequest.reviewThreads.nodes[]
    | select(.isResolved | not) | .comments.nodes[0]
    | select(.author.login | sub(\"\\\\[bot\\\\]\$\"; \"\") | IN($logins_json[]))
    | select(.body | test(\"CI change: needs approval\") | not)
    | select(.body | test(\"^\\\\s*\\\\*\\\\*Important\\\\b\"))
    | 1")" || fail "can't read PR #$pr's review threads"
open="$(grep -c . <<<"$threads")"
((open == 0)) || wait_for "Waiting: $open open Important thread(s). Resolve them, then reply on one or approve, or add the check label"
go
