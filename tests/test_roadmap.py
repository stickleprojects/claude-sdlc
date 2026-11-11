"""The optional roadmap check (#81): docs/roadmap.md, intents and adjustment records agree."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import commit, git, init_repo
from sdlc.artifacts import CHAIN
from sdlc.cli import main
from sdlc.roadmap import check_roadmap

REPO = Path(__file__).resolve().parents[1]

HEADER = "# Roadmap\n\n"


def milestone(n: int, status: str, rows: list[tuple[str, str]], criteria: str | None = None):
    tick = "✅ " if status == "done" else ""
    if criteria is None:
        criteria = "- [x] It works.\n" if status == "done" else "- [ ] It works.\n"
    parts = [f"## M{n}: Milestone {n} · {tick}`{status}`\n\n**Goal:** a goal.\n\n"]
    if criteria:
        parts.append(f"**Exit criteria**\n{criteria}\n")
    parts.append("### Changes\n\n| Change | Summary | Status |\n|---|---|---|\n")
    for slug, row_status in rows:
        parts.append(f"| [{slug}](../changes/{slug}/) | A summary | {row_status} |\n")
    return "".join(parts) + "\n"


def intent(milestone_line: str | None = "Milestone: M1", extra: str = "") -> str:
    head = "# Intent: x\n\nOriginator: a\nProduct owner: b\n"
    if milestone_line:
        head += milestone_line + "\n"
    head += extra
    return head + "".join(f"\n## {s}\n\ntext\n" for s in CHAIN["intent.md"])


def record(status: str = "accepted", milestones: str = "M1", supersedes: str = "") -> str:
    lines = [
        "# Adjustment 0001: x\n",
        f"Status: {status}",
        f"Milestones: {milestones}",
        "Changes: scope",
        "Intent: [0001-a](../../../changes/0001-a/)",
    ]
    if supersedes:
        lines.append(f"Supersedes: {supersedes}")
    return "\n".join(lines) + "\n\n## What changes\n\nScope.\n\n## Why\n\nReason.\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path


def setup(root: Path, roadmap: str, changes: dict[str, dict[str, str]]) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "roadmap.md").write_text(HEADER + roadmap)
    for slug, files in changes.items():
        for name, text in files.items():
            path = root / "changes" / slug / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)


def messages(root: Path, branch: str | None = "main") -> list[str]:
    return [str(p) for p in check_roadmap(root, branch)]


def test_no_roadmap_means_no_check(repo: Path) -> None:
    setup(repo, "", {"0001-a": {"intent.md": intent(None)}})
    (repo / "docs" / "roadmap.md").unlink()
    assert messages(repo) == []


def test_agreeing_roadmap_and_intents_pass(repo: Path) -> None:
    roadmap = milestone(1, "in progress", [("0001-a", "planned")]) + milestone(2, "draft", [], "")
    setup(repo, roadmap, {"0001-a": {"intent.md": intent()}})
    assert messages(repo) == []


def test_the_shipped_template_passes_with_no_changes(repo: Path) -> None:
    (repo / "docs").mkdir()
    (repo / "docs" / "roadmap.md").write_text((REPO / "templates" / "roadmap.md").read_text())
    assert messages(repo) == []


def test_bug_only_folders_are_ignored(repo: Path) -> None:
    setup(repo, milestone(1, "draft", [], ""), {"0001-b": {"bug.md": "# Bug\n"}})
    assert messages(repo) == []


def test_an_intent_without_a_row_fails(repo: Path) -> None:
    setup(repo, milestone(1, "draft", [], ""), {"0001-a": {"intent.md": intent()}})
    [problem] = messages(repo)
    assert "changes/0001-a: no row in docs/roadmap.md" in problem


def test_a_row_without_a_change_fails(repo: Path) -> None:
    setup(repo, milestone(1, "draft", [("0009-ghost", "planned")], ""), {})
    [problem] = messages(repo)
    assert "row 0009-ghost names no change" in problem


@pytest.mark.parametrize(
    "line, expected",
    [
        (None, "no Milestone: line"),
        ("Milestone: one", "is not M<number>"),
        ("Milestone: M7", "M7 is not a milestone"),
    ],
)
def test_the_intent_names_one_real_milestone(repo: Path, line, expected) -> None:
    setup(
        repo,
        milestone(1, "draft", [("0001-a", "planned")], ""),
        {"0001-a": {"intent.md": intent(line)}},
    )
    assert any(expected in m for m in messages(repo))


def test_a_milestone_line_in_a_comment_does_not_count(repo: Path) -> None:
    text = intent(None, "<!-- Milestone: M1 -->\n")
    setup(repo, milestone(1, "draft", [("0001-a", "planned")], ""), {"0001-a": {"intent.md": text}})
    assert any("no Milestone: line" in m for m in messages(repo))


def test_the_row_sits_under_the_intents_milestone(repo: Path) -> None:
    roadmap = milestone(1, "draft", [], "") + milestone(2, "draft", [("0001-a", "planned")], "")
    setup(repo, roadmap, {"0001-a": {"intent.md": intent("Milestone: M1")}})
    [problem] = messages(repo)
    assert "intent.md says M1, but its row is under M2" in problem


@pytest.mark.parametrize(
    "row, expected",
    [
        ("done", "write a done row's status as '✅ done'"),
        ("✅ planned", "and no other with ✅"),
        ("started", "status 'started' is not one of"),
    ],
)
def test_row_statuses_and_the_tick(repo: Path, row: str, expected: str) -> None:
    setup(repo, milestone(1, "draft", [("0001-a", row)], ""), {"0001-a": {"intent.md": intent()}})
    assert any(expected in m for m in messages(repo))


def test_an_unbuilt_change_must_be_planned(repo: Path) -> None:
    setup(
        repo,
        milestone(1, "draft", [("0001-a", "✅ done")], ""),
        {"0001-a": {"intent.md": intent()}},
    )
    [problem] = messages(repo)
    assert "row is done, but its build has not merged" in problem


def test_its_build_branch_may_mark_it_done(repo: Path) -> None:
    setup(
        repo,
        milestone(1, "draft", [("0001-a", "✅ done")], ""),
        {"0001-a": {"intent.md": intent()}},
    )
    assert messages(repo, branch="build/0001-a") == []


def test_build_md_pr_open_must_be_done(repo: Path) -> None:
    build = "# Build\n\n- **Status:** PR open (#4)\n"
    files = {"intent.md": intent(), "plan.md": "# Plan\n", "build.md": build}
    setup(repo, milestone(1, "draft", [("0001-a", "planned")], ""), {"0001-a": files})
    [problem] = messages(repo)
    assert "build.md says PR open, so it must be done" in problem


def test_an_unmerged_small_build_may_be_either(repo: Path) -> None:
    files = {"intent.md": intent(), "plan.md": "# Plan\n"}
    for row in ("planned", "✅ done"):
        setup(repo, milestone(1, "draft", [("0001-a", row)], ""), {"0001-a": files})
        assert messages(repo) == []


def test_a_merged_small_build_must_be_done(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    files = {"intent.md": intent(), "plan.md": "# Plan\n"}
    setup(root, milestone(1, "draft", [("0001-a", "planned")], ""), {"0001-a": files})
    commit(root, "plan")
    git(root, "checkout", "-q", "-b", "build/0001-a")
    commit(root, "feat(0001-a): build it")
    git(root, "checkout", "-q", "main")
    git(
        root,
        "merge",
        "-q",
        "--no-ff",
        "build/0001-a",
        "-m",
        "Merge pull request #7 from o/build/0001-a",
    )
    [problem] = messages(root)
    assert "its build merged (#7), so it must be done" in problem


def test_a_withdrawn_intent_must_be_withdrawn(repo: Path) -> None:
    text = intent(extra="Withdrawn: b, 2026-11-12: not needed\n")
    setup(repo, milestone(1, "draft", [("0001-a", "planned")], ""), {"0001-a": {"intent.md": text}})
    [problem] = messages(repo)
    assert "row is planned, but the intent is withdrawn" in problem


def test_withdrawn_needs_a_withdrawn_line(repo: Path) -> None:
    setup(
        repo,
        milestone(1, "draft", [("0001-a", "withdrawn")], ""),
        {"0001-a": {"intent.md": intent()}},
    )
    [problem] = messages(repo)
    assert "the intent has no Withdrawn: line" in problem


def test_a_done_milestone_needs_its_tick_and_only_it(repo: Path) -> None:
    roadmap = "## M1: One · `done`\n\n" + "## M2: Two · ✅ `agreed`\n\n"
    setup(repo, roadmap, {})
    problems = messages(repo)
    assert len(problems) == 2
    assert all("only a done one, has ✅" in p for p in problems)


def test_a_done_milestone_has_only_done_or_withdrawn_rows(repo: Path) -> None:
    files = {"intent.md": intent()}
    setup(repo, milestone(1, "done", [("0001-a", "planned")]), {"0001-a": files})
    assert any("M1 is done, but 0001-a is planned" in m for m in messages(repo))


def test_a_done_milestone_has_every_exit_criterion_ticked(repo: Path) -> None:
    setup(repo, milestone(1, "done", [], "- [x] One.\n- [ ] Two.\n"), {})
    [problem] = messages(repo)
    assert "M1 is done, but an exit criterion isn't: - [ ] Two." in problem


@pytest.mark.parametrize("status", ["agreed", "in progress"])
def test_a_milestone_past_draft_needs_exit_criteria(repo: Path, status: str) -> None:
    setup(repo, milestone(1, status, [], ""), {})
    [problem] = messages(repo)
    assert f"M1 is {status}, but has no **Exit criteria**" in problem


def test_a_draft_milestone_may_have_no_exit_criteria_yet(repo: Path) -> None:
    setup(repo, milestone(1, "draft", [], ""), {})
    assert messages(repo) == []


def test_other_sections_are_not_milestones(repo: Path) -> None:
    roadmap = milestone(1, "draft", [], "") + "## Later, not yet ordered\n\n- Something.\n"
    setup(repo, roadmap, {})
    assert messages(repo) == []


@pytest.mark.parametrize(
    "roadmap, expected",
    [
        ("## M1 Missing colon\n", "milestone heading is not"),
        ("## M1: One · `someday`\n", "milestone heading is not"),
        (milestone(1, "draft", [], "") + milestone(1, "draft", [], ""), "M1 appears twice"),
        ("### Changes\n\n| Change | Summary | Status |\n|---|---|---|\n", "is not under a ## M<n>"),
        ("## M1: One · `draft`\n\n### Changes\n\nNo table.\n", "has no | Change | Summary"),
        (
            "## M1: One · `draft`\n\n### Changes\n\n| Change | Summary | Status |\n|---|---|---|\n"
            "| 0001-a | x | planned |\n",
            "is not [NNNN-slug](../changes/NNNN-slug/)",
        ),
        (
            "## M1: One · `draft`\n\n### Changes\n\n| Change | Summary | Status |\n|---|---|---|\n"
            "| [0001-a](../changes/0001-a/) | planned |\n",
            "row has 2 cells, expected 3",
        ),
    ],
)
def test_unreadable_roadmaps_fail_and_name_the_line(
    repo: Path, roadmap: str, expected: str
) -> None:
    setup(repo, roadmap, {})
    problems = messages(repo)
    assert any(expected in p for p in problems), problems
    assert all(p.startswith("docs/roadmap.md:") for p in problems)


def write_record(root: Path, name: str, text: str) -> None:
    folder = root / "docs" / "roadmap" / "adjustments"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.md").write_text(text)


def test_an_adjustment_line_names_an_accepted_record(repo: Path) -> None:
    text = intent(extra="Adjustment: 0001-wider\n")
    setup(repo, milestone(1, "draft", [("0001-a", "planned")], ""), {"0001-a": {"intent.md": text}})
    assert any(
        "has no record at docs/roadmap/adjustments/0001-wider.md" in m for m in messages(repo)
    )
    write_record(repo, "0001-wider", record("proposed"))
    assert any("Adjustment: 0001-wider is proposed, not accepted" in m for m in messages(repo))
    write_record(repo, "0001-wider", record("accepted"))
    assert messages(repo) == []


@pytest.mark.parametrize(
    "text, expected",
    [
        (record("maybe"), "Status: 'maybe' is not one of"),
        (record(milestones="M9"), "Milestones: M9 is not a milestone"),
        (record(milestones="one"), "Milestones: 'one' is not M<number>"),
        (record().replace("Changes: scope", "Changes: everything"), "Changes: 'everything'"),
        (record().replace("0001-a", "0042-b"), "Intent: 'changes/0042-b' links to no change"),
        (record().replace("## Why\n\nReason.\n", ""), "no ## Why section"),
        (record().replace("Scope.", ""), "## What changes is empty"),
        (record().replace("Status: accepted\n", ""), "no Status: line"),
        (record(supersedes="0007"), "Supersedes: 0007 names no record"),
    ],
)
def test_records_are_checked_field_by_field(repo: Path, text: str, expected: str) -> None:
    setup(
        repo,
        milestone(1, "draft", [("0001-a", "planned")], ""),
        {"0001-a": {"intent.md": intent()}},
    )
    write_record(repo, "0001-wider", text)
    assert any(expected in m for m in messages(repo)), messages(repo)


def test_a_superseded_record_must_say_so(repo: Path) -> None:
    setup(
        repo,
        milestone(1, "draft", [("0001-a", "planned")], ""),
        {"0001-a": {"intent.md": intent()}},
    )
    write_record(repo, "0001-first", record("accepted"))
    write_record(repo, "0002-second", record("accepted", supersedes="0001"))
    assert any("Supersedes: 0001 is accepted, not superseded" in m for m in messages(repo))
    write_record(repo, "0001-first", record("superseded"))
    assert messages(repo) == []


def test_a_badly_named_record_fails(repo: Path) -> None:
    setup(repo, milestone(1, "draft", [], ""), {})
    write_record(repo, "Wider", record())
    assert any("name is not NNNN-<slug>.md" in m for m in messages(repo))


def test_make_validate_runs_the_roadmap_check(repo: Path, capsys) -> None:
    setup(repo, milestone(1, "draft", [], ""), {"0001-a": {"intent.md": intent()}})
    assert main(["--root", str(repo), "check"]) == 1
    assert "no row in docs/roadmap.md" in capsys.readouterr().err
