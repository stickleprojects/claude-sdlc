#!/usr/bin/env bash
# Clause coverage (#47): find the clauses of a change's requirements that no acceptance
# criterion tests (stage spec), that the plan doesn't design and verify (stage plan), or that
# the code and build.md deliver less of than the requirement says (stage build, #106).
#
# Usage: scripts/clause-check.sh --stage spec|plan|build <change> [--ref REF]
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
#   CLAUSE_MODEL  model for the per-requirement calls at stages spec and plan (default: haiku)
#   DELIVERY_MODEL, DELIVERY_MAX_TURNS  the same for stage build (default: sonnet, 15)
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

root="$(cd "$(dirname "$0")/.." && pwd)"

# The files the branch adds or edits against main, outside changes/, for stage build.
changed_files() {
  local base
  base="$(git -C "$root" merge-base origin/main HEAD 2>/dev/null \
    || git -C "$root" merge-base main HEAD 2>/dev/null)" || { echo "[]"; return; }
  { git -C "$root" diff --name-only "$base"; git -C "$root" ls-files --others --exclude-standard; } \
    | grep -v '^changes/' | sort -u | jq -R . | jq -sc .
}

# The change's folder, however it was named: a path, or a slug or number under changes/.
change_dir() {
  local change="$1" name="$2"
  if [[ -d "$change" ]]; then echo "$change"
  elif [[ -d "$root/$change" ]]; then echo "$root/$change"
  else echo "$root/changes/$name"
  fi
}

# check <stage> <change> <ref>: the JSON array for one change.
check() {
  local stage="$1" change="$2" ref="$3" blocks count results block rid text base prompt
  local answer line found entries prompt_file model turns tools files="[]" shape docs=""
  blocks="$(make -s -C "$root" clauses CHANGE="$change" ${ref:+REF="$ref"})" || return 1
  if [[ "$stage" == build ]]; then
    prompt_file=delivery-check.md model="${DELIVERY_MODEL:-sonnet}"
    turns="${DELIVERY_MAX_TURNS:-15}" tools="Read,Grep,Glob" files="$(changed_files)"
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
  count="$(jq '.requirements | length' <<<"$blocks")"
  results="[]"
  for ((i = 0; i < count; i++)); do
    block="$(jq -c --argjson f "$files" ".requirements[$i]"' + if $f == [] then {} else {changed_files: $f} end' <<<"$blocks")"
    rid="$(jq -r .id <<<"$block")"
    text="$(jq -r .text <<<"$block")"
    base="$(jq -nc --arg r "$rid" --arg t "$text" --arg s "$stage" \
      '{requirement: $r, text: $t, stage: $s}')"
    prompt="$(cat "$root/prompts/$prompt_file"; printf '\nStage: %s\n\nBlock:\n%s\n' "$stage" "$block")"
    if answer="$(AGENT_MAX_TURNS="$turns" AGENT_ALLOWED_TOOLS="$tools" \
        "$root/scripts/agent.sh" - --model "$model" <<<"$prompt" 2>/dev/null)"; then
      line="$(grep '^CLAUSES: ' <<<"$answer" | tail -n 1 || true)"
      if [[ -n "$line" ]] && found="$(jq -ce 'if type == "array" and all(.[]; type == "object" and (.clause | type) == "string")
          then . else error("not a list of clauses") end' <<<"${line#CLAUSES: }" 2>/dev/null)"; then
        entries="$(jq -c --argjson b "$base" \
          "map(\$b + $shape)" \
          <<<"$found")"
        if [[ "$stage" == build ]]; then
          # Keep an approval only if its quote is really there (PR #109 review).
          entries="$(jq -c --arg docs "$docs" '
            def norm: gsub("[*`]"; "") | gsub("\\s+"; " ") | ltrimstr(" ") | rtrimstr(" ");
            ($docs | norm) as $d
            | map((.approved // "" | norm) as $a
                  | if .approved == null or ($a != "" and ($d | contains($a))) then .
                  else . + {approved: null, approval_not_found: .approved} end)' <<<"$entries")"
        fi
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
