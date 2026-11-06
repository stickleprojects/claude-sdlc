from pathlib import Path

import pytest

from conftest import commit, git, init_repo
from sdlc.artifacts import (
    ADR_SECTIONS,
    BUG_CHAIN,
    BUILD_SECTIONS,
    CHAIN,
    TEMPLATES,
    build_progress,
    check_adrs,
    check_change,
    next_slug,
    stage,
)
from sdlc.cli import check_commits, main

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


@pytest.mark.parametrize(
    ("kind", "name"), [(k, n) for k, c in [("feature", CHAIN), ("bug", BUG_CHAIN)] for n in c]
)
def test_templates_satisfy_their_own_rules(kind: str, name: str) -> None:
    rules = CHAIN if kind == "feature" else BUG_CHAIN
    text = (REPO / "templates" / TEMPLATES[kind][name]).read_text()
    for section in rules[name]:
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


# --- commit guards -------------------------------------------------------------------------


@pytest.fixture
def branch_repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "r")
    commit(repo, "chore: start", {"README.md": "x\n"})
    git(repo, "switch", "-q", "-c", "feature")
    return repo


def test_tracked_node_modules_fail_validate(branch_repo: Path) -> None:
    commit(branch_repo, "oops", {"app/node_modules/left-pad/index.js": "x\n"})
    [problem] = check_commits(branch_repo)
    assert "node_modules" in problem
    assert main(["--root", str(branch_repo), "check"]) == 1


def test_branch_with_too_many_files_fails_validate(branch_repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDLC_MAX_CHANGED_FILES", "3")
    commit(branch_repo, "big", {f"out/{i}.txt": "x\n" for i in range(4)})
    [problem] = check_commits(branch_repo)
    assert "changes 4 files against main (limit 3)" in problem


def test_normal_branch_passes_commit_guards(branch_repo: Path) -> None:
    commit(branch_repo, "small", {"src/a.py": "x\n", "src/node_modules_helper.py": "x\n"})
    assert check_commits(branch_repo) == []


def test_commit_guards_skip_outside_git(tmp_path: Path) -> None:
    assert check_commits(tmp_path) == []


# --- bugs --------------------------------------------------------------------------------


def test_bug_with_short_spec_and_plan_is_valid(change: Path) -> None:
    write(change / "bug.md", BUG_CHAIN["bug.md"])
    assert check_change(change) == []
    assert stage(change) == "bug"
    write(change / "spec.md", ["Requirements", "Acceptance criteria"])
    write(change / "plan.md", CHAIN["plan.md"])
    assert check_change(change) == []
    assert stage(change) == "plan"


def test_bug_spec_still_needs_requirements_and_criteria(change: Path) -> None:
    write(change / "bug.md", BUG_CHAIN["bug.md"])
    write(change / "spec.md", ["Requirements"])
    [problem] = check_change(change)
    assert "Acceptance criteria" in problem.message


def test_feature_spec_still_needs_every_section(change: Path) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    write(change / "spec.md", ["Requirements", "Acceptance criteria"])
    [problem] = check_change(change)
    assert "Policy concerns" in problem.message


def test_intent_and_bug_together_are_reported(change: Path) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    write(change / "bug.md", BUG_CHAIN["bug.md"])
    assert any("both intent.md and bug.md" in p.message for p in check_change(change))


def _templates(root: Path) -> None:
    (root / "templates").mkdir()
    for name in ("intent.md", "bug.md"):
        (root / "templates" / name).write_text((REPO / "templates" / name).read_text())


def test_new_bug_round_trip(tmp_path: Path) -> None:
    _templates(tmp_path)
    assert main(["--root", str(tmp_path), "new", "export-hangs", "--type", "bug"]) == 0
    folder = tmp_path / "changes" / "0001-export-hangs"
    assert (folder / "bug.md").exists()
    assert not (folder / "intent.md").exists()
    assert main(["--root", str(tmp_path), "check"]) == 0


def test_new_reads_type_from_the_environment(tmp_path: Path, monkeypatch) -> None:
    # `make new-change NAME=x TYPE=bug` reaches the CLI as $TYPE.
    _templates(tmp_path)
    monkeypatch.setenv("TYPE", "bug")
    assert main(["--root", str(tmp_path), "new", "export-hangs"]) == 0
    assert (tmp_path / "changes" / "0001-export-hangs" / "bug.md").exists()


def test_new_rejects_unknown_type(tmp_path: Path) -> None:
    _templates(tmp_path)
    assert main(["--root", str(tmp_path), "new", "x", "--type", "chore"]) == 2


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


ADR_TEMPLATE = (REPO / "templates" / "adr.md").read_text()


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


def test_accepted_adr_with_a_trigger_is_valid(tmp_path: Path) -> None:
    adr(tmp_path, "0001-client-stack.md", accepted_adr())
    assert check_adrs(tmp_path) == []


@pytest.mark.parametrize("trigger", ["", "None.", "never", "<!-- later -->", "- <trigger>"])
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
