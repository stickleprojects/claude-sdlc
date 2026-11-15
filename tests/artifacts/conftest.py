from pathlib import Path

import pytest

from conftest import commit, git, init_repo


@pytest.fixture
def change(tmp_path: Path) -> Path:
    return tmp_path / "changes" / "0001-example"


# --- commit guards -------------------------------------------------------------------------


@pytest.fixture
def branch_repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "r")
    commit(repo, "chore: start", {"README.md": "x\n"})
    git(repo, "switch", "-q", "-c", "feature")
    return repo
