#!/usr/bin/env bash
# Pull the pipeline from the claude-sdlc framework into this (consumer) repo.
#
# Usage: .sdlc/scripts/sync-sdlc.sh [ref]     ref = tag, branch or SHA (default: latest vX.Y.Z tag,
#        make sync-sdlc REF=main          or main if there are no releases yet)
#
# Env:
#   SDLC_REPO    GitHub repo to pull from (default: stickleprojects/claude-sdlc)
#   SDLC_SOURCE  local path or URL to clone instead of SDLC_REPO, e.g. ../claude-sdlc
#                to try unpushed framework changes; the scenario tests use this.
#
# Copies the files the framework owns (the paths list in main), merging in any local edits
# instead of overwriting them (a clash stops the sync, like a git merge conflict), and records the exact commit in .sdlc/version and the installed files in .sdlc/files.
# Files the consumer adds, even inside framework folders such as .github/workflows or
# .claude/skills, are never touched. The result is staged for review in a PR.
#
# This script is itself framework-owned and may overwrite itself, so everything runs
# inside main(), which bash reads in full before executing.
set -euo pipefail

main() {
  local repo="${SDLC_REPO:-stickleprojects/claude-sdlc}" source="${SDLC_SOURCE:-}"
  local ref="${1:-}"

  # framework path -> path in the consumer repo. Everything lives in .sdlc/ (#133); the other
  # entries are small files Claude Code and GitHub only look for in their own folders: skill
  # and agent stubs that forward to .sdlc/, the hook settings, and the workflows.
  local paths=(
    ".sdlc:.sdlc"
    ".claude/skills:.claude/skills"
    ".claude/agents:.claude/agents"
    ".claude/settings.json:.claude/settings.json"
    ".github/workflows:.github/workflows"
  )
  # Where the sync keeps its own records, and where versions before v0.11 kept them.
  local files_list=".sdlc/files" version_file=".sdlc/version"
  local old_files_list=".sdlc-files" old_version_file=".sdlc-version"
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
    "clauses optional: the clause check (.sdlc/scripts/clause-check.sh) in the Claude review"
    "evals optional: the agent-evals workflow"
    "sync-sdlc optional: shortcut for this script"
    "deploy-dev optional: deploys to dev"
    "deploy-prod optional: the production gate's release route"
  )
  # Repo secrets and variables the synced workflows use: "<secret|variable> <NAME> <what uses it>".
  # Required ones break those workflows when missing. The agent App's three are optional but
  # go together: half set up, spec-from-intent or the Claude review fails at run time.
  # tests/test_scenario.py checks that every secrets.* and vars.* in the workflows is listed.
  local required_settings=(
    "secret CLAUDE_CODE_OAUTH_TOKEN the Claude review, @claude mentions, spec-from-intent and the agent evals"
  )
  local app_settings=(
    "variable SDLC_AGENT_APP_ID"
    "variable SDLC_AGENT_APP_SLUG"
    "secret SDLC_AGENT_APP_KEY"
  )
  # Opt-in auto-merge (#89): not reported when unset. When set, main's protection is checked.
  # The sync only reads these; it never writes repo variables, so an update can't reset them.
  local auto_merge_settings=(
    "variable SDLC_AUTO_MERGE"
    "variable SDLC_AUTO_MERGE_CONFIRMED"
  )
  # Optional runner (#126): every framework job runs on vars.SDLC_RUNNER when it's set, except
  # for fork PRs, which stay on GitHub-hosted runners. A fork PR can edit that line in its own
  # copy of the workflow, though, so on a public repo the sync checks that fork PR workflows
  # wait for a person's approval.
  local runner_settings=(
    "variable SDLC_RUNNER"
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
  if [[ -z "${SDLC_SYNC_SELF_UPDATED:-}" ]] && ! cmp -s "$tmp/fw/.sdlc/scripts/sync-sdlc.sh" "$0"; then
    echo "  the sync script itself changed; running the new one"
    SDLC_SYNC_SELF_UPDATED=1 bash "$tmp/fw/.sdlc/scripts/sync-sdlc.sh" "$ref"
    return $?
  fi

  # Install the new set, then delete files the previous sync installed (.sdlc/files) that
  # the framework has since dropped. Local edits are never lost: each file is merged three
  # ways, like `git merge`, against the base the previous sync installed (the commit in
  # .sdlc/version). A file unchanged locally takes the new version; a local edit is kept
  # and the framework's changes merged into it; a clash gets conflict markers and fails
  # the sync. Without a base (first sync, or a file the consumer already had), a file that
  # differs is a conflict. Writing in place, never delete-then-copy, matters: this script
  # is one of the files, and deleting an open file on some filesystems (NTFS via FUSE)
  # leaves a stray .fuse_hidden* behind. Files the consumer added are never touched.
  local previous="" base_sha="" base_ref="" files_list_src="" version_src=""
  [[ -f "$files_list" ]] || files_list_src="$old_files_list"
  [[ -f "$version_file" ]] || version_src="$old_version_file"
  [[ -f "${files_list_src:-$files_list}" ]] && previous="$(cat "${files_list_src:-$files_list}")"
  if [[ -f "${version_src:-$version_file}" ]]; then
    base_ref="$(sed -n '1s/^[^@]*@//p' "${version_src:-$version_file}")"
    base_sha="$(sed -n '2p' "${version_src:-$version_file}")"
    git -C "$tmp/fw" cat-file -e "${base_sha}^{commit}" 2>/dev/null || base_sha=""
  fi

  local pair src dst file installed=() merged=() conflicts=() kept=() sidecars=() executables=()
  local carried=() moved=()
  # The framework's executable files, by git's recorded mode (#79): the consumer's copies get
  # the same bit, whatever their extension. Nothing else is touched.
  local fw_exec
  fw_exec="$(git -C "$tmp/fw" ls-files -s | awk '$1 == "100755" { print $4 }')"
  # The v0.11 move (#133): where a file now under .sdlc/ lived before, in the consumer repo
  # (legacy_of) and in the framework (legacy_fw_of). The first sync after it uses these to
  # carry local edits to the new place and to delete the old copies.
  legacy_of() {  # <consumer path>
    case "$1" in
      .sdlc/src/sdlc/*) echo "tools/sdlc/src/sdlc/${1#.sdlc/src/sdlc/}" ;;
      .sdlc/hooks/* | .sdlc/skills/* | .sdlc/agents/*) echo ".claude/${1#.sdlc/}" ;;
      .sdlc/docs/* | .sdlc/scripts/* | .sdlc/templates/* | .sdlc/prompts/* | .sdlc/evals/* | .sdlc/REVIEW.md)
        echo "${1#.sdlc/}" ;;
    esac
  }
  legacy_fw_of() {  # <framework path>
    case "$1" in
      .sdlc/src/sdlc/*) echo "src/sdlc/${1#.sdlc/src/sdlc/}" ;;
      *) legacy_of "$1" ;;
    esac
  }
  was_installed() { grep -qxF -- "$1" <<<"$previous"; }
  base_of() {  # <framework path> <out file>: the file as the previous sync installed it
    rm -f "$2"
    [[ -n "$base_sha" ]] || return 1
    git -C "$tmp/fw" show "$base_sha:$1" > "$2" 2>/dev/null && return 0
    local old
    old="$(legacy_fw_of "$1")"
    [[ -n "$old" ]] && git -C "$tmp/fw" show "$base_sha:$old" > "$2" 2>/dev/null
  }
  install_file() {  # <framework path> <consumer path>
    local new="$tmp/fw/$1" base="$tmp/base" out="$tmp/merged"
    installed+=("$2")
    grep -qxF -- "$1" <<<"$fw_exec" && executables+=("$2")
    # Its old copy was carried to .sdlc/ (below), so this path now gets the new file as is.
    if printf '%s\n' ${carried[@]+"${carried[@]}"} | grep -qxF -- "$2"; then
      cp "$new" "$2"
      return
    fi
    # First sync after the move: a locally edited old copy becomes the starting point here,
    # so the edits are merged into the new file like any other local change.
    local legacy
    legacy="$(legacy_of "$2")"
    if [[ ! -e "$2" && -n "$legacy" && -f "$legacy" ]] && was_installed "$legacy"; then
      moved+=("$legacy")
      if ! { base_of "$1" "$base" && cmp -s "$base" "$legacy"; }; then
        mkdir -p "$(dirname "$2")"
        cp "$legacy" "$2"
        carried+=("$legacy")
      fi
    fi
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
  # Check the GitHub repo's secrets and variables by name (values are never readable). Skipped
  # quietly without a GitHub origin or a logged-in gh, so the sync works offline and in CI.
  report_settings() {
    # Plain strings, not arrays: under set -u, bash before 4.4 (macOS) treats an empty
    # array's expansion as an unbound variable.
    local url gh_repo secrets="" vars="" line kind name uses rc
    local have="" missing="" n_missing=0 unknown="" out=""
    url="$(git remote get-url origin 2>/dev/null)" || return 0
    [[ "$url" =~ github\.com[:/]([^/]+/[^/]+)$ ]] || return 0
    gh_repo="${BASH_REMATCH[1]%.git}"
    command -v gh >/dev/null && gh auth status >/dev/null 2>&1 || return 0
    names_of() {  # <secret|variable>: the repo's own names plus the org's shared with it
      local plural="${1}s"
      gh "$1" list -R "$gh_repo" --json name -q '.[].name' 2>/dev/null || return 1
      gh api --paginate "repos/$gh_repo/actions/organization-$plural" --jq ".$plural[].name" \
        2>"$tmp/gh-err" && return 0
      grep -q 'HTTP 422' "$tmp/gh-err"  # 422: a personal account's repo, which has no org ones
    }
    secrets="$(names_of secret)" || unknown+=" secret"
    vars="$(names_of variable)" || unknown+=" variable"
    set_in() {  # <kind> <name>: 0 set, 1 missing, 2 can't tell
      [[ "$unknown " == *" $1 "* ]] && return 2
      if [[ "$1" == secret ]]; then grep -qxF -- "$2" <<<"$secrets"; else grep -qxF -- "$2" <<<"$vars"; fi
    }
    for line in "${required_settings[@]}"; do
      read -r kind name uses <<<"$line"
      rc=0; set_in "$kind" "$name" || rc=$?
      ((rc != 1)) || out+="  MISSING (required): $kind $name. Without it these fail: $uses. Set it with .sdlc/scripts/bootstrap-github.sh."$'\n'
    done
    for line in "${app_settings[@]}"; do
      read -r kind name <<<"$line"
      rc=0; set_in "$kind" "$name" || rc=$?
      case $rc in 0) have+=" $name" ;; 1) missing+=" $name"; ((n_missing += 1)) ;; esac
    done
    if [[ -n "$have" && -n "$missing" ]]; then
      out+="  ERROR: the agent App is half set up:$have set,$missing missing. Spec-from-intent or the Claude review fails until all three are set (.sdlc/docs/setup-agent-apps.md)."$'\n'
    elif ((n_missing == ${#app_settings[@]})); then
      out+="  not set (optional): the agent App (${missing# }). Without it, spec PRs open as github-actions[bot] and need the 'Approve and run workflows' click (.sdlc/docs/setup-agent-apps.md)."$'\n'
    fi
    # Opt-in auto-merge: with this person's login (usually an admin), check main still qualifies.
    # The pipeline re-checks approvals and the review check live on each PR; the stale-approval
    # setting is the one an App token may not see, which SDLC_AUTO_MERGE_CONFIRMED stands in for.
    # By THE RULE in .sdlc/scripts/auto-merge.sh (#101): `off` is off, so it gets no warnings. A value
    # that can't be read still gets the check, as when only the name was known.
    local prot problems method=""
    if set_in variable SDLC_AUTO_MERGE; then
      method="$(GITHUB_REPOSITORY="$gh_repo" bash .sdlc/scripts/auto-merge.sh --method 2>/dev/null)" \
        || method="unknown"
    fi
    if [[ -n "$method" ]]; then
      if prot="$(gh api "repos/$gh_repo/branches/main/protection" 2>/dev/null)"; then
        problems="$(jq -r '[
          (if (.required_pull_request_reviews.required_approving_review_count // 0) < 1
            then "no approving review is required (solo mode)" else empty end),
          (if .required_pull_request_reviews.dismiss_stale_reviews != true
            then "stale approvals are not dismissed on push" else empty end),
          (if ([.required_status_checks.contexts[]?] | index("claude-review")) == null
            then "the claude-review status is not required" else empty end)
        ] | join("; ")' <<<"$prot" 2>/dev/null)"
        if [[ -n "$problems" ]]; then
          out+="  WARNING: SDLC_AUTO_MERGE is set, but main doesn't qualify: $problems. The pipeline won't enable auto-merge until .sdlc/scripts/bootstrap-github.sh --mode team fixes it."$'\n'
          if [[ "$problems" == *"stale approvals"* ]] && set_in variable SDLC_AUTO_MERGE_CONFIRMED; then
            out+="  ERROR: SDLC_AUTO_MERGE_CONFIRMED is set but no longer true of main. Delete it (gh variable delete SDLC_AUTO_MERGE_CONFIRMED) or re-run bootstrap."$'\n'
          fi
        fi
      else
        out+="  not checked: SDLC_AUTO_MERGE is set, but can't read main's branch protection (needs admin)."$'\n'
      fi
    fi
    local private policy
    if set_in variable SDLC_RUNNER; then
      private="$(gh api "repos/$gh_repo" --jq .private 2>/dev/null)" || private=""
      if [[ "$private" != true ]]; then
        policy="$(gh api "repos/$gh_repo/actions/permissions/fork-pr-contributor-approval" \
          --jq .approval_policy 2>/dev/null)" || policy=""
        if [[ -z "$policy" ]]; then
          out+="  not checked: SDLC_RUNNER is set, but can't read whether fork PR workflows need approval (needs admin). Check Settings > Actions > General (.sdlc/docs/self-hosted-runner.md)."$'\n'
        elif [[ "$policy" != all_external_contributors ]]; then
          out+="  WARNING: SDLC_RUNNER is set on a public repo, but some fork PRs run their workflows without approval ($policy). A fork PR can edit its workflow to run on your runner. In Settings > Actions > General, choose 'Require approval for all external contributors' (.sdlc/docs/self-hosted-runner.md)."$'\n'
        fi
      fi
    fi
    for kind in $unknown; do
      out+="  not checked: can't read $gh_repo's $kind names, its own or its organization's (needs admin or maintain access)."$'\n'
    done
    [[ -n "$out" ]] || return 0
    echo "secrets and variables the workflows use, in $gh_repo (its own and its organization's):"
    printf '%s' "$out"
  }
  src_of() {  # <consumer path>: the framework path it was installed from
    local p from to
    for p in "${paths[@]}"; do
      from="${p%%:*}" to="${p#*:}"
      [[ "$1" == "$to" ]] && { echo "$from"; return; }
      [[ "$1" == "$to/"* ]] && { echo "$from/${1#"$to/"}"; return; }
    done
    return 0  # not in the manifest: prints nothing (a path from before the move, #133)
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
  printf '%s\n' "${installed[@]}" | sort > "$files_list"
  local old from
  while IFS= read -r old; do
    [[ -n "$old" && "$old" != /* && "$old" != *..* ]] || continue
    grep -qxF -- "$old" "$files_list" && continue
    [[ -e "$old" ]] || continue
    # Carried to .sdlc/ with its edits: the old copy goes.
    if printf '%s\n' ${carried[@]+"${carried[@]}"} | grep -qxF -- "$old"; then
      rm -f -- "$old"
      continue
    fi
    from="$(src_of "$old")"
    # Paths from before the move (#133) aren't in the manifest: they were installed from the
    # same path in the framework, except the tool, which came from src/sdlc.
    if [[ -z "$from" ]]; then
      case "$old" in
        tools/sdlc/src/sdlc/*) from="src/sdlc/${old#tools/sdlc/src/sdlc/}" ;;
        *) from="$old" ;;
      esac
    fi
    if base_of "$from" "$tmp/base" && cmp -s "$tmp/base" "$old"; then
      rm -f -- "$old"
    else
      kept+=("$old")  # changed locally: it's the consumer's now, so leave it
    fi
  done <<<"$previous"
  # Drop folders the removal left empty (git doesn't track them anyway).
  find .claude .github .sdlc tools scripts templates prompts docs evals -type d -empty -delete \
    2>/dev/null || true

  printf '%s@%s\n%s\n' "$repo" "$ref" "$sha" > "$version_file"
  rm -f -- "$old_files_list" "$old_version_file"

  # Git loses the executable bit on some filesystems (NTFS); set it in the index from the
  # framework's modes, so a file executable there is executable here.
  git add -A
  ((${#executables[@]})) && git update-index --chmod=+x -- "${executables[@]}"
  # Like `git merge`, conflicted files stay unstaged until someone resolves them.
  ((${#conflicts[@]})) && git reset -q -- "${conflicts[@]}"
  ((${#sidecars[@]})) && git reset -q -- "${sidecars[@]}"

  report_targets
  report_settings
  local f
  # The repo's own scripts: the sync sets modes only on framework files, so it reports theirs
  # rather than changing them (#101). A non-executable hook or script is skipped silently.
  local not_exec
  not_exec="$(git ls-files -s -- '*.sh' | awk '$1 != "100755" { print $4 }' \
    | grep -vxF -f "$files_list" || true)"
  if [[ -n "$not_exec" ]]; then
    echo "your own scripts that aren't executable in git (the sync leaves them alone; fix with"
    echo "git update-index --chmod=+x <file>, which works on NTFS too, then commit):"
    while IFS= read -r f; do echo "  $f"; done <<<"$not_exec"
  fi
  if ((${#merged[@]})); then
    echo "kept your local changes (any framework changes are merged in):"
    for f in "${merged[@]}"; do echo "  $f"; done
  fi
  # After the move (#133): the repo's own files that still name an old path, such as a
  # Makefile running the tool from tools/sdlc/src. The sync never edits them.
  if ((${#moved[@]})); then
    # An old path on its own, not the tail of its new one (.sdlc/scripts/x contains scripts/x).
    local stale pats=(-e '(^|[^.[:alnum:]_/-])tools/sdlc/src') m
    for m in "${moved[@]}"; do pats+=(-e "(^|[^.[:alnum:]_/-])${m//./\\.}"); done
    # Matches in files the framework installed don't count: the sync just rewrote those.
    stale="$(git grep -n -E "${pats[@]}" -- . ':!.sdlc' ':!changes' ':!docs/release-notes' \
      2>/dev/null | awk -F: 'NR == FNR { ours[$0] = 1; next } !($1 in ours)' "$files_list" - \
      || true)"
    if [[ -n "$stale" ]]; then
      echo "the framework moved into .sdlc/; these lines of yours still use the old paths"
      echo "(tools/sdlc/src is now .sdlc/src, scripts/<x> is .sdlc/scripts/<x> and so on):"
      while IFS= read -r f; do echo "  $f"; done <<<"$stale"
    fi
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
