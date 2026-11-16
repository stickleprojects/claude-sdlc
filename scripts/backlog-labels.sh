#!/usr/bin/env bash
# The backlog's priority, impact and effort labels on this repo's issues (#204). The /backlog
# skill (.claude/skills/backlog/SKILL.md) runs it. Framework-only: never synced to consumers.
#
# Usage:
#   scripts/backlog-labels.sh labels
#       Create the nine labels, or bring their colour and description up to date.
#   scripts/backlog-labels.sh list
#       One tab-separated line per open issue (pull requests left out):
#       #<n>  <priority>  <impact>  <effort>  <title>
#       A category with no label shows "-", one with several shows them joined by "+".
#   scripts/backlog-labels.sh set <n> <P1|P2|P3> <high|medium|low> <S|M|L> [reason]
#       Give issue <n> exactly these three labels, removing any other label in the same
#       categories. When this changes a priority the issue already had, the reason is required
#       and is posted as a comment on the issue; a first priority, or an unchanged one, posts
#       nothing. Prints what changed.
#
# Labels: `priority: P1` (do next) to `P3`; `impact: high|medium|low`, what fixing it gains;
# `effort: S` (one PR), `M` (two or three), `L` (a design and several PRs). Size is "effort"
# because the `cost` label already means "uses Claude subscription or CI minutes".
#
# Env: BACKLOG_REPO (owner/name; default: the repo gh resolves from the git remote).
#      SDLC_AGENT_IDENTITY set: a comment is signed "— Claude"; otherwise "(posted from Claude Code)".
set -uo pipefail

repo="${BACKLOG_REPO:-}"
[[ -n "$repo" ]] || repo='{owner}/{repo}' # gh fills these in from the git remote

usage() {
  sed -n '5,16p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

# name<TAB>colour<TAB>description
LABELS="priority: P1	b60205	Do next: high impact, or blocking
priority: P2	d93f0b	Next tier
priority: P3	fbca04	Later
impact: high	5319e7	High gain from fixing it, or high cost of leaving it
impact: medium	8a63d2	Medium gain
impact: low	c5b5ea	Low gain
effort: S	0e8a16	One PR
effort: M	1d76db	Two or three PRs
effort: L	0052cc	A design and several PRs"

enc() { jq -rn --arg s "$1" '$s|@uri'; }

labels() {
  local name colour desc failed=0
  while IFS=$'\t' read -r name colour desc; do
    if gh api -X PATCH "repos/$repo/labels/$(enc "$name")" -f color="$colour" \
      -f description="$desc" >/dev/null 2>&1; then
      echo "updated: $name"
    elif gh api "repos/$repo/labels" -f name="$name" -f color="$colour" \
      -f description="$desc" >/dev/null; then
      echo "created: $name"
    else
      echo "error: couldn't create or update the label '$name'" >&2
      failed=1
    fi
  done <<<"$LABELS"
  return "$failed"
}

list() {
  gh api --paginate "repos/$repo/issues?state=open&per_page=100" --jq '
    .[] | select(.pull_request | not)
    | [.labels[].name] as $l
    | def cat($p): [$l[] | select(startswith($p)) | ltrimstr($p)] | if length == 0 then "-" else join("+") end;
    "#\(.number)\t\(cat("priority: "))\t\(cat("impact: "))\t\(cat("effort: "))\t\(.title)"'
}

sign() {
  if [[ -n "${SDLC_AGENT_IDENTITY:-}" ]]; then echo "— Claude"; else echo "(posted from Claude Code)"; fi
}

set_labels() {
  (($# >= 4 && $# <= 5)) || usage
  local n="$1" priority="$2" impact="$3" effort="$4" reason="${5:-}"
  [[ "$n" =~ ^[0-9]+$ ]] || { echo "error: '$n' isn't an issue number" >&2; exit 2; }
  [[ "$priority" =~ ^P[123]$ ]] || { echo "error: priority '$priority' isn't P1, P2 or P3" >&2; exit 2; }
  [[ "$impact" =~ ^(high|medium|low)$ ]] || { echo "error: impact '$impact' isn't high, medium or low" >&2; exit 2; }
  [[ "$effort" =~ ^[SML]$ ]] || { echo "error: effort '$effort' isn't S, M or L" >&2; exit 2; }

  local current
  current="$(gh api "repos/$repo/issues/$n" --jq '.labels[].name')" || {
    echo "error: couldn't read issue #$n" >&2
    exit 1
  }
  local want=("priority: $priority" "impact: $impact" "effort: $effort")
  local old_priority
  old_priority="$(grep '^priority: ' <<<"$current" | sed 's/^priority: //' | paste -sd+ -)"
  if [[ -n "$old_priority" && "$old_priority" != "$priority" && -z "$reason" ]]; then
    echo "error: #$n's priority changes from $old_priority to $priority: give the reason" >&2
    exit 2
  fi

  local label
  while IFS= read -r label; do
    [[ "$label" =~ ^(priority|impact|effort):\  ]] || continue
    [[ "$label" == "${want[0]}" || "$label" == "${want[1]}" || "$label" == "${want[2]}" ]] && continue
    gh api -X DELETE "repos/$repo/issues/$n/labels/$(enc "$label")" >/dev/null || {
      echo "error: couldn't remove '$label' from #$n" >&2
      exit 1
    }
  done <<<"$current"
  gh api "repos/$repo/issues/$n/labels" -f "labels[]=${want[0]}" -f "labels[]=${want[1]}" \
    -f "labels[]=${want[2]}" >/dev/null || {
    echo "error: couldn't add the labels to #$n" >&2
    exit 1
  }

  if [[ -n "$old_priority" && "$old_priority" != "$priority" ]]; then
    gh api "repos/$repo/issues/$n/comments" \
      -f body="Priority: $old_priority → $priority. $reason $(sign)" >/dev/null || {
      echo "error: labelled #$n, but couldn't post the comment on its priority" >&2
      exit 1
    }
    echo "#$n: priority $old_priority -> $priority (commented), impact $impact, effort $effort"
  else
    local was="new"
    [[ -n "$old_priority" ]] && was="unchanged"
    echo "#$n: priority $priority ($was), impact $impact, effort $effort"
  fi
}

case "${1:-}" in
  labels) labels ;;
  list) list ;;
  set) shift; set_labels "$@" ;;
  *) usage ;;
esac
