from conftest import REPO, run

# --- bootstrap -------------------------------------------------------------------------


def test_bootstrap_help_and_bad_args():
    assert run([".sdlc/scripts/bootstrap-github.sh", "--help"]).returncode == 0
    assert run([".sdlc/scripts/bootstrap-github.sh", "--bogus"]).returncode == 2


def test_bootstrap_creates_the_review_label_the_workflow_listens_for():
    script = (REPO / ".sdlc/scripts/bootstrap-github.sh").read_text()
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    assert "\nreview|" in script
    assert "github.event.label.name == 'review'" in workflow


def test_review_runs_on_every_push_only_with_auto_merge():
    # Each review uses subscription limits (#11). With auto-merge on, `review` is a required
    # check, and required checks belong to the head commit, so then every push needs one (#89).
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    assert "types: [opened, ready_for_review, labeled, synchronize]" in workflow
    assert "(github.event.action != 'synchronize' ||" in workflow
    assert "(vars.SDLC_AUTO_MERGE != '' && vars.SDLC_AUTO_MERGE != 'off'))" in workflow


def test_review_runs_once_per_pr_at_a_time():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    job = workflow.split("\njobs:", 1)[1]
    assert "group: claude-review-${{ github.event.pull_request.number }}" in job
    assert "cancel-in-progress: true" in job
    assert "\nconcurrency:" not in workflow, "workflow-level: any label would cancel a review"


def test_review_clears_its_label_through_the_rest_api():
    # `gh pr edit` fails in orgs hit by the Projects (classic) GraphQL deprecation.
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    assert "gh pr edit" not in workflow
    assert 'gh api -X DELETE "repos/$GITHUB_REPOSITORY/issues/$PR/labels/review"' in workflow
