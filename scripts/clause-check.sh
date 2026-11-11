#!/usr/bin/env bash
# Clause coverage (#47): find the clauses of a change's requirements that no acceptance
# criterion tests (stage spec), or that the plan doesn't design and verify (stage plan).
#
# Usage: scripts/clause-check.sh --stage spec|plan <change> [--ref REF]
#        scripts/clause-check.sh --changed-since REF
#   <change>  0002, 0002-name or a folder path
#   --ref     check only the requirements that are new or differ from REF (an amendment PR)
#   --changed-since  the Claude review's mode: every change whose spec.md or plan.md differs
#             where the branch left REF, at stage plan when its plan.md changed and spec otherwise, each with
#             --ref REF. Entries carry a "change" field. A change whose spec can't be split is
#             one unchecked entry, and the others are still checked.
#
# Splits the spec with `make clauses` (no model), then sends one requirement at a time to a
# small model through scripts/agent.sh, so no call reads the whole spec. Prints a JSON array:
#   {"requirement": "R2", "text": "...", "stage": "spec", "clause": "...", "missing": [...]}
# and, for a requirement whose answer couldn't be read or whose call failed:
#   {"requirement": "R2", "text": "...", "stage": "spec", "unchecked": "<why>"}
# A line under ## Requirements that couldn't be read as one is unchecked too, with
# "requirement": null and the line as its "text".
# An unchecked requirement is reported, never read as covered.
#
# Env:
#   CLAUSE_MODEL  model for the per-requirement calls (default: haiku)
#   AGENT         passed through to agent.sh (echo for a dry run)
set -euo pipefail

usage() {
  echo "usage: clause-check.sh --stage spec|plan <change> [--ref REF] | --changed-since REF" >&2
  exit 2
}

stage="" change="" ref="" since=""
while (($#)); do
  case "$1" in
    --stage) stage="${2:-}"; shift 2 || usage ;;
    --ref) ref="${2:-}"; shift 2 || usage ;;
    --changed-since) since="${2:-}"; shift 2 || usage ;;
    -*) usage ;;
    *) [[ -z "$change" ]] || usage; change="$1"; shift ;;
  esac
done
if [[ -n "$since" ]]; then
  [[ -z "$stage$change$ref" ]] || usage
else
  [[ "$stage" == spec || "$stage" == plan ]] || usage
  [[ -n "$change" ]] || usage
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
# check <stage> <change> <ref>: the JSON array for one change.
check() {
  local stage="$1" change="$2" ref="$3" blocks count results block rid text base prompt
  local answer line found entries
  blocks="$(make -s -C "$root" clauses CHANGE="$change" ${ref:+REF="$ref"})" || return 1
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
      if [[ -n "$line" ]] && found="$(jq -ce 'if type == "array" and all(.[]; type == "object" and (.clause | type) == "string")
          then . else error("not a list of clauses") end' <<<"${line#CLAUSES: }" 2>/dev/null)"; then
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
  # Lines under ## Requirements that couldn't be read as a requirement: nothing checked them.
  jq -c --argjson b "$blocks" --arg s "$stage" '. + ($b.unreadable // [] | map(
    {requirement: null, text: ., stage: $s,
     unchecked: "this line under ## Requirements could not be read as a requirement (expected \"- R<n>. <requirement>\"), so nothing checked it"}))' \
    <<<"$results"
}

if [[ -z "$since" ]]; then
  check "$stage" "$change" "$ref" | jq .
  exit "${PIPESTATUS[0]}"
fi

# Compare with where the branch left REF, so commits on REF since then aren't counted as changes.
fork="$(git -C "$root" merge-base "$since" HEAD)"
changed="$(git -C "$root" diff --name-only "$fork" -- 'changes/*/spec.md' 'changes/*/plan.md')"
err="$(mktemp)"
trap 'rm -f "$err"' EXIT
all="[]"
for dir in $(sed -n 's|^\(changes/[^/]*\)/.*|\1|p' <<<"$changed" | sort -u); do
  [[ -f "$root/$dir/spec.md" ]] || continue  # deleted, or a plan without a spec
  stage=spec
  grep -qx "$dir/plan.md" <<<"$changed" && [[ -f "$root/$dir/plan.md" ]] && stage=plan
  name="${dir#changes/}"
  if out="$(check "$stage" "$root/$dir" "$fork" 2>"$err")"; then
    entries="$(jq -c --arg c "$name" 'map({change: $c} + .)' <<<"$out")"
  else
    entries="$(jq -nc --arg c "$name" --arg s "$stage" --arg e "$(tail -n 3 "$err")" \
      '[{change: $c, stage: $s, unchecked: ("the spec could not be split: " + $e)}]')"
  fi
  all="$(jq -c --argjson e "$entries" '. + $e' <<<"$all")"
done
jq . <<<"$all"
