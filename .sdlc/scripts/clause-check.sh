#!/usr/bin/env bash
# Clause coverage (#47): find the clauses of a change's requirements that no acceptance
# criterion tests (stage spec), that the plan doesn't design and verify (stage plan), or that
# the code and build.md deliver less of than the requirement says (stage build, #106).
#
# Usage: .sdlc/scripts/clause-check.sh --stage spec|plan|build <change> [--ref REF]
#        .sdlc/scripts/clause-check.sh --changed-since REF
#   <change>  0002, 0002-name or a folder path
#   --ref     check only the requirements that are new or differ from REF (an amendment PR),
#             counting only what the stage reads: a new build.md doesn't widen stage plan (#257)
#   --changed-since  the Claude review's mode: every change whose spec.md or plan.md differs
#             where the branch left REF, at stage plan when its plan.md changed and spec otherwise, each with
#             --ref REF. Entries carry a "change" field. A change whose spec can't be split is
#             one unchecked entry, and the others are still checked.
#
# Splits the spec with `make clauses` (no model), then sends every block of the change to one
# small-model call through .sdlc/scripts/agent.sh (#257: one cold start, not one a requirement).
# The answer names each requirement it checked; one that isn't there reads as unchecked, never as
# covered. Prints a JSON array:
#   {"requirement": "R2", "text": "...", "stage": "spec", "clause": "...", "missing": [...]}
# Stage build reads the code (Read, Grep and Glob), so it uses a larger model and more turns, and
# its entries hold "delivered", "gap" ("large" when the delivery lacks the clause's main verb or
# noun, "small" for a modifier; anything else reads as large) and "approved" (a quote or null)
# in place of "missing". An approval is kept only when its quote is in the change's spec.md,
# plan.md or build.md (ignoring whitespace, `*` and backticks); otherwise "approved" is null and
# the quote moves to "approval_not_found", so a made-up approval can't hide a gap.
# For a requirement whose answer couldn't be read or whose call failed:
#   {"requirement": "R2", "text": "...", "stage": "spec", "unchecked": "<why>"}
# A line under ## Requirements that couldn't be read as one is unchecked too, with
# "requirement": null and the line as its "text".
# An unchecked requirement is reported, never read as covered.
#
# Env:
#   CLAUSE_MODEL  model for the call at stages spec and plan (default: haiku)
#   DELIVERY_MODEL, DELIVERY_MAX_TURNS  the same for stage build (default: sonnet; 15 turns a
#                 requirement, at most 60)
#   AGENT         passed through to agent.sh (echo for a dry run)
set -euo pipefail

usage() {
  echo "usage: clause-check.sh --stage spec|plan|build <change> [--ref REF] | --changed-since REF" >&2
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
  [[ "$stage" == spec || "$stage" == plan || "$stage" == build ]] || usage
  [[ -n "$change" ]] || usage
fi

root="$(cd "$(dirname "$0")/../.." && pwd)"

# The files the branch adds or edits against main, outside changes/, for stage build.
changed_files() {
  local base
  base="$(git -C "$root" merge-base origin/main HEAD 2>/dev/null \
    || git -C "$root" merge-base main HEAD 2>/dev/null)" || { echo "[]"; return; }
  { git -C "$root" diff --name-only "$base"; git -C "$root" ls-files --others --exclude-standard; } \
    | { grep -v '^changes/' || true; } | sort -u | jq -R . | jq -sc .  # none: grep exits 1
}

# The change's folder, however it was named: a path, or a slug or number under changes/.
change_dir() {
  local change="$1" name="$2"
  if [[ -d "$change" ]]; then echo "$change"
  elif [[ -d "$root/$change" ]]; then echo "$root/$change"
  else echo "$root/changes/$name"
  fi
}

# check <stage> <change> <ref>: the JSON array for one change. One model call per change and
# stage reads every block (#257); each requirement it sent must come back in the answer.
check() {
  local stage="$1" change="$2" ref="$3" blocks count results base prompt
  local answer line found prompt_file model turns tools files="[]" shape docs="" why=""
  # STAGE: with a ref, only what this stage reads counts as changed (#257).
  blocks="$(make -s -C "$root" clauses CHANGE="$change" ${ref:+REF="$ref"} STAGE="$stage")" || return 1
  count="$(jq '.requirements | length' <<<"$blocks")"
  if [[ "$stage" == build ]]; then
    prompt_file=delivery-check.md model="${DELIVERY_MODEL:-sonnet}" tools="Read,Grep,Glob"
    # Turns for the whole run: 15 a requirement, at most 60, unless DELIVERY_MAX_TURNS says.
    turns="${DELIVERY_MAX_TURNS:-$((count * 15 < 60 ? count * 15 : 60))}"
    files="$(changed_files)"
    local dir
    dir="$(change_dir "$change" "$(jq -r .change <<<"$blocks")")"
    docs="$(cat "$dir"/spec.md "$dir"/plan.md "$dir"/build.md 2>/dev/null || true)"
    shape='{clause, delivered: (.delivered // "" | tostring),
      gap: (if .gap == "small" then "small" else "large" end),
      approved: (if (.approved | type) == "string" and .approved != "" then .approved else null end)}'
  else
    prompt_file=clause-check.md model="${CLAUSE_MODEL:-haiku}" turns=1 tools=Read
    shape='{clause, missing: (.missing // [] | if type == "array" then . else [.] end)}'
  fi
  # One base entry per requirement sent: {requirement, text, stage}.
  base="$(jq -c --arg s "$stage" '[.requirements[] | {requirement: .id, text, stage: $s}]' <<<"$blocks")"
  found="null"
  if ((count > 0)); then
    prompt="$("$root/.sdlc/scripts/resolve.sh" "prompts/$prompt_file"
      printf '\nStage: %s\n\nBlocks:\n' "$stage"
      jq -c --argjson f "$files" '.requirements | if $f == [] then . else {changed_files: $f, requirements: .} end' <<<"$blocks")"
    if answer="$(AGENT_MAX_TURNS="$turns" AGENT_ALLOWED_TOOLS="$tools" \
        "$root/.sdlc/scripts/agent.sh" - --model "$model" <<<"$prompt" 2>/dev/null)"; then
      line="$(grep '^CLAUSES: ' <<<"$answer" | tail -n 1 || true)"
      if [[ -z "$line" ]] || ! found="$(jq -ce 'if type == "array" and all(.[]; type == "object"
            and (.requirement | type) == "string" and (.clauses | type) == "array"
            and all(.clauses[]; type == "object" and (.clause | type) == "string"))
          then . else error("not a list of requirements with their clauses") end' <<<"${line#CLAUSES: }" 2>/dev/null)"; then
        found="null" why="the clause check gave no CLAUSES line that could be read"
      fi
    else
      why="the clause check call failed"
    fi
  fi
  # Each requirement sent: its clauses from the answer, or unchecked when the answer has no entry
  # for it. Entries for a requirement that wasn't sent are dropped.
  results="$(jq -c --argjson found "$found" --arg why "$why" "
    map(. as \$b | (\$found // [] | map(select(.requirement == \$b.requirement))) as \$mine
      | if \$found == null then [\$b + {unchecked: \$why}]
        elif \$mine == [] then [\$b + {unchecked: \"the clause check gave no answer for this requirement\"}]
        else [\$mine[].clauses[] | \$b + $shape] end) | add // []" <<<"$base")"
  if [[ "$stage" == build ]]; then
    # Keep an approval only if its quote is really there (PR #109 review).
    results="$(jq -c --arg docs "$docs" '
      def norm: gsub("[*`]"; "") | gsub("\\s+"; " ") | ltrimstr(" ") | rtrimstr(" ");
      ($docs | norm) as $d
      | map(if has("unchecked") then . else (.approved // "" | norm) as $a
            | if .approved == null or ($a != "" and ($d | contains($a))) then .
              else . + {approved: null, approval_not_found: .approved} end end)' <<<"$results")"
  fi
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
