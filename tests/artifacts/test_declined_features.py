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


def test_optional_feature_titles_are_unique_across_releases() -> None:
    """A decline is keyed by the title, so two features with one title would share it."""
    titles = [
        m.lower()
        for notes in sorted((REPO / "docs/release-notes").glob("v*.md"))
        for m in re.findall(r"^## Optional: (.+)$", notes.read_text(), re.MULTILINE)
    ]
    assert titles and len(titles) == len(set(titles)), titles


def test_review_skills_check_for_stale_text_before_every_push() -> None:
    # #173 (spellbound3d#183): a stale build.md and a PR body the push made untrue each cost
    # another review round.
    findings = (REPO / ".sdlc/skills/review-findings/SKILL.md").read_text()
    before_push = findings.split("## Before you push", 1)[1].split("\n## ", 1)[0]
    for step in ("make next REF=origin/main", "make clauses CHANGE=<slug>", "pulls/<N> --jq .body"):
        assert step in before_push, step
    po = (REPO / ".sdlc/skills/po-review/SKILL.md").read_text()
    assert "follow *Before you push*" in po
