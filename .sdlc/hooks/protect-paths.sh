#!/usr/bin/env bash
# PreToolUse (Edit|Write|MultiEdit|NotebookEdit): block edits to protected paths.
# Exit 2 blocks the edit and shows stderr to Claude.
#
# Tests lock for a bug fix once its failing test is committed (.sdlc/scripts/tests-locked.sh:
# a change with bug.md and a `test(<slug>): …` commit on the branch), or whenever
# SDLC_LOCK_TESTS=1. SDLC_LOCK_TESTS=0 unlocks them deliberately.
set -euo pipefail

path="$(jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')"
[[ -z "$path" ]] && exit 0
rel="${path#"${CLAUDE_PROJECT_DIR:-$PWD}"/}"

block() {
  echo "Blocked edit to $rel: $1" >&2
  exit 2
}

case "$rel" in
  .git/*) block "git internals are never edited directly." ;;
  uv.lock|*.lock) block "lockfiles change only through the package manager (make setup)." ;;
  .env|.env.*|*.pem|*.key) block "secrets stay out of the repo and out of diffs." ;;
  .sdlc/hooks/*|.claude/settings.json)
    block "guardrails change only through a human-reviewed PR; describe the change you want instead." ;;
esac

lock="${CLAUDE_PROJECT_DIR:-$PWD}/.sdlc/scripts/tests-locked.sh"
if [[ -x "$lock" ]]; then
  if reason="$(cd "${CLAUDE_PROJECT_DIR:-$PWD}" && "$lock" "$rel")"; then
    block "tests are locked for this bug fix: $reason Fix the code so the committed test passes (SDLC_LOCK_TESTS=0 unlocks)."
  fi
elif [[ "${SDLC_LOCK_TESTS:-0}" == "1" && "$rel" == tests/* ]]; then
  block "tests are locked for this fix task (SDLC_LOCK_TESTS=1). Fix the code so the committed test passes."
fi
exit 0
