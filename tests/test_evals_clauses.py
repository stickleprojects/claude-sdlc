"""The clause-review evals (#160) without a model: their fixtures say what the evals rely on,
and their checks pass the findings the review rules ask for and fail the ones they rule out."""

import json
import os
import shutil
from pathlib import Path

import pytest

from conftest import REPO, git, run

FIXTURE = REPO / "evals/fixtures/clause-one-pass"
ONE_PASS = REPO / "evals/checks/clause-one-pass.sh"
REREVIEW = REPO / "evals/checks/clause-rereview.sh"


def requirement(spec: str, rid: str) -> str:
    return next(line for line in spec.splitlines() if line.startswith(f"- {rid}. "))


def check(tmp_path: Path, script: Path, findings: str):
    (tmp_path / "findings.md").write_text(findings)
    return run(["bash", str(script)], cwd=tmp_path, env={**os.environ, "EVAL_ROOT": str(REPO)})


# --- the fixtures -----------------------------------------------------------------------------


def test_rereview_fixture_keeps_r1_and_rewords_r2():
    before = (FIXTURE / "rereview/spec-before.md").read_text()
    after = (FIXTURE / "rereview/spec-after.md").read_text()
    assert requirement(before, "R1") == requirement(after, "R1"), "R1's text is unchanged"
    assert "on the large Barbarian" in requirement(after, "R1")
    assert requirement(before, "R2") != requirement(after, "R2")
    assert "names the character" in requirement(after, "R2")
    assert "names the character" not in after.split("## Acceptance criteria")[1], "untested"


def test_rereview_fixture_covers_exactly_what_the_earlier_thread_listed():
    [thread] = json.loads((FIXTURE / "rereview/earlier-threads.json").read_text())
    listed = [row for row in thread["body"].splitlines() if row.endswith("| none |")]
    assert len(listed) == 4 and "Barbarian" not in thread["body"].split("| Clause")[1]
    ac1 = next(
        line
        for line in (FIXTURE / "rereview/spec-after.md").read_text().splitlines()
        if line.startswith("- AC1 ")
    )
    for term in ("Rig_Large", "Flexing", "docs/gdd/characters.md", "docs/architecture.md"):
        assert term in ac1
    assert "Barbarian" not in ac1


def test_rereview_setup_builds_the_two_commits(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "evals/fixtures/clause-one-pass")
    result = run(["bash", "evals/fixtures/clause-one-pass/rereview/setup.sh"], cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    repo = tmp_path / "rereview"
    first, second = git(repo, "rev-list", "--reverse", "HEAD").split()
    [thread] = json.loads((repo / "earlier-threads.json").read_text())
    assert thread["original_commit_id"] == first
    diff = git(repo, "diff", first, second, "--", "changes/0001-hero-docs/spec.md")
    assert "+- R2." in diff and "+- R1." not in diff, "R2 reworded, R1 not"


def test_one_pass_fixture_leaves_four_clauses_of_r1_untested():
    spec = (FIXTURE / "0001-hero-docs/spec.md").read_text()
    ac1 = next(line for line in spec.splitlines() if line.startswith("- AC1 "))
    for term in ("Rig_Large", "Flexing", "characters.md", "architecture.md"):
        assert term in requirement(spec, "R1") and term not in ac1


# --- the checks -------------------------------------------------------------------------------

ALL_IN_ONE = """# Findings

## R1 has clauses no acceptance criterion tests

**Important (product owner decides):** R1 has clauses no criterion tests.

| Clause | Covered by |
|---|---|
| with `Rig_Large` clips | none |
| `Flexing` for interact | none |
| `docs/gdd/characters.md` gives his height as 3.0 | none |
| `docs/architecture.md` shows the per-rig animation libraries | none |
"""

SPLIT_ACROSS = """## R1: the art bible line

**Important (product owner decides):** nothing checks `Rig_Large` or `Flexing`.

## R1: the other docs

**Important (product owner decides):** nothing checks characters.md or architecture.md.
"""


def test_one_pass_check_passes_one_finding_with_every_clause(tmp_path):
    result = check(tmp_path, ONE_PASS, ALL_IN_ONE)
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "findings",
    [SPLIT_ACROSS, ALL_IN_ONE.replace("| `Flexing` for interact | none |\n", ""), ""],
    ids=["split-across-findings", "a-clause-missing", "no-findings"],
)
def test_one_pass_check_fails_a_partial_finding(tmp_path, findings):
    assert check(tmp_path, ONE_PASS, findings).returncode == 1


R2_FINDING = """## R2's new error case has no criterion

**Important (product owner decides):** R2 now says loading fails with an error that names the
character when a look names a rig `looks.json` doesn't define. No criterion tests it.
"""

BARBARIAN_NIT = """## R1 never checks the model

**Nit:** AC1 doesn't check "on the large Barbarian". The earlier split didn't list it.
"""

BARBARIAN_IMPORTANT = """## R1 never checks the model

**Important (product owner decides):** AC1 doesn't check "on the large Barbarian".
"""


@pytest.mark.parametrize("findings", [R2_FINDING, R2_FINDING + "\n" + BARBARIAN_NIT])
def test_rereview_check_passes_a_review_that_keeps_the_split(tmp_path, findings):
    result = check(tmp_path, REREVIEW, findings)
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    ("findings", "says"),
    [
        (R2_FINDING + "\n" + BARBARIAN_IMPORTANT, "unchanged text"),
        (BARBARIAN_NIT, "isn't an Important finding"),
        (R2_FINDING.replace("**Important (product owner decides):**", "**Nit:**"), "isn't an"),
    ],
    ids=["new-clause-in-unchanged-text", "missed-the-reworded-clause", "reworded-only-a-nit"],
)
def test_rereview_check_fails_a_moved_split_or_a_missed_clause(tmp_path, findings, says):
    result = check(tmp_path, REREVIEW, findings)
    assert result.returncode == 1 and says in result.stdout


def test_rereview_check_reads_findings_written_inside_the_repo(tmp_path):
    (tmp_path / "rereview").mkdir()
    (tmp_path / "rereview/findings.md").write_text(R2_FINDING)
    result = run(["bash", str(REREVIEW)], cwd=tmp_path)
    assert result.returncode == 0, result.stdout


# --- the rules and the tasks ------------------------------------------------------------------


def test_review_rules_ask_for_every_clause_once_and_keep_the_first_split():
    review = (REPO / ".sdlc/REVIEW.md").read_text()
    assert "**Every clause of a requirement in one finding (#160).**" in review
    assert "one thread per requirement that lists every clause" in review
    assert "**On a re-review, the first split stands (#160).**" in review
    assert "In text that hasn't changed, raise no new clauses" in review
    assert "original_commit_id" in review and "is a Nit at most" in review
    assert "If that commit is no longer in the repo" in review
    assert "treat the whole text as changed" in review
    prompt = (REPO / ".sdlc/prompts/clause-check.md").read_text()
    assert "Split the whole requirement's text into clauses, start to end" in prompt
    assert "Report every clause that isn't covered, not only the first one you find." in prompt


def test_clause_eval_tasks_are_wired_to_their_checks():
    tasks = REPO / "evals/tasks"
    one = json.loads((tasks / "review-lists-every-clause-in-one-finding.json").read_text())
    again = json.loads((tasks / "review-rereview-keeps-the-first-split.json").read_text())
    assert "clause-one-pass.sh" in one["check"] and "0001-hero-docs/spec.md" in one["prompt"]
    assert "clause-rereview.sh" in again["check"] and "rereview/setup.sh" in again["setup"]
    assert "earlier-threads.json" in again["prompt"] and "Bash(git -C rereview:*)" in again["tools"]
