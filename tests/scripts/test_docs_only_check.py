import os
import re
import shutil

import pytest

from conftest import REPO, commit, git, init_repo, run

# --- make check skips the tests for a docs-only branch (#140) -------------------------------

DOCS_ONLY = REPO / "scripts/docs-only.sh"


@pytest.fixture
def docs_repo(tmp_path):
    """A repo whose `main` is the base, on a branch `work` to change."""
    repo = init_repo(tmp_path / "repo")
    commit(repo, "chore: start", {"readme.md": "x\n", "Makefile": "x\n"})
    git(repo, "switch", "-q", "-c", "work")
    return repo


def docs_only(repo, base="main"):
    return run(["bash", str(DOCS_ONLY), base], cwd=repo)


@pytest.mark.parametrize(
    "files",
    [
        ["readme.md"],
        ["CLAUDE.md", "docs/progress.md"],
        ["docs/assets/logo.svg", "readme.md"],
        ["docs/issue-priorities.md"],
    ],
    ids=str,
)
def test_docs_only_branch_is_recognised(docs_repo, files):
    commit(docs_repo, "docs: change", {f: "changed\n" for f in files})
    result = docs_only(docs_repo)
    assert result.returncode == 0, result.stdout
    assert f"only documentation changed since main ({len(files)} file" in result.stdout


@pytest.mark.parametrize(
    "path",
    [
        ".sdlc/skills/sdlc/SKILL.md",  # skills, templates, prompts and REVIEW.md are tested
        ".sdlc/REVIEW.md",
        ".claude/skills/sdlc-next/SKILL.md",
        ".github/pull_request_template.md",
        "changes/0001-x/spec.md",
        "tests/fixtures/consumer/readme.md",
        "evals/fixtures/a/spec.md",
        "docs/release-notes/v9.9.9.md",  # the release tests read them
        "Makefile",
        "scripts/docs-only.sh",
        "pyproject.toml",
    ],
)
def test_any_other_change_runs_the_tests(docs_repo, path):
    commit(docs_repo, "feat: change", {"readme.md": "changed\n", path: "changed\n"})
    result = docs_only(docs_repo)
    assert result.returncode == 1
    assert f"{path} changed" in result.stdout


def test_uncommitted_and_untracked_changes_count(docs_repo):
    # A local `make check` before committing sees the change CI will.
    (docs_repo / "readme.md").write_text("edited, not committed\n")
    assert docs_only(docs_repo).returncode == 0
    (docs_repo / "new.py").write_text("print()\n")
    result = docs_only(docs_repo)
    assert result.returncode == 1 and "new.py changed" in result.stdout
    (docs_repo / "new.py").unlink()
    (docs_repo / "Makefile").write_text("edited\n")
    assert docs_only(docs_repo).returncode == 1


def test_when_unsure_everything_runs(docs_repo):
    assert "nothing changed since main" in docs_only(docs_repo).stdout
    assert docs_only(docs_repo).returncode == 1
    commit(docs_repo, "docs: change", {"readme.md": "changed\n"})
    missing = docs_only(docs_repo, base="origin/main")  # no such ref
    assert missing.returncode == 1 and "can't find origin/main" in missing.stdout
    git(docs_repo, "switch", "-q", "--orphan", "unrelated")
    commit(docs_repo, "docs: unrelated history", {"readme.md": "y\n"})
    unrelated = docs_only(docs_repo)  # no merge base, as in a shallow clone
    assert unrelated.returncode == 1 and "no merge base with main" in unrelated.stdout


@pytest.fixture
def make_repo(docs_repo, tmp_path):
    """The framework's Makefile in a throwaway repo, with a `uv` that only says it ran."""
    for path in ("Makefile", ".sdlc/sdlc.mk", "scripts/docs-only.sh", "scripts/scenario-needed.sh"):
        target = docs_repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / path, target)
    git(docs_repo, "add", "-A")
    git(docs_repo, "commit", "-q", "-m", "chore: the framework's Makefile")
    git(docs_repo, "branch", "-f", "main")  # the Makefile is on main: not part of the change
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "uv").write_text('#!/bin/sh\necho "uv $*"\n')
    (fake / "uv").chmod(0o755)
    # An outer `make check FULL=1` (CI on main) hands FULL=1 to every make below it through
    # MAKEFLAGS, where it beats the environment, so the inner make starts with none.
    # TEST_ARGS likewise: `make check` without FULL runs these tests with it set.
    env = {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "FULL": "",
        "TEST_ARGS": "",
        "MAKEFLAGS": "",
        "MAKELEVEL": "",
    }
    return docs_repo, env


def test_make_check_test_skips_the_suite_for_docs_only(make_repo):
    repo, env = make_repo
    commit(repo, "docs: change", {"readme.md": "changed\n"})
    result = run(["make", "check-test", "CHECK_BASE=main"], cwd=repo, env=env)
    assert result.returncode == 0, result.stderr
    assert "test: skipped, only documentation changed since main (1 file)" in result.stdout
    assert "(FULL=1 runs it)" in result.stdout
    assert "uv run pytest" not in result.stdout


def test_make_check_test_runs_the_suite_for_code_or_full(make_repo):
    repo, env = make_repo
    commit(repo, "docs: change", {"readme.md": "changed\n"})
    full = run(["make", "check-test", "CHECK_BASE=main", "FULL=1"], cwd=repo, env=env)
    assert "uv run pytest -q" in full.stdout and "skipped" not in full.stdout
    assert "not scenario" not in full.stdout
    commit(repo, "test: change", {"tests/test_x.py": "x = 1\n"})
    tests_only = run(["make", "check-test", "CHECK_BASE=main"], cwd=repo, env=env)
    assert "uv run pytest -q -m not scenario" in tests_only.stdout
    assert (
        "test: without the scenario tests, only documentation and other tests changed since "
        "main (FULL=1 runs them)" in tests_only.stdout
    )
    full = run(["make", "check-test", "CHECK_BASE=main", "FULL=1"], cwd=repo, env=env)
    assert "uv run pytest -q" in full.stdout and "not scenario" not in full.stdout


@pytest.mark.parametrize("path", [".sdlc/scripts/x.sh", "src.py", "tests/test_scenario.py"])
def test_make_check_test_runs_the_scenario_tests_for_what_they_test(make_repo, path):
    repo, env = make_repo
    commit(repo, "feat: change", {path: "x = 1\n"})
    code = run(["make", "check-test", "CHECK_BASE=main"], cwd=repo, env=env)
    assert code.returncode == 0, code.stderr
    assert f"test: everything, scenario tests included: {path} changed" in code.stdout
    assert code.stdout.strip().splitlines()[-1] == "uv run pytest -q"


def test_make_test_runs_everything(make_repo):
    repo, env = make_repo
    result = run(["make", "test"], cwd=repo, env=env)
    assert result.stdout.strip().splitlines()[-1] == "uv run pytest -q"


def test_the_scenario_tests_are_marked_and_main_and_the_release_run_them():
    assert "pytestmark = pytest.mark.scenario" in (REPO / "tests/test_scenario.py").read_text()
    assert '"scenario:' in (REPO / "pyproject.toml").read_text()
    release = (REPO / ".github/workflows/release.yml").read_text()
    assert "- run: make check FULL=1" in release


def test_check_runs_the_tests_through_check_test_and_main_runs_them_all():
    makefile = (REPO / "Makefile").read_text()
    assert re.search(r"^check: lint check-test validate exec-bits$", makefile, re.MULTILINE)
    ci = (REPO / ".github/workflows/sdlc-ci.yml").read_text()
    assert "- run: make check ${{ github.event_name == 'push' && 'FULL=1' || '' }}" in ci
    assert "fetch-depth: 0" in ci
    release = (REPO / ".github/workflows/release.yml").read_text()
    assert "- run: make check FULL=1" in release
