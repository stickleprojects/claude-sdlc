"""The handling-line evals (#289) without a model: the setup builds PR 41 with either body, and
the check passes a summary that follows the rule and fails one that breaks it, such as the line
PR #284's review wrote."""

import json
import os
from pathlib import Path

import pytest

from conftest import REPO, git, run

TASKS = {
    "clean": REPO / "evals/tasks/review-clean-pr-has-no-handling-line.json",
    "unexplained": REPO / "evals/tasks/review-issues-repo-names-no-command.json",
}
CHECK = REPO / "evals/checks/handling-line.sh"
OLD_LINE = (
    "Handling: the engineer runs `/sdlc-pr 41` in Claude Code (no "
    "`.claude/skills/sdlc-pr/SKILL.md` here, so it follows `.sdlc/skills/pr/SKILL.md`)."
)


def setup(tmp_path: Path, variant: str) -> Path:
    task = json.loads(TASKS[variant].read_text())
    assert task["check"].endswith(f'handling-line.sh" {variant}')
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals/fixtures").symlink_to(REPO / "evals/fixtures")
    result = run(["bash", "-c", task["setup"]], cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    return tmp_path


def check(work: Path, variant: str, summary: str):
    (work / "summary.md").write_text(summary)
    return run(["bash", str(CHECK), variant], cwd=work, env={**os.environ, "EVAL_ROOT": str(REPO)})


@pytest.mark.parametrize("variant", ["clean", "unexplained"])
def test_the_setup_builds_the_pr(tmp_path, variant):
    repo = setup(tmp_path, variant) / "handling"
    assert git(repo, "branch", "--show-current") == "fix/greeting-space"
    assert "Change tracking: issues" in (repo / "CLAUDE.md").read_text()
    assert json.loads((repo / ".review-threads.json").read_text()) == []
    body = (repo / "pr-body.md").read_text()
    assert ("Closes #7" in body) == (variant == "clean")
    # The fix is right, so the clean PR has nothing to find: its test passes.
    test = run(
        ["python3", "-c", "from app.greet import greet; assert greet('Ana') == 'Hello, Ana'"],
        cwd=repo,
    )
    assert test.returncode == 0, test.stderr


CLEAN = (
    "**Review of #41**\n\n- Findings: 0 Important, 0 Nit.\n\n"
    "<!-- review-findings: important=0 nit=0 -->\n"
)
UNEXPLAINED = (
    "**Review of #41**\n\n- Findings: 1 Important, 0 Nit.\n"
    "- The PR body links no issue and doesn't say how it was tested ([thread](x)).\n\n"
    "Handling: ask Claude Code to work through PR 41's findings.\n\n"
    "<!-- review-findings: important=1 nit=0 -->\n"
)


@pytest.mark.parametrize(("variant", "summary"), [("clean", CLEAN), ("unexplained", UNEXPLAINED)])
def test_a_summary_that_follows_the_rule_passes(tmp_path, variant, summary):
    work = setup(tmp_path, variant)
    result = check(work, variant, summary)
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    ("variant", "summary", "why"),
    [
        # PR #284's line, which main's REVIEW.md asks for, fails both.
        ("clean", CLEAN.replace("\n\n<!--", f"\n\n{OLD_LINE}\n\n<!--"), "/sdlc- command"),
        (
            "unexplained",
            UNEXPLAINED.replace(
                "Handling: ask Claude Code to work through PR 41's findings.", OLD_LINE
            ),
            "/sdlc- command",
        ),
        (
            "clean",
            CLEAN.replace(
                "\n\n<!--",
                "\n\nHandling: ask Claude Code to work through PR 41's findings.\n\n<!--",
            ),
            "how-to-handle line",
        ),
        ("clean", CLEAN.replace("nit=0", "nit=1"), "the eval needs none"),
        ("unexplained", UNEXPLAINED.replace("important=1", "important=0"), "wasn't raised"),
        (
            "unexplained",
            UNEXPLAINED.replace(
                "Handling: ask Claude Code to work through PR 41's findings.\n\n", ""
            ),
            "no line asks",
        ),
        (
            "unexplained",
            UNEXPLAINED.replace("<!-- review-findings: important=1 nit=0 -->\n", ""),
            "no hidden count",
        ),
    ],
)
def test_a_summary_that_breaks_the_rule_fails(tmp_path, variant, summary, why):
    work = setup(tmp_path, variant)
    result = check(work, variant, summary)
    assert result.returncode == 1 and why in result.stdout, result.stdout


def test_the_check_needs_a_summary(tmp_path):
    work = setup(tmp_path, "clean")
    result = run(["bash", str(CHECK), "clean"], cwd=work)
    assert result.returncode == 1 and "no summary.md" in result.stdout
