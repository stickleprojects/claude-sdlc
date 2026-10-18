#!/usr/bin/env bash
# Pull the pipeline from the claude-sdlc framework into this (consumer) repo.
#
# Usage: scripts/sync-sdlc.sh [ref]     ref = tag, branch or SHA (default: latest vX.Y.Z tag,
#        make sync-sdlc REF=main          or main if there are no releases yet)
#
# Env:
#   SDLC_REPO    GitHub repo to pull from (default: stickleprojects/claude-sdlc)
#   SDLC_SOURCE  local path or URL to clone instead of SDLC_REPO, e.g. ../claude-sdlc
#                to try unpushed framework changes; the scenario tests use this.
#
# Copies the files the framework owns (the paths list in main), overwriting local copies,
# and records the exact commit in .sdlc-version and the installed files in .sdlc-files.
# Files the consumer adds, even inside framework folders such as .github/workflows or
# .claude/skills, are never touched. The result is staged for review in a PR.
#
# This script is itself framework-owned and may overwrite itself, so everything runs
# inside main(), which bash reads in full before executing.
set -euo pipefail

main() {
  local repo="${SDLC_REPO:-stickleprojects/claude-sdlc}" source="${SDLC_SOURCE:-}"
  local ref="${1:-}"

  # framework path -> path in the consumer repo
  local paths=(
    ".claude/agents:.claude/agents"
    ".claude/hooks:.claude/hooks"
    ".claude/skills:.claude/skills"
    ".claude/settings.json:.claude/settings.json"
    ".github/workflows:.github/workflows"
    "scripts/agent.sh:scripts/agent.sh"
    "scripts/bootstrap-github.sh:scripts/bootstrap-github.sh"
    "scripts/sync-sdlc.sh:scripts/sync-sdlc.sh"
    "templates:templates"
    "prompts:prompts"
    "evals/run.sh:evals/run.sh"
    "REVIEW.md:REVIEW.md"
    "docs/roles.md:docs/roles.md"
    "src/sdlc:tools/sdlc/src/sdlc"
  )
  # Framework-only workflows that consumers must not run.
  local skip_workflows=("release.yml")

  cd "$(git rev-parse --show-toplevel)"
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "working tree has uncommitted changes; commit or stash them first" >&2
    return 1
  fi

  local tmp label
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  if [[ -n "$source" ]]; then
    label="$source"
    git clone --quiet "$source" "$tmp/fw"
    [[ -n "$ref" ]] || ref="$(git -C "$tmp/fw" tag --list 'v*.*.*' --sort=-v:refname | head -1)"
  else
    label="$repo"
    gh repo clone "$repo" "$tmp/fw" -- --quiet
    [[ -n "$ref" ]] || ref="$(git -C "$tmp/fw" tag --list 'v*.*.*' --sort=-v:refname | head -1)"
  fi
  ref="${ref:-main}"
  git -C "$tmp/fw" -c advice.detachedHead=false checkout --quiet "$ref"
  local sha
  sha="$(git -C "$tmp/fw" rev-parse HEAD)"
  echo "syncing from $label@$ref (${sha:0:7})"

  # Remove the files the previous sync installed (listed in .sdlc-files), then copy the
  # new set. Files the framework dropped disappear; files the consumer added inside
  # framework folders (its own workflows, skills, agents, hooks) are never touched.
  local old
  if [[ -f .sdlc-files ]]; then
    while IFS= read -r old; do
      [[ -n "$old" && "$old" != /* && "$old" != *..* ]] && rm -f -- "$old"
    done < .sdlc-files
  fi

  local pair src dst file installed=()
  install_file() {  # <framework file> <consumer path>
    mkdir -p "$(dirname "$2")"
    cp "$1" "$2"
    installed+=("$2")
  }
  for pair in "${paths[@]}"; do
    src="$tmp/fw/${pair%%:*}" dst="${pair#*:}"
    if [[ -f "$src" ]]; then
      install_file "$src" "$dst"
    elif [[ -d "$src" ]]; then
      while IFS= read -r -d '' file; do
        file="${file#./}"
        [[ "$file" == *__pycache__* ]] && continue
        [[ "$dst" == .github/workflows ]] && printf '%s\n' "${skip_workflows[@]}" | grep -qxF "$file" && continue
        install_file "$src/$file" "$dst/$file"
      done < <(cd "$src" && find . -type f -print0)
    else
      echo "  skip (not in framework): ${pair%%:*}"
    fi
  done
  printf '%s\n' "${installed[@]}" | sort > .sdlc-files
  # Drop folders the removal left empty (git doesn't track them anyway).
  find .claude .github tools templates prompts -type d -empty -delete 2>/dev/null || true

  printf '%s@%s\n%s\n' "$repo" "$ref" "$sha" > .sdlc-version

  # Git loses the executable bit on some filesystems (NTFS); set it in the index.
  git add -A
  git ls-files '*.sh' | xargs -r git update-index --chmod=+x

  if git diff --cached --quiet; then
    echo "already up to date"
    return 0
  fi
  echo
  git diff --cached --stat
  echo
  echo "Changes are staged. Next:"
  echo "  make check"
  echo "  git switch -c chore/sync-sdlc-${sha:0:7} && git commit -m 'chore: sync pipeline from claude-sdlc $ref'"
  echo "  git push -u origin HEAD && gh pr create --fill"
}

main "$@"
exit $?
