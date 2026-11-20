#!/usr/bin/env bash
# The summary a re-review replaces, and the PR's commits, for the Claude review (#242).
#
# Usage: .sdlc/scripts/review-earlier-summary.sh <pr-number>
#
# The review edits its one summary comment in place, so the summary can't be resolved, and a
# note in it (the PR body out of date, an approval still needed) had no answer anyone could
# see: on spellbound3d #225 three notes sat there after their fixes, and nobody could tell
# whether they'd been dealt with. A re-review marks each earlier note addressed or still open
# (.sdlc/REVIEW.md, "Summary comment"). The workflow runs this before the review, with its own
# token, from the base's copy, and the review reads the file it writes.
#
# Prints markdown: the earlier summary (the newest comment by a bot that carries the hidden
# `<!-- review-findings:` count line) with when it was last edited, then the PR's commits,
# oldest first, as `<short sha> <date> <subject>`. With no earlier summary it says this is the
# first review. Exits 0, 2 on bad arguments, and 3 when GitHub can't be read (nothing on stdout).
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
set -uo pipefail

pr="${1:-}"
[[ "$pr" =~ ^[0-9]+$ ]] || { sed -n '2,18p' "$0" >&2; exit 2; }
repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
[[ "$repo" == */* ]] || { echo "review-earlier-summary: can't tell which repo this is" >&2; exit 3; }

comments="$(gh api --paginate "repos/$repo/issues/$pr/comments?per_page=100")" \
  || { echo "review-earlier-summary: can't read PR #$pr's comments" >&2; exit 3; }
commits="$(gh api --paginate "repos/$repo/pulls/$pr/commits?per_page=100")" \
  || { echo "review-earlier-summary: can't read PR #$pr's commits" >&2; exit 3; }

summary="$(jq -s 'add // [] | map(select(.user.type == "Bot" and
    ((.body // "") | contains("<!-- review-findings:")))) | last // empty' <<<"$comments")" \
  || { echo "review-earlier-summary: PR #$pr's comments aren't JSON" >&2; exit 3; }
log="$(jq -rs 'add // [] | .[] | "\(.sha[0:7]) \(.commit.committer.date) \(.commit.message | split("\n")[0])"' \
  <<<"$commits")" || { echo "review-earlier-summary: PR #$pr's commits aren't JSON" >&2; exit 3; }

if [[ -z "$summary" ]]; then
  echo "# No earlier summary"
  echo
  echo "This is the PR's first review: there are no earlier notes to mark."
else
  echo "# The summary this review replaces"
  echo
  echo "Last edited: $(jq -r '.updated_at' <<<"$summary")"
  echo
  jq -r '.body' <<<"$summary"
fi
echo
echo "# The PR's commits, oldest first"
echo
echo "${log:-(none)}"
