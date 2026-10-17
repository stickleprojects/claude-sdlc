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

if grep -Eq 'git[[:space:]]+push' <<<"$cmd"; then
  if grep -Eq '(--force|-f([[:space:]]|$)|--force-with-lease)' <<<"$cmd"; then
    echo "Blocked: force pushes are not allowed for the agent." >&2
    exit 2
  fi
  if grep -Eq '([[:space:]:]|^)(main|master)([[:space:]]|$)' <<<"$cmd"; then
    echo "Blocked: the agent has no direct path to main. Push a branch and open a PR." >&2
    exit 2
  fi
fi
exit 0
