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
# Copies the files the framework owns (the paths list in main), merging in any local edits
# instead of overwriting them (a clash stops the sync, like a git merge conflict), and records the exact commit in .sdlc-version and the installed files in .sdlc-files.
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
    "scripts/spec-pr.sh:scripts/spec-pr.sh"
    "scripts/agent-identity.sh:scripts/agent-identity.sh"
    "scripts/agent-session.sh:scripts/agent-session.sh"
    "scripts/create-agent-apps.py:scripts/create-agent-apps.py"
    "scripts/tests-locked.sh:scripts/tests-locked.sh"
    "scripts/sync-sdlc.sh:scripts/sync-sdlc.sh"
    "templates:templates"
    "prompts:prompts"
    "evals/run.sh:evals/run.sh"
    "REVIEW.md:REVIEW.md"
    "docs/roles.md:docs/roles.md"
    "docs/agent-identity.md:docs/agent-identity.md"
    "docs/setup-agent-apps.md:docs/setup-agent-apps.md"
    "src/sdlc:tools/sdlc/src/sdlc"
  )
  # Framework-only workflows that consumers must not run.
  local skip_workflows=("release.yml")
  # make targets the synced files call: "<target> <what uses it>". The stack contract
  # is required; the optional ones are only needed for what they name.
  local contract_targets=(
    "setup stack contract: install dependencies"
    "fmt stack contract: the format-after-edit hook"
    "lint stack contract: make check"
    "test stack contract: make check"
    "validate stack contract: artifact checks in make check"
    "check stack contract: CI and every skill"
    "new-change stack contract: /intent"
    "status stack contract: /next"
    "next stack contract: /next and the entry skills' routing"
  )
  local optional_targets=(
    "coverage optional: /build runs it when present"
    "evals optional: the agent-evals workflow"
    "sync-sdlc optional: shortcut for this script"
    "deploy-dev optional: deploys to dev"
    "deploy-prod optional: the production gate's release route"
  )

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

  # This script's file list is part of what changes between versions. If the framework's
  # copy differs from the one running, run that copy instead (once), so files a new
  # version adds arrive in this sync, not the next one.
  if [[ -z "${SDLC_SYNC_SELF_UPDATED:-}" ]] && ! cmp -s "$tmp/fw/scripts/sync-sdlc.sh" "$0"; then
    echo "  the sync script itself changed; running the new one"
    SDLC_SYNC_SELF_UPDATED=1 bash "$tmp/fw/scripts/sync-sdlc.sh" "$ref"
    return $?
  fi

  # Install the new set, then delete files the previous sync installed (.sdlc-files) that
  # the framework has since dropped. Local edits are never lost: each file is merged three
  # ways, like `git merge`, against the base the previous sync installed (the commit in
  # .sdlc-version). A file unchanged locally takes the new version; a local edit is kept
  # and the framework's changes merged into it; a clash gets conflict markers and fails
  # the sync. Without a base (first sync, or a file the consumer already had), a file that
  # differs is a conflict. Writing in place, never delete-then-copy, matters: this script
  # is one of the files, and deleting an open file on some filesystems (NTFS via FUSE)
  # leaves a stray .fuse_hidden* behind. Files the consumer added are never touched.
  local previous="" base_sha="" base_ref=""
  [[ -f .sdlc-files ]] && previous="$(cat .sdlc-files)"
  if [[ -f .sdlc-version ]]; then
    base_ref="$(sed -n '1s/^[^@]*@//p' .sdlc-version)"
    base_sha="$(sed -n '2p' .sdlc-version)"
    git -C "$tmp/fw" cat-file -e "${base_sha}^{commit}" 2>/dev/null || base_sha=""
  fi

  local pair src dst file installed=() merged=() conflicts=() kept=() sidecars=()
  base_of() {  # <framework path> <out file>: the file as the previous sync installed it
    rm -f "$2"
    [[ -n "$base_sha" ]] && git -C "$tmp/fw" show "$base_sha:$1" > "$2" 2>/dev/null
  }
  install_file() {  # <framework path> <consumer path>
    local new="$tmp/fw/$1" base="$tmp/base" out="$tmp/merged"
    installed+=("$2")
    if [[ ! -e "$2" ]]; then
      mkdir -p "$(dirname "$2")"
      cp "$new" "$2"
      return
    fi
    cmp -s "$new" "$2" && return
    if base_of "$1" "$base" && cmp -s "$base" "$2"; then
      cp "$new" "$2"  # unchanged locally: take the new version (cp writes in place)
      return
    fi
    [[ -f "$base" ]] || : > "$base"
    local rc=0
    git merge-file -p -L "yours" -L "${base_ref:-none}" -L "$ref" "$2" "$base" "$new" > "$out" || rc=$?
    if ((rc == 0)); then
      merged+=("$2")
    elif ((rc < 128)); then
      conflicts+=("$2")
    else  # can't merge (binary?): leave the local file alone, put the new one beside it
      cp "$new" "$2.sdlc-new"
      sidecars+=("$2.sdlc-new")
      return
    fi
    cat "$out" > "$2"
  }
  # The Makefile is the consumer's, but the synced hooks, skills and workflows call these
  # targets. Name the ones it doesn't define (each line: target, what uses it).
  report_targets() {
    local have line t missing=()
    have="$(make -pRrq __sdlc_probe__ 2>/dev/null | awk '
      /^# Not a target/ { skip = 1; next }
      /^[a-zA-Z0-9][^$#\/\t=]*:([^=]|$)/ && !skip {
        split($0, a, ":"); n = split(a[1], t, " "); for (i = 1; i <= n; i++) print t[i] }
      { skip = 0 }')" || true  # make exits 2 here: the probe target doesn't exist
    for line in "${contract_targets[@]}" "${optional_targets[@]}"; do
      t="${line%% *}"
      grep -qxF -- "$t" <<<"$have" || missing+=("$line")
    done
    ((${#missing[@]})) || return 0
    echo "your Makefile doesn't define these targets the pipeline uses:"
    for line in "${missing[@]}"; do echo "  make ${line%% *}  (${line#* })"; done
  }
  src_of() {  # <consumer path>: the framework path it was installed from
    local p from to
    for p in "${paths[@]}"; do
      from="${p%%:*}" to="${p#*:}"
      [[ "$1" == "$to" ]] && { echo "$from"; return; }
      [[ "$1" == "$to/"* ]] && { echo "$from/${1#"$to/"}"; return; }
    done
  }
  for pair in "${paths[@]}"; do
    src="${pair%%:*}" dst="${pair#*:}"
    if [[ -f "$tmp/fw/$src" ]]; then
      install_file "$src" "$dst"
    elif [[ -d "$tmp/fw/$src" ]]; then
      while IFS= read -r -d '' file; do
        file="${file#./}"
        [[ "$file" == *__pycache__* ]] && continue
        [[ "$dst" == .github/workflows ]] && printf '%s\n' "${skip_workflows[@]}" | grep -qxF "$file" && continue
        install_file "$src/$file" "$dst/$file"
      done < <(cd "$tmp/fw/$src" && find . -type f -print0)
    else
      echo "  skip (not in framework): $src"
    fi
  done
  printf '%s\n' "${installed[@]}" | sort > .sdlc-files
  local old from
  while IFS= read -r old; do
    [[ -n "$old" && "$old" != /* && "$old" != *..* ]] || continue
    grep -qxF -- "$old" .sdlc-files && continue
    [[ -e "$old" ]] || continue
    from="$(src_of "$old")"
    if [[ -n "$from" ]] && base_of "$from" "$tmp/base" && cmp -s "$tmp/base" "$old"; then
      rm -f -- "$old"
    else
      kept+=("$old")  # changed locally: it's the consumer's now, so leave it
    fi
  done <<<"$previous"
  # Drop folders the removal left empty (git doesn't track them anyway).
  find .claude .github tools templates prompts -type d -empty -delete 2>/dev/null || true

  printf '%s@%s\n%s\n' "$repo" "$ref" "$sha" > .sdlc-version

  # Git loses the executable bit on some filesystems (NTFS); set it in the index.
  git add -A
  git ls-files '*.sh' | xargs -r git update-index --chmod=+x
  # Like `git merge`, conflicted files stay unstaged until someone resolves them.
  ((${#conflicts[@]})) && git reset -q -- "${conflicts[@]}"
  ((${#sidecars[@]})) && git reset -q -- "${sidecars[@]}"

  report_targets
  local f
  if ((${#merged[@]})); then
    echo "kept your local changes (any framework changes are merged in):"
    for f in "${merged[@]}"; do echo "  $f"; done
  fi
  if ((${#kept[@]})); then
    echo "kept (the framework dropped these, but you changed them; they're yours now):"
    for f in "${kept[@]}"; do echo "  $f"; done
  fi
  if ((${#conflicts[@]} + ${#sidecars[@]})); then
    echo
    if ((${#conflicts[@]})); then
      echo "CONFLICT: your local changes clash with the framework's in:" >&2
      for f in "${conflicts[@]}"; do echo "  $f" >&2; done
      echo "Resolve the <<<<<<< markers (yours / ${base_ref:-none} / $ref), git add the files, then run make check." >&2
    fi
    if ((${#sidecars[@]})); then
      echo "CONFLICT: these can't be merged automatically (binary?); your file is untouched and the framework's version is beside it:" >&2
      for f in "${sidecars[@]}"; do echo "  ${f%.sdlc-new} (framework's version: $f)" >&2; done
      echo "Merge each one by hand, delete the .sdlc-new file, git add the result, then run make check." >&2
    fi
    echo "The rest of the sync is staged." >&2
    return 1
  fi

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

# One line: bash reads a whole line before running it, so nothing after main is read from
# the file, which main may have replaced with a longer or shorter version.
main "$@"; exit $?
