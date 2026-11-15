import re
from pathlib import Path

import pytest

from sdlc.artifacts import check_features
from sdlc.cli import main

from .helpers import REPO

# --- optional features a project declined (#74) -----------------------------------------------

DECLINED = """
[[features.declined]]
feature = "architecture decision records (ADRs)"
reason = "a short-lived prototype"
by = "Sam"
date = 2026-11-13
"""


def _config_problems(tmp_path: Path, text: str) -> list[str]:
    (tmp_path / ".sdlc.toml").write_text(text)
    return check_features(tmp_path)


def test_a_declined_feature_with_its_reason_is_valid(tmp_path: Path) -> None:
    assert _config_problems(tmp_path, DECLINED) == []
    assert main(["--root", str(tmp_path), "check"]) == 0


def test_no_config_or_no_features_table_is_fine(tmp_path: Path) -> None:
    assert check_features(tmp_path) == []
    assert _config_problems(tmp_path, '[placeholders.explicit_none]\nkeywords = ["None"]\n') == []


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('[[features.declined]]\nfeature = "ADRs"\n', "entry 1 has no reason"),
        ('[[features.declined]]\nreason = "x"\n', "entry 1 has no feature"),
        ('[[features.declined]]\nfeature = "ADRs"\nreason = "  "\n', "reason must be text"),
        ('[[features.declined]]\nfeature = "ADRs"\nreason = "x"\nwhy = "y"\n', "unknown key why"),
        (
            '[[features.declined]]\nfeature = "ADRs"\nreason = "x"\ndate = 3\n',
            "date must be a date",
        ),
        ('[features]\ndeclined = ["ADRs"]\n', "must be [[features.declined]] entries"),
        ("features = 1\n", "[features] must be a table"),
        ('[features]\nadopted = ["x"]\n', "unknown key features.adopted"),
        (
            '[[features.declined]]\nfeature = "Optional: ADRs"\nreason = "x"\n',
            'without "Optional:"',
        ),
        (
            '[[features.declined]]\nfeature = "ADRs"\nreason = "x"\n'
            '[[features.declined]]\nfeature = "adrs"\nreason = "y"\n',
            "declined twice",
        ),
    ],
)
def test_a_declined_entry_that_cant_be_read_fails_validate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, problem: str
) -> None:
    problems = _config_problems(tmp_path, text)
    assert any(problem in p for p in problems), problems
    assert main(["--root", str(tmp_path), "check"]) == 1
    assert ".sdlc.toml" in capsys.readouterr().err


def test_invalid_toml_is_reported_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _config_problems(tmp_path, "[[features.declined]\n") == []
    assert main(["--root", str(tmp_path), "check"]) == 1
    assert capsys.readouterr().err.count("isn't valid TOML") == 1


def test_the_sdlc_skills_example_entry_is_valid(tmp_path: Path) -> None:
    """The entry /sdlc writes, copied from the skill, passes make validate as it stands."""
    skill = (REPO / ".sdlc/skills/sdlc/SKILL.md").read_text()
    block = re.search(r"```toml\n(.*?)```", skill, re.DOTALL).group(1)
    example = "\n".join(line.strip() for line in block.splitlines()).replace("<who decided>", "Sam")
    assert _config_problems(tmp_path, example) == []
    assert "Not now" in skill and "Not for us" in skill and "never make one up" in skill


def test_the_sdlc_skill_lists_declined_features_after_the_update_without_offering_them() -> None:
    """#147: a declined feature is skipped in what's new and the offers, then listed after."""
    skill = (REPO / ".sdlc/skills/sdlc/SKILL.md").read_text()
    whats_new, rest = skill.split("## 3. Update on a branch")
    afterwards = rest.split("## 5. Afterwards")[1]
    assert "Leave out each feature the project has declined" in whats_new
    assert "how many you left out" not in whats_new
    offer, listing = afterwards.split("Then list the optional features")
    assert "hasn't adopted or declined" in offer
    assert "without offering them" in listing
    assert "Not offered, since you've said no to these before:" in listing
    assert "declined by" in listing and "delete its entry in `.sdlc.toml`" in listing


def test_optional_feature_titles_are_unique_across_releases() -> None:
    """A decline is keyed by the title, so two features with one title would share it."""
    titles = [
        m.lower()
        for notes in sorted((REPO / "docs/release-notes").glob("v*.md"))
        for m in re.findall(r"^## Optional: (.+)$", notes.read_text(), re.MULTILINE)
    ]
    assert titles and len(titles) == len(set(titles)), titles


def test_scope_rules_script_a_check_before_handing_it_to_a_person() -> None:
    # #171 (spellbound3d, 14 Nov): five things handed to the person to try, several of which a
    # test could check and none of which had one.
    scope = (REPO / ".sdlc/skills/scope.md").read_text()
    human = scope.split("## Human checks", 1)[1].split("\n## ", 1)[0]
    assert "in the plan or not" in human
    assert "write that test first and run it" in human
    assert "which test is still owed" in human and "Engineer decides: yes" in human


def test_build_all_orchestrator_opens_the_pr_itself() -> None:
    # #170 (spellbound3d 0029, PR #182): the orchestrator holds the run's decisions, which the PR
    # body records; a worker sees only its own unit.
    build = (REPO / ".sdlc/skills/build/SKILL.md").read_text()
    assert "No FAIL: open the PR from this session" in build
    assert "No FAIL: start a worker with the per-criterion results to open the PR." not in build
    assert "the orchestrator usually opens the PR itself" in build


def test_review_checks_the_design_text_a_requirement_change_makes_stale() -> None:
    # #172 (spellbound3d#183): round 1 found a stale plan Approach after a spec amendment.
    review = (REPO / ".sdlc/REVIEW.md").read_text()
    assert "The design text that depends on it, in the same pass (#172)" in review
    assert "Approach, Steps, Verification rows" in review
    findings = (REPO / ".sdlc/skills/review-findings/SKILL.md").read_text()
    assert "fix the whole requirement it names and the plan text that depends on it" in findings
    po = (REPO / ".sdlc/skills/po-review/SKILL.md").read_text()
    assert "every clause the finding lists is covered at once" in po


def test_review_skills_check_for_stale_text_before_every_push() -> None:
    # #173 (spellbound3d#183): a stale build.md and a PR body the push made untrue each cost
    # another review round.
    findings = (REPO / ".sdlc/skills/review-findings/SKILL.md").read_text()
    before_push = findings.split("## Before you push", 1)[1].split("\n## ", 1)[0]
    for step in ("make next REF=origin/main", "make clauses CHANGE=<slug>", "pulls/<N> --jq .body"):
        assert step in before_push, step
    assert "Fix the whole requirement" in before_push
    po = (REPO / ".sdlc/skills/po-review/SKILL.md").read_text()
    assert "follow *Before you push*" in po
