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
# Commands that can't run their arguments as code (rg --pre, sort --compress-program and the
# like can, so they're not here). git and gh count only with the subcommands below.
text_tools='git|gh|echo|printf|cat|tee|grep|egrep|fgrep|jq|head|tail|wc|uniq|cut|tr|diff|cmp|ls|test|true|mkdir|touch|cd|pwd'
git_text='commit|tag|notes|log|show|status|diff'
gh_text='pr|issue|api|release|label'

segments() { sed -E 's/(&&|\|\||;|\|)/\n/g'; }  # each command
lists() { sed -E 's/(&&|\|\||;)/\n/g'; }  # each pipeline: commands joined by |

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
  # A process substitution, >(sh) or <(sh), runs a command of its own.
  [[ "$1" == *'>('* || "$1" == *'<('* ]] && return 1
  while IFS= read -r segment; do
    # Variables set for the command can be run by it (GIT_PAGER, GIT_EDITOR, PAGER, …).
    [[ "$segment" =~ ^[[:space:]]*(env[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*= ]] && return 1
    word="$(command_word "$segment")"
    [[ "$word" =~ ^($text_tools)$ ]] || return 1
    # git and gh run strings through aliases, config, hooks and subcommands such as
    # `rebase -x` or `submodule foreach`: allow only those that take messages or patterns,
    # with no -c or --config-env before them.
    if [[ "$word" == git ]] && ! [[ "$segment" =~ (^|[[:space:]])git([[:space:]]+(-C[[:space:]]+[^[:space:]]+|--no-pager))*[[:space:]]+($git_text)([[:space:]]|$) ]]; then
      return 1
    fi
    if [[ "$word" == gh ]] && ! [[ "$segment" =~ (^|[[:space:]])gh[[:space:]]+($gh_text)([[:space:]]|$) ]]; then
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
      if [[ "$t" == "$delim" ]]; then
        delim=""
      elif [[ "$line" == *'$('* || "$line" == *'`'* ]]; then
        # An unquoted heredoc runs $( and backticks. By now the delimiter's quotes are gone
        # (single words were unquoted above), so keep such lines either way: fail safe.
        printf '%s\n' "$line"
      fi
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

# Join the lines of a quoted string that spans several, so a multi-line `--body "…"` or `-m "…"`
# given to a text tool is dropped as one string (#88). It follows bash, failing safe where it
# can't: heredoc bodies are left line by line (bash reads no quotes there), a `#` comment opens
# no quote, and backslashes still escape, in `$'…'` too (this runs before they're removed). A
# heredoc opened inside a quote (`--body "$(cat <<'EOF'`) is never joined across; the quote it was in
# carries on after the body, so `)"` closes it. Text it can't follow stays line by line, as
# before this was added.
join_quoted_lines() {
  awk '
    function scan(s,   i, n, c, prev) {
      n = length(s); prev = " "
      for (i = 1; i <= n; i++) {
        c = substr(s, i, 1)
        if (state == 1) { if (c == "\047") state = 0; prev = c; continue }
        if (c == "\\") { i++; prev = "x"; continue }
        if (state == 3) { if (c == "\047") state = 0; prev = c; continue }  # ANSI-C string: a backslash escapes its quote
        if (state == 2) { if (c == "\"") state = 0; prev = c; continue }
        if (c == "#" && prev ~ /[[:space:];&|(]/) return  # a comment: no quotes after it
        if (c == "\047") state = (prev == "$") ? 3 : 1; else if (c == "\"") state = 2
        prev = c
      }
    }
    function heredocs(s,   rest, op, word) {  # queue each heredoc this line opens
      rest = s; gsub(/<<</, "", rest)
      while (match(rest, /<<-?[ \t]*["\047]?[A-Za-z_][A-Za-z0-9_]*/)) {
        op = substr(rest, RSTART, RLENGTH); rest = substr(rest, RSTART + RLENGTH)
        dash[++nq] = (op ~ /^<<-/); word = op
        sub(/^<<-?[ \t]*["\047]?/, "", word); delim[nq] = word
      }
    }
    {
      if (body) {  # inside a heredoc: print it as it is, and watch for its delimiter
        t = $0; if (dash[cur]) sub(/^\t+/, "", t)
        print
        if (t == delim[cur]) { if (++cur > nq) { body = 0; nq = 0; cur = 0; state = saved } }
        next
      }
      line = open ? pending " " $0 : $0
      scan($0); heredocs($0)
      if (nq) {  # a heredoc starts: print what we have, then its body line by line
        print line; open = 0; pending = ""; saved = state; state = 0; body = 1; cur = 1; next
      }
      if (state) { open = 1; pending = line } else { open = 0; pending = ""; print line }
    }
    END { if (open) print pending }
  '
}

runs_prod_deploy() {
  local code segment
  # A backslash-newline continues the command. Escapes and quotes around a single word don't
  # make it text: `make "deploy-prod"`, `make $'deploy-prod'` and `make deploy\-prod` run the
  # target. Deliberate disguises (brace expansion, the target built from variables) are out of
  # scope: this guards against accidents, and a human still holds the release.
  code="$(awk '{ while (/\\$/ && (getline nxt) > 0) { sub(/\\$/, ""); $0 = $0 " " nxt } print }' <<<"$1" \
    | join_quoted_lines \
    | sed -E "s/\\\$(['\"])/\1/g; s/\\\\(.)/\1/g" \
    | sed -E "s/'([^'[:space:]]*)'/\\1/g; s/\"([^\"[:space:]\\\\\$\`]*)\"/\\1/g")"
  code="$(drop_text_heredocs <<<"$code")"
  # `… | xargs make` with the target anywhere in the command.
  if grep -Eq "(^|[^[:alnum:]_.-])xargs([[:space:]][^|;&]*)?[[:space:]](g?make)([[:space:]]|$)" <<<"$code" \
    && grep -Eq "(^|[^[:alnum:]_-])$target([^[:alnum:]_-]|$)" <<<"$code"; then
    return 0
  fi
  local pipeline
  while IFS= read -r pipeline; do
    # Quoted strings are text only when every command in the pipeline is a text tool:
    # `echo '…' | sh` runs them. Even then, $( and backticks run.
    if is_text "$pipeline"; then
      pipeline="$(sed -E "s/'[^']*'//g; s/\"([^\"\\\\\$\`]|\\\\.)*\"//g" <<<"$pipeline")"
    fi
    while IFS= read -r segment; do
      grep -Eq "$make_target" <<<"$segment" && return 0
    done < <(segments <<<"$pipeline")
  done < <(lists <<<"$code")
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

# Auto-merge is allowed only through scripts/auto-merge.sh, which first checks that a person's
# approval is still required (#89). Typing the mutation directly would skip those checks. The
# whole command is checked, not each line, because a GraphQL query usually spans several. The
# script's own call never reaches this hook: the hook sees only the command line. Disguising
# the mutation (variables, base64, eval) is not caught, deliberately, like the merge rules
# below: the hook stops honest mistakes, not a determined bypass.
if grep -Eq '(^|[[:space:]])gh[[:space:]]+api([[:space:]]|$)' <<<"$cmd" && grep -q 'enablePullRequestAutoMerge' <<<"$cmd"; then
  cat >&2 <<'EOF'
Blocked: turn on auto-merge with scripts/auto-merge.sh <PR>, which checks first that a person's
approval is still required. Enabling it directly could merge a PR nobody approves.
EOF
  exit 2
fi

# The agent opens and updates PRs but never merges or approves them: a human does.
# In solo mode Claude uses the human's gh login, so GitHub can't enforce this; this can.
merge_or_approve() {
  cat >&2 <<'EOF'
Blocked: merging and approving PRs is a human decision, not the agent's.
Route: tell the human the PR is ready (checks green, review summary read) and let them merge it.
For auto-merge (--auto), run scripts/auto-merge.sh <PR>: it enables it only where an approval is required.
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
