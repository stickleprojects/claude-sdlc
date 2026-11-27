#!/usr/bin/env bash
# Does every Important finding in the Claude review have an open thread (#130), and is every Nit
# it counts written down (#266)?
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
# A Nit needs no thread, but it must be somewhere: on #263 the summary said "2 Nit (see above)"
# with nothing above. So at least M Nits must be lines of the summary that start with `Nit`
# (`- **Nit:** …`; a bare count such as `Nit: 2` isn't one) or the reviewer's unresolved threads
# that start with `**Nit`.
#
# Exits 1 when the line is missing, the numbers differ or a Nit is missing (printing a one-line
# reason, short enough for a commit status), and 3 when the comments or threads can't be read.
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
#      REVIEW_BOT (default: github-actions[bot],claude[bot]): the reviewer's logins, comma-separated.
#        The review posts with the job's token (ADR 0001); claude[bot] covers earlier reviews.
set -uo pipefail

pr="${1:-}"
[[ "$pr" =~ ^[0-9]+$ ]] || { sed -n '2,23p' "$0" >&2; exit 2; }
repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
[[ "$repo" == */* ]] || { echo "review-findings: can't tell which repo this is" >&2; exit 3; }
bots="${REVIEW_BOT:-github-actions[bot],claude[bot]}"
# As JSON arrays for jq: the REST logins, and GraphQL's, which drop an App's [bot] suffix.
bots_json="[$(sed -E 's/[^,]+/"&"/g' <<<"$bots")]"
logins_json="${bots_json//\[bot\]/}"

# The reviewer's comments, oldest first; the last one with the count line is the summary.
bodies="$(gh api "repos/$repo/issues/$pr/comments" --paginate \
  --jq ".[] | select(.user.login | IN($bots_json[])) | .body | @json")" \
  || { echo "review-findings: can't read PR #$pr's comments" >&2; exit 3; }
marker="" nits=0 summary=""
while IFS= read -r body; do
  [[ -n "$body" ]] || continue
  found="$(jq -r 'capture("<!--\\s*review-findings:\\s*important=(?<n>[0-9]+)") | .n' <<<"$body" 2>/dev/null)"
  [[ -n "$found" ]] || continue
  marker="$found" summary="$body"
  nits="$(jq -r '[capture("<!--\\s*review-findings:[^>]*\\bnit=(?<m>[0-9]+)") | .m][0] // "0"' <<<"$body")"
done <<<"$bodies"
if [[ -z "$marker" ]]; then
  echo "The review summary has no findings count line: add the review label to run it again"
  exit 1
fi

# Unresolved threads the reviewer started with **Important or **Nit, one line each.
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
    | .body | capture(\"^\\\\s*\\\\*\\\\*(?<kind>Important|Nit)\\\\b\") | .kind")" \
  || { echo "review-findings: can't read PR #$pr's review threads" >&2; exit 3; }
open="$(grep -cx Important <<<"$threads")"
nit_threads="$(grep -cx Nit <<<"$threads")"

if ((open != marker)); then
  echo "The review lists $marker Important finding(s) but $open open Important thread(s): add the review label to run it again"
  exit 1
fi
nit_lines="$(jq -r '[split("\n")[]
  | select(test("^\\s*([-*]|[0-9]+[.)])?\\s*\\**Nit\\b") and (test("^\\W*([0-9]+[.)])?\\W*Nit\\W*[0-9]+\\W*$") | not))]
  | length' <<<"$summary")"
if ((nit_threads + nit_lines < nits)); then
  echo "The review counts $nits Nit(s) but writes down $((nit_threads + nit_lines)): add the review label to run it again"
  exit 1
fi
echo "review-findings: $open open Important finding(s), each in its own thread"
