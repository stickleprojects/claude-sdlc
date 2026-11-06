#!/usr/bin/env bash
# PreToolUse (Bash): the agent may act up to the production gate and cannot pass it.
# Exit 2 blocks the command and shows stderr to Claude, including the route to approval.
set -euo pipefail

cmd="$(jq -r '.tool_input.command // empty')"

# The production deploy is `make deploy-prod`. Block a command that runs make with that
# target, not one that only mentions it (#78). Text is ignored only where it's safe to call it
# text: quoted strings and heredoc bodies given to a known text tool (git, gh, echo, cat,
# grep, …) that isn't piped on. Strings given to anything else (a shell, eval, python3 -c,
# ssh, …) are checked as code. It errs towards blocking: a dry run (`make -n`) is blocked too.
target='deploy-prod'
make_target="(^|[^[:alnum:]_.-])(g?make|\\\$\\(MAKE\\)|\\\$\\{MAKE\\})([[:space:]]+[^[:space:]]+)*[[:space:]]+$target([^[:alnum:]_-]|$)"
text_tools='git|gh|echo|printf|cat|tee|grep|egrep|fgrep|rg|jq|yq|head|tail|wc|sort|uniq|cut|tr|diff|cmp|ls|test|true|mkdir|touch|cd|pwd'

segments() { sed -E 's/(&&|\|\||;|\|)/\n/g'; }

command_word() {  # the command a segment runs: its first word after variables and keywords
  local w words
  read -ra words <<<"$1" || true
  for w in "${words[@]}"; do
    while [[ "$w" == [\(\{\!]* ]]; do w="${w:1}"; done  # leading ( { !
    [[ -z "$w" || "$w" =~ ^(then|do|else|elif|if|while|until|time)$ ]] && continue
    [[ "$w" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] && continue
    echo "${w##*/}"
    return
  done
}

is_text() {  # every segment of $1 runs a known text tool
  local segment word
  while IFS= read -r segment; do
    word="$(command_word "$segment")"
    [[ "$word" =~ ^($text_tools)$ ]] || return 1
    # git and gh can run a string as a command through config and aliases
    # (`git -c alias.x='!…'`, `git -c core.pager=…`, `git config`, `gh alias set`).
    if [[ "$word" == git ]] \
      && grep -Eq '(^|[[:space:]])(-c|--config-env)([[:space:]=]|$)|[[:space:]]config([[:space:]]|$)' <<<"$segment"; then
      return 1
    fi
    if [[ "$word" == gh ]] && grep -Eq '[[:space:]]alias([[:space:]]|$)' <<<"$segment"; then
      return 1
    fi
  done < <(segments <<<"$1")
}

# Drop heredoc bodies fed to a text tool (`cat > f <<EOF`, `gh … --body "$(cat <<EOF`).
drop_text_heredocs() {
  local line l delim="" tabs="" t
  while IFS= read -r line; do
    if [[ -n "$delim" ]]; then
      t="$line"
      [[ -n "$tabs" ]] && t="${t#"${t%%[!$'\t']*}"}"
      [[ "$t" == "$delim" ]] && delim=""
      continue
    fi
    printf '%s\n' "$line"
    l="${line//<<</}"  # a here-string, not a heredoc
    if [[ "$l" =~ \<\<(-?)[[:space:]]*[\"\']?([A-Za-z_][A-Za-z0-9_]*) ]]; then
      local d="${BASH_REMATCH[2]}" dash="${BASH_REMATCH[1]}"
      if is_text "$l"; then delim="$d" tabs="$dash"; fi
    fi
  done
}

runs_prod_deploy() {
  local code segment
  # A backslash-newline continues the command. Quotes around a single word don't make it
  # text: `make "deploy-prod"` runs the target.
  code="$(awk '{ while (/\\$/ && (getline nxt) > 0) { sub(/\\$/, ""); $0 = $0 " " nxt } print }' <<<"$1" \
    | sed -E "s/'([^'[:space:]]*)'/\\1/g; s/\"([^\"[:space:]\\\\\$\`]*)\"/\\1/g")"
  code="$(drop_text_heredocs <<<"$code")"
  # `… | xargs make` with the target anywhere in the command.
  if grep -Eq "(^|[^[:alnum:]_.-])xargs([[:space:]][^|;&]*)?[[:space:]](g?make)([[:space:]]|$)" <<<"$code" \
    && grep -Eq "(^|[^[:alnum:]_-])$target([^[:alnum:]_-]|$)" <<<"$code"; then
    return 0
  fi
  while IFS= read -r segment; do
    # A text tool's quoted strings are text, unless they hold $( or a backtick, which run.
    if is_text "$segment"; then
      segment="$(sed -E "s/'[^']*'//g; s/\"([^\"\\\\\$\`]|\\\\.)*\"//g" <<<"$segment")"
    fi
    grep -Eq "$make_target" <<<"$segment" && return 0
  done < <(segments <<<"$code")
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
