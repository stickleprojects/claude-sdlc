#!/usr/bin/env bash
# Re-check a PR's descope decisions and update its `claude-review` status (#132).
#
# Usage: .sdlc/scripts/descopes-status.sh <pr-number> <head-sha>
#
# Run by .github/workflows/sdlc-descopes.yml when a decision can change (a reply in a thread,
# a review of the PR). It moves the status only between the review's own "posted" (success)
# and a descope failure this check set, whose description mentions a descope:
#   - success, and a descope isn't decided  -> failure, saying which and what to do;
#   - descope failure, and now all decided  -> success, naming who approved each one;
#   - descope failure, still not decided    -> failure, with the current reason.
# Anything else (pending, "Not reviewed", a failed review) is left alone: the review job sets
# those, and it runs the same check when it posts. Exits 1 when the decisions can't be read.
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
set -uo pipefail

pr="${1:-}"
sha="${2:-}"
[[ "$pr" =~ ^[0-9]+$ && "$sha" =~ ^[0-9a-f]{7,40}$ ]] || { sed -n '2,15p' "$0" >&2; exit 2; }
repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
[[ "$repo" == */* ]] || { echo "descopes-status: can't tell which repo this is" >&2; exit 1; }
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

current="$(gh api "repos/$repo/commits/$sha/statuses" \
  --jq '[.[] | select(.context == "claude-review")][0] | select(.) | "\(.state)\t\(.description)"')" \
  || { echo "descopes-status: can't read $sha's statuses" >&2; exit 1; }
state="${current%%$'\t'*}"
description="${current#*$'\t'}"
ours=""
[[ "$state" == failure && "$description" == *descope* ]] && ours=1
if [[ "$state" != success && -z "$ours" ]]; then
  echo "descopes-status: claude-review is '${state:-unset}' on $sha; the review job owns it, leaving it"
  exit 0
fi

reason="$("$here/descopes-decided.sh" "$pr")"
rc=$?
post() {  # <state> <description>
  gh api "repos/$repo/statuses/$sha" --silent -f state="$1" -f context=claude-review \
    -f description="${2:0:140}"
  echo "descopes-status: $1: ${2:0:140}"
}
case $rc in
  0)
    if [[ -n "$ours" ]]; then
      post success "The Claude review is posted; $reason"
    else
      echo "descopes-status: $reason; claude-review stays as it is"
    fi
    ;;
  1) post failure "$reason" ;;
  *) echo "descopes-status: the descope check couldn't run" >&2; exit 1 ;;
esac
