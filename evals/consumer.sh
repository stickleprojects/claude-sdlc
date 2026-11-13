#!/usr/bin/env bash
# Turn an eval's working copy into a consumer repo that has synced this framework (#160).
#
# Usage (an eval task's "setup"): bash "$EVAL_ROOT/evals/consumer.sh" <fixture>
#   Run in the eval's working directory, which .sdlc/evals/run.sh fills with a copy of the
#   framework's working tree. That copy becomes the sync's source (uncommitted changes
#   included), and the directory is replaced by evals/fixtures/<fixture>/consumer/ with the
#   framework synced into it, on `main`, tagged `eval-base`. So an eval runs the pipeline the
#   way a consumer gets it, not the framework's own copy.
set -euo pipefail

fixture="${1:?usage: consumer.sh <fixture>}"
root="${EVAL_ROOT:?EVAL_ROOT must name the framework checkout}"
src="$PWD/evals/fixtures/$fixture/consumer"
[[ -d "$src" ]] || { echo "consumer.sh: no fixture at evals/fixtures/$fixture/consumer" >&2; exit 2; }

snap="$(mktemp -d)"
trap 'rm -rf "$snap"' EXIT
shopt -s dotglob
mv ./* "$snap"/
shopt -u dotglob

# The modes git records, not the disk's: on NTFS every file looks executable.
git -C "$snap" init -q -b main
chmod -R u+rwX,go-w "$snap"
find "$snap" -path "$snap/.git" -prune -o -type f -exec chmod 644 {} +
git -C "$root" ls-files -s | awk '$1 == "100755" {print $4}' | while IFS= read -r rel; do
  [[ -f "$snap/$rel" ]] && chmod 755 "$snap/$rel"
done
git -C "$snap" add -A
git -C "$snap" -c user.name=eval -c user.email=eval@example.invalid commit -q -m snapshot
git -C "$snap" tag v0.0.1

cp -R "$snap/evals/fixtures/$fixture/consumer"/. .
mkdir -p .sdlc/scripts
cp "$snap/.sdlc/scripts/sync-sdlc.sh" .sdlc/scripts/sync-sdlc.sh
git init -q -b main
git config user.name "Eval Engineer"
git config user.email eval@example.invalid
git add -A
git commit -q -m "chore: consumer skeleton"
SDLC_SOURCE="$snap" bash .sdlc/scripts/sync-sdlc.sh >/dev/null
git add -A
git commit -q -m "chore: sync pipeline"
git tag eval-base
