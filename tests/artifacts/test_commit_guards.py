from pathlib import Path

from conftest import commit, git
from sdlc.cli import check_commits, main


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


def test_large_change_trailer_allows_a_big_branch(branch_repo: Path, monkeypatch, capsys) -> None:
    # #63: a PR can't set an env var in CI, but it can carry a commit trailer.
    monkeypatch.setenv("SDLC_MAX_CHANGED_FILES", "3")
    commit(branch_repo, "big", {f"out/{i}.txt": "x\n" for i in range(4)})
    [problem] = check_commits(branch_repo)
    assert "Large-change: <reason>" in problem
    git(
        branch_repo,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "chore: scaffold",
        "-m",
        "Large-change: generated API client",
    )
    assert check_commits(branch_repo) == []
    assert "allowed by Large-change: generated API client" in capsys.readouterr().err


def test_large_change_trailer_still_rejects_node_modules(branch_repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDLC_MAX_CHANGED_FILES", "1")
    commit(branch_repo, "oops", {"node_modules/x/index.js": "x\n", "a.txt": "x\n"})
    git(branch_repo, "commit", "-q", "--allow-empty", "-m", "c", "-m", "Large-change: why")
    [problem] = check_commits(branch_repo)
    assert "node_modules" in problem


def test_normal_branch_passes_commit_guards(branch_repo: Path) -> None:
    commit(branch_repo, "small", {"src/a.py": "x\n", "src/node_modules_helper.py": "x\n"})
    assert check_commits(branch_repo) == []


def test_commit_guards_skip_outside_git(tmp_path: Path) -> None:
    assert check_commits(tmp_path) == []
