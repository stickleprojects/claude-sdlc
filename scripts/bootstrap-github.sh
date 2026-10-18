#!/usr/bin/env bash
# Configure a GitHub repo for this pipeline. Safe to re-run: each step checks, then fixes.
#
# Usage: scripts/bootstrap-github.sh [--repo owner/name] [--mode solo|team] [--dry-run] [--skip-token]
#
# Every setting below was learned the hard way when this repo was first set up:
#   1. executable bits    NTFS/Windows checkouts commit scripts as 100644; hooks then fail silently
#   2. labels             `pipeline`, for platform-team issues
#   3. CODEOWNERS         names the repo owner; team mode requires a code owner's review
#   4. Claude token       CLAUDE_CODE_OAUTH_TOKEN secret (from `claude setup-token`; Pro/Max plan)
#   5. Actions → PRs      Spec from intent opens PRs; GitHub blocks that by default
#   6. branch protection  PR + `check` and `pr-title` statuses, no admin bypass, and:
#        --mode solo (default)  0 approvals: one person, with Claude using their gh login. GitHub
#                               can't tell them apart, so the human gate is the merge click, and
#                               the production-gate hook stops the agent from merging or approving.
#        --mode team            1 code-owner approval: several people, or Claude under its own bot
#                               account, so authors and approvers are different GitHub users.
# Steps it can only check or print (they need a browser or a human):
#   7. Claude GitHub app  https://github.com/apps/claude, needed by claude-code-action
#   8. workspace trust    run `claude` here once; until then .claude/settings.json allow rules are ignored
set -euo pipefail

repo="" mode=solo dry=0 skip_token=0 print_protection=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --mode) mode="$2"; shift 2 ;;
    --dry-run) dry=1; shift ;;
    --skip-token) skip_token=1; shift ;;
    --print-protection) print_protection=1; shift ;;  # print the step 6 JSON and exit (tests)
    -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ "$mode" == solo || "$mode" == team ]] || { echo "--mode must be solo or team" >&2; exit 2; }

protection_json() {
  local approvals=0 code_owners=false
  [[ "$mode" == team ]] && approvals=1 code_owners=true
  jq -n --argjson n "$approvals" --argjson co "$code_owners" '{
    required_status_checks: { strict: false, contexts: ["check", "pr-title"] },
    enforce_admins: true,
    required_pull_request_reviews: {
      require_code_owner_reviews: $co,
      required_approving_review_count: $n,
      dismiss_stale_reviews: true
    },
    restrictions: null,
    allow_force_pushes: false,
    allow_deletions: false
  }'
}
if ((print_protection)); then protection_json; exit 0; fi

cd "$(git rev-parse --show-toplevel)"
for tool in gh git jq; do command -v "$tool" >/dev/null || { echo "missing: $tool" >&2; exit 1; }; done
gh auth status >/dev/null 2>&1 || { echo "run: gh auth login" >&2; exit 1; }
repo="${repo:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
owner="${repo%%/*}"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
todo() { printf '  \033[33m!\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
run()  { if ((dry)); then printf '    would run: %s\n' "$*"; else "$@"; fi; }

echo "Configuring $repo$( ((dry)) && echo ' (dry run)')"

step "1. Executable bits on committed scripts"
bad=$(git ls-files -s '*.sh' | awk '$1 != "100755" {print $4}')
if [[ -z "$bad" ]]; then ok "all *.sh are 100755"
else
  for f in $bad; do run git update-index --chmod=+x "$f"; done
  todo "marked executable: $(echo $bad); commit this in a PR"
fi

step "2. Labels"
if gh label list -R "$repo" --json name -q '.[].name' | grep -qx pipeline; then ok "label pipeline"
else
  run gh label create pipeline -R "$repo" --color 5319e7 --description "Pipeline, tooling and permissions (platform team)"
  ((dry)) || ok "created label pipeline"
fi

step "3. CODEOWNERS"
want="* @$owner"
if [[ -f .github/CODEOWNERS ]] && grep -qxF "$want" .github/CODEOWNERS; then ok ".github/CODEOWNERS names @$owner"
else
  if ((dry)); then echo "    would write: $want"
  else
    mkdir -p .github
    printf '# Code owners approve PRs when branch protection runs in team mode.\n# The agent never counts as a code owner.\n%s\n' "$want" > .github/CODEOWNERS
  fi
  todo ".github/CODEOWNERS set to @$owner; commit it in a PR (team mode needs it on main)"
fi

step "4. Claude token secret (CLAUDE_CODE_OAUTH_TOKEN)"
has_secret=0
gh secret list -R "$repo" --json name -q '.[].name' | grep -qx CLAUDE_CODE_OAUTH_TOKEN && has_secret=1
if ((has_secret)) && ! ((dry)) && ! ((skip_token)); then
  read -rp "  secret already exists; replace it? [y/N] " answer
  [[ "$answer" == [yY]* ]] || skip_token=1
fi
if ((skip_token)); then
  if ((has_secret)); then ok "secret exists"; else todo "secret missing; re-run without --skip-token"; fi
elif ((dry)); then
  ((has_secret)) && ok "secret exists (a real run asks whether to replace it)" \
    || echo "    would prompt for the token, test it with claude -p, then gh secret set"
else
  echo "  Run 'claude setup-token' in another terminal and copy the token it prints."
  echo "  Paste it below (input hidden). Line wraps are fine; finish with an empty line."
  token=""
  while IFS= read -rs line && [[ -n "$line" ]]; do token+="$line"; done
  token="$(tr -d '[:space:]' <<<"$token")"
  [[ "$token" == sk-ant-oat01-* ]] || { echo "  token should start with sk-ant-oat01- (got ${#token} chars); not saved" >&2; exit 1; }
  if command -v claude >/dev/null; then
    reply=$(CLAUDE_CODE_OAUTH_TOKEN="$token" claude -p "reply with just: ok" 2>&1 || true)
    [[ "$reply" == *ok* ]] || { echo "  token test failed: ${reply:0:200}" >&2; exit 1; }
    ok "token works locally"
  fi
  printf '%s' "$token" | gh secret set CLAUDE_CODE_OAUTH_TOKEN -R "$repo"
  unset token
  ok "secret saved"
fi

step "5. Let GitHub Actions create pull requests"
if [[ "$(gh api "repos/$repo/actions/permissions/workflow" -q .can_approve_pull_request_reviews)" == true ]]; then
  ok "already allowed"
else
  echo '{"default_workflow_permissions":"read","can_approve_pull_request_reviews":true}' \
    | run gh api -X PUT "repos/$repo/actions/permissions/workflow" --input -
  ((dry)) || ok "allowed (an approval by Actions never counts: team mode requires a code owner)"
fi

step "6. Branch protection on main ($mode mode)"
summary="PR + 'check' and 'pr-title' statuses, no admin bypass"
[[ "$mode" == team ]] && summary+=", 1 code-owner approval" || summary+=", 0 approvals (you merge; the hook stops the agent)"
# Compare the settings that matter, normalised, with what this mode wants.
shape='{checks: (.required_status_checks.contexts | sort),
        admins: (if (.enforce_admins | type) == "object" then .enforce_admins.enabled else .enforce_admins end),
        approvals: .required_pull_request_reviews.required_approving_review_count,
        owners: .required_pull_request_reviews.require_code_owner_reviews}'
want="$(protection_json | jq -c "$shape")"
have="$(gh api "repos/$repo/branches/main/protection" 2>/dev/null | jq -c "$shape" 2>/dev/null || true)"
if [[ "$have" == "$want" ]]; then
  ok "already protected: $summary"
elif ((dry)); then
  echo "    would PUT repos/$repo/branches/main/protection"
  echo "    have: ${have:-none}"
  echo "    want: $want"
elif protection_json | gh api -X PUT "repos/$repo/branches/main/protection" --input - >/dev/null 2>/tmp/bootstrap-err; then
  ok "protected: $summary"
else
  todo "could not protect main: $(head -c 200 /tmp/bootstrap-err). Private repos on a free plan need GitHub Pro."
fi

step "7. Claude GitHub app (manual)"
todo "install it on $repo: https://github.com/apps/claude → Configure → Only select repositories"

step "8. Claude Code workspace trust (manual)"
todo "run 'claude' in this folder once and accept the trust prompt"

echo
echo "Done. Verify: open a test PR and check that both 'check' and 'review' pass and Claude posts a review summary."
