"""overlay-changes.sh: a copy of main with the PR's changed specs and plans put in, as data
(ADR 0001, #293). The clause check runs main's tool there, never the PR's Makefile."""

import os

import pytest

from conftest import REPO, commit, git, init_repo, run

from .helpers import synced

SCRIPT = REPO / ".sdlc/scripts/overlay-changes.sh"


@pytest.fixture
def repo(tmp_path):
    path = init_repo(tmp_path / "repo")
    commit(
        path,
        "main",
        {
            "Makefile": "clauses:\n\techo main\n",
            "changes/0001-old/spec.md": "old spec v1\n",
            "changes/0001-old/plan.md": "old plan v1\n",
            "changes/0002-other/spec.md": "other v1\n",
        },
    )
    git(path, "checkout", "-q", "-b", "pr")
    return path


def overlay(repo, dest):
    return run(["bash", str(SCRIPT), str(dest), "main", "pr"], cwd=repo)


def test_puts_the_prs_changed_folders_into_a_copy_of_main(repo, tmp_path):
    commit(
        repo,
        "pr",
        {
            "Makefile": "clauses:\n\techo PR CODE\n",
            "changes/0001-old/spec.md": "old spec v2\n",
            "changes/0001-old/notes.md": "pr notes\n",
            "changes/0003-new/spec.md": "new spec\n",
            "changes/0002-other/build.md": "only a build file\n",
        },
    )
    git(repo, "checkout", "-q", "main")
    commit(repo, "main moves on", {"changes/0002-other/spec.md": "other v2\n"})
    dest = tmp_path / "copy"
    result = overlay(repo, dest)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["0001-old", "0003-new"]
    assert (dest / "Makefile").read_text() == "clauses:\n\techo main\n", "never the PR's"
    assert (dest / "changes/0001-old/spec.md").read_text() == "old spec v2\n"
    assert (dest / "changes/0001-old/plan.md").read_text() == "old plan v1\n"
    assert (dest / "changes/0001-old/notes.md").read_text() == "pr notes\n"
    assert (dest / "changes/0003-new/spec.md").read_text() == "new spec\n"
    assert (dest / "changes/0002-other/spec.md").read_text() == "other v2\n", "main's own"
    assert not (dest / "changes/0002-other/build.md").exists(), "no spec or plan changed there"
    # What clause-check.sh --changed-since HEAD sees: the PR's specs and plans, new ones too.
    specs = ("changes/*/spec.md", "changes/*/plan.md")
    changed = git(dest, "diff", "--name-only", "HEAD", "--", *specs)
    assert changed.split() == ["changes/0001-old/spec.md", "changes/0003-new/spec.md"]


def test_a_folder_the_pr_trims_loses_its_files(repo, tmp_path):
    git(repo, "rm", "-q", "changes/0001-old/plan.md")
    commit(repo, "drop the plan", {"changes/0001-old/spec.md": "v2\n"})
    dest = tmp_path / "copy"
    assert overlay(repo, dest).returncode == 0
    assert not (dest / "changes/0001-old/plan.md").exists()


def test_symlinks_and_submodule_links_are_left_out(repo, tmp_path):
    folder = repo / "changes/0001-old"
    (folder / "spec.md").unlink()
    (folder / "plan.md").unlink()
    os.symlink("/proc/self/environ", folder / "spec.md")
    os.symlink("../../Makefile", folder / "plan.md")
    commit(repo, "links")
    dest = tmp_path / "copy"
    result = overlay(repo, dest)
    assert result.returncode == 0, result.stderr
    for name in ("spec.md", "plan.md"):
        target = dest / "changes/0001-old" / name
        assert not target.exists() and not target.is_symlink(), name


def test_no_spec_or_plan_changed_makes_nothing(repo, tmp_path):
    commit(repo, "code", {"src/app.py": "x\n", "changes/0001-old/build.md": "b\n"})
    dest = tmp_path / "copy"
    result = overlay(repo, dest)
    assert result.returncode == 0 and result.stdout == "" and not dest.exists()


def test_bad_usage_and_unknown_commits(repo, tmp_path):
    assert run(["bash", str(SCRIPT), str(tmp_path / "c"), "main"], cwd=repo).returncode == 2
    bad = run(["bash", str(SCRIPT), str(tmp_path / "c"), "main", "nope"], cwd=repo)
    assert bad.returncode == 3


def test_it_is_synced_and_executable():
    assert synced(".sdlc/scripts/overlay-changes.sh")
    mode = run(["git", "ls-files", "-s", ".sdlc/scripts/overlay-changes.sh"]).stdout
    assert mode.startswith("100755"), mode
