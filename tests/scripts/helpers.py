"""Helpers shared by more than one test file in this package."""

import json
import re

from conftest import REPO, run


def synced(path: str) -> bool:
    """The sync installs everything under .sdlc/ (#133), so a file there reaches consumers."""
    sync = (REPO / ".sdlc/scripts/sync-sdlc.sh").read_text()
    return '".sdlc:.sdlc"' in sync and path.startswith(".sdlc/") and (REPO / path).is_file()


# --- next-version ----------------------------------------------------------------------


def _next_version(repo):
    result = run(["bash", str(REPO / "scripts/next-version.sh"), "--explain"], cwd=repo)
    return result.returncode, result.stdout.strip()


# --- spec-pr: one spec PR per change --------------------------------------------------------

FAKE_GH = r"""#!/usr/bin/env bash
# Records each call; answers from $FAKE_GH_DIR/<name> files keyed by what the call asks for.
echo "$*" >> "$FAKE_GH_DIR/calls"
case "$*" in
  *"head=$OWNER:spec/"*)
    all="$*"; branch="${all#*head=$OWNER:}"; branch="${branch%% *}"
    f="$FAKE_GH_DIR/open-${branch//\//_}"; [[ -f "$f" ]] && cat "$f"
    [[ -f "$FAKE_GH_DIR/fail" ]] && exit 1 ;;
  *"pulls?state=open&per_page"*) cat "$FAKE_GH_DIR/legacy" 2>/dev/null || true ;;
  *"/files"*) cat "$FAKE_GH_DIR/legacy-files" 2>/dev/null || true ;;
  *"repos/o/r/pulls -f title"*) echo 42 ;;
esac
exit 0
"""


def spec_pr(repo, env, *args):
    return run(["bash", str(REPO / ".sdlc/scripts/spec-pr.sh"), *args], cwd=repo, env=env)


# --- auto-merge: opt-in, only where a person's approval is still required (#89) -------------

FAKE_GH_AUTO_MERGE = r"""#!/usr/bin/env bash
# Answers from $D/<name> files; records each call. Applies --jq like gh does.
echo "$*" >> "$D/calls"
args=("$@") jqf=""
for ((i = 0; i < ${#args[@]}; i++)); do [[ "${args[i]}" == --jq ]] && jqf="${args[i+1]}"; done
out() { if [[ -n "$jqf" ]]; then jq -r "$jqf"; else cat; fi; }
# Like gh api: a failed call prints the response body on stdout and the status on stderr.
fail() { printf '{"message":"%s","status":"%s"}' "$2" "$1"; echo "gh: $2 (HTTP $1)" >&2; exit 1; }
case "$1 $2" in
  "api repos/o/r/actions/variables/"*)
    [[ -f "$D/vars-forbidden" ]] && fail 403 "Resource not accessible by integration"
    f="$D/var-${2##*/}"; [[ -f "$f" ]] && { out < "$f"; exit 0; }
    fail 404 "Not Found" ;;
  "api repos/o/r/actions/organization-variables")
    [[ -f "$D/personal-account" ]] && fail 422 "Validation Failed"
    out < "$D/org-vars.json" ;;
  "api graphql")
    if [[ "$*" == *mutation* ]]; then
      [[ -f "$D/mutation-fails" ]] && { echo "Pull request is in clean status" >&2; exit 1; }
      exit 0
    fi
    out < "$D/pr.json" ;;
  "api repos/o/r") out < "$D/repo.json" ;;
  "api repos/o/r/branches/main") out < "$D/branch.json" ;;
  "api repos/o/r/branches/main/protection")
    [[ -f "$D/no-classic-protection" ]] && fail 404 "Branch not protected"
    [[ -f "$D/protection.json" ]] || { echo "Not accessible (HTTP 403)" >&2; exit 1; }
    out < "$D/protection.json" ;;
  "api repos/o/r/rules/branches/main") cat "$D/rules.json" 2>/dev/null || echo '[]' ;;
  "api repos/o/r/pulls/7/files")
    [[ -f "$D/pr-files.json" ]] || echo '[]' > "$D/pr-files.json"; out < "$D/pr-files.json" ;;
  *) exit 1 ;;
esac
"""
MUTATION = "enablePullRequest" + "AutoMerge"


def _pr(decision):
    pr = {"id": "PR_kw1", "reviewDecision": decision, "baseRefName": "main"}
    return json.dumps({"data": {"repository": {"pullRequest": pr}}})


def identity(env, *args, stdin=None):
    return run(["bash", str(REPO / ".sdlc/scripts/agent-identity.sh"), *args], env=env, input=stdin)


# #126: SDLC_RUNNER picks the runner. Fork PRs, PRs whose fork was deleted and comments on any
# PR never get it (they check out code the repo's people didn't write), and unset means GitHub's.
RUNS_ON = (
    "runs-on: ${{ vars.SDLC_RUNNER && !github.event.issue.pull_request && "
    "(!github.event.pull_request || "
    "github.event.pull_request.head.repo.full_name == github.repository) "
    "&& vars.SDLC_RUNNER || 'ubuntu-latest' }}"
)

# #222: jobs that run `make check` or the evals use SDLC_RUNNER_HEAVY when it's set, falling back
# to SDLC_RUNNER and then to GitHub's runners, behind the same fork guard.
RUNS_ON_HEAVY = (
    "runs-on: ${{ (vars.SDLC_RUNNER_HEAVY || vars.SDLC_RUNNER) && "
    "!github.event.issue.pull_request && "
    "(!github.event.pull_request || "
    "github.event.pull_request.head.repo.full_name == github.repository) "
    "&& (vars.SDLC_RUNNER_HEAVY || vars.SDLC_RUNNER) || 'ubuntu-latest' }}"
)
# #236: sdlc-ci.yml's `check` is heavy, except when SDLC_CHECK_AFTER_REVIEW defers it on a
# same-repo PR: then it only prints a note and takes SDLC_RUNNER (or GitHub's).
CI_DEFERRED = (
    "github.event_name == 'pull_request' && vars.SDLC_CHECK_AFTER_REVIEW != '' && "
    "vars.SDLC_CHECK_AFTER_REVIEW != 'off' && "
    "github.event.pull_request.head.repo.full_name == github.repository"
)
RUNS_ON_DEFERRABLE = (
    f"runs-on: ${{{{ {CI_DEFERRED} && (vars.SDLC_RUNNER || 'ubuntu-latest') || "
    + RUNS_ON_HEAVY.removeprefix("runs-on: ${{ ")
)
# The jobs that get RUNS_ON_HEAVY or RUNS_ON_DEFERRABLE, by workflow. Every other job gets RUNS_ON.
HEAVY_JOBS = {
    "release.yml": {"release"},
    "sdlc-agent-evals.yml": {"evals"},
    "sdlc-check-after-review.yml": {"make-check"},
}
DEFERRABLE_JOBS = {"sdlc-ci.yml": {"check"}}


def gh_expr(expr, ctx):
    """Evaluate a GitHub Actions expression made of what RUNS_ON and the job conditions use:
    property paths, 'strings', !, ==, !=, &&, || and parentheses. Like Actions, a missing
    property is null, && and || return an operand, and null, false, 0 and '' are falsy."""
    tokens = re.findall(r"'[^']*'|&&|\|\||==|!=|!|\(|\)|[A-Za-z_][\w.-]*", expr)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def take():
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def operand():
        tok = take()
        if tok == "!":
            return not operand()
        if tok == "(":
            value = either()
            assert take() == ")"
            return value
        if tok.startswith("'"):
            return tok[1:-1]
        value = ctx
        for part in tok.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        return value

    def equality():
        left = operand()

        # Like Actions: strings compare ignoring case, and values of different types compare
        # as numbers (null and '' are both 0, so an unset variable equals '').
        def num(v):
            if v is None or v == "":
                return 0.0
            if isinstance(v, bool):
                return float(v)
            try:
                return float(v)
            except (TypeError, ValueError):
                return float("nan")

        def same(a, b):
            if isinstance(a, str) and isinstance(b, str):
                return a.lower() == b.lower()
            if type(a) is type(b):
                return a == b
            return num(a) == num(b)

        while peek() in ("==", "!="):
            op = take()
            right = operand()
            left = same(left, right) == (op == "==")
        return left

    def both():
        left = equality()
        while peek() == "&&":
            take()
            right = equality()
            left = right if left else left
        return left

    def either():
        left = both()
        while peek() == "||":
            take()
            right = both()
            left = left if left else right
        return left

    value = either()
    assert pos == len(tokens), tokens[pos:]
    return value


# --- clause check (#47) -------------------------------------------------------------------

CLAUSE_FIXTURE = "evals/fixtures/clause-coverage/0001-role-search"


# --- asking for a review after a push (#105) ------------------------------------------------

FAKE_GH_REQUEST_REVIEW = r"""#!/usr/bin/env bash
# Serves $D/<file> for each API path and logs every call to $D/calls.
printf '%s\n' "$*" >> "$D/calls"
path="$2" jq_filter="" post=0
shift 2
while (($#)); do
  case "$1" in --jq) jq_filter="$2"; shift 2 ;; -f) post=1; shift 2 ;; *) shift ;; esac
done
serve() { if [[ -n "$jq_filter" ]]; then jq -r "$jq_filter" "$D/$1"; else cat "$D/$1"; fi; }
case "$path" in
  repos/o/r/pulls/7)
    # Each call takes the next head from $D/heads (the push shows up after a while).
    head="$(head -n 1 "$D/heads")"
    (($(wc -l < "$D/heads") > 1)) && sed -i 1d "$D/heads"
    ref="$(cat "$D/ref")"
    echo "{\"head\": {\"sha\": \"$head\", \"ref\": \"$ref\"}}" > "$D/pull.json"; serve pull.json ;;
  repos/o/r/issues/7/labels)
    if ((post)); then [[ ! -e "$D/label-fails" ]] || exit 1; else serve labels.json; fi ;;
  repos/o/r/actions/variables/SDLC_AUTO_MERGE)
    status="$(cat "$D/var-status")"
    [[ "$status" == 200 ]] || { echo "gh: HTTP $status" >&2; exit 1; }
    serve var.json ;;
  repos/o/r/actions/organization-variables)
    echo '{"variables": []}' > "$D/org.json"; serve org.json ;;
  repos/o/r/actions/runs*) serve runs.json ;;
  *) echo "unexpected: $path" >&2; exit 1 ;;
esac
"""

PUSHED = "abc1234def5678abc1234def5678abc1234def56"


def review_run(conclusion=None, path=".github/workflows/sdlc-claude-review.yml"):
    status = "completed" if conclusion else "in_progress"
    return {"path": path, "status": status, "conclusion": conclusion}


# --- a stale review blocks the merge (#46) --------------------------------------------------

FAKE_GH_REVIEW_CURRENT = r"""#!/usr/bin/env bash
# PR #7's commits from $D/commits (oldest first), each commit's statuses from $D/status-<sha>.
echo "$*" >> "$D/calls"
args=("$@") jqf=""
for ((i = 0; i < ${#args[@]}; i++)); do [[ "${args[i]}" == --jq ]] && jqf="${args[i+1]}"; done
case "$2" in
  repos/o/r/pulls/7/commits)
    jq -Rn '[inputs | {sha: .}]' < "$D/commits" | jq -r "$jqf" ;;
  repos/o/r/commits/*/statuses)
    sha="${2#repos/o/r/commits/}"; sha="${sha%/statuses}"
    f="$D/status-$sha"; [[ -f "$f" ]] || echo '[]' > "$f"
    jq -r "$jqf" < "$f" ;;
  repos/o/r/statuses/*)
    [[ -f "$D/post-fails" ]] && exit 1
    printf '%s\n' "$*" > "$D/posted" ;;
  repos/o/r/pulls/7) jq -r "$jqf" < "$D/pull" ;;
  repos/o/r/actions/workflows/sdlc-claude-review.yml/runs*) jq -r "$jqf" < "$D/runs" ;;
  -X)
    [[ -f "$D/cancel-fails" ]] && exit 1
    id="${4#repos/o/r/actions/runs/}"; echo "${id%/cancel}" >> "$D/cancelled" ;;
  *) exit 1 ;;
esac
"""


def sha(n: int) -> str:
    return f"{n:040x}"


def thread(body="**Important:** x", login="claude", resolved=False):
    return {
        "isResolved": resolved,
        "comments": {"nodes": [{"author": {"login": login}, "body": body}]},
    }


# --- install-claude: Claude Code per job, never globally (#136) --------------------------------

# Records its arguments and, like npm, puts `claude` in <prefix>/node_modules/.bin.
FAKE_NPM = """#!/usr/bin/env bash
echo "$*" >> "$NPM_LOG"
[[ -n "${NPM_NO_BIN:-}" ]] && exit 0
while [[ $# -gt 0 ]]; do [[ "$1" == --prefix ]] && prefix="$2"; shift; done
mkdir -p "$prefix/node_modules/.bin"
printf '#!/bin/sh\\necho job-local\\n' > "$prefix/node_modules/.bin/claude"
chmod +x "$prefix/node_modules/.bin/claude"
"""


# --- a fast-path bug PR is titled fix(<slug>) (#154) -----------------------------------------

FAST = ["changes/0010-z/bug.md", "changes/0010-z/spec.md", "tests/test_z.py", "src/z.py"]


# --- a descope waits for a person's decision (#132) ------------------------------------------

FAKE_GH_DESCOPES = r"""#!/usr/bin/env bash
[[ "$1" == api ]] || exit 1
echo "$*" >> "$FAKE_CALLS"
case "$2" in
  graphql) file="$FAKE_THREADS" ;;
  repos/o/r/issues/7/comments) file="$FAKE_COMMENTS" ;;
  repos/o/r/commits/abc1234/statuses) file="$FAKE_STATUSES" ;;
  repos/o/r/statuses/abc1234) echo "$*" >> "$FAKE_POSTED"; exit 0 ;;
  *) echo "unexpected: $2" >&2; exit 1 ;;
esac
[[ -e "$file" ]] || { echo "gh: HTTP 502" >&2; exit 1; }
jqx=.
while (($#)); do [[ "$1" == --jq ]] && jqx="$2"; shift; done
jq -r "$jqx" "$file"
"""

DESCOPE = "**Important (product owner decides):** Descope: needs approval. The export isn't built."


def note(who, body, at, kind="User"):
    return {"author": {"login": who, "__typename": kind}, "body": body, "createdAt": at}


def descope_thread(*replies, first=DESCOPE, by="claude"):
    return {"comments": {"nodes": [note(by, first, "2026-11-13T10:00:00Z", "Bot"), *replies]}}


# --- sdlc-ci.yml's check job: which step a run makes (#240, #244) -------------------------------

CHECK_STEPS = {
    "full": "make check FULL=1 (push to main)",
    "docs": "make validate (docs-only push to main)",
    "pr": "make check (PR, or SDLC_PR_CHECK_TARGET)",
}
# The steps' make mustn't inherit an outer `make check FULL=1` (CLAUDE.md, Known mistakes).
CLEAN_MAKE = {"MAKEFLAGS": "", "MAKELEVEL": "", "FULL": ""}


def run_check_job(repo, env, tmp_path):
    """Run sdlc-ci.yml's `check` job as Actions would: the "Which check" step, then the one
    step whose `if:` its mode selects. Returns (mode, the which step's run, that step's run)."""
    from test_check_after_review import CI, load

    steps = {s.get("name"): s for s in load(CI)["jobs"]["check"]["steps"]}
    out = tmp_path / "github-output"
    out.write_text("")
    which = run(
        ["bash", "-e", "-c", steps["Which check this run makes"]["run"]],
        cwd=repo,
        env={**CLEAN_MAKE, "GITHUB_OUTPUT": str(out), **env},
    )
    assert which.returncode == 0, which.stderr
    mode = dict(line.split("=", 1) for line in out.read_text().split()).get("mode")
    want = f"steps.which.outputs.mode == '{mode}' && env.DEFERRED != 'true'"
    chosen = [n for n, s in steps.items() if s.get("if") == want]
    assert chosen == [CHECK_STEPS[mode]], (mode, chosen)
    step = steps[chosen[0]]
    result = run(["bash", "-e", "-c", step["run"]], cwd=repo, env={**CLEAN_MAKE, **env})
    return mode, which, result
