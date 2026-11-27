#!/usr/bin/env bash
# Ask a person to approve a PR's change to the files that set CI's rules (ADR 0001, #293).
#
# Usage: .sdlc/scripts/ci-change-thread.sh <pr-number> <base> <head>
#
# Run by the Claude review job before the review, with both commits in this checkout. When the
# PR changes a file on the approval list (ci-changes.sh), it posts one file-level thread on the
# PR that starts `CI change: needs approval` and lists those files. descopes-decided.sh then holds
# `claude-review` until a person replies `Approved: <name>, <date>`. The job posts it, not the
# reviewer, so the thread doesn't depend on a model remembering to.
#
# It doesn't start with `**Important`, the review's finding marker: the review posts with the same
# login (github-actions[bot], ADR 0001), and review-findings.sh and check-gate.sh count only the
# review's own findings. descopes-decided.sh holds this one instead.
#
# The thread ends with a digest of those files' diff. A push that changes them again, or changes
# another one, gets a new thread, so an approval covers only the change it was given for. The same
# change keeps its thread: nothing is posted twice.
#
# Exits 0 when there's nothing to ask or the thread is posted or already there, 1 when it can't
# be posted (the job then fails, so a CI change is never left unflagged), 2 on bad usage.
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
#      CI_BOT (default: github-actions[bot], the login this job's token comments as).
set -uo pipefail

pr="${1:-}" base="${2:-}" head="${3:-}"
[[ "$pr" =~ ^[0-9]+$ && -n "$base" && "$head" =~ ^[0-9a-f]{40}$ ]] || { sed -n '2,20p' "$0" >&2; exit 2; }
repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
[[ "$repo" == */* ]] || { echo "ci-change-thread: can't tell which repo this is" >&2; exit 1; }
bot="${CI_BOT:-github-actions[bot]}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

files="$("$here/ci-changes.sh" "$base" "$head")" || { echo "ci-change-thread: can't list the CI changes" >&2; exit 1; }
if [[ -z "$files" ]]; then
  echo "ci-change-thread: no file on the approval list changed"
  exit 0
fi
digest="$("$here/ci-changes.sh" "$base" "$head" --digest)" && [[ -n "$digest" ]] \
  || { echo "ci-change-thread: can't hash the CI changes" >&2; exit 1; }
marker="<!-- ci-change: $digest -->"

asked="$(gh api "repos/$repo/pulls/$pr/comments" --paginate \
  --jq ".[] | select(.user.login == \"$bot\") | select(.body | contains(\"$marker\")) | .id")" \
  || { echo "ci-change-thread: can't read PR #$pr's comments" >&2; exit 1; }
if [[ -n "$asked" ]]; then
  echo "ci-change-thread: this CI change already has its thread"
  exit 0
fi

mapfile -t list <<<"$files"
n="${#list[@]}"
s=""; ((n == 1)) || s="s"
body="**CI change: needs approval.** This PR changes $n file$s that set CI's rules:

$(printf -- '- `%s`\n' "${list[@]}")

They decide what runs in CI, with what permissions, who approves, and what the agent may do (ADR 0001). Read the change to each, then reply \`Approved: <name>, <date>\`. The Claude review reviews these files too, but only as advice. A later push that changes them again asks again.

$marker"

# A file-level comment needs a path in the PR's diff: try each file until one takes it.
for path in "${list[@]}"; do
  if gh api "repos/$repo/pulls/$pr/comments" --silent -f subject_type=file -f path="$path" \
      -f commit_id="$head" -f body="$body" 2>/dev/null; then
    echo "ci-change-thread: asked for approval of $n file$s, on $path"
    exit 0
  fi
done
echo "ci-change-thread: couldn't post the thread on any of: ${list[*]}" >&2
exit 1
