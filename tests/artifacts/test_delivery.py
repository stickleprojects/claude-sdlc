from pathlib import Path

from conftest import commit
from sdlc.cli import main

from .helpers import CLAUSE_SPEC, REPO, clause_blocks, clause_repo

# --- delivery against each requirement (#106) -----------------------------------------------

CLAUSE_BUILD = """# Build

- **First demo:** after M1: a list

## Milestones

### M1. Search

- **Goal:** Filter the list as the user types
- **Acceptance criteria:** AC1, AC2
- **Demo:** the list filters

### M2. Export

- **Goal:** Export the list
- **Demo:** nothing, backend only

## Deviations from the plan

- R4 writes TSV, not CSV. Engineer decides: yes
"""


def test_clauses_bring_each_milestones_goal_and_demo_with_its_criteria() -> None:
    found = clause_blocks(plan=None, build=CLAUSE_BUILD)
    assert [(p.section, p.text) for p in found["R1"].build] == [
        ("M1. Search", "- **Goal:** Filter the list as the user types"),
        ("M1. Search", "- **Acceptance criteria:** AC1, AC2"),
        ("M1. Search", "- **Demo:** the list filters"),
    ]
    assert [p.text for p in found["R2"].build] == [p.text for p in found["R1"].build]
    # M2 cites nothing, so its Goal and Demo reach no requirement; a deviation citing R4 does.
    assert [p.text for p in found["R4"].build] == [
        "- R4 writes TSV, not CSV. Engineer decides: yes"
    ]
    assert found["R3"].build == []


def test_clauses_with_a_ref_notices_a_changed_build_plan(tmp_path: Path, capsys) -> None:
    import json

    root = clause_repo(tmp_path)
    commit(root, "build plan", {"changes/0001-search/build.md": CLAUSE_BUILD})
    (root / "changes/0001-search/build.md").write_text(
        CLAUSE_BUILD.replace("the list filters", "a diagram of the list")
    )
    assert main(["--root", str(root), "clauses", "0001", "--ref", "HEAD"]) == 0
    assert [b["id"] for b in json.loads(capsys.readouterr().out)["requirements"]] == ["R1", "R2"]


def test_delivery_gaps_reach_every_stage_and_escalate_only_when_unapproved() -> None:
    for path in (
        ".sdlc/agents/verifier.md",
        ".sdlc/skills/build/SKILL.md",
        ".sdlc/skills/scope.md",
        ".sdlc/REVIEW.md",
    ):
        assert "Descope: needs approval" in (REPO / path).read_text(), path
    verifier = (REPO / ".sdlc/agents/verifier.md").read_text()
    assert ".sdlc/scripts/clause-check.sh --stage build" in verifier
    assert "Wording drift" in verifier and "main verb or noun" in verifier
    assert "no routine human sign-off" in (REPO / ".sdlc/skills/scope.md").read_text()
    build = (REPO / ".sdlc/skills/build/SKILL.md").read_text()
    assert "check each milestone's Goal and Demo against the requirements" in build


def test_clauses_list_requirement_lines_they_cant_read() -> None:
    # PR #107 review: a line in another form, or an R<n> with no text, was dropped silently.
    from sdlc.clauses import blocks, unreadable

    spec = CLAUSE_SPEC.replace(
        "- R4: Export writes a CSV.",
        "- R4: Export writes a CSV.\n- Requirement 5: Import reads a CSV.\n- R6.\n"
        "3. The export is quick.\n<!-- - an HTML comment isn't a line -->",
    )
    assert unreadable(spec) == [
        "- Requirement 5: Import reads a CSV.",
        "- R6.",
        "3. The export is quick.",
    ]
    assert [b.id for b in blocks(spec)] == ["R1", "R2", "R3", "R4"], "the rest are still checked"
    # Wrapped lines, group labels and prose aren't requirements that went missing.
    assert unreadable(CLAUSE_SPEC) == []
    # Lettered requirements (spellbound3d 0006's `- **R14a.** …`) are read, not reported.
    lettered = CLAUSE_SPEC.replace("- R4: Export", "- **R4a.** Export")
    assert unreadable(lettered) == [] and "R4a" in [b.id for b in blocks(lettered)]


def test_clauses_command_warns_and_lists_unreadable_lines(tmp_path: Path, capsys) -> None:
    import json

    root = clause_repo(tmp_path)
    spec = root / "changes/0001-search/spec.md"
    spec.write_text(CLAUSE_SPEC.replace("- R4: Export", "- Requirement 4: Export"))
    for ref in ([], ["--ref", "HEAD"]):  # new since HEAD, so listed either way
        assert main(["--root", str(root), "clauses", "0001", *ref]) == 0
        out, err = capsys.readouterr()
        assert json.loads(out)["unreadable"] == ["- Requirement 4: Export writes a CSV."]
        assert "warning: can't read this as a requirement" in err
    # Once merged, an amendment that doesn't touch the line leaves it alone: done work.
    commit(root, "merged with the odd line")
    spec.write_text(spec.read_text().replace("ordered by title", "ordered by date"))
    assert main(["--root", str(root), "clauses", "0001", "--ref", "HEAD"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["unreadable"] == [] and [b["id"] for b in out["requirements"]] == ["R3"]
