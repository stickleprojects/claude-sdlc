"""The earlier-notes eval (#242) without a model: its setup builds the PR, and its check passes
a summary that marks each earlier note right and fails one that drops or mis-marks a note."""

import json
import os
from pathlib import Path

import pytest

from conftest import REPO, git, run

TASK = REPO / "evals/tasks/review-marks-earlier-summary-notes.json"
CHECK = REPO / "evals/checks/earlier-notes.sh"


@pytest.fixture
def work(tmp_path) -> Path:
    setup = json.loads(TASK.read_text())["setup"]
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir()
    (evals_dir / "fixtures").symlink_to(REPO / "evals/fixtures")
    result = run(["bash", "-c", setup], cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    return tmp_path


def sha(work: Path) -> str:
    return git(work / "notes", "rev-parse", "--short=7", "HEAD")


def check(work: Path, summary: str):
    (work / "summary.md").write_text(summary)
    return run(["bash", str(CHECK)], cwd=work, env={**os.environ, "EVAL_ROOT": str(REPO)})


def good(work: Path) -> str:
    return f"""**Review of #31** (CSV export)

- Findings: 0 Important, 0 Nit.
- Earlier notes:
  - ✅ The PR body said semicolons; the code writes commas — PR body updated
  - ✅ CHANGELOG.md had no entry for the export — addressed in {sha(work)}
  - ⬜ The product owner's approval is needed before this merges — still open

<!-- review-findings: important=0 nit=0 -->
"""


def test_the_setup_writes_what_the_workflow_writes(work):
    notes = work / "notes"
    earlier = (notes / ".review-earlier-summary.md").read_text()
    assert earlier.startswith("# The summary this review replaces\n")
    assert "semicolon-separated" in earlier and "<!-- review-findings:" in earlier
    assert f"{sha(work)} " in earlier.split("# The PR's commits")[1], (
        "the changelog commit is listed"
    )
    assert json.loads((notes / ".review-threads.json").read_text()) == []
    assert "comma-separated" in (notes / "pr-body.md").read_text()
    assert git(notes, "branch", "--show-current") == "feat/csv-export"


def test_a_summary_that_marks_each_note_passes(work):
    result = check(work, good(work))
    assert result.returncode == 0, result.stdout
    assert f"the CHANGELOG one with {sha(work)}" in result.stdout


@pytest.mark.parametrize(
    ("edit", "why"),
    [
        (lambda s, h: s.replace("✅ The PR body", "⬜ The PR body"), "isn't marked addressed"),
        (lambda s, h: s.replace(f"addressed in {h}", "addressed"), "doesn't name the commit"),
        (
            lambda s, h: s.replace("⬜ The product owner", "✅ The product owner"),
            "isn't marked still open",
        ),
        (
            lambda s, h: "\n".join(ln for ln in s.splitlines() if "CHANGELOG" not in ln),
            "CHANGELOG note was dropped",
        ),
        (
            lambda s, h: "\n".join(ln for ln in s.splitlines() if "product owner" not in ln),
            "approval note was dropped",
        ),
        (
            lambda s, h: "\n".join(ln for ln in s.splitlines() if "PR body" not in ln),
            "PR body note was dropped",
        ),
        (lambda s, h: s.replace("✅", "-").replace("⬜", "-"), "no note is marked"),
    ],
    ids=[
        "body open",
        "no sha",
        "approval ticked",
        "changelog dropped",
        "approval dropped",
        "body dropped",
        "unmarked",
    ],
)
def test_a_summary_that_drops_or_mis_marks_a_note_fails(work, edit, why):
    result = check(work, edit(good(work), sha(work)))
    assert result.returncode == 1 and why in result.stdout, result.stdout


def test_no_summary_fails(work):
    result = run(["bash", str(CHECK)], cwd=work)
    assert result.returncode == 1 and "no summary.md" in result.stdout
