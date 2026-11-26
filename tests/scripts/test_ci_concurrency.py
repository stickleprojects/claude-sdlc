import re

import pytest

from conftest import REPO
from test_check_after_review import load

from .helpers import gh_expr

# --- #138: a new push to a PR cancels its stale CI and title runs; main never cancels ----------


def concurrency(workflow):
    """The workflow-level concurrency block's group and cancel-in-progress expressions."""
    text = (REPO / ".github/workflows" / workflow).read_text()
    block = re.search(r"^concurrency:\n  group: (.+)\n  cancel-in-progress: (.+)$", text, re.M)
    assert block, f"{workflow} has no workflow-level concurrency block"
    strip = lambda s: s.removeprefix("${{").removesuffix("}}").strip()  # noqa: E731
    return block.group(1), strip(block.group(2))


def group(template, ctx):
    return re.sub(r"\$\{\{(.+?)\}\}", lambda m: str(gh_expr(m.group(1).strip(), ctx)), template)


PR_PUSH = {
    "github": {
        "event_name": "pull_request",
        "ref": "refs/pull/7/merge",
        "event": {"pull_request": {"number": 7}},
    }
}
MAIN_PUSH = {
    "github": {"event_name": "push", "ref": "refs/heads/main", "sha": "abc123", "event": {}}
}


def test_ci_cancels_a_prs_stale_run_but_never_one_on_main():
    group_expr, cancel = concurrency("sdlc-ci.yml")
    assert group(group_expr, PR_PUSH) == "ci-7"
    assert gh_expr(cancel, PR_PUSH) is True
    # Every commit on main gets its own result. A group keeps one pending run, and a newer one
    # replaces it even without cancel-in-progress, so each push to main has a group of its own.
    assert group(group_expr, MAIN_PUSH) == "ci-abc123"
    assert gh_expr(cancel, MAIN_PUSH) is False
    next_merge = {"github": {**MAIN_PUSH["github"], "sha": "def456"}}
    assert group(group_expr, next_merge) != group(group_expr, MAIN_PUSH)
    # Two PRs never share a group, so one PR's push can't cancel another's CI.
    other = {"github": {**PR_PUSH["github"], "event": {"pull_request": {"number": 8}}}}
    assert group(group_expr, other) != group(group_expr, PR_PUSH)


def test_pr_title_cancels_the_older_check_on_the_same_pr():
    group_expr, cancel = concurrency("sdlc-pr-title.yml")
    assert group(group_expr, PR_PUSH) == "pr-title-7"
    assert cancel == "true"
    on = (REPO / ".github/workflows/sdlc-pr-title.yml").read_text()
    assert "\n  push:" not in on  # only PR events, so cancelling never touches main


# --- #283: one reply in a thread runs the descope check once, and nothing cancels it ------------


def descopes_job():
    workflow = load(REPO / ".github/workflows/sdlc-descopes.yml")
    assert "concurrency" not in workflow, "a skipped run mustn't take the group's turn"
    return workflow["jobs"]["descopes"]


def review(state, body, user="User"):
    return "pull_request_review", {"review": {"state": state, "body": body, "user": {"type": user}}}


def reply(user="User"):
    return "pull_request_review_comment", {"comment": {"user": {"type": user}}}


@pytest.mark.parametrize(
    ("event", "runs"),
    [
        (reply(), True),
        (review("commented", None), False),
        (review("commented", ""), False),
        (review("commented", "Approved: Kieron"), True),
        (review("approved", None), True),
        (review("changes_requested", None), True),
        (review("dismissed", None), True),
        (reply("Bot"), False),
        (review("commented", None, "Bot"), False),
        (review("approved", "ok", "Bot"), False),
    ],
)
@pytest.mark.parametrize("same_repo", [True, False])
def test_which_events_run_the_descope_check(event, runs, same_repo):
    name, payload = event
    head = {"repo": {"full_name": "o/r" if same_repo else "fork/r"}}
    payload = {**payload, "pull_request": {"number": 7, "head": head}}
    ctx = {"github": {"event_name": name, "repository": "o/r", "event": payload}}
    assert bool(gh_expr(" ".join(descopes_job()["if"].split()), ctx)) is (runs and same_repo)


def test_a_descope_check_is_never_cancelled():
    concurrency = descopes_job()["concurrency"]
    assert concurrency["cancel-in-progress"] is False
    assert group(concurrency["group"], PR_PUSH) == "descopes-7"
