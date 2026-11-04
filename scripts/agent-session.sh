#!/usr/bin/env bash
# Start Claude Code as the agent's GitHub identity (see docs/agent-identity.md).
#
# Usage: scripts/agent-session.sh [--persona <name>] [claude arguments...]
#          e.g. scripts/agent-session.sh --persona build --worktree 0002-jd-extraction
#        scripts/agent-session.sh --hook
#          As a SessionStart hook: appends the identity's environment to $CLAUDE_ENV_FILE, so
#          every Bash command in the session commits, pushes and comments as the agent.
#
# When the identity isn't configured, the session starts as the person, with a note.
# Env: SDLC_CLAUDE  the command to run instead of `claude` (tests use `env`).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == --hook ]]; then
  [[ -n "${CLAUDE_ENV_FILE:-}" ]] || exit 0
  "$here/agent-identity.sh" env >> "$CLAUDE_ENV_FILE" || true  # never block a session start
  exit 0
fi

persona=()
if [[ "${1:-}" == --persona ]]; then
  [[ -n "${2:-}" ]] || { echo "--persona needs a name, e.g. build" >&2; exit 2; }
  persona=(--persona "$2")
  shift 2
fi
eval "$("$here/agent-identity.sh" env "${persona[@]}")"
# A bug fix whose failing test is already committed starts with its tests locked, so nobody
# has to remember SDLC_LOCK_TESTS=1 (the protect-paths hook reads it).
if [[ -z "${SDLC_LOCK_TESTS:-}" ]] && why="$("$here/tests-locked.sh")"; then
  export SDLC_LOCK_TESTS=1
  echo "tests locked: $why" >&2
fi
exec ${SDLC_CLAUDE:-claude} "$@"
