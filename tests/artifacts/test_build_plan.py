from pathlib import Path

import pytest

from sdlc.artifacts import (
    ADR_SECTIONS,
    BUILD_SECTIONS,
    CHAIN,
    build_progress,
    check_adrs,
    check_change,
    check_config,
    placeholders,
    stage,
)
from sdlc.cli import main

from .helpers import REPO, messages, write

# --- build.md: the optional build plan -------------------------------------------------

BUILD_TEMPLATE = (REPO / ".sdlc" / "templates" / "build.md").read_text()


def planned(change: Path) -> Path:
    for name, sections in CHAIN.items():
        write(change / name, sections)
    return change / "build.md"


def approved(text: str) -> str:
    return text.replace(
        "- **Status:** draft, awaiting approval", "- **Status:** in progress"
    ).replace("- **Approved:** not yet", "- **Approved:** Sam, 2026-11-05")


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


ADR_TEMPLATE = (REPO / ".sdlc" / "templates" / "adr.md").read_text()


def accepted_adr(trigger: str = "- a plan hand-builds navigation state") -> str:
    text = ADR_TEMPLATE.replace("proposed <!--", "accepted (Sam, 2026-11-06) <!--", 1)
    return text.replace("- <trigger>", trigger)


def adr(root: Path, name: str, text: str) -> Path:
    path = root / "docs" / "adr" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def adr_messages(root: Path) -> list[str]:
    return [p.message for p in check_adrs(root)]


def test_no_adr_folder_is_fine(tmp_path: Path) -> None:
    assert check_adrs(tmp_path) == []


def test_adr_template_has_its_sections() -> None:
    for heading in ADR_SECTIONS:
        assert f"## {heading}" in ADR_TEMPLATE


def test_adr_template_is_a_valid_proposal(tmp_path: Path) -> None:
    adr(tmp_path, "0001-client-stack.md", ADR_TEMPLATE)
    adr(tmp_path, "README.md", "# Decisions\n")
    assert check_adrs(tmp_path) == []


def test_leftover_placeholder_beside_a_real_trigger_is_reported(tmp_path: Path) -> None:
    adr(tmp_path, "0001-client-stack.md", accepted_adr("- a plan hand-builds routing\n- <trigger>"))
    assert adr_messages(tmp_path) == ["Revisit when still has the template's <trigger>"]


def test_accepted_adr_with_a_trigger_is_valid(tmp_path: Path) -> None:
    adr(tmp_path, "0001-client-stack.md", accepted_adr())
    assert check_adrs(tmp_path) == []


@pytest.mark.parametrize(
    "trigger",
    [
        "",
        "None.",
        "never",
        "<!-- later -->",
        "- <trigger>",
        "- None",
        "- N/A",
        "* TBD.",
        "1. todo",
        "-",
    ],
)
def test_accepted_adr_without_a_trigger_is_reported(tmp_path: Path, trigger: str) -> None:
    adr(tmp_path, "0001-client-stack.md", accepted_adr(trigger))
    assert any("Revisit when names no trigger" in m for m in adr_messages(tmp_path))


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("proposed <!--", "agreed <!--", "Status must"),
        ("proposed <!--", "<!--", "Status must"),
        ("## Revisit when", "## Later", "missing sections: Revisit when"),
        ("## Alternatives considered", "## Options", "missing sections: Alternatives"),
    ],
)
def test_unrecognised_adr_text_fails_safe(
    tmp_path: Path, old: str, new: str, expected: str
) -> None:
    adr(tmp_path, "0001-client-stack.md", ADR_TEMPLATE.replace(old, new, 1))
    assert any(expected in m for m in adr_messages(tmp_path))


def test_superseded_adr_names_an_existing_one(tmp_path: Path) -> None:
    adr(
        tmp_path,
        "0001-client-stack.md",
        ADR_TEMPLATE.replace("proposed <!--", "superseded by 0002 <!--"),
    )
    assert any("no such ADR" in m for m in adr_messages(tmp_path))
    adr(tmp_path, "0002-adopt-router.md", accepted_adr())
    assert check_adrs(tmp_path) == []


def test_bad_adr_names_and_duplicate_numbers_are_reported(tmp_path: Path) -> None:
    adr(tmp_path, "client-stack.md", ADR_TEMPLATE)
    adr(tmp_path, "0001-a.md", ADR_TEMPLATE)
    adr(tmp_path, "0001-b.md", ADR_TEMPLATE)
    found = adr_messages(tmp_path)
    assert any("0001-short-slug.md" in m for m in found)
    assert any("0001 is used twice" in m for m in found)


def test_check_reports_adr_problems(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    adr(tmp_path, "0001-client-stack.md", accepted_adr(""))
    assert main(["--root", str(tmp_path), "check"]) == 1
    assert "Revisit when" in capsys.readouterr().err


def test_placeholder_words_come_from_the_framework_file(tmp_path: Path) -> None:
    words = placeholders(tmp_path)
    assert {"none", "tbd"} <= words.nothing_written
    assert words.explicit_none == {"None", "None."}
    assert check_config(tmp_path) == []


def repo_config(root: Path, text: str) -> None:
    (root / ".sdlc.toml").write_text(text)


def test_repo_config_adds_to_the_framework_list(tmp_path: Path) -> None:
    repo_config(tmp_path, '[placeholders.nothing_written]\nadditional_keywords = ["Pending."]\n')
    for trigger in ("- pending", "- tbd"):
        adr(tmp_path, "0001-client-stack.md", accepted_adr(trigger))
        assert any("names no trigger" in m for m in adr_messages(tmp_path)), trigger
    assert check_config(tmp_path) == []


def test_repo_config_replaces_the_framework_list(tmp_path: Path) -> None:
    repo_config(tmp_path, '[placeholders.nothing_written]\nkeywords = ["none", "pending"]\n')
    adr(tmp_path, "0001-client-stack.md", accepted_adr("- pending"))
    assert any("names no trigger" in m for m in adr_messages(tmp_path))
    adr(tmp_path, "0001-client-stack.md", accepted_adr("- tbd"))
    assert adr_messages(tmp_path) == [], "the repo's keywords replaced the framework's"


def test_repo_config_replaces_then_adds(tmp_path: Path) -> None:
    repo_config(
        tmp_path,
        "[placeholders.explicit_none]\n"
        'keywords = ["None."]\nadditional_keywords = ["Nothing open."]\n',
    )
    assert placeholders(tmp_path).explicit_none == {"None.", "Nothing open."}


def test_repo_config_sets_what_clears_a_build(change: Path) -> None:
    repo_config(
        change.parents[1], '[placeholders.explicit_none]\nadditional_keywords = ["Nothing open."]\n'
    )
    cleared = approved(BUILD_TEMPLATE).replace(
        "None.\n\n## Milestones", "Nothing open.\n\n## Milestones"
    )
    planned(change).write_text(cleared)
    assert check_change(change) == []
    planned(change).write_text(approved(BUILD_TEMPLATE))
    assert check_change(change) == [], "the framework's None. still clears it"
    planned(change).write_text(cleared.replace("Nothing open.", "TBD"))
    assert any("Questions before approval" in m for m in messages(change))


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ("[placeholders\n", "isn't valid TOML"),
        ("placeholders = 1\n", "must be a table"),
        ('[placeholders.nothing]\nkeywords = ["x"]\n', "unknown list placeholders.nothing"),
        ('[placeholders]\nexplicit_none = ["None."]\n', "explicit_none must be a table"),
        ('[placeholders.explicit_none]\nwords = ["x"]\n', "unknown key placeholders.explicit_none"),
        ('[placeholders.explicit_none]\nkeywords = "None."\n', "keywords must be a list"),
        ("[placeholders.explicit_none]\nadditional_keywords = [1]\n", "must be a list of strings"),
    ],
)
def test_bad_repo_config_is_reported_and_ignored(
    tmp_path: Path, config: str, expected: str
) -> None:
    (tmp_path / ".sdlc.toml").write_text(config)
    [problem] = check_config(tmp_path)
    assert expected in problem.message
    assert placeholders(tmp_path).explicit_none == {"None", "None."}
    assert main(["--root", str(tmp_path), "check"]) == 1
