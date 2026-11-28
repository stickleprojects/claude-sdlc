"""tidy-worktrees.py (#279): removes a copy of the code only when its work is finished. Each test
runs it on a scratch repo with its own origin, and `gh pr list` answered from $GH_PRS."""

import json
import os
import shutil
import subprocess
import time

import pytest

from conftest import REPO, commit, git, init_repo, run

SCRIPT = REPO / ".sdlc/scripts/tidy-worktrees.py"
FAKE_GH = """#!/usr/bin/env bash
printf '%s\\n' "${GH_PRS:-[]}"
"""


@pytest.fixture
def repo(tmp_path):
    seed = init_repo(tmp_path / "seed")
    commit(seed, "seed", {"readme.md": "x\n", ".gitignore": "scratch/\n*.log\n"})
    git(tmp_path, "clone", "-q", "--bare", str(seed), "origin.git")
    git(tmp_path, "clone", "-q", "origin.git", "main")
    root = tmp_path / "main"
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH)
    (bin_dir / "gh").chmod(0o755)

    class Repo:
        path = root
        home = tmp_path / "home"
        prs: list = []

        def copy(self, name, branch):
            """A copy on a new branch at origin/main, with no commits of its own."""
            path = root / ".claude/worktrees" / name
            git(root, "worktree", "add", "-q", "-b", branch, str(path), "origin/main")
            return path

        def pr(self, branch, state, oid):
            self.prs.append({"headRefName": branch, "state": state, "headRefOid": oid})

        def tidy(self, *args):
            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "GH_PRS": json.dumps(self.prs),
                "HOME": str(self.home),
            }
            return run(["python3", "-I", str(SCRIPT), *args], cwd=root, env=env)

    return Repo()


def line(result, name):
    return next((out for out in result.stdout.splitlines() if f" {name}" in out), "")


def test_a_finished_copy_is_listed_then_removed_with_go_and_its_own_files_saved(repo):
    done = repo.copy("0063", "build/0063-garden")
    repo.pr("build/0063-garden", "MERGED", git(done, "rev-parse", "HEAD"))
    (done / "scratch").mkdir()
    (done / "scratch/mockup.txt").write_text("hand-made\n")  # ignored, kept
    (done / "run.log").write_text("generated\n")  # ignored, a log: not kept
    listed = repo.tidy()
    assert listed.returncode == 0, listed.stderr
    assert line(listed, "0063") == "remove  0063 (build/0063-garden), saves 1 ignored file(s)"
    assert "1 to remove. Run: .sdlc/scripts/tidy-worktrees.py --go" in listed.stdout
    assert done.exists(), "listing removes nothing"
    gone = repo.tidy("--go")
    assert gone.returncode == 0, gone.stdout + gone.stderr
    assert not done.exists()
    [saved] = list(repo.home.glob(".local/state/removed-worktrees/main/*/0063/scratch/mockup.txt"))
    assert saved.read_text() == "hand-made\n"
    assert not list(repo.home.glob(".local/state/removed-worktrees/main/*/0063/run.log"))
    assert "build/0063-garden" in git(repo.path, "branch", "--list"), "the branch stays"


@pytest.mark.parametrize(
    "case, why",
    [
        ("no PR", "no merged PR"),  # a new copy with no commits looks merged: the PR decides
        ("open", "open PR"),
        ("dirty", "uncommitted: notes.txt"),
        ("unpushed", "has commits that aren't on origin/main"),
        ("other commit", "its commit isn't part of the merged PR"),
    ],
)
def test_a_copy_whose_work_isnt_finished_stays(repo, case, why):
    path = repo.copy("0064", "plan/0064-lift")
    head = git(path, "rev-parse", "HEAD")
    if case == "open":
        repo.pr("plan/0064-lift", "MERGED", head)
        repo.pr("plan/0064-lift", "OPEN", head)
    elif case == "dirty":
        repo.pr("plan/0064-lift", "MERGED", head)
        (path / "notes.txt").write_text("mine\n")
    elif case == "unpushed":
        repo.pr("plan/0064-lift", "MERGED", head)
        commit(path, "more work", {"more.md": "x\n"})
    elif case == "other commit":
        repo.pr("plan/0064-lift", "MERGED", "0" * 40)
    result = repo.tidy("--go")
    assert line(result, "0064") == f"keep    0064: {why}", result.stdout
    assert path.exists()


def test_a_copy_a_process_works_in_stays(repo, tmp_path):
    path = repo.copy("0065", "build/0065-door")
    repo.pr("build/0065-door", "MERGED", git(path, "rev-parse", "HEAD"))
    fake = tmp_path / "claude"  # bash under the name claude, working in the copy
    fake.symlink_to(shutil.which("bash"))
    proc = subprocess.Popen([str(fake), "-c", "sleep 30; :"], cwd=path)
    try:
        time.sleep(0.2)
        result = repo.tidy("--go")
        assert line(result, "0065").startswith("keep    0065: in use by claude"), result.stdout
        assert path.exists()
    finally:
        proc.kill()


def test_the_main_checkout_always_stays(repo):
    result = repo.tidy()
    assert line(result, "main") == "keep    main: the main checkout"


def test_bad_arguments_print_the_usage():
    result = run(["python3", "-I", str(SCRIPT), "--force"])
    assert result.returncode == 2 and "Usage: .sdlc/scripts/tidy-worktrees.py" in result.stdout


def test_it_is_synced_and_executable():
    assert git(REPO, "ls-files", "-s", ".sdlc/scripts/tidy-worktrees.py").startswith("100755")
