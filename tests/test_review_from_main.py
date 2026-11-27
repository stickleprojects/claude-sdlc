"""ADR 0001 (#293): the Claude review runs main's copy of its workflow on pull_request_target,
and never runs the PR's code. The rules for that privileged job, the transition workflow for the
PR that crosses over, and the run-name contract the gate and scripts read."""

import base64
import json
import os
import re
import subprocess

import pytest

from conftest import REPO, run
from scripts.helpers import gh_expr
from test_check_after_review import AFTER, ON, ctx, expr, load

REVIEW = REPO / ".github/workflows/sdlc-claude-review.yml"
TRANSITION = REPO / ".github/workflows/sdlc-claude-review-transition.yml"
FORK_GUARD = "github.event.pull_request.head.repo.full_name == github.repository"
RUN_NAME = (
    "Claude review of #${{ github.event.pull_request.number }} "
    "at ${{ github.event.pull_request.head.sha }}"
)


def jobs():
    return load(REVIEW)["jobs"]


def test_the_review_runs_mains_copy_and_names_what_it_reviews():
    workflow = load(REVIEW)
    assert list(workflow["on"]) == ["pull_request_target"]
    assert workflow["run-name"] == RUN_NAME


@pytest.mark.parametrize("job", ["review", "unreviewed-push"])
def test_the_privileged_job_never_runs_the_prs_code(job):
    """The ADR's rules: each fails the test on its own."""
    spec = jobs()[job]
    assert FORK_GUARD in spec["if"], "a fork's PR must run no step"
    for step in spec["steps"]:
        uses = step.get("uses", "")
        if uses.startswith("./"):
            assert not uses.startswith("./pr"), f"a local action from the PR: {uses}"
        assert step.get("working-directory", "").split("/")[0] != "pr", step
        assert not re.search(r"(^|[\s\"'=(])\.?/?pr/", step.get("run", "")), (
            f"a run step reads or runs the PR's checkout: {step.get('name')}"
        )
        if uses.startswith("actions/checkout@") and "head" in str(step.get("with", {})):
            assert step["with"].get("path") == "pr", step
            assert step["with"].get("persist-credentials") is False, step


def test_the_prs_head_is_checked_out_as_data_only():
    checkouts = [
        s for s in jobs()["review"]["steps"] if s.get("uses", "").startswith("actions/checkout@")
    ]
    root, pr = checkouts
    assert "ref" not in root.get("with", {}), "the root is main, as pull_request_target checks out"
    assert pr["with"] == {
        "ref": "${{ github.event.pull_request.head.sha }}",
        "path": "pr",
        "persist-credentials": False,
    }


def test_the_ci_change_thread_comes_before_the_review_reads_the_threads():
    names = [s.get("name") or s.get("uses") for s in jobs()["review"]["steps"]]
    ask = names.index("Ask a person to approve a CI change")
    assert names.index("Fetch the PR's commits") < ask < names.index("Read the review threads")
    step = jobs()["review"]["steps"][ask]
    assert step["run"].strip() == '.sdlc/scripts/ci-change-thread.sh "$PR" "$BASE" "$HEAD_SHA"'
    assert "if" not in step and "continue-on-error" not in step, "never skipped, fails closed"


def test_both_prompts_point_the_review_at_pr():
    text = REVIEW.read_text()
    assert text.count("are under pr/: review those") == 2
    assert text.count('"CI change: needs approval" is this job\'s own: never post one') == 2
    assert "sdlc-claude-*.yml" not in text and "(sdlc-)?claude-" not in text


# --- the transition workflow -------------------------------------------------------------------


def test_the_transition_runs_the_prs_copy_only_for_a_review_change():
    workflow = load(TRANSITION)
    assert list(workflow["on"]) == ["pull_request"]
    assert workflow["on"]["pull_request"]["paths"] == [".github/workflows/sdlc-claude-review.yml"]
    assert workflow["name"] == "Claude review", "so the gate's workflow_run sees it"
    job = workflow["jobs"]["transition"]
    assert FORK_GUARD in job["if"] and "${{ secrets." not in TRANSITION.read_text()


def transition(tmp_path, main_copy, action="opened"):
    """Run the transition step against a fake gh serving main's copy of the review workflow."""
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    calls = tmp_path / "calls"
    calls.unlink(missing_ok=True)
    content = json.dumps(base64.b64encode(main_copy.encode()).decode()) if main_copy else ""
    (fake / "gh").write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> {calls}\n'
        'if [[ "$2" == *"/contents/"* ]]; then\n'
        f"  {'echo ' + content if content else 'exit 1'}\n"
        "fi\n"
    )
    (fake / "gh").chmod(0o755)
    step = load(TRANSITION)["jobs"]["transition"]["steps"][0]["run"]
    script = step.replace("${{ github.event.action }}", action)
    env = {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "o/r",
        "PR": "7",
        "HEAD_SHA": "a" * 40,
        "BASE_SHA": "b" * 40,
    }
    result = run(["bash", "-c", script], env=env)
    assert result.returncode == 0, result.stderr
    return result, calls.read_text() if calls.exists() else ""


def old_review():
    """Main's copy before ADR 0001 (#305's merge), which listens to pull_request."""
    return subprocess.run(
        ["git", "show", "4d840eb:.github/workflows/sdlc-claude-review.yml"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_the_transition_marks_the_crossing_pr_for_a_review_by_hand(tmp_path):
    for main_copy in (old_review(), ""):  # the old review, or none at all
        _, calls = transition(tmp_path, main_copy)
        assert f"statuses/{'a' * 40} --silent -f state=success -f context=claude-review" in calls
        assert "a code owner reviews it by hand" in calls and "issues/7/comments" in calls
    _, calls = transition(tmp_path, old_review(), action="synchronize")
    assert "state=success" in calls and "issues/7/comments" not in calls, "says so once"


def test_the_transition_does_nothing_once_main_runs_on_pull_request_target(tmp_path):
    result, calls = transition(tmp_path, REVIEW.read_text())
    assert "nothing to do" in result.stdout and "statuses/" not in calls


# --- the run-name contract ---------------------------------------------------------------------


def gate_find(tmp_path, title, from_repo="o/r"):
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    (fake / "gh").write_text(f"#!/usr/bin/env bash\necho {from_repo}\n")
    (fake / "gh").chmod(0o755)
    step = next(s for s in load(AFTER)["jobs"]["gate"]["steps"] if s.get("id") == "pr")
    out = tmp_path / "out"
    out.write_text("")
    env = {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_OUTPUT": str(out),
        "EVENT": "workflow_run",
        "RUN_EVENT": "pull_request_target",
        "RUN_TITLE": title,
        "RUN_HEAD": "f" * 40,  # main's head: never the one gated
        "RUN_NAME": "Claude review",
    }
    result = run(["bash", "-c", step["run"]], env=env)
    assert result.returncode == 0, result.stderr
    return dict(line.split("=", 1) for line in out.read_text().split())


def test_the_gate_reads_the_pr_and_reviewed_head_from_the_run_name(tmp_path):
    head = "c" * 40
    title = RUN_NAME.replace("${{ github.event.pull_request.number }}", "12").replace(
        "${{ github.event.pull_request.head.sha }}", head
    )
    assert gate_find(tmp_path, title) == {"pr": "12", "head": head}
    assert gate_find(tmp_path, title, from_repo="stranger/r") == {"pr": "", "head": ""}
    assert gate_find(tmp_path, "Some other title") == {"pr": "", "head": ""}


def test_the_gate_takes_a_pull_request_target_run():
    run_ = {
        "workflow_run": {
            "event": "pull_request_target",
            "name": "Claude review",
            "conclusion": "success",
            "head_repository": {"full_name": "o/r"},
        }
    }
    gate_if = expr(load(AFTER)["jobs"]["gate"]["if"])
    assert gh_expr(gate_if, ctx("workflow_run", run_, ON))


def test_every_reader_of_the_run_name_uses_its_one_form():
    prefix = "Claude review of #"
    for path in (
        ".sdlc/scripts/request-review.sh",
        ".sdlc/scripts/review-current.sh",
        ".github/workflows/sdlc-check-after-review.yml",
    ):
        text = (REPO / path).read_text()
        assert prefix in text or r"Claude\ review\ of\ \#" in text, path
        assert " at " in text, path


def test_the_review_posts_with_the_jobs_token_not_the_claude_apps():
    """ADR 0001's amendment: Anthropic's token exchange refuses pull_request_target
    (anthropics/claude-code-action#713), so each review step passes the job's token and the
    workflow asks for no OIDC token."""
    workflow = load(REVIEW)
    assert "id-token" not in workflow["permissions"]
    steps = [s for s in jobs()["review"]["steps"] if "claude-code-action" in s.get("uses", "")]
    assert len(steps) == 2, "the review and its retry"
    for step in steps:
        token = step["with"]["github_token"]
        assert token == "${{ github.token }}", step["name"]  # noqa: S105 (an expression, not a secret)
