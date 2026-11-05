from pathlib import Path

import pytest

from sdlc.artifacts import BUILD_SECTIONS, CHAIN, build_progress, check_change, next_slug, stage
from sdlc.cli import main

REPO = Path(__file__).resolve().parents[1]


def write(path: Path, sections: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Title\n\n" + "".join(f"## {s}\n\ntext\n\n" for s in sections))


@pytest.fixture
def change(tmp_path: Path) -> Path:
    return tmp_path / "changes" / "0001-example"


def test_complete_intent_is_valid(change: Path) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    assert check_change(change) == []
    assert stage(change) == "intent"


def test_missing_sections_are_reported(change: Path) -> None:
    write(change / "intent.md", ["Problem"])
    [problem] = check_change(change)
    assert "Proposed outcome" in problem.message


def test_spec_without_intent_breaks_chain(change: Path) -> None:
    write(change / "spec.md", CHAIN["spec.md"])
    messages = [p.message for p in check_change(change)]
    assert any("earlier artifact" in m for m in messages)
    assert any("no intent.md" in m for m in messages)


def test_bad_folder_name(tmp_path: Path) -> None:
    bad = tmp_path / "changes" / "Example"
    write(bad / "intent.md", CHAIN["intent.md"])
    assert any("folder name" in p.message for p in check_change(bad))


def test_next_slug_increments(tmp_path: Path) -> None:
    (tmp_path / "changes" / "0007-old").mkdir(parents=True)
    assert next_slug(tmp_path, "new-thing") == "0008-new-thing"


@pytest.mark.parametrize("name", list(CHAIN))
def test_templates_satisfy_their_own_rules(name: str) -> None:
    text = (REPO / "templates" / name).read_text()
    for section in CHAIN[name]:
        assert f"## {section}" in text


def test_new_then_check_round_trip(tmp_path: Path) -> None:
    (tmp_path / "templates").mkdir()
    template = (REPO / "templates" / "intent.md").read_text()
    (tmp_path / "templates" / "intent.md").write_text(template)
    assert main(["--root", str(tmp_path), "new", "add-login"]) == 0
    assert (tmp_path / "changes" / "0001-add-login" / "intent.md").exists()
    assert main(["--root", str(tmp_path), "check"]) == 0


def test_new_rejects_bad_name(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), "new", "Bad Name"]) == 2


# --- build.md: the optional build plan -------------------------------------------------

BUILD_TEMPLATE = (REPO / "templates" / "build.md").read_text()


def planned(change: Path) -> Path:
    for name, sections in CHAIN.items():
        write(change / name, sections)
    return change / "build.md"


def approved(text: str) -> str:
    return text.replace(
        "- **Status:** draft, awaiting approval", "- **Status:** in progress"
    ).replace("- **Approved:** not yet", "- **Approved:** Sam, 2026-11-05")


def messages(change: Path) -> list[str]:
    return [p.message for p in check_change(change)]


def test_build_template_is_a_valid_draft(change: Path) -> None:
    planned(change).write_text(BUILD_TEMPLATE)
    assert check_change(change) == []
    assert stage(change) == "build"
    assert build_progress(change) == "draft, awaiting approval, 0/2 milestones done"


def test_build_template_has_its_sections() -> None:
    for heading in BUILD_SECTIONS:
        assert f"## {heading}" in BUILD_TEMPLATE


def test_build_without_plan_is_reported(change: Path) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    (change / "build.md").write_text(BUILD_TEMPLATE)
    assert any("plan.md is missing" in m for m in messages(change))


def test_approved_build_is_valid(change: Path) -> None:
    planned(change).write_text(approved(BUILD_TEMPLATE))
    assert check_change(change) == []


def test_approval_with_open_questions_is_reported(change: Path) -> None:
    text = approved(BUILD_TEMPLATE).replace(
        "None.\n\n## Milestones", "1. Keep the backend-first order?\n\n## Milestones"
    )
    planned(change).write_text(text)
    assert any("Questions before approval" in m for m in messages(change))


def test_approval_without_approver_is_reported(change: Path) -> None:
    text = BUILD_TEMPLATE.replace(
        "- **Status:** draft, awaiting approval", "- **Status:** in progress"
    )
    planned(change).write_text(text)
    assert any("Approved" in m for m in messages(change))


def test_not_yet_approved_in_any_case_is_reported(change: Path) -> None:
    text = approved(BUILD_TEMPLATE).replace("Sam, 2026-11-05", "Not yet")
    planned(change).write_text(text)
    assert any("Approved" in m for m in messages(change))


def test_building_from_a_draft_is_reported(change: Path) -> None:
    text = BUILD_TEMPLATE.replace("- **Status:** todo", "- **Status:** in progress", 1)
    planned(change).write_text(text)
    assert any("still a draft" in m for m in messages(change))


def test_redraft_keeps_done_milestones(change: Path) -> None:
    text = BUILD_TEMPLATE.replace("- **Status:** todo", "- **Status:** done (abc1234)", 1)
    planned(change).write_text(text)
    assert check_change(change) == []
    assert build_progress(change).endswith("1/2 milestones done")


def test_one_milestone_build_is_reported(change: Path) -> None:
    text = BUILD_TEMPLATE.split("### M2.")[0] + "## Deviations from the plan\n\n"
    text += "## Flaky tests\n\n## Session log\n"
    planned(change).write_text(text)
    assert any("one milestone" in m for m in messages(change))


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("- **Status:** draft, awaiting approval", "- **Status:** nearly done", "Status must"),
        ("- **Status:** draft, awaiting approval <!--", "<!--", "Status must"),
        ("- **Status:** todo", "- **Status:** finished", "M1 status"),
        ("- **Status:** todo", "- **Owner:** me", "M1 status"),
        ("## Flaky tests", "## Flakes", "missing sections: Flaky tests"),
    ],
)
def test_unrecognised_build_text_fails_safe(
    change: Path, old: str, new: str, expected: str
) -> None:
    planned(change).write_text(BUILD_TEMPLATE.replace(old, new, 1))
    assert any(expected in m for m in messages(change))


def test_finished_build_from_before_the_template_stays_valid(change: Path) -> None:
    planned(change).write_text(
        "# Build\n\n- **Status:** PR open (#12)\n\n## Milestones\n\n"
        "### M1. Server\n\n- **Status:** done (abc1234)\n"
    )
    assert check_change(change) == []


def test_status_shows_build_progress(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    planned(tmp_path / "changes" / "0001-example").write_text(approved(BUILD_TEMPLATE))
    write(tmp_path / "changes" / "0002-other" / "intent.md", CHAIN["intent.md"])
    assert main(["--root", str(tmp_path), "status"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "0001-example\tbuild\tin progress, 0/2 milestones done",
        "0002-other\tintent",
    ]
