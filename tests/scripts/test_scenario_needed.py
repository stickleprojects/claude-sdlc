"""scripts/scenario-needed.sh: a PR runs the slow scenario tests when it changes what they test."""

import pytest

from conftest import REPO, commit, git, init_repo, run

SCRIPT = REPO / "scripts/scenario-needed.sh"


@pytest.fixture
def repo(tmp_path):
    """A repo whose `main` is the base, on a branch `work` to change."""
    repo = init_repo(tmp_path / "repo")
    commit(repo, "chore: start", {"readme.md": "x\n", "Makefile": "x\n"})
    git(repo, "switch", "-q", "-c", "work")
    return repo


def needed(repo, base="main"):
    return run(["bash", str(SCRIPT), base], cwd=repo)


@pytest.mark.parametrize(
    "files",
    [
        ["readme.md"],
        ["docs/progress.md", "CLAUDE.md"],
        ["tests/test_routing.py"],
        ["tests/scripts/test_pr_title.py", "docs/release-notes/v9.9.9.md"],
    ],
    ids=str,
)
def test_docs_and_other_tests_leave_them_out(repo, files):
    commit(repo, "test: change", {f: "changed\n" for f in files})
    result = needed(repo)
    assert result.returncode == 1, result.stdout
    assert "only documentation and other tests changed since main" in result.stdout


@pytest.mark.parametrize(
    "path",
    [
        ".sdlc/scripts/sync-sdlc.sh",
        ".sdlc/skills/sdlc/SKILL.md",
        ".sdlc/hooks/hooks.tsv",
        ".sdlc/src/sdlc/cli.py",
        ".github/workflows/sdlc-ci.yml",
        ".claude/settings.json",
        "scripts/sync-sdlc.sh",
        "tests/test_scenario.py",
        "tests/conftest.py",
        "tests/fixtures/consumer/Makefile",
        "evals/tasks/x.json",
        "Makefile",
        "pyproject.toml",
        "uv.lock",
    ],
)
def test_anything_they_test_runs_them(repo, path):
    commit(repo, "feat: change", {path: "changed\n", "readme.md": "y\n"})
    result = needed(repo)
    assert result.returncode == 0, result.stdout
    assert f"{path} changed" in result.stdout


def test_an_uncommitted_change_counts(repo):
    (repo / ".sdlc").mkdir()
    (repo / ".sdlc/new.sh").write_text("x\n")
    result = needed(repo)
    assert result.returncode == 0 and ".sdlc/new.sh changed" in result.stdout


def test_when_unsure_it_runs_them(repo):
    assert needed(repo).stdout.strip() == "nothing changed since main"
    assert needed(repo).returncode == 0
    missing = needed(repo, base="nope")
    assert missing.returncode == 0 and "can't find nope" in missing.stdout
    git(repo, "switch", "-q", "--orphan", "unrelated")
    commit(repo, "docs: unrelated history", {"readme.md": "y\n"})
    unrelated = needed(repo)
    assert unrelated.returncode == 0 and "no merge base with main" in unrelated.stdout


def test_the_script_is_executable_in_git():
    mode = run(["git", "ls-files", "-s", "scripts/scenario-needed.sh"], cwd=REPO).stdout
    assert mode.startswith("100755"), mode
