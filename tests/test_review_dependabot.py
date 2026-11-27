"""A Dependabot PR gets no AI review, and says so: its diff is a tag and a SHA, and the action
refuses a bot that isn't allowed and gets no secrets on such a run (#143)."""

import os

import pytest

from conftest import REPO, run
from test_check_after_review import load

REVIEW = REPO / ".github/workflows/sdlc-claude-review.yml"


def steps():
    return {s.get("name") or s.get("uses"): s for s in load(REVIEW)["jobs"]["review"]["steps"]}


def note_step(tmp_path, author, action, changed=""):
    """Run the 'Note when the AI review can't run' step; return (outputs, gh calls)."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    calls = tmp_path / "gh-calls"
    (bin_ / "gh").write_text(f'#!/usr/bin/env bash\necho "$*" >> {calls}\n')
    (bin_ / "gh").chmod(0o755)
    (bin_ / "git").write_text(f"#!/usr/bin/env bash\nprintf '%s' '{changed}'\n")
    (bin_ / "git").chmod(0o755)
    script = (
        steps()["Note when the AI review can't run"]["run"]
        .replace("${{ github.event.action }}", action)
        .replace("${{ github.event.pull_request.base.sha }}", "base")
    )
    out = tmp_path / "out"
    out.touch()
    env = {
        "PATH": f"{bin_}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(out),
        "GITHUB_REPOSITORY": "o/r",
        "PR": "7",
        "AUTHOR": author,
        "BEFORE": "before",
    }
    result = run(["bash", "-c", script], env=env)
    assert result.returncode == 0, result.stderr
    return out.read_text(), calls.read_text() if calls.exists() else ""


@pytest.mark.parametrize("action,comments", [("opened", True), ("synchronize", False)])
def test_a_dependabot_pr_is_skipped_and_says_so_once(tmp_path, action, comments):
    outputs, gh = note_step(tmp_path, "dependabot[bot]", action)
    assert "skipped=true" in outputs and "why=dependabot" in outputs
    assert ("Dependabot update" in gh) is comments


def test_a_persons_pr_is_not_skipped(tmp_path):
    outputs, gh = note_step(tmp_path, "kieron", "opened", changed="src/app.py")
    assert outputs == "" and gh == ""


def test_the_review_action_never_runs_for_dependabot_and_the_status_says_why():
    review = steps()["Review"]
    assert review["if"] == "steps.workflow_change.outputs.why != 'dependabot'"
    done = steps()["Mark the review as done"]
    assert done["env"]["WHY"] == "${{ steps.workflow_change.outputs.why }}"
    assert '"$WHY" == dependabot' in done["run"] and "Dependabot update" in done["run"]
