from pathlib import Path

import pytest

from sdlc.artifacts import CHAIN, check_change, definition_of_done
from sdlc.cli import main

from .helpers import REPO, edited_plan, plan_with, write

# --- definition of done (#95) ---------------------------------------------------------------

DOD_TEMPLATE = (REPO / ".sdlc/templates/definition-of-done.md").read_text()


def dod_root(tmp_path: Path, project: str | None = None) -> Path:
    (tmp_path / ".sdlc" / "templates").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".sdlc/templates/definition-of-done.md").write_text(DOD_TEMPLATE)
    if project is not None:
        (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs/definition-of-done.md").write_text(project)
    return tmp_path


def test_definition_of_done_defaults_cover_the_kinds_from_95() -> None:
    dod = definition_of_done(REPO)
    assert dod.problems == ()
    for kind in ("Any code", "UI", "Plugin or extension", "Data or schema"):
        assert kind in dod.kinds
    assert "through the UI" in dod.rows["ui"][1]


def test_project_rows_replace_and_add(tmp_path: Path) -> None:
    project = (
        "| Kind of work | Done means |\n|---|---|\n"
        "| **ui** | Widget tests in the real editor, and a contrast check. |\n"
        "| Godot scene | The scene loads headless and its signals are connected. |\n"
    )
    dod = definition_of_done(dod_root(tmp_path, project))
    assert dod.problems == ()
    assert dod.rows["ui"] == ("ui", "Widget tests in the real editor, and a contrast check.")
    assert "Godot scene" in dod.kinds and "Any code" in dod.kinds


@pytest.mark.parametrize(
    ("project", "expected"),
    [
        ("# Our definition of done\n\nWe test everything.\n", "has no rows"),
        ("| Kind of work | Done means |\n|---|---|\n| UI | a |\n| ui | b |\n", "twice"),
        ("| Kind of work | Done means |\n|---|---|\n| UI, web | a |\n", "has a comma"),
        ("| Kind of work | Done means |\n|---|---|\n| UI |  |\n", "doesn't say what done means"),
    ],
)
def test_bad_project_table_is_reported(tmp_path: Path, project: str, expected: str) -> None:
    [problem] = definition_of_done(dod_root(tmp_path, project)).problems
    assert expected in problem.message and "docs/definition-of-done.md" in str(problem.path)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("- **Definition of done:** Any code, UI", None),
        ("- **Definition of done:** any code, ui.", None),  # case and a full stop don't matter
        ("", "no '- **Definition of done:** <kinds>' line"),
        (
            "- **Definition of done:** <the kinds of work that apply, e.g. Any code, UI>",
            "names no kind",
        ),
        ("- **Definition of done:**", "names no kind"),
        ("- **Definition of done:** Any code, UX", "names UX, not in the definition of done"),
    ],
)
def test_plan_names_its_definition_of_done(tmp_path: Path, line: str, expected: str | None) -> None:
    root = dod_root(tmp_path)
    change = root / "changes" / "0001-x"
    plan = plan_with("None.").replace("- **Definition of done:** Any code\n", line + "\n")
    problems = edited_plan(change, plan)
    if expected is None:
        assert problems == []
    else:
        [problem] = problems
        assert expected in problem
        assert "known kinds: Any code, UI" in problem


def test_merged_plan_needs_no_definition_of_done_line(tmp_path: Path) -> None:
    change = dod_root(tmp_path) / "changes" / "0001-x"
    write(change / "intent.md", CHAIN["intent.md"])
    write(change / "spec.md", CHAIN["spec.md"])
    (change / "plan.md").write_text(
        plan_with(None).replace("- **Definition of done:** Any code\n", "")
    )
    assert check_change(change, changed=set()) == []


def test_a_project_kind_can_be_named(tmp_path: Path) -> None:
    project = "| Kind of work | Done means |\n|---|---|\n| Godot scene | Loads headless. |\n"
    change = dod_root(tmp_path, project) / "changes" / "0001-x"
    plan = plan_with("None.").replace("Any code\n", "Any code, Godot scene\n", 1)
    assert edited_plan(change, plan) == []


def test_validate_reports_a_bad_project_table(tmp_path: Path) -> None:
    dod_root(tmp_path, "nothing here\n")
    assert main(["--root", str(tmp_path), "check"]) == 1


def test_stages_hold_work_to_the_definition_of_done() -> None:
    for path in (
        ".sdlc/skills/scope.md",
        ".sdlc/skills/plan/SKILL.md",
        ".sdlc/skills/build/SKILL.md",
        ".sdlc/agents/verifier.md",
        ".sdlc/REVIEW.md",
    ):
        text = (REPO / path).read_text()
        assert "definition-of-done.md" in text, path
        assert "Definition of done:" in text, path
    assert "- **Definition of done:**" in (REPO / ".sdlc/templates/plan.md").read_text()


def test_an_edited_plan_fails_without_a_definition_of_done(change: Path) -> None:
    # Fail safe (PR #100 review): with no table, a plan could name any kind and pass.
    write(change / "intent.md", CHAIN["intent.md"])
    write(change / "spec.md", CHAIN["spec.md"])
    plan = change / "plan.md"
    plan.write_text(plan_with("None.").replace("Any code", "Banana"))
    [problem] = check_change(change, changed={plan})
    assert (
        problem.message
        == "no definition of done found: expected .sdlc/templates/definition-of-done.md"
    )
    assert check_change(change, changed=set()) == []  # a merged plan isn't held to it
