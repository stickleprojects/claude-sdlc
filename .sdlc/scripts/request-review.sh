#!/usr/bin/env bash
# Ask for a fresh Claude review of a push, without cancelling one the push already started (#105).
#
# Usage: .sdlc/scripts/request-review.sh <pr-number> [<sha>]     sha: the commit just pushed (default HEAD)
#
# sdlc-claude-review.yml runs on a push (`synchronize`) only when the repo variable SDLC_AUTO_MERGE is
# set; otherwise a review needs the `review` label. Adding the label after a push that already
# started a review cancels that review (one review per PR at a time), which shows a cancelled
# check and spends a second review. So this script:
#   1. reads SDLC_AUTO_MERGE the way .sdlc/scripts/auto-merge.sh does;
#   2. on (THE RULE in .sdlc/scripts/auto-merge.sh, which the workflow's condition follows: set, and not
#      `off`): waits for the Claude review run on the pushed commit and doesn't add the label;
#      adds it only if no run starts;
#      unset: adds the label; can't be read: looks for the run, and adds the label if none starts;
#   3. before adding the label, waits until the PR's head is the pushed commit, so the label's
#      review never runs on the old one. Without a label to add, there's nothing to wait for.
# It prints one line saying what it did and why, for the session and the PR reply. It exits 0
# whatever happened, so it never fails the session that called it.
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
#      REQUEST_REVIEW_WAIT  seconds to wait for the PR's head and for a review run (default 60).
#      REQUEST_REVIEW_POLL  seconds between checks (default 5).
set -uo pipefail

pr="${1:-}"
[[ "$pr" =~ ^[0-9]+$ ]] || { sed -n '2,22p' "$0" >&2; exit 2; }
sha="${2:-HEAD}"
# The runs API needs the full sha; expand a short one when this checkout has the commit.
sha="$(git rev-parse --verify --quiet "$sha^{commit}" 2>/dev/null || echo "$sha")"
[[ "$sha" =~ ^[0-9a-f]{7,40}$ ]] || { echo "request-review: no commit to review" >&2; exit 2; }
repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
[[ -n "$repo" ]] || { echo "Not adding the review label: can't tell which repo this is."; exit 0; }
wait="${REQUEST_REVIEW_WAIT:-60}" poll="${REQUEST_REVIEW_POLL:-5}"
short="${sha:0:7}"

# Repeat a check until it succeeds or the wait runs out.
until_ok() {
  local waited=0
  until "$@"; do
    ((waited >= wait)) && return 1
    sleep "$poll"
    waited=$((waited + poll))
  done
}

head_is_pushed() {
  head="$(gh api "repos/$repo/pulls/$pr" --jq .head.sha 2>/dev/null)" && [[ "$head" == "$sha"* ]]
}
# A Claude review run on the pushed commit that is queued, running or finished: not one the job's
# condition skipped (a push without auto-merge) or one a newer run cancelled.
review_run_started() {
  local runs
  runs="$(gh api "repos/$repo/actions/runs?head_sha=$sha&event=pull_request&per_page=100" --jq '
    [.workflow_runs[] | select(.path | endswith("/sdlc-claude-review.yml"))
      | select(.conclusion != "skipped" and .conclusion != "cancelled")] | length' 2>/dev/null)" \
    && ((runs > 0))
}
add_label() {
  until_ok head_is_pushed || {
    echo "Not adding the review label ($1): the PR's head is still ${head:0:7}, not the pushed" \
      "$short; add the label once GitHub shows the push, or a review would run on the old commit."
    return
  }
  if gh api "repos/$repo/issues/$pr/labels" -f "labels[]=review" --silent 2>/dev/null; then
    echo "Added the review label: $1."
  else
    echo "Couldn't add the review label ($1): add it by hand to review $short."
  fi
}

head=""
labels="$(gh api "repos/$repo/issues/$pr/labels" --jq '[.[].name] | index("review") != null' 2>/dev/null)"
if [[ "$labels" == true ]]; then
  echo "Not adding the review label: it's already on, so a review of $short is about to start."
  exit 0
fi

if method="$(bash "$(dirname "$0")/auto-merge.sh" --method 2>/dev/null)"; then
  if [[ -z "$method" ]]; then
    add_label "auto-merge is off, so pushes don't start a review"
  elif until_ok review_run_started; then
    echo "Not adding the review label: auto-merge is on (SDLC_AUTO_MERGE=$method), so this push" \
      "already started a review on $short."
  else
    add_label "auto-merge is on (SDLC_AUTO_MERGE=$method), but no review run started on $short"
  fi
elif until_ok review_run_started; then
  echo "Not adding the review label: couldn't read SDLC_AUTO_MERGE, but a review run already" \
    "started on $short."
else
  add_label "couldn't read SDLC_AUTO_MERGE, and no review run had started on $short"
fi
