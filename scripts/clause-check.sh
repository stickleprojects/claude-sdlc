#!/usr/bin/env bash
# Clause coverage (#47): find the clauses of a change's requirements that no acceptance
# criterion tests (stage spec), or that the plan doesn't design and verify (stage plan).
#
# Usage: scripts/clause-check.sh --stage spec|plan <change> [--ref REF]
#   <change>  0002, 0002-name or a folder path
#   --ref     check only the requirements that are new or differ from REF (an amendment PR)
#
# Splits the spec with `make clauses` (no model), then sends one requirement at a time to a
# small model through scripts/agent.sh, so no call reads the whole spec. Prints a JSON array:
#   {"requirement": "R2", "text": "...", "stage": "spec", "clause": "...", "missing": [...]}
# and, for a requirement whose answer couldn't be read or whose call failed:
#   {"requirement": "R2", "text": "...", "stage": "spec", "unchecked": "<why>"}
# An unchecked requirement is reported, never read as covered.
#
# Env:
#   CLAUSE_MODEL  model for the per-requirement calls (default: haiku)
#   AGENT         passed through to agent.sh (echo for a dry run)
set -euo pipefail

usage() { echo "usage: clause-check.sh --stage spec|plan <change> [--ref REF]" >&2; exit 2; }

stage="" change="" ref=""
while (($#)); do
  case "$1" in
    --stage) stage="${2:-}"; shift 2 || usage ;;
    --ref) ref="${2:-}"; shift 2 || usage ;;
    -*) usage ;;
    *) [[ -z "$change" ]] || usage; change="$1"; shift ;;
  esac
done
[[ "$stage" == spec || "$stage" == plan ]] || usage
[[ -n "$change" ]] || usage

root="$(cd "$(dirname "$0")/.." && pwd)"
blocks="$(make -s -C "$root" clauses CHANGE="$change" ${ref:+REF="$ref"})"

count="$(jq '.requirements | length' <<<"$blocks")"
results="[]"
for ((i = 0; i < count; i++)); do
  block="$(jq -c ".requirements[$i]" <<<"$blocks")"
  rid="$(jq -r .id <<<"$block")"
  text="$(jq -r .text <<<"$block")"
  base="$(jq -nc --arg r "$rid" --arg t "$text" --arg s "$stage" \
    '{requirement: $r, text: $t, stage: $s}')"
  prompt="$(cat "$root/prompts/clause-check.md"; printf '\nStage: %s\n\nBlock:\n%s\n' "$stage" "$block")"
  if answer="$(AGENT_MAX_TURNS=1 AGENT_ALLOWED_TOOLS=Read \
      "$root/scripts/agent.sh" - --model "${CLAUSE_MODEL:-haiku}" <<<"$prompt" 2>/dev/null)"; then
    line="$(grep '^CLAUSES: ' <<<"$answer" | tail -n 1 || true)"
    if found="$(jq -ce 'if type == "array" and all(.[]; type == "object" and (.clause | type) == "string")
        then . else error("not a list of clauses") end' <<<"${line#CLAUSES: }" 2>/dev/null)" \
        && [[ -n "$line" ]]; then
      entries="$(jq -c --argjson b "$base" \
        'map($b + {clause, missing: (.missing // [] | if type == "array" then . else [.] end)})' \
        <<<"$found")"
    else
      entries="$(jq -c '[. + {unchecked: "the clause check gave no CLAUSES line that could be read"}]' <<<"$base")"
    fi
  else
    entries="$(jq -c '[. + {unchecked: "the clause check call failed"}]' <<<"$base")"
  fi
  results="$(jq -c --argjson e "$entries" '. + $e' <<<"$results")"
done
jq . <<<"$results"
