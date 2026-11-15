from pathlib import Path

import pytest

from sdlc.artifacts import CHAIN, check_change

from .helpers import REPO, write

# --- readable requirements in new and edited specs (#47) --------------------------------------


@pytest.mark.parametrize(
    ("requirements", "problem"),
    [
        ("- R1. The list has a search box.", None),
        ("- R1. Search.\n- Requirement 2: Export.", "can't read this as a requirement"),
        ("- R1. Search.\n- R2.", "can't read this as a requirement"),
        ("The list has a search box.", "no requirement under ## Requirements can be read"),
    ],
)
def test_an_edited_spec_needs_requirements_the_clause_check_can_read(
    change: Path, requirements: str, problem: str | None
) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    spec = change / "spec.md"
    write(spec, CHAIN["spec.md"])
    spec.write_text(
        spec.read_text().replace("## Requirements\n\ntext", f"## Requirements\n\n{requirements}")
    )
    found = [p.message for p in check_change(change, changed={spec})]
    if problem is None:
        assert found == []
    else:
        assert len(found) == 1 and problem in found[0]
    assert check_change(change, changed=set()) == [], "a merged spec is left alone"
    assert check_change(change, changed=None) == [], "no main to compare with: skipped"


def test_the_spec_templates_show_a_requirement_the_checks_read() -> None:
    from sdlc.clauses import blocks, unreadable

    for name in ("spec.md", "bug-spec.md"):
        text = (REPO / ".sdlc" / "templates" / name).read_text()
        assert [b.id for b in blocks(text)] == ["R1"] and unreadable(text) == [], name
