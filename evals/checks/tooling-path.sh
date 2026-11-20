#!/usr/bin/env bash
# The check for the tooling path's intent step (#221), run in the eval's consumer after the agent
# stops. The consumer's CLAUDE.md says `Tooling paths: scripts/`.
#
# Usage: tooling-path.sh tooling   a dev script only: the intent says `Kind: tooling`, is
#                                  committed on build/<slug>, and opens no intent PR
#        tooling-path.sh full      the same script plus product code: a plain intent, no Kind
#                                  line, its own intent PR, and no build/<slug> branch
# Either way: no spec, nothing in app/ or tests/, and `make validate` passes.
set -uo pipefail
fail() { echo "check: $*"; git log --oneline --all --name-only eval-base.. 2>/dev/null | head -30 | sed 's/^/      /'; exit 1; }

want="${1:?usage: tooling-path.sh tooling|full}"
slug="$(ls changes 2>/dev/null | grep -E '^[0-9]{4}-' | head -1)"
[[ -n "$slug" ]] || fail "no change folder"
dir="changes/$slug"
[[ -f "$dir/intent.md" ]] || fail "no $dir/intent.md"
kind="$(PYTHONPATH=.sdlc/src python3 -m sdlc.cli kind "$dir")" || fail "can't read the change's kind"
git log --all --format=%H -- "$dir/spec.md" | grep -q . && fail "a spec.md was committed"
[[ -e "$dir/spec.md" ]] && fail "a spec.md exists"
changed="$(git status --porcelain -- app tests | head -5)$(git log --all --format= --name-only eval-base.. -- app tests | head -5)"
[[ -z "$changed" ]] || fail "app or tests changed: $changed"
make -s validate >/dev/null 2>&1 || fail "make validate fails"
title="$(head -1 pr-title.txt 2>/dev/null)"

case "$want" in
  tooling)
    [[ "$kind" == tooling ]] || fail "the intent isn't marked 'Kind: tooling' (kind: $kind)"
    git cat-file -e "build/$slug:$dir/intent.md" 2>/dev/null \
      || fail "intent.md isn't committed on build/$slug"
    [[ "$title" == intent* ]] && fail "it opened an intent PR ('$title'): the tooling path has one PR"
    files="$(git diff --name-only "eval-base...build/$slug")"
    .sdlc/scripts/check-plan-first.sh "build/$slug" <<<"$files" >/dev/null \
      || fail "CI's plan check refuses build/$slug"
    echo "check: $slug took the tooling path"
    ;;
  full)
    [[ "$kind" == feature ]] || fail "the intent is marked '$kind': it changes product code"
    git branch --format='%(refname:short)' | grep -qx "build/$slug" && fail "a build/$slug branch exists"
    other="$(git log --all --format= --name-only eval-base.. | grep -vE '^(changes|docs)/' | grep -v '^$' | sort -u)"
    [[ -z "$other" ]] || fail "files outside changes/ and docs/ were committed: $other"
    [[ "$title" == intent* ]] || fail "no intent PR title in pr-title.txt (got '$title')"
    .sdlc/scripts/check-pr-title.sh "$title" <<<"$dir/intent.md" >/dev/null \
      || fail "CI's title check refuses '$title'"
    echo "check: $slug took the full path"
    ;;
  *) fail "unknown mode $want" ;;
esac
