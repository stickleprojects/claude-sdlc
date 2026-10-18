#!/usr/bin/env bash
# Write release notes for the changes since the last release, grouped by PR title type.
#
# Usage: scripts/release-notes.sh <version> [repo]    e.g. v0.2.0 stickleprojects/claude-sdlc
#   Prints Markdown to stdout. Uses the same PR-title rules as next-version.sh.
set -euo pipefail

version="${1:?usage: release-notes.sh <version> [owner/repo]}"
repo="${2:-${GITHUB_REPOSITORY:-stickleprojects/claude-sdlc}}"
last="$(git tag --list 'v*.*.*' --sort=-v:refname | head -1)"
range="${last:+$last..}HEAD"

breaking=() features=() fixes=() other=()
while IFS= read -r -d $'\x1e' entry; do
  entry="${entry#$'\n'}"  # git log puts a newline before every entry after the first
  subject="${entry%%$'\x1f'*}"
  body="${entry#*$'\x1f'}"
  pr=""
  if [[ "$subject" =~ ^Merge\ pull\ request\ \#([0-9]+) ]]; then
    pr="${BASH_REMATCH[1]}"
    subject="$(sed -n '/./{p;q}' <<<"$body")"
  elif [[ "$subject" =~ \ \(\#([0-9]+)\)$ ]]; then
    pr="${BASH_REMATCH[1]}"
    subject="${subject% (#*}"
  fi
  [[ -z "$subject" ]] && continue
  line="- ${subject#*: }${pr:+ (#$pr)}"
  if [[ "$subject" =~ ^[a-z]+(\([^\)]*\))?!: ]] || grep -q '^BREAKING CHANGE' <<<"$body"; then
    breaking+=("$line")
  elif [[ "$subject" =~ ^feat(\([^\)]*\))?: ]]; then
    features+=("$line")
  elif [[ "$subject" =~ ^fix(\([^\)]*\))?: ]]; then
    fixes+=("$line")
  else
    other+=("$line")
  fi
done < <(git log --first-parent --format='%s%x1f%b%x1e' "$range")

section() {
  local title="$1"; shift
  (($#)) || return 0
  printf '\n## %s\n\n' "$title"
  printf '%s\n' "$@"
}

printf '# %s (%s)\n' "$version" "$(date -u +%Y-%m-%d)"
if ((${#breaking[@]})); then
  printf '\n> **This release has breaking changes.** Read them before upgrading a consumer repo.\n'
fi
section "⚠ Breaking changes" "${breaking[@]}"
section "Features" "${features[@]}"
section "Fixes" "${fixes[@]}"
section "Pipeline, docs and chores" "${other[@]}"
if ! ((${#breaking[@]} + ${#features[@]} + ${#fixes[@]} + ${#other[@]})); then
  printf '\nNo changes.\n'
fi
cat <<EOF

## Upgrading a consumer repo

\`\`\`
make sync-sdlc REF=$version
make check
\`\`\`
EOF
if [[ -n "$last" ]]; then
  printf '\nFull diff: https://github.com/%s/compare/%s...%s\n' "$repo" "$last" "$version"
fi
