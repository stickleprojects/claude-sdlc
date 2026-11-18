#!/usr/bin/env bash
# A PR's review threads, with whether each is resolved, as JSON for the Claude review (#220).
#
# Usage: .sdlc/scripts/review-threads.sh <pr-number>
#
# The review's rules turn on thread state: an unresolved Important thread still counts, so
# don't post it again, and the summary's count is the unresolved Important threads
# (.sdlc/REVIEW.md, "Posting findings"). REST review comments don't say whether a thread is
# resolved, and the review's allowed tools don't include GraphQL, so on spellbound3d #203 it
# guessed: it posted a second "Plan changes" thread and counted a fixed finding as open. The
# workflow runs this before the review, with its own token, and the review reads the file.
#
# Prints a JSON array, one object per thread, in the PR's order:
#   {"path", "line", "resolved", "outdated",
#    "first": {"author", "bot", "body"}, "replies": [{"author", "bot", "body"}, ...]}
# Bodies are cut at 600 characters. Exits 0 with the array, 2 on bad arguments, and 3 when
# the threads can't be read (nothing on stdout).
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
set -uo pipefail

pr="${1:-}"
[[ "$pr" =~ ^[0-9]+$ ]] || { sed -n '2,18p' "$0" >&2; exit 2; }
repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
[[ "$repo" == */* ]] || { echo "review-threads: can't tell which repo this is" >&2; exit 3; }

query='query($owner: String!, $name: String!, $pr: Int!, $endCursor: String) {
  repository(owner: $owner, name: $name) { pullRequest(number: $pr) {
    reviewThreads(first: 100, after: $endCursor) {
      pageInfo { hasNextPage endCursor }
      nodes { isResolved isOutdated path line
        comments(first: 50) { nodes { author { login __typename } body } } } } } } }'
nodes="$(gh api graphql --paginate -f query="$query" -F owner="${repo%%/*}" \
  -F name="${repo#*/}" -F pr="$pr" --jq '.data.repository.pullRequest.reviewThreads.nodes[]')" \
  || { echo "review-threads: can't read PR #$pr's review threads" >&2; exit 3; }

jq -s '
  def who: {author: (.author.login // "ghost"), bot: ((.author.__typename // "") != "User"),
            body: (.body[0:600])};
  map({path, line, resolved: .isResolved, outdated: .isOutdated,
       first: (.comments.nodes[0] | who), replies: [.comments.nodes[1:][] | who]})
' <<<"$nodes" || { echo "review-threads: can't parse PR #$pr's review threads" >&2; exit 3; }
