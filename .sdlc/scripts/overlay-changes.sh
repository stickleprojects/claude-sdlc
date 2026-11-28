#!/usr/bin/env bash
# Put a PR's changed specs and plans into a copy of the base branch, as data (ADR 0001, #293).
#
# Usage: .sdlc/scripts/overlay-changes.sh <dest> <base> <head>
#
# The Claude review runs with secrets and a token that can write, so it never runs the PR's code,
# its Makefile included. The clause check still needs the PR's spec.md and plan.md. So this makes
# <dest> a git worktree of <base> (main, whose tools the check runs), and for each change whose
# spec.md or plan.md the PR changes (from the fork to <head>), it replaces that change's folder,
# changes/<slug>/, with the PR's copy. It writes only regular files, from git's objects: a symlink
# or submodule in the PR is left out, so a spec can't point the check at a file on the runner.
# The new files are staged, so `git diff HEAD` in <dest> shows the PR's changes, added ones too:
# run `.sdlc/scripts/clause-check.sh --changed-since HEAD` there.
#
# Prints each change's slug, one per line (nothing when the PR changes no spec or plan).
# Exits 0, 2 on bad usage, 3 when git can't read the commits or make the worktree.
set -uo pipefail

dest="${1:-}" base="${2:-}" head="${3:-}"
[[ -n "$dest" && -n "$base" && -n "$head" && $# -eq 3 ]] || { sed -n '2,16p' "$0" >&2; exit 2; }
fail() { echo "overlay-changes: $*" >&2; exit 3; }

fork="$(git merge-base "$base" "$head" 2>/dev/null)" || fail "can't find where $head forked from $base"
changed="$(git diff --no-renames --name-only "$fork" "$head" -- 'changes/*/spec.md' 'changes/*/plan.md' 2>/dev/null)" \
  || fail "can't compare $fork with $head"
mapfile -t slugs < <(sed -E 's#^changes/([^/]+)/.*#\1#' <<<"$changed" | grep . | sort -u)
((${#slugs[@]})) || exit 0

git worktree add --quiet --detach "$dest" "$base" 2>/dev/null || fail "can't make a worktree of $base at $dest"
for slug in "${slugs[@]}"; do
  rm -rf "${dest:?}/changes/$slug"
  while IFS= read -r -d '' entry; do
    meta="${entry%%$'\t'*}" path="${entry#*$'\t'}"
    read -r mode type object <<<"$meta"
    [[ "$type" == blob && ( "$mode" == 100644 || "$mode" == 100755 ) ]] || continue
    mkdir -p "$dest/$(dirname "$path")"
    git cat-file blob "$object" > "$dest/$path" || fail "can't read $path at $head"
  done < <(git ls-tree -r -z "$head" -- "changes/$slug/")
  printf '%s\n' "$slug"
done
git -C "$dest" add -A changes || fail "can't stage the PR's changes in $dest"
