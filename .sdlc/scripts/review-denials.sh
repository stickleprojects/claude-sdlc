#!/usr/bin/env bash
# Why did a Claude review stop without posting? (#157) Print what claude-code-action's run
# refused, from its execution output, so the job log says which tool calls were blocked.
#
# Usage: .sdlc/scripts/review-denials.sh <claude-execution-output.json> [label]
#
# The action writes the session as JSON (an array of messages, the last one the result). Its
# job log gives only `permission_denials_count`; the result message lists each denial with the
# tool and its input. This prints one line per denial, the turn count and how the run ended.
# Never fails: a missing or unreadable file is said, not an error, since it runs only to
# explain a failure that is already reported.
set -uo pipefail

file="${1:-}"
label="${2:-the review}"
if [[ -z "$file" || ! -s "$file" ]]; then
  echo "review-denials: no execution output for $label${file:+ at $file}"
  exit 0
fi
summary="$(jq -r '
  (if type == "array" then . else [.] end) as $msgs
  | ($msgs | map(select(.type? == "result")) | last) as $r
  | if $r == null then "review-denials: no result message in the execution output"
    else
      "\($r.subtype // "unknown") after \($r.num_turns // "?") turn(s), \($r.permission_denials // [] | length) refused tool call(s)",
      ($r.permission_denials // [] | .[]
        | "  refused: \(.tool_name // "?"): \(.tool_input // {} | if has("command") then .command else tostring end | .[0:300])")
    end' "$file" 2>/dev/null)" || summary="review-denials: $file isn't the JSON it should be"
echo "$label: $summary"
exit 0
