#!/usr/bin/env bash
# The check for the hand-check eval (#171), run in the eval's consumer after the agent stops.
# Before handing the person things to try, the agent must have scripted every behaviour a test
# can check: each one gets a mutant of app/menu.py, and the agent's tests must fail on it.
# Only what no test in this repo can settle (the menu's slide-in animation) goes to the person.
set -uo pipefail
fail() { echo "check: $*"; [[ -f handoff.md ]] && sed 's/^/      /' handoff.md; exit 1; }

[[ -s handoff.md ]] || fail "no handoff.md"
grep -qiE 'anim|slide' handoff.md || fail "handoff.md doesn't ask the person about the animation"
git diff --quiet HEAD -- app tests || fail "uncommitted changes in app/ or tests/"
make -s test >/dev/null 2>&1 || fail "make test fails on the agent's commit"

cp app/menu.py /tmp/menu.py.orig.$$
restore() { cp /tmp/menu.py.orig.$$ app/menu.py; }
mutant() {  # $1: what the mutant breaks; $2: a python3 expression that rewrites src
  python3 -c "import sys; src = open('app/menu.py').read(); new = $2; assert new != src, 'mutant changed nothing'; open('app/menu.py', 'w').write(new)" \
    || { restore; fail "can't make the mutant for $1 (was app/menu.py rewritten?)"; }
  if make -s test >/dev/null 2>&1; then restore; fail "no test catches a broken $1"; fi
  restore
}
mutant "--start-room check" "src.replace('if arg not in ROOMS:', 'if False:')"
mutant "B closing the menu" "src.replace('elif button == \"B\" and self.menu_open:\n            self.menu_open = False', 'elif button == \"B\" and self.menu_open:\n            pass')"
mutant "pause while the menu is open" "src.replace('elif button == \"pause\":', 'elif button == \"pause\" and not self.menu_open:')"
rm -f /tmp/menu.py.orig.$$
echo "check: ok"
