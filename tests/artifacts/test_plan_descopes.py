from pathlib import Path

import pytest

from conftest import commit, git
from sdlc.artifacts import BUG_CHAIN, CHAIN, check_change
from sdlc.cli import main

from .helpers import REPO, edited_plan, plan_with, with_dod, write


def test_merged_plan_without_descopes_stays_valid(change: Path) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    write(change / "spec.md", CHAIN["spec.md"])
    (change / "plan.md").write_text(plan_with(None))
    assert check_change(change) == []  # not known to be edited
    assert check_change(change, changed=set()) == []  # not edited on this branch


def test_edited_plan_needs_descopes(change: Path) -> None:
    [problem] = edited_plan(change, plan_with(None))
    assert problem == "missing sections: Descopes"


@pytest.mark.parametrize(
    "descopes",
    [
        "None.",
        "- Descope: dock UI widget tests because the editor can't run headless. "
        "Approved: Sam, 2026-11-10.",
        "- **Descope:** lint of game/addons/x because it's vendored. **Approved:** Sam, 2026-11-10",
        "- Descope: the export step because it needs a signing key we\n"
        "  don't have in CI. Approved: Sam, 2026-11-10.",  # wrapped
        "- Human check: walk the new room and check the lighting feels right because no test "
        "measures feel. Approved: Sam, 2026-11-10.\n"
        "- Descope: x because y. Approved: Ana (tech lead), 2026-11-10.",
    ],
)
def test_descopes_that_pass(change: Path, descopes: str) -> None:
    assert edited_plan(change, plan_with(descopes)) == []


@pytest.mark.parametrize(
    ("descopes", "expected"),
    [
        ("", "Descopes is empty"),
        ("<None., or each descope and human check, as below>", "still has the template's text"),
        ("The dock UI isn't unit-tested.", "isn't in the form"),
        ("- Descope: dock UI tests because they're slow.", "no 'Approved: <name>, <date>'"),
        ("- Descope: x because y. Approved: <name>, <date>.", "no 'Approved"),
        ("- Descope: x because y. Approved: not yet", "no 'Approved"),
        ("- Descope: x because y. Approved: TBD", "no 'Approved"),
        ("- Human check: play level 1 because feel. Approved:", "no 'Approved"),
        ("- Not tested: the dock, like the rest of it", "isn't in the form"),
        # Prose after an approved entry is an entry of its own, not part of the approved one.
        (
            "- Descope: a because b. Approved: Sam, 2026-11-10.\n\nThe dock isn't unit-tested.",
            "isn't in the form",
        ),
        (
            "- Descope: a because b. Approved: Sam, 2026-11-10.\nThe dock isn't unit-tested.",
            "isn't in the form",
        ),
        (
            "- Descope: a because b. Approved: Sam, 2026-11-10.\n\n  The dock isn't unit-tested.",
            "isn't in the form",
        ),
    ],
)
def test_descopes_that_fail(change: Path, descopes: str, expected: str) -> None:
    [problem] = edited_plan(change, plan_with(descopes))
    assert expected in problem


def test_a_descope_left_in_risks_is_reported(change: Path) -> None:
    risks = "- Descope: dock UI tests because thin. Approved: Sam, 2026-11-10."
    [problem] = edited_plan(change, plan_with("None.", risks=risks))
    assert "move it to Descopes" in problem


def test_bug_plan_needs_descopes_too(change: Path) -> None:
    with_dod(change.parents[1])
    write(change / "bug.md", BUG_CHAIN["bug.md"])
    write(change / "spec.md", BUG_CHAIN["spec.md"])
    (change / "plan.md").write_text(plan_with(None))
    [problem] = check_change(change, changed={change / "plan.md"})
    assert "Descopes" in problem.message


def test_plan_template_fails_until_descopes_are_filled(change: Path) -> None:
    template = (REPO / ".sdlc/templates/plan.md").read_text()
    problems = " | ".join(edited_plan(change, template))
    assert "Definition of done names no kind" in problems
    assert "still has the template's text" in problems
    filled = template.replace("<None., or each", "None.\n\n<!--", 1)
    filled = filled.replace("<the kinds of work that apply, e.g. Any code, UI>", "Any code")
    assert edited_plan(change, filled) == []


def test_validate_requires_descopes_only_in_plans_the_branch_edits(branch_repo: Path) -> None:
    change = "changes/0001-x/"
    sections = {n: "# T\n\n" + "".join(f"## {s}\n\ntext\n\n" for s in CHAIN[n]) for n in CHAIN}
    old_plan = plan_with(None)
    git(branch_repo, "switch", "-q", "main")
    with_dod(branch_repo)
    commit(
        branch_repo,
        "plan: merged before descopes",
        {change + "intent.md": sections["intent.md"], change + "spec.md": sections["spec.md"]}
        | {change + "plan.md": old_plan},
    )
    git(branch_repo, "switch", "-q", "-c", "next")
    root = ["--root", str(branch_repo), "check"]
    assert main(root) == 0  # merged plan, untouched

    plan = branch_repo / change / "plan.md"
    # Uncommitted, as /sdlc-plan validates before committing.
    plan.write_text(old_plan + "\nAn edit.\n")
    assert main(root) == 1
    plan.write_text(plan_with("None."))
    assert main(root) == 0
    commit(branch_repo, "plan: descopes")
    assert main(root) == 0

    new = "changes/0002-y/"
    for name in ("intent.md", "spec.md"):
        (branch_repo / new / name).parent.mkdir(parents=True, exist_ok=True)
        (branch_repo / new / name).write_text(sections[name])
    (branch_repo / new / "plan.md").write_text(plan_with(None))  # untracked
    assert main(root) == 1


def test_guardrails_point_at_the_descopes_section() -> None:
    scope = (REPO / ".sdlc/skills/scope.md").read_text()
    assert "under **Descopes**" in scope and "- Human check:" in scope
    plan = (REPO / ".sdlc/skills/plan/SKILL.md").read_text()
    assert "**Descopes**" in plan and "Human check:" in plan
    for path in (".sdlc/skills/build/SKILL.md", ".sdlc/agents/verifier.md", ".sdlc/REVIEW.md"):
        text = (REPO / path).read_text()
        assert "Descopes" in text, path


def test_human_checks_are_pending_and_listed_for_the_owner() -> None:
    verifier = (REPO / ".sdlc/agents/verifier.md").read_text()
    assert "`VERDICT: PENDING (<k> human checks)`" in verifier
    build = (REPO / ".sdlc/skills/build/SKILL.md").read_text()
    assert "**To check by hand**" in build and "`VERDICT: PENDING`" in build
    assert "**To check by hand**" in (REPO / ".sdlc/REVIEW.md").read_text()
