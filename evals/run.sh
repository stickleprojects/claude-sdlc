#!/usr/bin/env bash
# Run every eval task against the current agent configuration.
#
# A task (evals/tasks/*.json) is {"name", "prompt", "check"}: the prompt goes to
# scripts/agent.sh in a throwaway copy of the repo, then `check` (a shell command)
# runs in that copy and must exit 0. Fails when the pass rate is below EVAL_MIN_PASS_RATE.
# EVAL_TASKS_DIR points at another task folder (the framework's own tests use this).
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
tasks_dir="${EVAL_TASKS_DIR:-$root/evals/tasks}"
min_rate="${EVAL_MIN_PASS_RATE:-0.8}"
pass=0
total=0

for task in "$tasks_dir"/*.json; do
  name="$(jq -r .name "$task")"
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  # Copy tracked and new files only, so the agent sees a clean checkout.
  (cd "$root" && git ls-files -co --exclude-standard -z | xargs -0 cp --parents -t "$work")
  total=$((total + 1))
  if (cd "$work" && jq -r .prompt "$task" | "$root/scripts/agent.sh" - >"$work/.agent.log" 2>&1 \
      && bash -c "$(jq -r .check "$task")"); then
    pass=$((pass + 1))
    echo "PASS  $name"
  else
    echo "FAIL  $name (log: tail of agent output below)"
    tail -n 20 "$work/.agent.log" 2>/dev/null | sed 's/^/      /'
  fi
  rm -rf "$work"
done

echo "evals: $pass/$total passed (minimum rate $min_rate)"
awk -v p="$pass" -v t="$total" -v m="$min_rate" 'BEGIN { exit !(t > 0 && p / t >= m) }'
