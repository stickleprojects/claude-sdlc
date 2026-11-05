"""The routing table the entry skills share: each change's next step, and who owns it."""

import re
from pathlib import Path

import pytest

from conftest import commit, init_repo
from sdlc.artifacts import BUG_CHAIN, CHAIN
from sdlc.cli import main
from sdlc.routing import steps

REPO = Path(__file__).resolve().parents[1]
BUILD_TEMPLATE = (REPO / "templates" / "build.md").read_text()
ENTRY = ["intent", "plan", "build", "pr", "next"]
INTERNAL = ["spec", "po-review", "review-findings", "agent-identity", "security-policy"]


def files(sections: list[str]) -> str:
    return "# T\n\n" + "".join(f"## {s}\n\nx\n\n" for s in sections)


def change(root: Path, slug: str, upto: str, chain=CHAIN) -> Path:
    folder = root / "changes" / slug
    folder.mkdir(parents=True)
    for name, sections in chain.items():
        (folder / name).write_text(files(sections))
        if name == upto:
            break
    return folder


@pytest.mark.parametrize(
    ("upto", "skill"),
    [("intent.md", "spec"), ("spec.md", "plan"), ("plan.md", "build")],
)
def test_each_stage_points_at_the_next_skill(tmp_path: Path, upto: str, skill: str) -> None:
    change(tmp_path, "0001-x", upto)
    [step] = steps(tmp_path)
    assert step.skill == skill


def test_a_bug_routes_like_an_intent(tmp_path: Path) -> None:
    change(tmp_path, "0001-x", "bug.md", BUG_CHAIN)
    [step] = steps(tmp_path)
    assert (step.stage, step.skill) == ("bug", "spec")


def test_build_plan_states(tmp_path: Path) -> None:
    folder = change(tmp_path, "0001-x", "plan.md")
    (folder / "build.md").write_text(BUILD_TEMPLATE)
    assert steps(tmp_path)[0].detail == "approve the build plan (build.md)"
    approved = BUILD_TEMPLATE.replace("draft, awaiting approval", "in progress", 1)
    one_done = approved.replace("- **Status:** todo", "- **Status:** done", 1)
    (folder / "build.md").write_text(one_done)
    [step] = steps(tmp_path)
    assert step.skill == "build" and "1/2 milestones done; next M2" in step.detail
    (folder / "build.md").write_text(approved.replace("in progress", "PR open (#12)", 1))
    assert steps(tmp_path)[0].skill == "pr", "on the build branch, the PR is open"


def test_a_build_plan_on_main_saying_pr_open_means_merged(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "r")
    folder = change(repo, "0001-x", "plan.md")
    status = "- **Status:** draft, awaiting approval"
    (folder / "build.md").write_text(BUILD_TEMPLATE.replace(status, "- **Status:** PR open (#12)"))
    commit(repo, "feat: built")
    [step] = steps(repo, ref="HEAD")
    assert (step.skill, step.detail) == ("done", "built and merged (#12)")


def test_ref_reads_what_is_merged_not_the_working_tree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "r")
    change(repo, "0001-x", "spec.md")
    commit(repo, "spec: 0001")
    (repo / "changes/0001-x/plan.md").write_text(files(CHAIN["plan.md"]))  # not committed
    assert steps(repo)[0].skill == "build"
    assert steps(repo, ref="HEAD")[0].skill == "plan"


def test_one_change_by_number_or_slug(tmp_path: Path, capsys) -> None:
    change(tmp_path, "0001-x", "intent.md")
    change(tmp_path, "0002-y", "spec.md")
    assert main(["--root", str(tmp_path), "next", "0002"]) == 0
    assert capsys.readouterr().out == "0002-y\tspec\tplan\tplan it\n"
    assert main(["--root", str(tmp_path), "next", "0009"]) == 1


def _front(name: str) -> str:
    return (REPO / ".claude/skills" / name / "SKILL.md").read_text().split("---")[1]


@pytest.mark.parametrize("name", INTERNAL)
def test_internal_skills_are_hidden(name: str) -> None:
    assert "\nuser-invocable: false\n" in _front(name)


@pytest.mark.parametrize("name", ENTRY)
def test_entry_skills_are_visible_and_route(name: str) -> None:
    assert "user-invocable" not in _front(name)
    body = (REPO / ".claude/skills" / name / "SKILL.md").read_text()
    assert "routing" in body or name == "pr"


def test_routing_lists_exactly_the_entry_and_internal_skills() -> None:
    routing = (REPO / ".claude/skills/routing.md").read_text()
    table = re.findall(r"^\| `/([a-z]+)", routing, re.MULTILINE)
    assert table == ENTRY
    skills = {p.parent.name for p in (REPO / ".claude/skills").glob("*/SKILL.md")}
    assert skills == set(ENTRY) | set(INTERNAL), "every skill is an entry point or internal"
