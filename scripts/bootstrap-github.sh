#!/usr/bin/env bash
# Configure a GitHub repo for this pipeline. Safe to re-run: each step checks, then fixes.
#
# Usage: scripts/bootstrap-github.sh [--repo owner/name] [--mode solo|team] [--dry-run] [--skip-token]
#        scripts/bootstrap-github.sh --gitignore-only   (step 9 alone; needs no GitHub access)
#
# Every setting below was learned the hard way when this repo was first set up:
#   1. executable bits    NTFS/Windows checkouts commit scripts as 100644; hooks then fail silently
#   2. labels             `pipeline`, for platform-team issues; `review`, to re-run the AI review on a PR
#   3. CODEOWNERS         names the repo owner; team mode requires a code owner's review
#   4. Claude token       CLAUDE_CODE_OAUTH_TOKEN secret (from `claude setup-token`; Pro/Max plan)
#   5. Actions → PRs      Spec from intent opens PRs; GitHub blocks that by default
#   6. branch protection  PR + `check` and `pr-title` statuses, no admin bypass, branches must be
#                         up to date with main before merging (otherwise nobody is told that an
#                         open PR is behind main), and:
#        --mode solo (default)  0 approvals: one person, with Claude using their gh login. GitHub
#                               can't tell them apart, so the human gate is the merge click, and
#                               the production-gate hook stops the agent from merging or approving.
#        --mode team            1 code-owner approval: several people, or Claude under its own bot
#                               account, so authors and approvers are different GitHub users.
#   7. delete branches    delete_branch_on_merge, so merged PR branches don't pile up
#   8. agent identity     if scripts/agent-identity.sh create was run: checks each App is installed, and
#                         sets the SDLC_AGENT_APP_ID/_SLUG variables and SDLC_AGENT_APP_KEY secret
#                         the workflows use. With an agent identity, use --mode team.
#   9. .gitignore         adds any line of templates/gitignore that's missing; a stray `git add -A`
#                         once committed ~82,000 node_modules and build files
# Steps it can only check or print (they need a browser or a human):
#  10. Claude GitHub app  https://github.com/apps/claude, needed by claude-code-action
#  11. workspace trust    run `claude` here once; until then .claude/settings.json allow rules are ignored
set -euo pipefail

repo="" mode=solo dry=0 skip_token=0 print_protection=0 gitignore_only=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --mode) mode="$2"; shift 2 ;;
    --dry-run) dry=1; shift ;;
    --skip-token) skip_token=1; shift ;;
    --print-protection) print_protection=1; shift ;;  # print the step 6 JSON and exit (tests)
    --gitignore-only) gitignore_only=1; shift ;;       # run only step 9, no GitHub calls
    -h|--help) sed -n '2,29p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ "$mode" == solo || "$mode" == team ]] || { echo "--mode must be solo or team" >&2; exit 2; }

protection_json() {
  local approvals=0 code_owners=false
  [[ "$mode" == team ]] && approvals=1 code_owners=true
  jq -n --argjson n "$approvals" --argjson co "$code_owners" '{
    required_status_checks: { strict: true, contexts: ["check", "pr-title"] },
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

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
todo() { printf '  \033[33m!\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
run()  { if ((dry)); then printf '    would run: %s\n' "$*"; else "$@"; fi; }

# Step 9: append every line of templates/gitignore that .gitignore lacks. Idempotent.
merge_gitignore() {
  local line missing=()
  if [[ ! -f templates/gitignore ]]; then
    todo "templates/gitignore not found; run make sync-sdlc first"
    return 0
  fi
  while IFS= read -r line; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ -f .gitignore ]] && grep -qxF -- "$line" .gitignore && continue
    missing+=("$line")
  done < templates/gitignore
  if ((${#missing[@]} == 0)); then ok ".gitignore has every baseline line"
  elif ((dry)); then echo "    would add to .gitignore: ${missing[*]}"
  else
    { if [[ -s .gitignore ]]; then echo; fi
      echo "# claude-sdlc baseline (templates/gitignore)"
      printf '%s\n' "${missing[@]}"; } >> .gitignore
    todo "added ${#missing[@]} line(s) to .gitignore; commit it in a PR"
  fi
}

cd "$(git rev-parse --show-toplevel)"
if ((gitignore_only)); then merge_gitignore; exit 0; fi
for tool in gh git jq; do command -v "$tool" >/dev/null || { echo "missing: $tool" >&2; exit 1; }; done
gh auth status >/dev/null 2>&1 || { echo "run: gh auth login" >&2; exit 1; }
repo="${repo:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
owner="${repo%%/*}"


echo "Configuring $repo$( ((dry)) && echo ' (dry run)')"

step "1. Executable bits on committed scripts"
bad=$(git ls-files -s '*.sh' | awk '$1 != "100755" {print $4}')
if [[ -z "$bad" ]]; then ok "all *.sh are 100755"
else
  for f in $bad; do run git update-index --chmod=+x "$f"; done
  todo "marked executable: $(echo $bad); commit this in a PR"
fi

step "2. Labels"
labels=$(gh label list -R "$repo" --limit 200 --json name -q '.[].name')
while IFS='|' read -r name color desc; do
  if grep -qx "$name" <<<"$labels"; then ok "label $name"
  else
    run gh label create "$name" -R "$repo" --color "$color" --description "$desc"
    ((dry)) || ok "created label $name"
  fi
done <<'EOF'
pipeline|5319e7|Pipeline, tooling and permissions (platform team)
review|0e8a16|While on, the Claude review runs again on every push
EOF

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
summary="PR + 'check' and 'pr-title' statuses, up to date with main, no admin bypass"
[[ "$mode" == team ]] && summary+=", 1 code-owner approval" || summary+=", 0 approvals (you merge; the hook stops the agent)"
# Compare the settings that matter, normalised, with what this mode wants.
shape='{checks: (.required_status_checks.contexts | sort),
        strict: .required_status_checks.strict,
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

step "7. Delete PR branches after merge"
if [[ "$(gh api "repos/$repo" -q .delete_branch_on_merge)" == true ]]; then
  ok "already on"
else
  run gh api -X PATCH "repos/$repo" -F delete_branch_on_merge=true --silent
  ((dry)) || ok "turned on"
fi

step "8. Claude agent identity (GitHub Apps)"
configured=0
for identity in $(scripts/agent-identity.sh identities 2>/dev/null); do
  if ! agent="$(SDLC_AGENT_IDENTITY_NAME="$identity" scripts/agent-identity.sh show 2>/dev/null)"; then
    todo "identity $identity isn't set up on this machine; run: scripts/agent-identity.sh create"
    continue
  fi
  configured=1
  read -r _ app_slug <<<"$agent"
  if SDLC_AGENT_IDENTITY_NAME="$identity" SDLC_AGENT_REPO="$repo" scripts/agent-identity.sh token >/dev/null 2>/tmp/bootstrap-err; then
    ok "$identity: $app_slug[bot] can act on $repo"
  else
    todo "$identity: install $app_slug on $repo: https://github.com/apps/$app_slug/installations/new"
  fi
done
# The workflows act as the identity the spec-ci persona maps to.
ci="$(scripts/agent-identity.sh identity-of spec-ci 2>/dev/null || true)"
if ((configured == 0)); then
  todo "no App set up: Claude sessions act as you. Create one with: scripts/agent-identity.sh create [--per-persona]"
elif ! agent="$(SDLC_AGENT_IDENTITY_NAME="$ci" scripts/agent-identity.sh show 2>/dev/null)"; then
  todo "the CI identity ($ci, used by spec-ci) isn't set up; the spec workflow will use GITHUB_TOKEN"
else
  read -r app_id app_slug <<<"$agent"
  vars=$(gh variable list -R "$repo" --json name,value -q '.[] | "\(.name)=\(.value)"' 2>/dev/null || true)
  for pair in "SDLC_AGENT_APP_ID=$app_id" "SDLC_AGENT_APP_SLUG=$app_slug"; do
    if grep -qxF "$pair" <<<"$vars"; then ok "variable ${pair%%=*}"
    else run gh variable set "${pair%%=*}" -R "$repo" --body "${pair#*=}"; ((dry)) || ok "set variable ${pair%%=*}"
    fi
  done
  if gh secret list -R "$repo" --json name -q '.[].name' | grep -qx SDLC_AGENT_APP_KEY; then ok "secret SDLC_AGENT_APP_KEY"
  elif ((dry)); then echo "    would store $ci's private key as secret SDLC_AGENT_APP_KEY"
  else SDLC_AGENT_IDENTITY_NAME="$ci" scripts/agent-identity.sh key | gh secret set SDLC_AGENT_APP_KEY -R "$repo"; ok "stored secret SDLC_AGENT_APP_KEY ($ci)"
  fi
  [[ "$mode" == team ]] || todo "Claude has its own identity: re-run with --mode team so GitHub requires your approval on its PRs"
fi

step "9. .gitignore baseline"
merge_gitignore

step "10. Claude GitHub app (manual)"
todo "install it on $repo: https://github.com/apps/claude → Configure → Only select repositories"

step "11. Claude Code workspace trust (manual)"
todo "run 'claude' in this folder once and accept the trust prompt"

echo
echo "Done. Verify: open a test PR and check that both 'check' and 'review' pass and Claude posts a review summary."
