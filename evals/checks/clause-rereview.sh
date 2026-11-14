#!/usr/bin/env bash
# The check for the re-review rule (#160). An earlier thread split R1 and the author covered
# what it listed; R1's text is unchanged, so "on the large Barbarian", which that thread didn't
# list, must not become an Important finding now. R2 was reworded with a new clause (the error
# that names the character), which no criterion tests: that one must still be Important.
set -uo pipefail
# The prompt asks for ./findings.md; a review that took rereview/ as "the repo" is read too.
[[ -s findings.md ]] || cp rereview/findings.md findings.md 2>/dev/null
[[ -s findings.md ]] || { echo "check: no findings.md"; exit 1; }
sections="$(awk '/^## / { if (sec != "") print sec; sec = "" } { sec = sec " " $0 } END { if (sec != "") print sec }' findings.md)"
important="$(grep -F '**Important' <<<"$sections" || true)"
if grep -qi 'barbarian' <<<"$important"; then
  echo "check: a new Important finding on R1's unchanged text (the Barbarian clause):"
  cat findings.md
  exit 1
fi
if ! grep -qiE 'names the character|doesn.t define' <<<"$important"; then
  echo "check: R2's new clause (an error that names the character) isn't an Important finding:"
  cat findings.md
  exit 1
fi
echo "check: the earlier split stood, and the new clause was caught"
