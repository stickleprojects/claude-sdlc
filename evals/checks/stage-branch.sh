#!/usr/bin/env bash
# The stage-branch evals (#279): a plain /sdlc-build in a copy still on its merged plan branch.
#
# Usage: stage-branch.sh setup <mode>    in the eval's consumer, before the agent
#        stage-branch.sh check <mode>    after it
#   clean      nothing to lose: the copy moves to build/<slug>, from origin/main
#   dirty      an uncommitted edit: the agent asks, and the branch and the edit stay as they were
#   unmerged   a commit that isn't on main: the agent asks, and the branch stays as it was
# The agent writes MOVED or ASK to outcome.txt.
set -euo pipefail
fail() { echo "check: $*"; git status -sb | head -5 | sed 's/^/      /'; exit 1; }

slug=0063-roof-garden
action="${1:?usage: stage-branch.sh setup|check clean|dirty|unmerged}"
mode="${2:?usage: stage-branch.sh setup|check clean|dirty|unmerged}"
case "$mode" in clean | dirty | unmerged) ;; *) fail "unknown mode $mode" ;; esac

if [[ "$action" == setup ]]; then
  git switch -qc "plan/$slug"
  mkdir -p "changes/$slug"
  cp .sdlc/templates/intent.md .sdlc/templates/spec.md .sdlc/templates/plan.md "changes/$slug/"
  git add -A
  git commit -qm "plan($slug): the plan"
  git switch -q main
  git merge -q --no-ff -m "Merge pull request #7 from example/plan/$slug" "plan/$slug"
  git clone -q --bare . .git/origin.git
  git remote add origin "$PWD/.git/origin.git"
  git fetch -q origin
  git switch -q "plan/$slug"
  case "$mode" in
    dirty) echo "# half-finished work" >>app/prices.py ;;
    unmerged)
      echo "A late thought." >>"changes/$slug/plan.md"
      git commit -qam "plan($slug): a late thought"
      ;;
  esac
  git tag eval-start
  exit 0
fi
[[ "$action" == check ]] || fail "unknown action $action"

outcome="$(head -1 outcome.txt 2>/dev/null || true)"
branch="$(git branch --show-current)"
if [[ "$mode" == clean ]]; then
  [[ "$outcome" == MOVED && "$branch" == "build/$slug" ]] || fail "outcome '$outcome', on '$branch'"
  [[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || fail "not from origin/main"
  exit 0
fi
[[ "$outcome" == ASK ]] || fail "outcome '$outcome', not ASK"
[[ "$branch" == "plan/$slug" ]] || fail "the copy left its branch: on '$branch'"
[[ "$(git rev-parse HEAD)" == "$(git rev-parse eval-start)" ]] || fail "the branch's commit changed"
[[ -z "$(git stash list)" ]] || fail "work was stashed"
changed="$(git diff --name-only HEAD)"
if [[ "$mode" == dirty ]]; then
  [[ "$changed" == app/prices.py ]] || fail "changed files: '$changed'"
  tail -1 app/prices.py | grep -qx "# half-finished work" || fail "the edit is gone"
else
  [[ -z "$changed" ]] || fail "changed files: '$changed'"
fi
