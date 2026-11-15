from pathlib import Path

import pytest

from sdlc.artifacts import CHAIN, check_change

from .helpers import REPO, write

# --- acceptance criteria format (#90) -----------------------------------------------------


def spec_with_criteria(change: Path, criteria: str) -> Path:
    write(change / "intent.md", CHAIN["intent.md"])
    spec = change / "spec.md"
    write(spec, [s for s in CHAIN["spec.md"] if s != "Acceptance criteria"])
    body = spec.read_text().replace("## Requirements\n\ntext", "## Requirements\n\n- R1. text")
    spec.write_text(body + f"## Acceptance criteria\n\n{criteria}\n")
    return spec


@pytest.mark.parametrize(
    "criteria",
    [
        "- AC1 (R1): `make check` exits 0.\n- AC2 (R2): prints X.",
        "- A1 (R1). Starting the app exits non-zero.\n  It names the setting.",
        "Each is a test that fails before the change.\n\n- AC1: a test shows it.",
        "- AC1 (R1): the save flow works:\n  1. open the app\n  2. click save",
    ],
)
def test_readable_criteria_are_valid(change: Path, criteria: str) -> None:
    spec_with_criteria(change, criteria)
    assert check_change(change, changed={change / "spec.md"}) == []


@pytest.mark.parametrize(
    ("criteria", "says"),
    [
        ("1. `make check` exits 0.\n2. prints X.", "numbered list"),
        ("- `make check` exits 0.", "no criterion"),
        ("Quantifiable checks.", "no criterion"),
    ],
)
def test_unreadable_criteria_fail_on_the_spec_pr(change: Path, criteria: str, says: str) -> None:
    spec_with_criteria(change, criteria)
    [problem] = check_change(change, changed={change / "spec.md"})
    assert says in problem.message and "AC<n>" in problem.message


def test_criteria_of_a_merged_spec_are_left_alone(change: Path) -> None:
    # #101 finding 9: it failed every unrelated branch, sync PRs included, until someone edited it.
    spec_with_criteria(change, "1. `make check` exits 0.")
    assert check_change(change, changed=set()) == []
    assert check_change(change, changed=None) == [], "no main to compare with: skipped"


def test_criteria_of_a_planned_spec_are_left_as_merged(change: Path) -> None:
    spec_with_criteria(change, "1. `make check` exits 0.")
    write(change / "plan.md", CHAIN["plan.md"])
    assert check_change(change) == []


def test_spec_templates_show_a_readable_criterion() -> None:
    for name in ("spec.md", "bug-spec.md"):
        text = (REPO / ".sdlc" / "templates" / name).read_text()
        assert "\n- AC1 (R1): " in text
