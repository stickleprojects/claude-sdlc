from pathlib import Path

import pytest

from conftest import REPO


def test_a_merge_of_the_base_with_the_same_diff_keeps_the_review(base_merge):
    git_, reviewed, go = base_merge
    git_("merge", "-q", "--no-edit", "main")
    result, posted = go(git_("rev-parse", "HEAD"))
    assert result.returncode == 0, result.stderr
    assert "state=success" in posted, posted
    assert f"The Claude review of {reviewed[:7]} still holds: only main was merged in" in posted


def test_a_merge_that_changes_the_prs_diff_still_needs_a_review(base_merge):
    git_, _, go = base_merge
    git_("merge", "-q", "--no-commit", "main")
    (Path(git_("rev-parse", "--show-toplevel")) / "app.py").write_text("a = 3\n")  # slipped in
    git_("add", "app.py")
    git_("commit", "-qm", "merge main, and a change")
    _, posted = go(git_("rev-parse", "HEAD"))
    assert "state=pending" in posted and "Not reviewed: 1 commit since the review" in posted


def test_a_plain_commit_after_the_review_still_needs_one(base_merge):
    git_, _, go = base_merge
    (Path(git_("rev-parse", "--show-toplevel")) / "app.py").write_text("a = 4\n")
    git_("commit", "-qam", "another change")
    _, posted = go(git_("rev-parse", "HEAD"))
    assert "state=pending" in posted


@pytest.mark.parametrize("base_ref", [None, "no-such-branch"])
def test_without_a_readable_base_every_push_needs_a_review(base_merge, base_ref):
    git_, _, go = base_merge
    git_("merge", "-q", "--no-edit", "main")
    _, posted = go(git_("rev-parse", "HEAD"), base_ref=base_ref)
    assert "state=pending" in posted


def test_the_unreviewed_push_job_gives_the_script_the_base_and_history():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    job = workflow[workflow.index("  unreviewed-push:") :]
    assert "BASE_REF: ${{ github.event.pull_request.base.ref }}" in job
    assert "fetch-depth: 0" in job
