#!/usr/bin/env bash
# The check for the plan-amendments eval (#174). The build PR amends its plan three ways: two
# recorded in build.md with who decided (the brick runs, the two-level warp list), and one that
# isn't (AC3's Verification row removed). One finding must be the single "Plan changes: needs
# approval" thread naming both recorded amendments, and the unrecorded one must be its own.
set -uo pipefail
[[ -s findings.md ]] || { echo "check: no findings.md"; exit 1; }
sections="$(awk '/^## / { if (sec != "") print sec; sec = "" } { sec = sec " " $0 } END { if (sec != "") print sec }' findings.md)"
single=0 own=0
while IFS= read -r sec; do
  if grep -q 'Plan changes: needs approval' <<<"$sec"; then
    ((single += 1))
    grep -qi 'brick' <<<"$sec" && grep -qiE 'two.level|warp' <<<"$sec" \
      || { echo "check: the Plan changes thread doesn't name both recorded amendments:"; cat findings.md; exit 1; }
  elif grep -q 'Important' <<<"$sec" && grep -qiE 'AC3|lift' <<<"$sec"; then
    own=1
  fi
done <<<"$sections"
((single == 1)) || { echo "check: expected one Plan changes thread, found $single:"; cat findings.md; exit 1; }
((own)) || { echo "check: the unrecorded amendment (AC3's row removed) has no Important finding of its own:"; cat findings.md; exit 1; }
echo "check: ok"
