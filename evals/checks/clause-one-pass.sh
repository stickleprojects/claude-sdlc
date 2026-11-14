#!/usr/bin/env bash
# The check for the one-pass clause rule (#160): R1 of the hero-docs fixture has four clauses
# no criterion tests, and one finding (one `## ` section of findings.md) must name them all.
set -uo pipefail
[[ -s findings.md ]] || { echo "check: no findings.md"; exit 1; }
sections="$(awk '/^## / { if (sec != "") print sec; sec = "" } { sec = sec " " $0 } END { if (sec != "") print sec }' findings.md)"
while IFS= read -r sec; do
  if grep -q 'Rig_Large' <<<"$sec" && grep -q 'Flexing' <<<"$sec" \
      && grep -q 'characters\.md' <<<"$sec" && grep -q 'architecture\.md' <<<"$sec"; then
    echo "check: one finding names every uncovered clause of R1"
    exit 0
  fi
done <<<"$sections"
echo "check: no single finding names Rig_Large, Flexing, characters.md and architecture.md:"
cat findings.md
exit 1
