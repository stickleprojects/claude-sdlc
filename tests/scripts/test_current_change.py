"""current-change.sh: which change a copy of the code is for (#279)."""

import pytest

from conftest import REPO, commit, git, init_repo, run


@pytest.fixture
def repo(tmp_path):
    repo = init_repo(tmp_path / "r")
    files = {f"changes/{s}/intent.md": "# i\n" for s in ("0003-x", "0005-a", "0005-b")}
    commit(repo, "changes", files)
    return repo


def current(cwd, env=None):
    script = str(REPO / ".sdlc/scripts/current-change.sh")
    result = run([script], cwd=cwd, env={"SDLC_CHANGE": "", **(env or {})})
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def worktree(repo, folder, branch):
    path = repo.parent / folder
    git(repo, "worktree", "add", "-q", "-b", branch, str(path))
    return path


@pytest.mark.parametrize("branch", ["build/0003-x", "plan/0003-x", "fix/0003-x"])
def test_the_branch_names_the_change(repo, branch):
    git(repo, "switch", "-q", "-c", branch)
    assert current(repo) == "0003-x"
    assert current(repo / "changes") == "0003-x", "from a folder below the top too"


@pytest.mark.parametrize("branch", ["main", "chore/bump", "build/0009-gone"])
def test_no_change(repo, branch):
    if branch != "main":
        git(repo, "switch", "-q", "-c", branch)
    assert current(repo) == ""


@pytest.mark.parametrize(
    ("folder", "slug"),
    [("0003", "0003-x"), ("0003-x", "0003-x"), ("0005", ""), ("0009", ""), ("copy-0003", "")],
)
def test_the_folder_names_the_change_when_the_branch_does_not(repo, folder, slug):
    assert current(worktree(repo, folder, "wip")) == slug


def test_the_branch_beats_the_folder(repo):
    assert current(worktree(repo, "0003", "build/0005-a")) == "0005-a"


def test_sdlc_change_beats_both(repo):
    git(repo, "switch", "-q", "-c", "build/0003-x")
    assert current(repo, {"SDLC_CHANGE": "0005-a"}) == "0005-a"


def test_outside_a_repo(tmp_path):
    assert current(tmp_path) == ""
