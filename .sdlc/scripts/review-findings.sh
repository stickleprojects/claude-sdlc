#!/usr/bin/env bash
# Does every Important finding in the Claude review have an open thread? (#130)
#
# Usage: .sdlc/scripts/review-findings.sh <pr-number>
#
# Conversation resolution only sees review threads, so a finding that lives only in the summary
# comment blocks nothing: spellbound3d#124 merged with "3 Important" in its summary and no threads.
# .sdlc/REVIEW.md has the reviewer start each Important thread with `**Important` (`**Important:**`,
# `**Important (product owner decides):**`) and end its
# summary with `<!-- review-findings: important=<N> nit=<M> -->`. This exits 0 only when the
# reviewer's latest comment carrying that line says N, and N unresolved threads the reviewer
# started begin with `**Important`. The threads are what's counted; the line must agree.
#
# Exits 1 when the line is missing or the numbers differ (printing a one-line reason, short
# enough for a commit status), and 3 when the comments or threads can't be read.
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
#      REVIEW_BOT (default: claude[bot], the login claude-code-action comments as).
set -uo pipefail

pr="${1:-}"
[[ "$pr" =~ ^[0-9]+$ ]] || { sed -n '2,17p' "$0" >&2; exit 2; }
repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
[[ "$repo" == */* ]] || { echo "review-findings: can't tell which repo this is" >&2; exit 3; }
bot="${REVIEW_BOT:-claude[bot]}"
login="${bot%\[bot\]}"  # GraphQL names an App's account without the [bot] suffix

# The reviewer's comments, oldest first; the last one with the count line is the summary.
bodies="$(gh api "repos/$repo/issues/$pr/comments" --paginate \
  --jq ".[] | select(.user.login == \"$bot\") | .body | @json")" \
  || { echo "review-findings: can't read PR #$pr's comments" >&2; exit 3; }
marker=""
while IFS= read -r body; do
  [[ -n "$body" ]] || continue
  found="$(jq -r 'capture("<!--\\s*review-findings:\\s*important=(?<n>[0-9]+)") | .n' <<<"$body" 2>/dev/null)"
  [[ -n "$found" ]] && marker="$found"
done <<<"$bodies"
if [[ -z "$marker" ]]; then
  echo "The review summary has no findings count line: add the review label to run it again"
  exit 1
fi

# Unresolved threads the reviewer started with **Important, one line each.
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
    | 1")" \
  || { echo "review-findings: can't read PR #$pr's review threads" >&2; exit 3; }
open="$(grep -c . <<<"$threads")"

if ((open != marker)); then
  echo "The review lists $marker Important finding(s) but $open open Important thread(s): add the review label to run it again"
  exit 1
fi
echo "review-findings: $open open Important finding(s), each in its own thread"
