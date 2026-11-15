from pathlib import Path

import pytest

from conftest import commit, git, init_repo
from sdlc.cli import main

from .helpers import CLAUSE_PLAN, CLAUSE_SPEC, REPO, clause_blocks, clause_repo


def test_clauses_reads_each_requirement_with_its_continuation_lines() -> None:
    found = clause_blocks()
    assert list(found) == ["R1", "R2", "R3", "R4"]
    assert found["R2"].text == (
        'When nothing matches, the list shows "No roles match", offers a button that clears the '
        "search, and keeps the text."
    )
    assert found["R3"].text == "Results are ordered by title."
    # Prose after a blank line, and group labels, aren't part of the requirement above.
    assert found["R1"].text == "The list has a search box. It filters by title."
    assert found["R4"].text == "Export writes a CSV."


def test_clauses_attach_the_criteria_that_cite_each_requirement() -> None:
    found = clause_blocks()
    assert [c.id for c in found["R1"].criteria] == ["AC1", "AC3"]
    assert [c.id for c in found["R2"].criteria] == ["AC2", "AC3", "Untestable"]
    assert [c.id for c in found["R3"].criteria] == ["AC3"], "R1–R3 is a range"
    assert [c.id for c in found["R4"].criteria] == ["A4"]
    assert "2. type zzz" in found["R2"].criteria[0].text, "nested steps stay with the criterion"


def test_clauses_attach_plan_lines_citing_a_requirement_or_its_criteria() -> None:
    found = clause_blocks()
    assert [(p.section, p.text) for p in found["R1"].plan] == [
        ("Approach", "The box filters on each keystroke (R1).")
    ]
    assert [p.text for p in found["R2"].plan] == ["| AC2 | `make test` | message shows |"]
    assert [p.text for p in found["R4"].plan] == ["| A4 | `make test` | a CSV |"], (
        "an HTML comment isn't a plan line"
    )
    assert clause_blocks(plan=None)["R1"].plan == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("R1, R2", {"R1", "R2"}),
        ("R2–R4", {"R2", "R3", "R4"}),
        ("AC1-AC3", {"AC1", "AC2", "AC3"}),
        ("R5 to 6", {"R5", "R6"}),
        ("R2D2 and FOR1", set()),
        ("R14a, R14b", {"R14a", "R14b"}),
    ],
)
def test_cited_expands_ranges(text: str, expected: set[str]) -> None:
    from sdlc.clauses import cited

    assert cited(text) == expected


@pytest.mark.parametrize(
    "requirements",
    ["", "Numbered, testable requirements (R1, R2, ...).", "1. The list has a search box."],
)
def test_clauses_fail_safe_when_no_requirement_can_be_read(requirements: str) -> None:
    from sdlc.clauses import ClauseError, blocks

    with pytest.raises(ClauseError, match="no requirements could be read"):
        blocks(f"# Spec\n\n## Requirements\n\n{requirements}\n\n## Acceptance criteria\n")


def test_clauses_command_prints_json_for_a_change(tmp_path: Path, capsys) -> None:
    import json

    root = clause_repo(tmp_path)
    for name in ("0001", "0001-search", str(root / "changes/0001-search")):
        assert main(["--root", str(root), "clauses", name]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["change"] == "0001-search"
        assert [b["id"] for b in out["requirements"]] == ["R1", "R2", "R3", "R4"]
        assert out["requirements"][3]["criteria"] == [
            {"id": "A4", "text": "(R4). Export writes a CSV."}
        ]


def test_clauses_command_fails_for_an_unknown_change_or_unreadable_spec(
    tmp_path: Path, capsys
) -> None:
    root = clause_repo(tmp_path)
    assert main(["--root", str(root), "clauses", "0009"]) == 1
    assert "no change matching '0009'" in capsys.readouterr().err
    (root / "changes/0001-search/spec.md").write_text("# Spec\n\n## Requirements\n\nTBD\n")
    assert main(["--root", str(root), "clauses", "0001"]) == 1
    assert "no requirements could be read" in capsys.readouterr().err
    (root / "changes/0001-search/spec.md").unlink()
    assert main(["--root", str(root), "clauses", "0001"]) == 1


def test_clauses_with_a_ref_keeps_only_what_changed(tmp_path: Path, capsys) -> None:
    import json

    root = clause_repo(tmp_path)
    spec = root / "changes/0001-search/spec.md"
    plan = root / "changes/0001-search/plan.md"
    spec.write_text(
        CLAUSE_SPEC.replace("Results are ordered by title.", "Results are ordered by date.")
        + "- R9. not in Requirements, so not read.\n"
    )
    plan.write_text(CLAUSE_PLAN + "| AC1 | `make test` | filtered |\n")

    def ids(*ref: str) -> list[str]:
        assert main(["--root", str(root), "clauses", "0001", *ref]) == 0
        return [b["id"] for b in json.loads(capsys.readouterr().out)["requirements"]]

    # R3's text changed, and R1 has a new plan row for its criterion AC1.
    assert ids("--ref", "HEAD") == ["R1", "R3"]
    assert ids() == ["R1", "R2", "R3", "R4"]
    # A ref without the spec (a new change): check everything.
    git(root, "rm", "-q", "--cached", "changes/0001-search/spec.md")
    git(root, "commit", "-q", "-m", "drop spec")
    assert ids("--ref", "HEAD") == ["R1", "R2", "R3", "R4"]


def test_clause_coverage_reaches_every_stage() -> None:
    for path in (
        ".sdlc/skills/spec/SKILL.md",
        ".sdlc/skills/plan/SKILL.md",
        ".sdlc/agents/verifier.md",
        ".sdlc/REVIEW.md",
    ):
        text = (REPO / path).read_text()
        assert "clause" in text.lower(), path
    review = (REPO / ".sdlc/REVIEW.md").read_text()
    assert ".sdlc/scripts/clause-check.sh" in review
    assert "IDs only" in review, "the spec-match line states its basis"
    assert "Untestable (R<n>)" in (REPO / ".sdlc/templates/spec.md").read_text()
    assert "make clauses CHANGE=" in (REPO / ".sdlc/agents/verifier.md").read_text()


def test_clauses_with_a_ref_whose_spec_cant_be_read_checks_everything(
    tmp_path: Path, capsys
) -> None:
    import json

    root = init_repo(tmp_path / "repo")
    commit(root, "old", {"changes/0001-search/spec.md": "# Spec\n\n## Requirements\n\nTBD\n"})
    (root / "changes/0001-search/spec.md").write_text(CLAUSE_SPEC)
    assert main(["--root", str(root), "clauses", "0001", "--ref", "HEAD"]) == 0
    assert len(json.loads(capsys.readouterr().out)["requirements"]) == 4
