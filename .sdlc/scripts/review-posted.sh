#!/usr/bin/env bash
# Did the Claude review post its summary? The claude-review gate needs more than a green job.
#
# Usage: .sdlc/scripts/review-posted.sh <pr-number> <since>     since = ISO 8601 UTC, e.g. 2026-11-12T09:00:00Z
#
# The review job used to mark `claude-review` as success whenever the review action finished
# without error. On PR #129 the action ended after 22 seconds, with 4 tool calls refused and no
# comment posted, and the gate still said "The Claude review is posted". This reads the PR's
# comments and exits 0 only if the reviewer created or edited one at or after <since> (the job's
# start), printing its URL. The review edits its one summary in place, so a re-review shows as
# an edit.
#
# Exits 1 when there's no such comment, and 3 when the comments can't be read: either way the
# job marks the review as not done.
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
#      REVIEW_BOT (default: claude[bot], the login claude-code-action comments as).
set -uo pipefail

pr="${1:-}" since="${2:-}"
[[ "$pr" =~ ^[0-9]+$ && "$since" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] \
  || { sed -n '2,17p' "$0" >&2; exit 2; }
repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
[[ -n "$repo" ]] || { echo "review-posted: can't tell which repo this is" >&2; exit 3; }
bot="${REVIEW_BOT:-claude[bot]}"

# `since` keeps only comments updated at or after it; the select repeats it so a fake or an
# older API that ignores the parameter can't pass an old summary off as new.
found="$(gh api "repos/$repo/issues/$pr/comments?since=$since" --paginate \
  --jq ".[] | select(.user.login == \"$bot\" and .updated_at >= \"$since\") | .html_url")" \
  || { echo "review-posted: can't read PR #$pr's comments" >&2; exit 3; }
if [[ -z "$found" ]]; then
  echo "review-posted: $bot posted no comment on PR #$pr since $since" >&2
  exit 1
fi
echo "review-posted: $(printf '%s\n' "$found" | tail -n 1)"
