from pathlib import Path

import pytest

from conftest import commit, git, init_repo
from sdlc.artifacts import BUG_CHAIN, CHAIN, TEMPLATES, check_change, next_slug, stage
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
