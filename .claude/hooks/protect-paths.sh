#!/usr/bin/env bash
# PreToolUse (Edit|Write|MultiEdit|NotebookEdit): block edits to protected paths.
# Exit 2 blocks the edit and shows stderr to Claude.
#
# Set SDLC_LOCK_TESTS=1 for bug-fix sessions: the failing test is committed first,
# then the code is fixed without touching the test.
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
  .claude/hooks/*|.claude/settings.json)
    block "guardrails change only through a human-reviewed PR; describe the change you want instead." ;;
esac

if [[ "${SDLC_LOCK_TESTS:-0}" == "1" && "$rel" == tests/* ]]; then
  block "tests are locked for this fix task (SDLC_LOCK_TESTS=1). Fix the code so the committed test passes."
fi
exit 0
