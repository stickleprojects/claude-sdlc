#!/usr/bin/env bash
# Ask for a fresh Claude review of a push, without cancelling one the push already started (#105).
#
# Usage: .sdlc/scripts/request-review.sh [--again] <pr-number> [<sha>]   sha: the commit just pushed
#   Default: this checkout's HEAD when it's on the PR's branch (the session that just pushed, which
#   GitHub may not show yet), otherwise the PR's head on GitHub (another checkout pushed nothing).
#   --again: nothing was pushed since the last review (only replies or resolved threads), so a
#   finished review of the commit doesn't count, only one still queued or running (#287).
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
# With --again, steps 1 and 2 become one check for a queued or running review: if there is none,
# it adds the label, whatever SDLC_AUTO_MERGE says.
# It prints one line saying what it did and why, for the session and the PR reply. It exits 0
# whatever happened, so it never fails the session that called it.
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
#      REQUEST_REVIEW_WAIT  seconds to wait for the PR's head and for a review run (default 60).
#      REQUEST_REVIEW_POLL  seconds between checks (default 5).
set -uo pipefail

again=""
args=()
for arg in "$@"; do
  if [[ "$arg" == --again ]]; then again=1; else args+=("$arg"); fi
done
set -- ${args[@]+"${args[@]}"}  # bash 3.2 (macOS) calls an empty array unbound
pr="${1:-}"
[[ "$pr" =~ ^[0-9]+$ ]] || { sed -n '2,28p' "$0" >&2; exit 2; }
# A sha given as an argument is checked before anything else, so a bad one is a usage error
# wherever the script runs, even where it can't tell which repo this is.
if [[ -n "${2:-}" ]]; then
  given="$(git rev-parse --verify --quiet "$2^{commit}" 2>/dev/null || echo "$2")"
  [[ "$given" =~ ^[0-9a-f]{7,40}$ ]] || { echo "request-review: no commit to review" >&2; exit 2; }
fi
repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
[[ -n "$repo" ]] || { echo "Not adding the review label: can't tell which repo this is."; exit 0; }
sha="${2:-}"
if [[ -z "$sha" ]]; then
  # Run from another checkout, HEAD is some other branch's commit (spellbound3d#183).
  read -r pr_ref pr_sha < <(gh api "repos/$repo/pulls/$pr" --jq '.head.ref + " " + .head.sha' \
    2>/dev/null) || true
  if [[ -n "${pr_ref:-}" && "$(git branch --show-current 2>/dev/null)" != "$pr_ref" ]]; then
    sha="${pr_sha:-}"
  else
    sha=HEAD
  fi
fi
# The runs API needs the full sha; expand a short one when this checkout has the commit.
sha="$(git rev-parse --verify --quiet "$sha^{commit}" 2>/dev/null || echo "$sha")"
[[ "$sha" =~ ^[0-9a-f]{7,40}$ ]] || { echo "request-review: no commit to review" >&2; exit 2; }
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
# condition skipped (a push without auto-merge) or one a newer run cancelled. Right after a push, a
# finished one is that push's review. With --again it was the last review, so only an unfinished
# run counts.
review_run_started() {
  local runs unfinished=""
  [[ -n "$again" ]] && unfinished='| select(.status != "completed")'
  runs="$(gh api "repos/$repo/actions/runs?head_sha=$sha&event=pull_request&per_page=100" --jq "
    [.workflow_runs[] | select(.path | endswith(\"/sdlc-claude-review.yml\"))
      | select(.conclusion != \"skipped\" and .conclusion != \"cancelled\") $unfinished]
    | length" 2>/dev/null)" && ((runs > 0))
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

# Asked again with no push: nothing new will start, so check once. Auto-merge doesn't matter here,
# since a label added while a review runs cancels it either way.
if [[ -n "$again" ]]; then
  if review_run_started; then
    echo "Not adding the review label: a review of $short is still queued or running, and the" \
      "label would cancel it. Ask again once it has finished."
  else
    add_label "asked again (--again), and no review of $short is queued or running"
  fi
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
