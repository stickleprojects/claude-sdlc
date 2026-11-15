#!/usr/bin/env bash
# The check for the dependent-design rule (#172): the spec PR moves Thor to the large rig at
# 3.0 units, but the change's plan still says he stays on the medium rig at 2.4 and that no
# animation library changes. One review must name every uncovered clause of R1 in one finding
# (#160) and also flag the plan's Approach that the new requirement makes false.
set -uo pipefail
[[ -s findings.md ]] || { echo "check: no findings.md"; exit 1; }
sections="$(awk '/^## / { if (sec != "") print sec; sec = "" } { sec = sec " " $0 } END { if (sec != "") print sec }' findings.md)"
clauses=0 design=0
while IFS= read -r sec; do
  grep -q 'Rig_Large' <<<"$sec" && grep -q 'Flexing' <<<"$sec" && grep -q 'characters\.md' <<<"$sec" \
    && grep -q 'architecture\.md' <<<"$sec" && clauses=1
  grep -qiE 'medium rig|2\.4' <<<"$sec" && grep -qiE 'approach|plan' <<<"$sec" && design=1
done <<<"$sections"
((clauses)) || { echo "check: no single finding names every uncovered clause of R1:"; cat findings.md; exit 1; }
((design)) || { echo "check: no finding flags the plan's Approach (medium rig at 2.4) as out of date:"; cat findings.md; exit 1; }
echo "check: ok"
