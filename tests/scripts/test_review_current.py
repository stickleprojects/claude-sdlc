import json
import os

import pytest

from conftest import REPO, run

from .helpers import FAKE_GH_REVIEW_CURRENT, sha, synced


@pytest.fixture
def review_current(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_REVIEW_CURRENT)
    (fake / "gh").chmod(0o755)

    def go(
        commits, statuses, post_fails=False, runs=(), head_ref="", pr_head=None, cancel_fails=False
    ):
        for f in tmp_path.glob("status-*"):
            f.unlink()
        for name in ("posted", "post-fails", "calls", "cancel-fails", "cancelled"):
            (tmp_path / name).unlink(missing_ok=True)
        (tmp_path / "commits").write_text("".join(f"{sha(c)}\n" for c in commits))
        for c, states in statuses.items():
            entries = [{"context": ctx, "state": st} for ctx, st in states]
            (tmp_path / f"status-{sha(c)}").write_text(json.dumps(entries))
        if post_fails:
            (tmp_path / "post-fails").write_text("")
        (tmp_path / "runs").write_text(json.dumps({"workflow_runs": list(runs)}))
        (tmp_path / "pull").write_text(json.dumps({"head": {"sha": sha(pr_head or commits[-1])}}))
        if cancel_fails:
            (tmp_path / "cancel-fails").write_text("")
        result = run(
            ["bash", str(REPO / ".sdlc/scripts/review-current.sh"), "7", sha(commits[-1])],
            env={
                "PATH": f"{fake}:{os.environ['PATH']}",
                "D": str(tmp_path),
                "GITHUB_REPOSITORY": "o/r",
                "HEAD_REF": head_ref,
            },
        )
        cancelled = tmp_path / "cancelled"
        result.cancelled = cancelled.read_text().split() if cancelled.exists() else []
        posted = tmp_path / "posted"
        return result, posted.read_text() if posted.exists() else None

    return go


def test_review_current_marks_commits_after_the_review_as_not_reviewed(review_current):
    # jobhunt-app#7: requirements pushed after the review merged unreviewed.
    result, posted = review_current([1, 2, 3, 4], {2: [("claude-review", "success")]})
    assert result.returncode == 0, result.stderr
    assert f"repos/o/r/statuses/{sha(4)}" in posted
    assert "-f state=pending" in posted and "-f context=claude-review" in posted
    assert "Not reviewed: 2 commits since the review of 0000000. Add the review label" in posted


def test_review_current_counts_one_commit_without_a_plural(review_current):
    _, posted = review_current([1, 2], {1: [("claude-review", "success")]})
    assert "Not reviewed: 1 commit since the review of" in posted


def test_review_current_uses_the_newest_review_status_of_each_commit(review_current):
    # Statuses come newest first: a later failure on a commit replaces an earlier success.
    _, posted = review_current(
        [1, 2, 3],
        {
            1: [("claude-review", "success")],
            2: [("claude-review", "failure"), ("claude-review", "success")],
        },
    )
    assert "2 commits since the review of" in posted


def test_review_current_says_when_nothing_was_reviewed(review_current):
    _, posted = review_current([1, 2], {1: [("check", "success")]})
    assert "Not reviewed yet: add the review label" in posted


@pytest.mark.parametrize("state", ["pending", "success", "failure"])
def test_review_current_leaves_a_commit_that_has_a_review_status(review_current, state):
    # A review running on the push (auto-merge on, or the label added already) owns it.
    result, posted = review_current([1, 2], {2: [("claude-review", state)]})
    assert result.returncode == 0 and posted is None
    assert "already has a claude-review status" in result.stdout


def test_review_current_fails_when_it_cant_post(review_current):
    result, _ = review_current([1, 2], {}, post_fails=True)
    assert result.returncode == 1 and "can't post" in result.stderr


def run_of(n, status="in_progress", branch="b", repo="o/r", id=1):
    return {
        "id": id,
        "status": status,
        "head_branch": branch,
        "head_sha": sha(n),
        "head_repository": {"full_name": repo},
    }


def test_a_push_cancels_only_reviews_of_its_branchs_older_commits(review_current):
    runs = [
        run_of(1, id=11),
        run_of(9, "queued", id=12),  # force-pushed away
        run_of(2, id=13),  # the pushed commit's own
        run_of(1, "completed", id=14),
        run_of(1, branch="other", id=15),
        run_of(1, repo="fork/r", id=16),
    ]
    result, posted = review_current([1, 2], {1: []}, runs=runs, head_ref="b")
    assert result.returncode == 0 and "state=pending" in posted
    assert result.cancelled == ["11", "12"]


def test_nothing_is_cancelled_when_it_shouldnt_be(review_current):
    runs = [run_of(1, id=11)]
    newer, _ = review_current([1, 2], {}, runs=runs, head_ref="b", pr_head=3)
    assert newer.cancelled == [], "a newer push's review isn't older"
    assert review_current([1, 2], {}, runs=runs)[0].cancelled == [], "no HEAD_REF"
    own = {2: [("claude-review", "pending")]}
    assert review_current([1, 2], own, runs=runs, head_ref="b")[0].cancelled == []


def test_a_cancel_that_fails_doesnt_fail_the_push(review_current):
    result, posted = review_current(
        [1, 2], {}, runs=[run_of(1, id=11)], head_ref="b", cancel_fails=True
    )
    assert result.returncode == 0 and "state=pending" in posted
    assert "couldn't cancel run 11" in result.stdout


def test_review_current_usage():
    assert run(["bash", ".sdlc/scripts/review-current.sh", "7"]).returncode == 2
    assert run(["bash", ".sdlc/scripts/review-current.sh", "x", sha(1)]).returncode == 2


def test_unreviewed_pushes_are_marked_when_the_review_doesnt_run():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    job = workflow[workflow.index("\n  unreviewed-push:") :]
    # The exact complement of the review job's push condition: off means the review skips it.
    assert "github.event.action == 'synchronize'" in job
    assert "(vars.SDLC_AUTO_MERGE == '' || vars.SDLC_AUTO_MERGE == 'off')" in job
    assert "github.event.pull_request.head.repo.full_name == github.repository" in job
    assert '.sdlc/scripts/review-current.sh "$PR" "$HEAD_SHA"' in job
    assert "actions: write" in job and "HEAD_REF: ${{ github.event.pull_request.head.ref" in job
    assert "claude-code-action" not in job and "secrets." not in job, "no model, no secrets"
    for script in ("review-current.sh", "check-pr-title.sh"):
        assert synced(f".sdlc/scripts/{script}"), script
