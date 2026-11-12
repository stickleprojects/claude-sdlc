#!/usr/bin/env bash
# The one hook entry point (#133): .claude/settings.json runs `dispatch.sh <event>` for each
# event, and this runs every row of .sdlc/hooks/hooks.tsv, then .sdlc-local/hooks/hooks.tsv,
# whose event matches and whose tool regex matches the call's tool_name.
#
# Each hook gets the event's JSON on stdin, as Claude Code would give it. The first to exit 2
# blocks the call: its stderr goes to Claude and nothing after it runs. Any other failure is
# reported (exit 1) once every hook has run, which Claude Code shows without blocking.
set -uo pipefail

event="${1:?usage: dispatch.sh <event>}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
input="$(cat)"
tool="$(jq -r '.tool_name // empty' <<<"$input" 2>/dev/null)" || tool=""
status=0

run_table() {  # <table file>
  local ev match cmd parts rc
  [[ -f "$1" ]] || return 0
  while IFS=$'\t' read -r ev match cmd || [[ -n "$ev" ]]; do
    [[ -z "$ev" || "$ev" == \#* || "$ev" != "$event" || -z "$cmd" ]] && continue
    if [[ "$match" != "*" ]]; then
      [[ -n "$tool" && "$tool" =~ ^($match)$ ]] || continue
    fi
    read -ra parts <<<"$cmd"
    rc=0
    "$root/${parts[0]}" "${parts[@]:1}" <<<"$input" || rc=$?
    ((rc == 2)) && exit 2
    ((rc == 0)) || status=1
  done < "$1"
}

run_table "$root/.sdlc/hooks/hooks.tsv"
run_table "$root/.sdlc-local/hooks/hooks.tsv"
exit "$status"
