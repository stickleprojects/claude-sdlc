from pathlib import Path

import pytest

from conftest import commit, git, init_repo
from sdlc.artifacts import CHAIN, check_change, next_slug, stage
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


@pytest.mark.parametrize("name", list(CHAIN))
def test_templates_satisfy_their_own_rules(name: str) -> None:
    text = (REPO / "templates" / name).read_text()
    for section in CHAIN[name]:
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
