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
#                    ran or is running on this head
# --force (the `check` label) runs it whatever the review says, unless the head is stale.
# Exits 0 with a decision, 2 on bad arguments, 3 when GitHub can't be read or written.
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
#      REVIEW_BOT (default: claude[bot], the login claude-code-action comments as).
set -uo pipefail

pr="${1:-}" head="${2:-}" force="${3:-}"
[[ "$pr" =~ ^[0-9]+$ && "$head" =~ ^[0-9a-f]{40}$ && "$force" =~ ^(--force)?$ ]] \
  || { sed -n '2,21p' "$0" >&2; exit 2; }
repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
[[ "$repo" == */* ]] || { echo "check-gate: can't tell which repo this is" >&2; exit 3; }
bot="${REVIEW_BOT:-claude[bot]}"
login="${bot%\[bot\]}"  # GraphQL names an App's account without the [bot] suffix
RUNNING="make check is running"

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
esac
[[ -z "$force" ]] || { echo run; exit 0; }

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
  pending*) wait_for "Waiting for the Claude review, which is running" ;;
  success*) ;;
  *) wait_for "Waiting for a clean Claude review: ${review#* }" ;;
esac

# Unresolved threads the reviewer started with **Important (as .sdlc/scripts/review-findings.sh).
query='query($owner: String!, $name: String!, $pr: Int!, $endCursor: String) {
  repository(owner: $owner, name: $name) { pullRequest(number: $pr) {
    reviewThreads(first: 100, after: $endCursor) {
      pageInfo { hasNextPage endCursor }
      nodes { isResolved comments(first: 1) { nodes { author { login } body } } } } } } }'
threads="$(gh api graphql --paginate -f query="$query" -F owner="${repo%%/*}" \
  -F name="${repo#*/}" -F pr="$pr" --jq "
    .data.repository.pullRequest.reviewThreads.nodes[]
    | select(.isResolved | not) | .comments.nodes[0]
    | select((.author.login | sub(\"\\\\[bot\\\\]\$\"; \"\")) == \"$login\")
    | select(.body | test(\"^\\\\s*\\\\*\\\\*Important\\\\b\"))
    | 1")" || fail "can't read PR #$pr's review threads"
open="$(grep -c . <<<"$threads")"
((open == 0)) || wait_for "Waiting: $open open Important thread(s). Resolve them, then reply on one or approve, or add the check label"
echo run
