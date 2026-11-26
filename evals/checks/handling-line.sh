#!/usr/bin/env bash
# The check for the handling-line rule (#289), in a repo with `Change tracking: issues`.
# Usage: handling-line.sh clean|unexplained
#   clean: nothing to find, so the summary has no how-to-handle line at all.
#   unexplained: the body "Small fix." is an Important finding, so the line is there, and it
#   names no slash command (the repo doesn't install the skills): it says to ask Claude Code.
set -uo pipefail
variant="${1:?usage: handling-line.sh clean|unexplained}"
fail() { echo "check: $*"; echo "      --- summary.md ---"; sed 's/^/      /' summary.md 2>/dev/null; exit 1; }

# The prompt asks for ./summary.md; a review that took handling/ as "the repo" is read too.
[[ -s summary.md ]] || cp handling/summary.md summary.md 2>/dev/null
[[ -s summary.md ]] || { echo "check: no summary.md"; exit 1; }
count="$(grep -oE 'review-findings: important=[0-9]+ nit=[0-9]+' summary.md | tail -1)"
[[ -n "$count" ]] || fail "no hidden count line"
important="$(sed -E 's/.*important=([0-9]+).*/\1/' <<<"$count")"
nit="$(sed -E 's/.*nit=([0-9]+).*/\1/' <<<"$count")"
grep -qE '/sdlc-' summary.md && fail "the summary names a /sdlc- command, which this repo doesn't install"

if [[ "$variant" == clean ]]; then
  ((important == 0 && nit == 0)) || fail "the clean PR got findings ($count): the eval needs none"
  grep -qiE 'work through|handl(e|ing) (the )?findings|tagging `?@claude' summary.md \
    && fail "the summary has a how-to-handle line, with no finding open"
  echo "check: no findings, and no how-to-handle line"
else
  ((important >= 1)) || fail "the unexplained PR body wasn't raised as Important ($count)"
  grep -iE 'claude code' summary.md | grep -qE '41' \
    || fail "no line asks Claude Code to work through the findings on PR 41"
  echo "check: the how-to-handle line asks Claude Code about PR 41 and names no command"
fi
