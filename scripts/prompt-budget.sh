#!/usr/bin/env bash
# Is each prompt within its word budget? (#201) The framework's own `make check` runs this.
# Framework-only: never synced to consumers.
#
# Usage: scripts/prompt-budget.sh [budget-file]    default scripts/prompt-budget.tsv
#
# A prompt is a file a skill, the review or the verifier puts in a model's context: REVIEW.md,
# .sdlc/skills/**/*.md, .sdlc/agents/*.md and .sdlc/prompts/*.md. Words are counted as `wc -w`
# counts them, leaving out the rules index's markers (`<!-- rule: <id> -->`, .sdlc/docs/rules.md).
#
# A file over its budget, or a prompt with no budget, is a warning: it prints `warning: …` and
# the script still exits 0. PROMPT_BUDGET_STRICT=1 makes a warning fail (exit 1), for when the
# budget becomes a rule. A budget row naming a file that doesn't exist always fails: the table
# is out of date.
set -uo pipefail

budgets="${1:-scripts/prompt-budget.tsv}"
[[ -f "$budgets" ]] || {
  echo "error: no budget file $budgets" >&2
  exit 1
}

words() { sed -E 's/ ?<!-- rule: [^ ]+ -->//g' "$1" | wc -w | tr -d ' '; }

declare -A budget
stale=0
while IFS=$'\t' read -r file max _; do
  [[ -z "$file" || "$file" == \#* ]] && continue
  if [[ ! -f "$file" ]]; then
    echo "error: $budgets names $file, which doesn't exist" >&2
    stale=1
    continue
  fi
  if [[ ! "$max" =~ ^[0-9]+$ ]]; then
    echo "error: $budgets gives $file the budget '$max', not a number of words" >&2
    stale=1
    continue
  fi
  budget["$file"]="$max"
done <"$budgets"
((stale)) && exit 1

warnings=0 total=0 n=0
while IFS= read -r file; do
  w="$(words "$file")"
  total=$((total + w))
  n=$((n + 1))
  if [[ -z "${budget[$file]:-}" ]]; then
    echo "warning: $file has no word budget in $budgets ($w words)"
    warnings=$((warnings + 1))
  elif ((w > budget[$file])); then
    echo "warning: $file is $w words, over its budget of ${budget[$file]}"
    warnings=$((warnings + 1))
  fi
done < <(
  {
    [[ -f .sdlc/REVIEW.md ]] && echo .sdlc/REVIEW.md
    find .sdlc/skills .sdlc/agents .sdlc/prompts -name '*.md' 2>/dev/null
  } | sort
)

if ((warnings)); then
  echo "prompt budget: $warnings warning(s); $n prompts, $total words"
  [[ "${PROMPT_BUDGET_STRICT:-}" == 1 ]] && exit 1
else
  echo "prompt budget: ok, $n prompts within budget, $total words"
fi
exit 0
