"""ci-changes.sh: the files on ADR 0001's approval list that a PR changes (#293)."""

import pytest

from conftest import REPO, commit, git, init_repo, run

from .helpers import synced

SCRIPT = REPO / ".sdlc/scripts/ci-changes.sh"

ON_THE_LIST = [
    ".github/workflows/sdlc-ci.yml",
    ".github/actions/setup-stack/action.yml",
    ".github/dependabot.yml",
    ".github/CODEOWNERS",
    ".github/workflows/actions.lock",
    ".sdlc/hooks/plan-gate.sh",
    ".claude/settings.json",
    "uv.lock",
]
OFF_THE_LIST = [
    "Makefile",
    ".sdlc/scripts/clause-check.sh",
    ".sdlc/REVIEW.md",
    "readme.md",
    "src/app.py",
    "docs/uv.lock",  # only the lockfile at the root
    ".claude/settings.local.json",
]


@pytest.fixture
def repo(tmp_path):
    path = init_repo(tmp_path / "repo")
    files = {name: "v1\n" for name in ON_THE_LIST + OFF_THE_LIST + ["gone.yml"]}
    files[".github/workflows/old.yml"] = "old\n"
    commit(path, "base", files)
    git(path, "checkout", "-q", "-b", "pr")
    return path


def changes(repo, *extra):
    result = run(["bash", str(SCRIPT), "main", "pr", *extra], cwd=repo)
    return result


def test_lists_only_changed_files_on_the_approval_list(repo):
    commit(repo, "change", {name: "v2\n" for name in ON_THE_LIST + OFF_THE_LIST})
    result = changes(repo)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == sorted(ON_THE_LIST)


def test_a_deleted_or_renamed_file_counts_on_both_sides(repo):
    git(repo, "rm", "-q", ".sdlc/hooks/plan-gate.sh")
    git(repo, "mv", ".github/workflows/old.yml", "renamed.yml")
    git(repo, "mv", "gone.yml", ".github/workflows/new.yml")
    git(repo, "commit", "-q", "-m", "move")
    assert changes(repo).stdout.split() == [
        ".github/workflows/new.yml",
        ".github/workflows/old.yml",
        ".sdlc/hooks/plan-gate.sh",
    ]


def test_nothing_on_the_list_prints_nothing(repo):
    commit(repo, "product", {"src/app.py": "v2\n", "Makefile": "v2\n"})
    for extra in ((), ("--digest",)):
        result = changes(repo, *extra)
        assert result.returncode == 0 and result.stdout == "", extra


def test_compares_from_the_fork_not_mains_later_commits(repo):
    git(repo, "checkout", "-q", "main")
    commit(repo, "main moves on", {".github/workflows/sdlc-ci.yml": "main\n"})
    git(repo, "checkout", "-q", "pr")
    commit(repo, "product", {"src/app.py": "v2\n"})
    assert changes(repo).stdout == ""


def test_the_digest_changes_with_the_ci_diff_only(repo):
    commit(repo, "ci", {".github/workflows/sdlc-ci.yml": "v2\n"})
    first = changes(repo, "--digest").stdout.strip()
    assert len(first) == 16 and int(first, 16) >= 0
    commit(repo, "product", {"src/app.py": "v2\n"})
    assert changes(repo, "--digest").stdout.strip() == first
    commit(repo, "same file again", {".github/workflows/sdlc-ci.yml": "v3\n"})
    assert changes(repo, "--digest").stdout.strip() != first


def test_bad_usage_and_unknown_commits(repo):
    for args in ((), ("main",), ("main", "pr", "--all")):
        assert run(["bash", str(SCRIPT), *args], cwd=repo).returncode == 2, args
    assert run(["bash", str(SCRIPT), "main", "nope"], cwd=repo).returncode == 3


def test_it_is_synced_and_executable():
    assert synced(".sdlc/scripts/ci-changes.sh")
    mode = run(["git", "ls-files", "-s", ".sdlc/scripts/ci-changes.sh"]).stdout
    assert mode.startswith("100755"), mode


def test_filter_reads_paths_on_stdin():
    paths = "\n".join(ON_THE_LIST + OFF_THE_LIST) + "\n"
    result = run(["bash", str(SCRIPT), "--filter"], input=paths)
    assert result.returncode == 0 and result.stdout.split() == ON_THE_LIST
    assert run(["bash", str(SCRIPT), "--filter"], input="").stdout == ""


def test_a_name_git_would_quote_is_still_on_the_list(repo):
    """PR #307's review: `git diff --name-only` quotes a non-ASCII name, so it missed the list."""
    odd = [
        ".github/workflows/ünïcode.yml",
        '.github/workflows/a "quoted" name.yml',
        ".github/[x].yml",
    ]
    commit(repo, "odd names", {name: "v1\n" for name in odd})
    assert sorted(changes(repo).stdout.splitlines()) == sorted(odd)
    first = changes(repo, "--digest").stdout.strip()
    commit(repo, "edit one", {".github/[x].yml": "v2\n"})
    assert changes(repo, "--digest").stdout.strip() != first
