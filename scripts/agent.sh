#!/usr/bin/env bash
# The single place the pipeline calls an AI agent. Everything else (CI workflows,
# evals) goes through this script, so another agent can be swapped in here alone.
#
# Usage: scripts/agent.sh <prompt-file | -> [extra agent args...]
#   Reads the prompt from the file (or stdin for "-"), runs the agent
#   non-interactively in the current directory, and prints its final output.
#
# Env:
#   AGENT     which adapter to use (default: claude)
#   AGENT_MAX_TURNS  turn budget for one run (default: 30)
set -euo pipefail

prompt_src="${1:?usage: agent.sh <prompt-file|-> [args...]}"
shift
if [[ "$prompt_src" == "-" ]]; then prompt="$(cat)"; else prompt="$(cat "$prompt_src")"; fi

case "${AGENT:-claude}" in
  claude)
    exec claude -p "$prompt" \
      --max-turns "${AGENT_MAX_TURNS:-30}" \
      --permission-mode acceptEdits \
      "$@"
    ;;
  echo)
    # Dry-run adapter for testing the pipeline without calling a model.
    printf '%s\n' "$prompt"
    ;;
  *)
    echo "agent.sh: unknown AGENT '${AGENT}'" >&2
    exit 2
    ;;
esac
