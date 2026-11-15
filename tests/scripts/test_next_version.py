import pytest

from conftest import commit, git, init_repo

from .helpers import _next_version


def test_first_release_is_0_1_0(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(repo, "chore: initial")
    assert _next_version(repo) == (0, "v0.1.0")


def test_nothing_to_release(released):
    assert _next_version(released)[0] == 1


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        (["fix: a bug"], "v0.4.3"),
        (["ci: tweak", "docs: words"], "v0.4.3"),
        (["fix: a", "feat: new skill"], "v0.5.0"),
        (["feat(hooks): scoped"], "v0.5.0"),
        (["feat!: drop make target"], "v0.5.0"),  # breaking while 0.x bumps minor
        (["fix: x\n\nBREAKING CHANGE: renamed"], "v0.5.0"),
        (["Merge pull request #7 from a/b\n\nfeat: via merge commit"], "v0.5.0"),
        (["Merge pull request #8 from a/b\n\nfix: via merge commit"], "v0.4.3"),
    ],
)
def test_bump_from_titles(released, messages, expected):
    for message in messages:
        commit(released, message)
    assert _next_version(released) == (0, expected)


def test_breaking_change_after_1_0_bumps_major(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(repo, "chore: initial")
    git(repo, "tag", "v1.2.3")
    commit(repo, "feat!: new contract")
    assert _next_version(repo) == (0, "v2.0.0")
