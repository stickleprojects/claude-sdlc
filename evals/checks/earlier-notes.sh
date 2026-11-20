#!/usr/bin/env bash
# The check for the earlier-notes rule (#242). The earlier summary had three notes: the PR body
# said semicolons (since fixed in the body, with no commit), CHANGELOG.md had no entry (since
# added by the PR's last commit), and the product owner's approval was needed (still missing).
# The new summary must mark the first two ✅, the CHANGELOG one with that commit's sha, and the
# approval ⬜ still open. It mustn't drop any. Only lines marked ✅ or ⬜ count, since a
# summary's other lines mention approval too.
set -uo pipefail
fail() { echo "check: $*"; echo "      --- summary.md ---"; sed 's/^/      /' summary.md 2>/dev/null; exit 1; }

# The prompt asks for ./summary.md; a review that took notes/ as "the repo" is read too.
[[ -s summary.md ]] || cp notes/summary.md summary.md 2>/dev/null
[[ -s summary.md ]] || { echo "check: no summary.md"; exit 1; }
sha="$(git -C notes rev-parse --short=7 HEAD)"
marked="$(grep -E '✅|⬜' summary.md || true)"
[[ -n "$marked" ]] || fail "no note is marked ✅ or ⬜"

body="$(grep -iE 'semicolon|pr body|body' <<<"$marked" | grep -viE 'changelog|product owner' || true)"
[[ -n "$body" ]] || fail "the PR body note was dropped"
grep -q '✅' <<<"$body" || fail "the PR body note isn't marked addressed, though the body now says commas"
grep -q '⬜' <<<"$body" && fail "the PR body note is marked still open"

changelog="$(grep -i 'changelog' <<<"$marked" || true)"
[[ -n "$changelog" ]] || fail "the CHANGELOG note was dropped"
grep -q '✅' <<<"$changelog" || fail "the CHANGELOG note isn't marked addressed"
grep -q "$sha" <<<"$changelog" || fail "the CHANGELOG note doesn't name the commit that added it ($sha)"

approval="$(grep -iE 'product owner|approv' <<<"$marked" | grep -vi 'changelog' || true)"
[[ -n "$approval" ]] || fail "the product owner's approval note was dropped"
grep -q '⬜' <<<"$approval" || fail "the approval note isn't marked still open, and nobody approved"
grep -q '✅' <<<"$approval" && fail "the approval note is marked addressed, and nobody approved"
echo "check: each earlier note was marked, the CHANGELOG one with $sha"
