#!/usr/bin/env bash
# Has a person decided every "Descope: needs approval" thread on a PR? (#132) And every
# "Session decisions: needs approval" thread (#218): the one thread for everything a person
# decided during the build session, its plan amendments (#174) and its descopes. It's read the
# same way, so one person's reply approves all of them, never a line in build.md. An older
# review's "Plan changes: needs approval" thread counts as one too. So does a "CI change: needs
# approval" thread (ADR 0001, #293): the review job posts it, not the reviewer, when a PR changes
# a file that sets CI's rules (ci-changes.sh), and only an `Approved:` reply settles it.
#
# Usage: .sdlc/scripts/descopes-decided.sh <pr-number>
#
# Conversation resolution lets anyone with write access, the agent's App included, resolve a
# thread, so a descope could merge with nobody approving it. This reads the decision from the
# thread's replies instead. A thread the reviewer started whose first comment says
# `Descope: needs approval` is decided when a person (not a bot or an App) has replied in it:
#   - a reply with `Approved: <name>, <date>` approves the descope; its author and time are the
#     audit record;
#   - any other reply from a person sends the work back to be built, or says it's built. An agent
#     can write it from the person's account, so it settles the thread only once the thread is
#     resolved and the Claude review has run after the reply (#275): the re-review keeps an
#     unresolved thread as needing approval, and posts a new one when a resolved thread's work
#     still isn't there. A thread left open needs the Approved reply.
# Resolving alone never settles a thread. GitHub doesn't say when one was resolved, so a thread
# resolved after the re-review also counts, the next time this runs.
#
# Exits 0 when every descope thread is decided, printing who approved each one (or that there
# are none), 1 when one isn't (printing a reason short enough for a commit status), and 3 when
# the threads or comments can't be read.
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
#      REVIEW_BOT (default: claude[bot], the login claude-code-action comments as).
#      CI_BOT (default: github-actions[bot], the login the review job posts a CI change as).
set -uo pipefail

pr="${1:-}"
[[ "$pr" =~ ^[0-9]+$ ]] || { sed -n '2,24p' "$0" >&2; exit 2; }
repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
[[ "$repo" == */* ]] || { echo "descopes-decided: can't tell which repo this is" >&2; exit 3; }
bot="${REVIEW_BOT:-claude[bot]}"
login="${bot%\[bot\]}"  # GraphQL names an App's account without the [bot] suffix
ci_bot="${CI_BOT:-github-actions[bot]}"
ci_login="${ci_bot%\[bot\]}"

# When the review last posted or replaced its summary (the comment with the count line).
reviewed="$(gh api "repos/$repo/issues/$pr/comments" --paginate \
  --jq ".[] | select(.user.login == \"$bot\") | select(.body | test(\"<!--\\\\s*review-findings:\")) | .updated_at")" \
  || { echo "descopes-decided: can't read PR #$pr's comments" >&2; exit 3; }
reviewed="$(sort <<<"$reviewed" | tail -1)"

# One JSON line per descope thread: its first line, and the people's replies in order.
query='query($owner: String!, $name: String!, $pr: Int!, $endCursor: String) {
  repository(owner: $owner, name: $name) { pullRequest(number: $pr) {
    reviewThreads(first: 100, after: $endCursor) {
      pageInfo { hasNextPage endCursor }
      nodes { isResolved comments(first: 100) { nodes {
        author { login __typename } body createdAt } } } } } } }'
threads="$(gh api graphql --paginate -f query="$query" -F owner="${repo%%/*}" \
  -F name="${repo#*/}" -F pr="$pr" --jq "
    .data.repository.pullRequest.reviewThreads.nodes[] | .isResolved as \$resolved | .comments.nodes
    | select(length > 0)
    | select(.[0].body | test(\"(Descope|Plan changes|Session decisions|CI change): needs approval\"))
    | (.[0].body | test(\"CI change: needs approval\")) as \$ci
    | select((.[0].author.login // \"\" | sub(\"\\\\[bot\\\\]\$\"; \"\"))
             == (if \$ci then \"$ci_login\" else \"$login\" end))
    | {kind: (if \$ci then \"CI change\"
              elif (.[0].body | test(\"Session decisions: needs approval\")) then \"session decision\"
              elif (.[0].body | test(\"Plan changes: needs approval\")) then \"plan change\" else \"descope\" end),
       resolved: \$resolved,
       first: (.[0].body | split(\"\\n\") | map(select(test(\"\\\\S\"))) | .[0] // \"\"),
       people: [.[1:][] | select(.author.__typename == \"User\")
                 | {who: .author.login, at: .createdAt,
                    approved: (.body | test(\"Approved:\\\\s*\\\\S\"))}]}
    | @json")" \
  || { echo "descopes-decided: can't read PR #$pr's review threads" >&2; exit 3; }

short() {  # the finding's first line, without its markdown lead-in, for a status
  local text
  text="$(sed -E 's/^\s*\*\*Important[^*]*\*\*:?\s*//; s/\*\*//g' <<<"$1")"
  text="${text#Descope: needs approval}"
  text="${text#Plan changes: needs approval}"
  text="${text#Session decisions: needs approval}"
  text="${text#CI change: needs approval}"
  text="$(sed -E 's/^[.:]?\s*//' <<<"$text")"
  printf '%s' "${text:0:40}"
}

decided=()
n=0
while IFS= read -r thread; do
  [[ -n "$thread" ]] || continue
  n=$((n + 1))
  first="$(jq -r .first <<<"$thread")"
  kind="$(jq -r .kind <<<"$thread")"
  approval="$(jq -r '[.people[] | select(.approved)] | last | select(.) | "\(.who) (\(.at[:10]))"' <<<"$thread")"
  if [[ -n "$approval" ]]; then
    case "$kind" in
      descope) decided+=("approved by @$approval") ;;
      "plan change") decided+=("plan changes approved by @$approval") ;;
      "CI change") decided+=("CI change approved by @$approval") ;;
      *) decided+=("session decisions approved by @$approval") ;;
    esac
    continue
  fi
  if [[ "$kind" == "CI change" ]]; then  # nothing to build: only a person's approval settles it
    echo "A CI change needs a person's approval: $(short "$first"). Reply Approved: <name>, <date>"
    exit 1
  fi
  reply="$(jq -r '.people | last | select(.) | "\(.who) \(.at)"' <<<"$thread")"
  if [[ -z "$reply" ]]; then
    echo "A $kind waits for a person's decision: $(short "$first"). Reply Approved: <name>, <date>, or send it back"
    exit 1
  fi
  who="${reply% *}"
  at="${reply#* }"
  if [[ -z "$reviewed" || ! "$reviewed" > "$at" ]]; then
    echo "@$who sent a $kind back ($(short "$first")): once it's built, add the review label to check it"
    exit 1
  fi
  if [[ "$(jq -r .resolved <<<"$thread")" != true ]]; then
    echo "A $kind still needs approval: $(short "$first"). Reply Approved: <name>, <date>, or build, resolve, re-review"
    exit 1
  fi
  decided+=("sent back by @$who, re-reviewed")
done <<<"$threads"

if ((n == 0)); then
  echo "no descopes to approve"
else
  printf -v list '%s; ' "${decided[@]}"
  echo "descopes decided: ${list%; }"
fi
