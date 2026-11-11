#!/usr/bin/env bash
# Turn on auto-merge for a PR the pipeline just opened, when the repo has opted in and a
# person's approval still stands between the PR and main (#89).
#
# Usage: scripts/auto-merge.sh <pr-number>
#        scripts/auto-merge.sh --setting <NAME>   print a variable as this script reads it:
#          empty when it isn't set anywhere; exit 1 when it can't be read (bootstrap uses this)
#        scripts/auto-merge.sh --method           print SDLC_AUTO_MERGE by THE RULE below: the
#          method in lower case, or empty when auto-merge is off; exit 1 when it can't be read
#
# THE RULE for SDLC_AUTO_MERGE (#101): case doesn't matter, and unset, empty or `off` means
# auto-merge is off. Anything else is the merge method. Every script reads it through
# `--method`; claude-review.yml can't run a script in its `if`, so it spells the same rule as
# `vars.SDLC_AUTO_MERGE != '' && vars.SDLC_AUTO_MERGE != 'off'` (expression comparisons ignore
# case). tests/test_scripts.py holds them all to the same answers.
#
# Run it straight after opening the PR: GitHub refuses once a PR is approved and green
# ("clean status"). It enables auto-merge only when all of these hold, and otherwise says why
# and exits 0, so it never fails the job or session that called it:
#   1. SDLC_AUTO_MERGE is merge, squash or rebase (off when unset), and the repo allows
#      auto-merge and that merge method.
#   2. An approving review is required: the PR's reviewDecision isn't null. In solo mode
#      (0 approvals) the merge click is the only human gate, so it's never automated.
#   3. The Claude review (`review`) is a required status check on the PR's base branch.
#   4. Stale approvals are dismissed on push, so an approval covers every commit that merges.
#      Read from branch protection or rulesets. A token that can't read protection (an App
#      without Administration: read) relies on SDLC_AUTO_MERGE_CONFIRMED=true, which only
#      bootstrap-github.sh sets, after reading the protection itself.
# It never merges directly.
#
# Env: GITHUB_REPOSITORY (owner/name; default: the gh repo of this checkout).
#      SDLC_AUTO_MERGE, SDLC_AUTO_MERGE_CONFIRMED: the repo variables. CI passes them in;
#      in a session, when they aren't in the environment, they're read from the repo (or its
#      organization). That needs Variables: read; a token without it gets a warning, never a
#      silent "not opted in" (spellbound3d's App, #89).
set -uo pipefail

get_setting=""
if [[ "${1:-}" == --method ]]; then
  get_setting=SDLC_AUTO_MERGE want_method=1
  pr=""
elif [[ "${1:-}" == --setting ]]; then
  get_setting="${2:-}"
  [[ "$get_setting" =~ ^[A-Z_][A-Z0-9_]*$ ]] || { echo "usage: $0 --setting <NAME>" >&2; exit 2; }
  pr=""
else
  pr="${1:-}"
  [[ "$pr" =~ ^[0-9]+$ ]] || { sed -n '2,35p' "$0" >&2; exit 2; }
fi
# THE RULE (see the header): the method in lower case, or empty when auto-merge is off.
method_of() {
  local value
  value="$(tr '[:upper:]' '[:lower:]' <<<"$1")"
  [[ "$value" == off ]] || printf '%s' "$value"
}
# A setting given in the environment needs no repo to read it.
if [[ -n "$get_setting" && -n "${!get_setting+set}" ]]; then
  if [[ -n "${want_method:-}" ]]; then method_of "${!get_setting}"; else printf '%s' "${!get_setting}"; fi
  exit 0
fi
repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
if [[ -z "$repo" ]]; then
  [[ -z "$get_setting" ]] || { echo "auto-merge: can't tell which repo this is" >&2; exit 1; }
  echo "auto-merge: can't tell which repo this is; not enabled for #$pr" >&2; exit 0
fi

skip() { echo "auto-merge not enabled for #$pr: $*" >&2; exit 0; }
err="$(mktemp)"
trap 'rm -f "$err"' EXIT

# <name>: the environment's value when set (even empty), else the repo's variable, else the
# organization's. Prints nothing when it isn't set anywhere; fails when it can't be read.
# A failed `gh api` still prints the error's body on stdout, so each call's output is kept only
# when the call succeeds (spellbound3d: the 404 and 422 bodies came back as the value).
setting() {
  local out
  if [[ -n "${!1+set}" ]]; then printf '%s' "${!1}"; return 0; fi
  if out="$(gh api "repos/$repo/actions/variables/$1" --jq .value 2>"$err")"; then
    printf '%s' "$out"; return 0
  fi
  grep -q 'HTTP 404' "$err" || return 1
  # Not a repo variable; an organization one shared with the repo still counts. A personal
  # account's repo has none (404 or 422 here).
  if out="$(gh api "repos/$repo/actions/organization-variables" --paginate \
    --jq ".variables[] | select(.name == \"$1\") | .value" 2>"$err")"; then
    printf '%s' "$out"; return 0
  fi
  grep -Eq 'HTTP (404|422)' "$err"
}
if [[ -n "${want_method:-}" ]]; then
  value="$(setting SDLC_AUTO_MERGE)" || exit 1
  method_of "$value"
  exit 0
fi
if [[ -n "$get_setting" ]]; then setting "$get_setting"; exit; fi
unreadable="can't read the repo variable SDLC_AUTO_MERGE (the token needs Variables: read)"

value="$(setting SDLC_AUTO_MERGE)" || skip "$unreadable"
method="$(method_of "$value")"
case "$method" in
  "") exit 0 ;;  # not opted in: today's behaviour, say nothing
  merge) allow_field=allow_merge_commit ;;
  squash) allow_field=allow_squash_merge ;;
  rebase) allow_field=allow_rebase_merge ;;
  *) skip "SDLC_AUTO_MERGE is '$method'; use merge, squash or rebase" ;;
esac

# 1. The repo allows auto-merge and the method. A field the token can't see comes back null;
#    then the mutation itself is the check.
info="$(gh api "repos/$repo" --jq "[.allow_auto_merge, .$allow_field] | map(tostring) | join(\" \")")" \
  || skip "can't read repos/$repo"
read -r allow_auto allow_method <<<"$info"
[[ "$allow_auto" != false ]] || skip "the repo doesn't allow auto-merge (Settings → General → Allow auto-merge)"
[[ "$allow_method" != false ]] || skip "the repo doesn't allow '$method' merges"

# 2. An approval is required, read live from the PR (needs only read access).
owner="${repo%%/*}" name="${repo#*/}"
pr_info="$(gh api graphql -F pr="$pr" -f owner="$owner" -f name="$name" -f query='
  query($owner: String!, $name: String!, $pr: Int!) {
    repository(owner: $owner, name: $name) {
      pullRequest(number: $pr) { id reviewDecision baseRefName }
    }
  }' --jq '.data.repository.pullRequest | "\(.id) \(.reviewDecision // "NONE") \(.baseRefName)"')" \
  || skip "can't read the PR"
read -r node_id decision base <<<"$pr_info"
[[ -n "$node_id" && "$node_id" != null ]] || skip "can't read the PR"
[[ "$decision" != NONE ]] \
  || skip "$base doesn't require an approving review (solo mode), so the merge click is the only human gate"

# 3. The Claude review is a required check: classic protection's summary (read access) or rulesets.
checks="$(gh api "repos/$repo/branches/$base" \
  --jq '.protection.required_status_checks // {} | [.contexts[]?, .checks[]?.context] | .[]' 2>/dev/null)"
rules="$(gh api "repos/$repo/rules/branches/$base" 2>/dev/null || echo '[]')"
checks+=$'\n'"$(jq -r '.[] | select(.type == "required_status_checks")
  | .parameters.required_status_checks[]?.context' <<<"$rules" 2>/dev/null)"
grep -qxF review <<<"$checks" \
  || skip "the Claude review ('review') isn't a required check on $base (re-run scripts/bootstrap-github.sh --mode team)"

# 4. Stale approvals are dismissed on push. "Branch not protected" means there's no classic
#    protection at all (rulesets only), so the rulesets alone decide: a stale CONFIRMED left over
#    from a classic setup must not stand in for them (#101). Any other failure is a token that
#    can't read protection, and only then does bootstrap's confirmation count.
if dismiss="$(gh api "repos/$repo/branches/$base/protection" \
  --jq '.required_pull_request_reviews.dismiss_stale_reviews // false' 2>"$err")"; then
  :
elif grep -q 'Branch not protected' "$err"; then
  dismiss=false
else
  dismiss=unknown
fi
if [[ "$dismiss" != true ]] && jq -e 'any(.[]; .type == "pull_request"
    and .parameters.dismiss_stale_reviews_on_push == true)' <<<"$rules" >/dev/null 2>&1; then
  dismiss=true
fi
if [[ "$dismiss" == unknown ]]; then
  # This token can't read classic protection. Fall back to bootstrap's confirmation.
  confirmed="$(setting SDLC_AUTO_MERGE_CONFIRMED)" \
    || skip "${unreadable/SDLC_AUTO_MERGE/SDLC_AUTO_MERGE_CONFIRMED}"
  [[ "$confirmed" == true ]] && dismiss=true
  [[ "$dismiss" == true ]] || skip "can't read $base's protection to confirm stale approvals are dismissed;" \
    "give the token Administration: read, or run scripts/bootstrap-github.sh --mode team as an admin"
fi
[[ "$dismiss" == true ]] || skip "$base doesn't dismiss stale approvals on push, so an early approval would cover later commits"

upper="$(tr '[:lower:]' '[:upper:]' <<<"$method")"
# The mutation runs only from this script: the production-gate hook blocks it typed directly.
if gh api graphql -f id="$node_id" -f method="$upper" -f query='
  mutation($id: ID!, $method: PullRequestMergeMethod!) {
    enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: $method}) {
      pullRequest { number }
    }
  }' --silent 2>"$err"; then
  echo "auto-merge enabled for #$pr ($method): it merges once a person approves and the checks pass"
else
  skip "GitHub refused: $(head -c 300 "$err")"
fi
