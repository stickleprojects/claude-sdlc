"""A tooling change (#221): intent.md says `Kind: tooling`, and the plan follows the intent
with no spec."""

from pathlib import Path

import pytest

from sdlc.artifacts import CHAIN, TOOLING_CHAIN, check_change, kind, stage
from sdlc.cli import main

from .helpers import write


def tooling(change: Path, line: str = "Kind: tooling") -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    intent = change / "intent.md"
    intent.write_text(intent.read_text().replace("# Title\n", f"# Title\n\n{line}\n", 1))


@pytest.mark.parametrize("line", ["Kind: tooling", "- Kind: tooling", "Kind:  Tooling  "])
def test_an_intent_with_the_kind_line_is_a_tooling_change(change: Path, line: str) -> None:
    tooling(change, line)
    assert kind(change) == "tooling"


@pytest.mark.parametrize(
    "line",
    [
        "<!-- Kind: tooling -->",
        "<!-- For a tooling change, add a line:\nKind: tooling\n-->",
        "Kind: tooling, mostly",
        "Kind: feature",
        "The kind: tooling",
    ],
    ids=["one-line comment", "multi-line comment", "extra words", "other kind", "mid-line"],
)
def test_only_a_plain_kind_line_counts(change: Path, line: str) -> None:
    """The template's commented example, or prose that mentions it, never opts a change in."""
    tooling(change, line)
    assert kind(change) == "feature"


def test_a_bug_is_never_a_tooling_change(change: Path) -> None:
    tooling(change)
    (change / "intent.md").rename(change / "bug.md")
    assert kind(change) == "bug"


def test_a_tooling_plan_needs_no_spec(change: Path) -> None:
    tooling(change)
    write(change / "plan.md", CHAIN["plan.md"])
    assert check_change(change) == []
    assert stage(change) == "plan"
    assert TOOLING_CHAIN["plan.md"] == CHAIN["plan.md"], "the same plan, sections and all"


def test_a_feature_plan_still_needs_its_spec(change: Path) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    write(change / "plan.md", CHAIN["plan.md"])
    assert any(
        "earlier artifact in the chain is missing" in p.message for p in check_change(change)
    )


def test_a_tooling_change_with_a_spec_is_reported(change: Path) -> None:
    tooling(change)
    write(change / "spec.md", CHAIN["spec.md"])
    write(change / "plan.md", CHAIN["plan.md"])
    [problem] = check_change(change)
    assert problem.path.name == "spec.md"
    assert "a tooling change (Kind: tooling) has no spec" in problem.message


def test_a_tooling_intent_still_needs_its_sections(change: Path) -> None:
    tooling(change)
    intent = change / "intent.md"
    intent.write_text(intent.read_text().replace("## Constraints", "## Limits"))
    [problem] = check_change(change)
    assert "missing sections: Constraints" in problem.message


def test_the_kind_command_prints_each_kind(tmp_path: Path, capsys) -> None:
    feature, bug, tool = (tmp_path / "changes" / n for n in ("0001-f", "0002-b", "0003-t"))
    write(feature / "intent.md", CHAIN["intent.md"])
    write(bug / "bug.md", ["What happens"])
    tooling(tool)
    for folder, expected in [(feature, "feature"), (bug, "bug"), (tool, "tooling")]:
        assert main(["kind", str(folder)]) == 0
        assert capsys.readouterr().out == f"{expected}\n"
    assert main(["kind", str(tmp_path / "changes" / "0009-gone")]) == 1
    assert "no change folder" in capsys.readouterr().err


def test_the_intent_templates_example_line_doesnt_make_a_tooling_change(change: Path) -> None:
    """The template shows the line inside a comment; a change made from it is a feature."""
    from .helpers import REPO

    template = (REPO / ".sdlc/templates/intent.md").read_text()
    assert "\nKind: tooling\n" in template, "the example is on a line of its own"
    change.mkdir(parents=True)
    (change / "intent.md").write_text(template)
    assert kind(change) == "feature"
    (change / "intent.md").write_text(template.replace("-->\n", "-->\nKind: tooling\n", 1))
    assert kind(change) == "tooling"
