"""SDLC_CHECK_AFTER_REVIEW (#163): `make check` waits for a clean Claude review.

The gate script against a fake GitHub, and the workflows' conditions evaluated the way Actions
evaluates them (gh_expr), since neither runs here."""

import json
import os
import re
from pathlib import Path

import pytest

from conftest import REPO, run
from test_scripts import RUNS_ON, gh_expr

GATE = REPO / ".sdlc/scripts/check-gate.sh"
CI = REPO / ".github/workflows/sdlc-ci.yml"
AFTER = REPO / ".github/workflows/sdlc-check-after-review.yml"


def load(path: Path):
    """The YAML subset the workflows use: maps, lists of maps, `|` and `>-` blocks, plain and
    quoted scalars, and [a, b] lists. PyYAML isn't a dependency (the lockfile is a person's)."""
    lines = [
        ln for ln in path.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#")
    ]
    pos = 0

    def scalar(v):
        v = v.strip()
        if v in ("true", "false"):
            return v == "true"
        if v.startswith("[") and v.endswith("]"):
            return [x.strip() for x in v[1:-1].split(",")]
        if len(v) > 1 and v[0] == v[-1] and v[0] in "'\"":
            return v[1:-1]
        return re.sub(r"\s+#.*$", "", v)

    def indent(ln):
        return len(ln) - len(ln.lstrip(" "))

    def block(style, ind):
        nonlocal pos
        body = []
        while pos < len(lines) and indent(lines[pos]) > ind:
            body.append(lines[pos])
            pos += 1
        cut = min(indent(b) for b in body)
        body = [b[cut:] for b in body]
        return "\n".join(body) + "\n" if style == "|" else " ".join(body)

    def node(ind):
        nonlocal pos
        if lines[pos].lstrip().startswith("- "):
            items = []
            while (
                pos < len(lines)
                and indent(lines[pos]) == ind
                and lines[pos].lstrip().startswith("- ")
            ):
                lines[pos] = " " * (ind + 2) + lines[pos].lstrip()[2:]
                items.append(node(ind + 2))
            return items
        out = {}
        while (
            pos < len(lines)
            and indent(lines[pos]) == ind
            and not lines[pos].lstrip().startswith("- ")
        ):
            key, _, value = lines[pos].strip().partition(":")
            pos += 1
            value = value.strip()
            if value in ("|", ">-"):
                out[key] = block(value, ind)
            elif value:
                out[key] = scalar(value)
            elif pos < len(lines) and indent(lines[pos]) > ind:
                out[key] = node(indent(lines[pos]))
            elif (
                pos < len(lines)
                and lines[pos].lstrip().startswith("- ")
                and indent(lines[pos]) == ind
            ):
                out[key] = node(ind)
            else:
                out[key] = None
        return out

    return node(0)


HEAD = "a" * 40
NEWER = "b" * 40

FAKE_GH = r"""#!/usr/bin/env bash
[[ "$1" == api ]] || exit 1
printf '%s\n' "${*:2}" >> "$FAKE_DIR/calls"
case "$2" in
  repos/o/r/pulls/7) file="$FAKE_DIR/pull.json" ;;
  repos/o/r/commits/*/statuses) file="$FAKE_DIR/statuses.json" ;;
  graphql) file="$FAKE_DIR/threads.json" ;;
  repos/o/r/statuses/*) [[ -e "$FAKE_DIR/no-write" ]] && exit 1; exit 0 ;;
  *) echo "unexpected: $2" >&2; exit 1 ;;
esac
[[ -e "$file" ]] || { echo "gh: HTTP 502" >&2; exit 1; }
jqx=.
while (($#)); do [[ "$1" == --jq ]] && jqx="$2"; shift; done
jq -r "$jqx" "$file"
"""


def status(context, state, description=""):
    return {"context": context, "state": state, "description": description}


def thread(body="**Important:** x", login="claude", resolved=False):
    return {
        "isResolved": resolved,
        "comments": {"nodes": [{"author": {"login": login}, "body": body}]},
    }


@pytest.fixture
def gate(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH)
    (fake / "gh").chmod(0o755)
    state = tmp_path / "gh"
    state.mkdir()

    def go(statuses=(), threads=(), head=HEAD, pr_state="open", force=False, broken=()):
        (state / "pull.json").write_text(json.dumps({"state": pr_state, "head": {"sha": head}}))
        (state / "statuses.json").write_text(json.dumps(list(statuses)))  # newest first
        page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": list(threads)}
        data = {"data": {"repository": {"pullRequest": {"reviewThreads": page}}}}
        (state / "threads.json").write_text(json.dumps(data))
        for name in broken:
            (state / name).unlink(missing_ok=True) if name.endswith(".json") else (
                state / name
            ).touch()
        (state / "calls").write_text("")
        env = {
            "PATH": f"{fake}:{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "o/r",
            "FAKE_DIR": str(state),
        }
        args = ["bash", str(GATE), "7", HEAD] + (["--force"] if force else [])
        result = run(args, env=env)
        posts = [
            c
            for c in (state / "calls").read_text().splitlines()
            if c.startswith("repos/o/r/statuses/")
        ]
        return result, posts

    return go


CLEAN = [status("claude-review", "success", "The Claude review is posted")]


def test_a_clean_review_runs_check(gate):
    found = [
        thread(resolved=True),  # fixed and resolved
        thread("**Nit:** naming"),  # nits don't hold it
        thread("**Important:** a person's note", login="kieron"),  # not the reviewer's
    ]
    result, posts = gate(CLEAN, found)
    assert (result.returncode, result.stdout) == (0, "run\n"), result.stderr
    assert posts == [], "the check job posts `running` itself"


def test_an_open_important_thread_waits_and_says_why(gate):
    result, posts = gate(
        CLEAN, [thread(), thread("**Important (product owner decides):** y", login="claude[bot]")]
    )
    assert result.returncode == 0
    assert result.stdout.startswith("wait Waiting: 2 open Important thread(s).")
    assert "reply on one or approve, or add the check label" in result.stdout
    [post] = posts
    assert (
        f"repos/o/r/statuses/{HEAD}" in post and "state=pending" in post and "context=check" in post
    )
    description = post.split("description=", 1)[1]
    assert len(description) <= 140 and description.startswith("Waiting: 2 open")


@pytest.mark.parametrize(
    ("review", "says"),
    [
        (None, "Waiting for the Claude review"),
        (
            status("claude-review", "pending", "The Claude review is running"),
            "Waiting for the Claude review, which is running",
        ),
        (
            status(
                "claude-review", "failure", "Not reviewed: 1 commit since the review of abc1234"
            ),
            "Waiting for a clean Claude review: Not reviewed: 1 commit since",
        ),
    ],
    ids=["no-review-yet", "review-running", "review-failed-or-not-reviewed"],
)
def test_a_review_that_isnt_green_waits(gate, review, says):
    result, posts = gate([review] if review else [])
    assert result.stdout.startswith(f"wait {says}") and len(posts) == 1


def test_a_green_review_alone_isnt_clean(gate):
    # `claude-review` success means each Important finding has its thread (#130), not none.
    result, _ = gate(CLEAN, [thread()])
    assert result.stdout.startswith("wait ")


def test_the_newest_status_of_each_context_counts(gate):
    statuses = [
        status("claude-review", "success"),
        status("check", "pending", "Waiting for the Claude review"),
        status("claude-review", "failure", "an older review"),
    ]
    assert gate(statuses)[0].stdout == "run\n"


@pytest.mark.parametrize(
    ("check", "says"),
    [
        (status("check", "success", "make check passed"), "already ran"),
        (status("check", "failure", "make check failed"), "already ran"),
        (status("check", "pending", "make check is running"), "already running"),
    ],
)
def test_check_runs_once_per_head(gate, check, says):
    result, posts = gate([check, *CLEAN])
    assert result.stdout.startswith("skip ") and says in result.stdout and posts == []


def test_a_cancelled_check_can_run_again(gate):
    cancelled = status("check", "pending", "make check was cancelled: add the check label")
    assert gate([cancelled, *CLEAN])[0].stdout == "run\n"


def test_a_stale_head_or_closed_pr_does_nothing(gate):
    result, posts = gate(CLEAN, head=NEWER)
    assert result.stdout.startswith("skip a newer push (bbbbbbb) replaced aaaaaaa") and posts == []
    result, posts = gate(CLEAN, pr_state="closed", force=True)
    assert result.stdout == "skip PR #7 is closed\n" and posts == []


def test_the_check_label_runs_it_whatever_the_review_says(gate):
    ran = status("check", "failure", "make check failed")
    for statuses in ([], [ran, status("claude-review", "failure", "x")]):
        result, posts = gate(statuses, [thread()], force=True)
        assert result.stdout == "run\n" and posts == []
    assert gate(CLEAN, head=NEWER, force=True)[0].stdout.startswith("skip a newer push")


@pytest.mark.parametrize("broken", ["pull.json", "statuses.json", "threads.json", "no-write"])
def test_it_fails_when_github_cant_be_read_or_written(gate, broken):
    statuses = CLEAN if broken != "no-write" else []
    result, _ = gate(statuses, broken=[broken])
    assert result.returncode == 3 and "check-gate:" in result.stderr


@pytest.mark.parametrize("args", [[], ["7"], ["x", HEAD], ["7", "abc"], ["7", HEAD, "--now"]])
def test_it_refuses_bad_arguments(args):
    assert run(["bash", str(GATE), *args]).returncode == 2


# --- the workflows ------------------------------------------------------------------------------

SAME = {"head": {"repo": {"full_name": "o/r"}}, "number": 7}
FORK = {"head": {"repo": {"full_name": "stranger/r"}}, "number": 7}
ON, OFF, UNSET = {"SDLC_CHECK_AFTER_REVIEW": "on"}, {"SDLC_CHECK_AFTER_REVIEW": "Off"}, {}


def expr(text: str) -> str:
    text = text.strip()
    if text.startswith("${{"):
        text = text.removeprefix("${{").removesuffix("}}")
    return " ".join(text.split())


def ci_job():
    return load(CI)["jobs"]["check"]


def ctx(event_name, event, variables):
    return {
        "github": {"event_name": event_name, "event": event, "repository": "o/r"},
        "vars": variables,
    }


@pytest.mark.parametrize(
    ("event_name", "event", "variables", "runs", "name"),
    [
        ("pull_request", {"pull_request": SAME}, UNSET, True, "check"),
        ("pull_request", {"pull_request": SAME}, OFF, True, "check"),
        ("pull_request", {"pull_request": SAME}, ON, False, "check (runs after the Claude review)"),
        ("pull_request", {"pull_request": FORK}, ON, True, "check"),
        ("push", {"ref": "refs/heads/main"}, ON, True, "check"),
    ],
    ids=["unset", "off", "on: same-repo PR", "on: fork PR", "on: push to main"],
)
def test_ci_check_hands_same_repo_prs_over_only_when_on(event_name, event, variables, runs, name):
    job = ci_job()
    c = ctx(event_name, event, variables)
    assert bool(gh_expr(expr(job["if"]), c)) is runs
    assert gh_expr(expr(job["name"]), c) == name


def test_a_skipped_ci_check_never_carries_the_required_name():
    # A skipped check run counts as passing for branch protection, so it mustn't be `check`.
    job = ci_job()
    for variables in (ON, OFF, UNSET):
        for event in ({"pull_request": SAME}, {"pull_request": FORK}):
            c = ctx("pull_request", event, variables)
            if not gh_expr(expr(job["if"]), c):
                assert gh_expr(expr(job["name"]), c) != "check"


def gate_if():
    return expr(load(AFTER)["jobs"]["gate"]["if"])


def run_event(repo="o/r", event="pull_request"):
    return {"workflow_run": {"event": event, "head_repository": {"full_name": repo}}}


@pytest.mark.parametrize(
    ("event_name", "event", "variables", "runs"),
    [
        ("workflow_run", run_event(), ON, True),
        ("workflow_run", run_event(), UNSET, False),
        ("workflow_run", run_event(), OFF, False),
        ("workflow_run", run_event("stranger/r"), ON, False),
        ("workflow_run", run_event(event="push"), ON, False),
        ("pull_request", {"pull_request": SAME, "action": "synchronize"}, ON, True),
        ("pull_request", {"pull_request": FORK, "action": "synchronize"}, ON, False),
        (
            "pull_request",
            {"pull_request": SAME, "action": "labeled", "label": {"name": "check"}},
            ON,
            True,
        ),
        (
            "pull_request",
            {"pull_request": SAME, "action": "labeled", "label": {"name": "review"}},
            ON,
            False,
        ),
        (
            "pull_request_review",
            {"pull_request": SAME, "action": "submitted", "review": {"user": {"login": "kieron"}}},
            ON,
            True,
        ),
        (
            "pull_request_review",
            {
                "pull_request": SAME,
                "action": "submitted",
                "review": {"user": {"login": "claude[bot]"}},
            },
            ON,
            False,
        ),
        (
            "pull_request_review_comment",
            {"pull_request": SAME, "action": "created", "comment": {"user": {"login": "kieron"}}},
            ON,
            True,
        ),
        (
            "pull_request_review_comment",
            {
                "pull_request": SAME,
                "action": "created",
                "comment": {"user": {"login": "claude[bot]"}},
            },
            ON,
            False,
        ),
    ],
    ids=[
        "review finished",
        "unset",
        "off",
        "fork review",
        "not a PR's review",
        "new push",
        "fork push",
        "check label",
        "another label",
        "a person's review",
        "the reviewer's own review",
        "a reply",
        "the reviewer's own comment",
    ],
)
def test_the_gate_runs_on_same_repo_prs_only_and_only_when_on(event_name, event, variables, runs):
    assert bool(gh_expr(gate_if(), ctx(event_name, event, variables))) is runs


def test_a_new_head_cancels_the_old_heads_check_and_nothing_else_does():
    jobs = load(AFTER)["jobs"]
    group = expr(jobs["gate"]["concurrency"]["group"])
    # format() isn't in gh_expr: read which group each event joins from the text instead.
    assert group.startswith(
        "github.event_name == 'pull_request' && github.event.action != 'labeled' &&"
    )
    assert "format('check-after-review-{0}', github.event.pull_request.number)" in group
    assert group.endswith("|| format('check-gate-{0}', github.run_id)")
    assert jobs["check"]["concurrency"] == {
        "group": "check-after-review-${{ needs.gate.outputs.pr }}",
        "cancel-in-progress": True,
    }
    assert jobs["gate"]["concurrency"]["cancel-in-progress"] is True


def steps(job):
    return {
        s.get("name") or s.get("uses") or s["run"]: s for s in load(AFTER)["jobs"][job]["steps"]
    }


def test_pr_code_runs_with_no_github_token():
    check = steps("check")
    for name, step in check.items():
        if "uses" in step:
            assert (
                step.get("with", {}).get("persist-credentials") is False
                or "setup-stack" in step["uses"]
            ), name
        if "GH_TOKEN" in step.get("env", {}):
            assert not re.search(r"^\s*make |\.sdlc/|\./", step["run"], re.M), name
    job = load(AFTER)["jobs"]["check"]
    assert "GH_TOKEN" not in job.get("env", {})
    assert steps("gate")["actions/checkout@v4"]["with"]["persist-credentials"] is False


def test_check_tests_the_merge_of_the_gated_head_and_posts_the_status():
    check = steps("check")
    assert (
        check["actions/checkout@v4"]["with"]["ref"]
        == "refs/pull/${{ needs.gate.outputs.pr }}/merge"
    )
    assert '[[ "$parent" == "$HEAD_SHA" ]]' in check["Check the merge is of this head"]["run"]
    assert check["make check"]["run"] == "make check"
    post = check["Post the result"]
    assert post["if"] == "always()"
    for line in ("state=success", "state=failure", "make check was cancelled: add the check label"):
        assert line in post["run"]
    assert "-f context=check" in post["run"]
    assert 'description="make check is running"' in check["Mark check as running"]["run"]
    # The gate script skips a head whose `check` says exactly this.
    assert 'RUNNING="make check is running"' in GATE.read_text()


def test_the_gate_feeds_the_script_and_the_label_forces_it():
    gate = steps("gate")
    assert (
        '.sdlc/scripts/check-gate.sh "$PR" "$HEAD_SHA" $FORCE'
        in gate["Is the review clean?"]["run"]
    )
    assert (
        gate["Is the review clean?"]["env"]["FORCE"]
        == "${{ github.event.action == 'labeled' && '--force' || '' }}"
    )
    assert "labels/check" in gate["Clear the check label"]["run"]
    on = load(AFTER)["on"]
    assert on["workflow_run"] == {"workflows": ["Claude review"], "types": ["completed"]}
    review = load(REPO / ".github/workflows/sdlc-claude-review.yml")
    assert review["name"] == "Claude review", "workflow_run names the review workflow"


def test_every_job_runs_on_sdlc_runner():
    text = AFTER.read_text()
    assert [line.strip() for line in text.splitlines() if line.strip().startswith("runs-on:")] == [
        RUNS_ON,
        RUNS_ON,
    ]


def test_the_setting_is_listed_and_documented():
    assert '"variable SDLC_CHECK_AFTER_REVIEW"' in (REPO / ".sdlc/scripts/sync-sdlc.sh").read_text()
    settings = (REPO / ".sdlc/docs/settings.md").read_text()
    row = next(
        line for line in settings.splitlines() if line.startswith("| `SDLC_CHECK_AFTER_REVIEW`")
    )
    assert "`on`, `off`" in row and "sdlc-check-after-review.yml" in row and "`check` label" in row
    assert "SDLC_CHECK_AFTER_REVIEW" in (REPO / ".sdlc/docs/self-hosted-runner.md").read_text()


def test_the_gate_script_is_executable_in_git():
    out = run(["git", "ls-files", "-s", str(GATE.relative_to(REPO))]).stdout
    assert out.startswith("100755"), out
