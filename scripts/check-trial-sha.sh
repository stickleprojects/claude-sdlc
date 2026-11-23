#!/usr/bin/env bash
# The release's consumer trial must be of the commit being released (#200).
#
# Usage: scripts/check-trial-sha.sh "<trial line>" <sha>
#
# The release workflow tags $GITHUB_SHA, and its `trial` input is free text written by hand from
# scripts/consumer-trial.sh. Nothing tied the two together: a trial of an older main, with fixes
# merged since, would still pass. The trial branch is chore/sdlc-trial-<short sha>, and the line
# must name that short SHA (7 hex characters). A line naming another SHA, or none, fails, saying
# which commit to re-run the trial on. It checks the text, so it stops a mistake, not a lie.
set -euo pipefail

line="${1:?usage: check-trial-sha.sh \"<trial line>\" <sha>}"
sha="${2:?usage: check-trial-sha.sh \"<trial line>\" <sha>}"
short="${sha:0:7}"
# A word of hex beginning with the short SHA: "x5df79ee" or "5df79eex" is another word.
if grep -qiE "(^|[^0-9a-z])${short}[0-9a-f]*([^0-9a-z]|$)" <<<"$line"; then
  echo "ok: the trial is of ${short}"
  exit 0
fi
named="$(grep -oiE '(^|[^0-9a-z])[0-9a-f]{7,40}([^0-9a-z]|$)' <<<"$line" | grep -oiE '[0-9a-f]{7,40}' | head -1 || true)"
if [[ -n "$named" ]]; then
  echo "::error::the trial line names ${named:0:7}, but this release tags ${short}: main moved since the trial. Re-run the trial from step 2 (scripts/consumer-trial.sh sync) on ${short}." >&2
else
  echo "::error::the trial line names no commit. Start it as scripts/consumer-trial.sh pr prints, with the trial's short SHA (${short} for this release)." >&2
fi
exit 1
