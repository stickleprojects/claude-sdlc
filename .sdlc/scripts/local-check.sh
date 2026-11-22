#!/usr/bin/env bash
# The local check before a push or a PR (#253): what the build skill, the build template, the
# verifier and the other skills run on the laptop, as `make local-check`.
#
# Usage: .sdlc/scripts/local-check.sh              run the local check from the repo root
#        .sdlc/scripts/local-check.sh --targets    print the targets it would run, one line
#        .sdlc/scripts/local-check.sh --validate   check the setting only (make validate)
#
# The repo's CLAUDE.md may name the targets on one line, for example `Local check: preflight`,
# or `Local check: check coverage`. A leading `make` is allowed (`Local check: make preflight`).
#   - No line: `check`, then `coverage` if the Makefile has that target (what the build skill
#     always ran).
#   - A line: exactly the targets it names, in order. Coverage runs only if it's named; otherwise
#     the PR's CI runs it, and the last line says so, for build.md's status and the PR body.
# A name that isn't a make target name, or that the Makefile doesn't define, fails with a message
# naming the setting (like .sdlc/scripts/pr-check-target.sh). `local-check` itself is refused,
# since it would run itself.
#
# The last line of a run is the coverage line the skills read:
#   coverage: ran (make coverage)
#   coverage: in CI (the Local check line leaves make coverage to the PR's CI)
#   coverage: none (the Makefile has no coverage target)
#
# Env: SDLC_CLAUDE_MD  the CLAUDE.md to read (default: CLAUDE.md)
set -euo pipefail

mode="run"
case "${1:-}" in
  "") ;;
  --targets) mode=targets ;;
  --validate) mode=validate ;;
  *) echo "usage: local-check.sh [--targets | --validate]" >&2; exit 2 ;;
esac

claude_md="${SDLC_CLAUDE_MD:-CLAUDE.md}"
# make's database, without running anything: -q runs no recipes, -p prints the rules. A target
# has a recipe or prerequisites; a name make only knows from .PHONY or as a prerequisite has
# neither, or comes after "# Not a target:", and doesn't count.
targets_known="$(make -pRrq 2>/dev/null | awk '
  function done() { if (name != "" && real) print name; name = ""; real = 0 }
  /^# Not a target:/ { done(); skip = 1; next }
  /^[a-z][a-z0-9-]*:/ && !/^[^:]*:=/ {
    done(); if (skip) { skip = 0; next }
    name = $0; sub(/:.*/, "", name); rest = $0; sub(/^[^:]*:+/, "", rest)
    real = (rest ~ /[^[:space:]]/); next }
  /^#  recipe to execute/ { real = 1 }
  /^$/ { done(); skip = 0 }
  END { done() }' || true)"
has_target() { grep -qx -- "$1" <<<"$targets_known"; }

line="$(sed -nE 's/^(- )?Local check:[[:space:]]*(.*[^[:space:]])?[[:space:]]*$/\2/p' "$claude_md" 2>/dev/null | tail -n 1 || true)"
set_by_line=false
if grep -qE '^(- )?Local check:' "$claude_md" 2>/dev/null; then
  set_by_line=true
  # Backticks are allowed around the value, as CLAUDE.md lines often have them.
  value="${line//\`/}"
  value="${value#make }"
  read -r -a targets <<<"$value" || true
  if ((${#targets[@]} == 0)); then
    echo "CLAUDE.md: the 'Local check:' line names no target. Name one, e.g. 'Local check: preflight', or delete the line to run 'check'." >&2
    exit 1
  fi
  for t in "${targets[@]}"; do
    if ! [[ "$t" =~ ^[a-z][a-z0-9-]*$ ]]; then
      echo "CLAUDE.md: 'Local check: $value' names '$t', which isn't a make target name (lower-case letters, digits and -)." >&2
      exit 1
    fi
    if [[ "$t" == local-check ]]; then
      echo "CLAUDE.md: 'Local check: $value' names 'local-check', which would run itself. Name the targets it should run." >&2
      exit 1
    fi
    if ! has_target "$t"; then
      echo "CLAUDE.md: 'Local check: $value' names '$t', but the Makefile has no '$t' target. Add it, or fix the line." >&2
      exit 1
    fi
  done
else
  targets=(check)
  has_target coverage && targets+=(coverage)
fi

[[ "$mode" == validate ]] && exit 0
if [[ "$mode" == targets ]]; then
  echo "${targets[*]}"
  exit 0
fi

for t in "${targets[@]}"; do
  echo "local-check: make $t"
  make --no-print-directory "$t"
done

if [[ " ${targets[*]} " == *" coverage "* ]]; then
  echo "coverage: ran (make coverage)"
elif has_target coverage; then
  echo "coverage: in CI (the Local check line leaves make coverage to the PR's CI)"
else
  echo "coverage: none (the Makefile has no coverage target)"
fi
