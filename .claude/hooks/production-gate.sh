#!/usr/bin/env bash
# PreToolUse (Bash): the agent may act up to the production gate and cannot pass it.
# Exit 2 blocks the command and shows stderr to Claude, including the route to approval.
set -euo pipefail

cmd="$(jq -r '.tool_input.command // empty')"

# The production deploy is `make deploy-prod`. Block a command that runs make with that
# target, not one that only mentions it (#78): text in a quoted string, a commit message or
# a PR body, a heredoc fed to cat or gh, or a grep pattern. Where text could be run as code
# (a heredoc or string given to a shell, eval, ssh, sudo or xargs), it's checked as code.
# It errs towards blocking: a dry run (`make -n`) is blocked too.
target='deploy-prod'
shells='(^|[^[:alnum:]_.-])((ba|z|da|k)?sh|eval|ssh|su|sudo|xargs|watch|docker|kubectl)([^[:alnum:]_.-]|$)'
make_target="(^|[^[:alnum:]_.-])(g?make|\\\$\\(MAKE\\)|\\\$\\{MAKE\\})([[:space:]]+[^[:space:]]+)*[[:space:]]+$target([^[:alnum:]_-]|$)"

# Drop heredoc bodies that go to something other than a shell (`cat <<EOF`, `gh … <<EOF`).
drop_data_heredocs() {
  awk -v shells="$shells" '
    skipping { t = $0; if (tabs) sub(/^\t+/, "", t); if (t == delim) skipping = 0; next }
    {
      print
      line = $0; gsub(/<<</, "", line)  # a here-string, not a heredoc
      if (match(line, /<<-?[[:space:]]*["\047]?[A-Za-z_][A-Za-z0-9_]*/)) {
        delim = substr(line, RSTART, RLENGTH); tabs = (delim ~ /^<<-/)
        sub(/^<<-?[[:space:]]*["\047]?/, "", delim)
        if (line !~ shells) skipping = 1
      }
    }'
}

# Drop quoted strings, which are text, unless a shell will run them. A double-quoted string
# with $( or a backtick is kept: the substitution runs.
drop_strings() {
  sed -E "s/'[^']*'//g; s/\"([^\"\\\\\$\`]|\\\\.)*\"//g"
}

runs_prod_deploy() {
  local code bare segment
  code="$(drop_data_heredocs <<<"$1")"
  bare="$(drop_strings <<<"$code")"
  grep -Eq "$shells" <<<"$bare" || code="$bare"
  # `… | xargs make` with the target anywhere in the command.
  if grep -Eq "(^|[^[:alnum:]_.-])xargs([[:space:]][^|;&]*)?[[:space:]](g?make)([[:space:]]|$)" <<<"$code" \
    && grep -Eq "(^|[^[:alnum:]_-])$target([^[:alnum:]_-]|$)" <<<"$code"; then
    return 0
  fi
  while IFS= read -r segment; do
    grep -Eq "$make_target" <<<"$segment" && return 0
  done < <(sed -E 's/(&&|\|\||;|\|)/\n/g' <<<"$code")
  return 1
}

if runs_prod_deploy "$cmd"; then
  cat >&2 <<'EOF'
Blocked: production deploys need a named release authorization from a human.
Route: open or update the PR, then ask the release manager to run
  make deploy-prod RELEASE_AUTHORIZED_BY=<their name>
EOF
  exit 2
fi

# The agent opens and updates PRs but never merges or approves them: a human does.
# In solo mode Claude uses the human's gh login, so GitHub can't enforce this; this can.
merge_or_approve() {
  cat >&2 <<'EOF'
Blocked: merging and approving PRs is a human decision, not the agent's.
Route: tell the human the PR is ready (checks green, review summary read) and let them merge it.
EOF
  exit 2
}

# Inspect each command segment on its own, so words elsewhere in a compound command
# (e.g. `git merge main && git push`) don't trigger a false block.
while IFS= read -r segment; do
  if [[ "$segment" =~ (^|[[:space:]])gh[[:space:]]+pr[[:space:]]+merge([[:space:]]|$) ]]; then
    merge_or_approve
  fi
  if [[ "$segment" =~ (^|[[:space:]])gh[[:space:]]+pr[[:space:]]+review([[:space:]]|$) ]] \
    && grep -Eq '(^|[[:space:]])(--approve|-a)([[:space:]]|$)' <<<"$segment"; then
    merge_or_approve
  fi
  if [[ "$segment" =~ (^|[[:space:]])gh[[:space:]]+api([[:space:]]|$) ]] \
    && grep -Eq '/pulls/[0-9]+/merge|event[=:"[:space:]]+"?APPROVE' <<<"$segment"; then
    merge_or_approve
  fi

  [[ "$segment" =~ git[[:space:]]+push([[:space:]]+(.*))?$ ]] || continue
  args="${BASH_REMATCH[2]:-}"
  if grep -Eq '(^|[[:space:]])(--force|--force-with-lease|-f)([=[:space:]]|$)' <<<"$args"; then
    echo "Blocked: force pushes are not allowed for the agent." >&2
    exit 2
  fi
  # A bare `main`/`master` ref, or `<src>:main`, means pushing to main.
  if grep -Eq '(^|[[:space:]:+])(main|master)([[:space:]]|$)' <<<"$args"; then
    echo "Blocked: the agent has no direct path to main. Push a branch and open a PR." >&2
    exit 2
  fi
done < <(sed -E 's/(&&|\|\||;|\|)/\n/g' <<<"$cmd")
exit 0
