#!/usr/bin/env bash
# Try a framework commit in a real consumer repo before releasing it (#200).
#
# Usage:
#   scripts/consumer-trial.sh sync [ref]   clone the consumer into a new scratch folder, sync
#                                          ref into it (default: claude-sdlc's main, pinned to
#                                          its SHA) and commit that on a trial branch.
#                                          Prints the folder; the other steps take it.
#   scripts/consumer-trial.sh check <dir>  make setup && make check there; the log is <dir>/check.log
#   scripts/consumer-trial.sh pr <dir>     push the branch and open a draft PR marked do-not-merge
#   scripts/consumer-trial.sh close <dir>  close that PR, delete its branch and the folder
#
# The consumer is always a fresh clone, never the person's working checkout. The trial PR
# runs the consumer's CI and review on the new framework and is then closed: the consumer
# upgrades for real after the release, through /sdlc. The release checklist is the /release
# skill (.claude/skills/release/SKILL.md). Framework-only: the sync never ships scripts/.
#
# Env:
#   SDLC_TRIAL_REPO   consumer to try (default: stickleprojects/sdlc-sandbox)
#   SDLC_TRIAL_CLONE  path or URL to clone instead of the consumer's GitHub repo (tests)
#   SDLC_REPO, SDLC_SOURCE  where the framework comes from, passed on to the consumer's sync
set -euo pipefail

dir="" branch="" sha="" pr=""
consumer="${SDLC_TRIAL_REPO:-stickleprojects/sdlc-sandbox}"
framework="${SDLC_SOURCE:-https://github.com/${SDLC_REPO:-stickleprojects/claude-sdlc}.git}"

usage() { sed -n '4,11p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

# Load the trial in folder $1 (consumer, branch, sha, pr), checking that `sync` made it.
load() {
  dir="${1:?a trial folder, as printed by: $0 sync}"
  [[ -f "$dir/trial" && -d "$dir/repo/.git" ]] || { echo "not a trial folder: $dir" >&2; exit 1; }
  # shellcheck source=/dev/null
  source "$dir/trial"
}

cmd_sync() {
  local ref="${1:-main}" script
  sha="$(git ls-remote "$framework" "refs/heads/$ref" "refs/tags/$ref" | awk 'NR==1 {print $1}')"
  if [[ -z "$sha" ]]; then
    # Not a branch or tag name: take it as a commit.
    [[ "$ref" =~ ^[0-9a-f]{7,40}$ ]] || { echo "no $ref in $framework" >&2; exit 1; }
    sha="$ref"
  fi
  dir="$(mktemp -d "${TMPDIR:-/tmp}/sdlc-trial.XXXXXX")"
  if [[ -n "${SDLC_TRIAL_CLONE:-}" ]]; then
    git clone --quiet "$SDLC_TRIAL_CLONE" "$dir/repo"
  else
    gh repo clone "$consumer" "$dir/repo" -- --quiet
  fi
  branch="chore/sdlc-trial-${sha:0:7}"
  git -C "$dir/repo" switch --quiet -c "$branch"
  printf 'consumer=%q\nbranch=%q\nsha=%q\npr=\n' "$consumer" "$branch" "$sha" > "$dir/trial"

  # The consumer's own sync script, as /sdlc runs it: older layouts kept it in scripts/.
  script=".sdlc/scripts/sync-sdlc.sh"
  [[ -f "$dir/repo/$script" ]] || script="scripts/sync-sdlc.sh"
  [[ -f "$dir/repo/$script" ]] || { echo "$consumer has no sync script" >&2; exit 1; }
  echo "trying claude-sdlc ${sha:0:7} in $consumer ($dir/repo)"
  if ! (cd "$dir/repo" && bash "$script" "$sha"); then
    echo "the sync stopped (conflicts?): resolve them in $dir/repo with the person, as /sdlc" >&2
    echo "would, and commit; that's a finding for the release notes" >&2
    echo "$dir"
    exit 1
  fi
  git -C "$dir/repo" commit --quiet -m "chore: trial sync of claude-sdlc ${sha:0:7}"
  if [[ -f "$dir/repo/.sdlc/upgrade-pending.md" ]]; then
    echo "upgrade steps are pending: work through $dir/repo/.sdlc/upgrade-pending.md with the" >&2
    echo "person, as /sdlc does, and commit, before the check" >&2
  fi
  echo "$dir"
}

cmd_check() {
  local status=0
  load "${1:-}"
  (cd "$dir/repo" && make setup && make check) > "$dir/check.log" 2>&1 || status=$?
  tail -n 15 "$dir/check.log"
  if ((status)); then
    echo "make check FAILED in $consumer (log: $dir/check.log)" >&2
    return "$status"
  fi
  echo "make check passed in $consumer"
}

cmd_pr() {
  local url
  load "${1:-}"
  [[ -z "$pr" ]] || { echo "$pr"; return 0; }
  git -C "$dir/repo" push --quiet -u origin "$branch"
  url="$(gh pr create -R "$consumer" --draft --head "$branch" \
    --title "chore: trial sync of claude-sdlc ${sha:0:7} (do not merge)" \
    --body "A trial of claude-sdlc ${sha:0:7} before it's released (claude-sdlc#200). It runs this repo's CI and review on the new framework, and is closed once the result is in the release notes. Upgrade through \`/sdlc\` after the release, not by merging this.")"
  sed -i "s|^pr=.*|pr=$(printf '%q' "$url")|" "$dir/trial"
  # The release's trial line starts with this: the release checks the SHA (scripts/check-trial-sha.sh).
  echo "trial line starts: ${url#https://github.com/} (claude-sdlc ${sha:0:7}):" >&2
  echo "$url"
}

cmd_close() {
  load "${1:-}"
  if [[ -n "$pr" ]]; then
    gh pr close "$pr" -R "$consumer" --delete-branch \
      --comment "Trial done; the result is in the claude-sdlc release notes."
  fi
  rm -rf "$dir"
  echo "closed the trial${pr:+ ($pr)} and removed $dir"
}

case "${1:-}" in
  sync | check | pr | close)
    step="$1"
    shift
    "cmd_$step" "$@"
    ;;
  *) usage ;;
esac
