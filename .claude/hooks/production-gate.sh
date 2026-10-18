#!/usr/bin/env bash
# PreToolUse (Bash): the agent may act up to the production gate and cannot pass it.
# Exit 2 blocks the command and shows stderr to Claude, including the route to approval.
set -euo pipefail

cmd="$(jq -r '.tool_input.command // empty')"

if grep -Eq '(^|[^[:alnum:]_-])deploy-prod([^[:alnum:]_-]|$)' <<<"$cmd"; then
  cat >&2 <<'EOF'
Blocked: production deploys need a named release authorization from a human.
Route: open or update the PR, then ask the release manager to run
  make deploy-prod RELEASE_AUTHORIZED_BY=<their name>
EOF
  exit 2
fi

# The agent opens and updates PRs but never merges or approves them: a human does.
# In solo mode Claude uses the human's gh login, so GitHub can't enforce this; this can.
merge_or_approve() {
  cat >&2 <<'EOF'
Blocked: merging and approving PRs is a human decision, not the agent's.
Route: tell the human the PR is ready (checks green, review summary read) and let them merge it.
EOF
  exit 2
}

# Inspect each command segment on its own, so words elsewhere in a compound command
# (e.g. `git merge main && git push`) don't trigger a false block.
while IFS= read -r segment; do
  if [[ "$segment" =~ (^|[[:space:]])gh[[:space:]]+pr[[:space:]]+merge([[:space:]]|$) ]]; then
    merge_or_approve
  fi
  if [[ "$segment" =~ (^|[[:space:]])gh[[:space:]]+pr[[:space:]]+review([[:space:]]|$) ]] \
    && grep -Eq '(^|[[:space:]])(--approve|-a)([[:space:]]|$)' <<<"$segment"; then
    merge_or_approve
  fi
  if [[ "$segment" =~ (^|[[:space:]])gh[[:space:]]+api([[:space:]]|$) ]] \
    && grep -Eq '/pulls/[0-9]+/merge|event[=:"[:space:]]+"?APPROVE' <<<"$segment"; then
    merge_or_approve
  fi

  [[ "$segment" =~ git[[:space:]]+push([[:space:]]+(.*))?$ ]] || continue
  args="${BASH_REMATCH[2]:-}"
  if grep -Eq '(^|[[:space:]])(--force|--force-with-lease|-f)([=[:space:]]|$)' <<<"$args"; then
    echo "Blocked: force pushes are not allowed for the agent." >&2
    exit 2
  fi
  # A bare `main`/`master` ref, or `<src>:main`, means pushing to main.
  if grep -Eq '(^|[[:space:]:+])(main|master)([[:space:]]|$)' <<<"$args"; then
    echo "Blocked: the agent has no direct path to main. Push a branch and open a PR." >&2
    exit 2
  fi
done < <(sed -E 's/(&&|\|\||;|\|)/\n/g' <<<"$cmd")
exit 0
