#!/usr/bin/env bash
# Work out the next semantic version from the PR titles merged since the last release.
#
# Usage: scripts/next-version.sh [--explain]
#   Prints the next version (e.g. v0.3.0). --explain also prints the reason to stderr.
#
# Each change on main is read from its PR title (conventional commits):
#   type!: ... or "BREAKING CHANGE" in the body  -> major (minor while the version is 0.x)
#   feat: ...                                     -> minor
#   anything else (fix, ci, chore, docs, ...)     -> patch
# Squash merges use the PR title as the subject; for "Merge pull request #N" commits the
# PR title is the first line of the body. With no release yet, the first version is v0.1.0.
set -euo pipefail

explain=0
[[ "${1:-}" == "--explain" ]] && explain=1
say() { ((explain)) && echo "$*" >&2 || true; }

last="$(git tag --list 'v*.*.*' --sort=-v:refname | head -1)"
if [[ -z "$last" ]]; then
  say "no previous release: starting at v0.1.0"
  echo "v0.1.0"
  exit 0
fi

range="$last..HEAD"
bump=""
while IFS= read -r -d $'\x1e' entry; do
  entry="${entry#$'\n'}"  # git log puts a newline before every entry after the first
  subject="${entry%%$'\x1f'*}"
  body="${entry#*$'\x1f'}"
  if [[ "$subject" == "Merge pull request #"* ]]; then
    subject="$(sed -n '/./{p;q}' <<<"$body")"
  fi
  [[ -z "$subject" ]] && continue
  if [[ "$subject" =~ ^[a-z]+(\([^\)]*\))?!: ]] || grep -q '^BREAKING CHANGE' <<<"$body"; then
    level=major
  elif [[ "$subject" =~ ^feat(\([^\)]*\))?: ]]; then
    level=minor
  else
    level=patch
  fi
  say "  $level  $subject"
  case "$level:$bump" in
    major:*) bump=major ;;
    minor:major) ;;
    minor:*) bump=minor ;;
    patch:) bump=patch ;;
  esac
done < <(git log --first-parent --format='%s%x1f%b%x1e' "$range")

if [[ -z "$bump" ]]; then
  say "no changes since $last"
  exit 1
fi

IFS=. read -r major minor patch <<<"${last#v}"
if [[ "$bump" == major && "$major" == 0 ]]; then
  say "breaking change while 0.x: bumping minor"
  bump=minor
fi
case "$bump" in
  major) major=$((major + 1)) minor=0 patch=0 ;;
  minor) minor=$((minor + 1)) patch=0 ;;
  patch) patch=$((patch + 1)) ;;
esac
say "$last -> v$major.$minor.$patch ($bump)"
echo "v$major.$minor.$patch"
