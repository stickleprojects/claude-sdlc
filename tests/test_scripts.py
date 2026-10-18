"""Layer 1: the pipeline's shell scripts."""

import json

import pytest

from conftest import REPO, commit, git, init_repo, run

SCRIPTS = sorted(
    p.relative_to(REPO) for p in [*REPO.glob("scripts/*.sh"), *REPO.glob(".claude/hooks/*.sh")]
) + [REPO.joinpath("evals/run.sh").relative_to(REPO)]


@pytest.mark.parametrize("script", SCRIPTS, ids=str)
def test_scripts_parse(script):
    assert run(["bash", "-n", str(script)]).returncode == 0


# --- agent adapter ---------------------------------------------------------------------


def test_agent_echo_reads_stdin():
    result = run(["scripts/agent.sh", "-"], env={"AGENT": "echo"}, input="hello agent")
    assert result.returncode == 0
    assert result.stdout.strip() == "hello agent"


def test_agent_echo_reads_prompt_file(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("from a file")
    result = run(["scripts/agent.sh", str(prompt)], env={"AGENT": "echo"})
    assert result.stdout.strip() == "from a file"


def test_agent_rejects_unknown_adapter():
    result = run(["scripts/agent.sh", "-"], env={"AGENT": "nope"}, input="x")
    assert result.returncode == 2
    assert "unknown AGENT" in result.stderr


def test_agent_requires_a_prompt():
    assert run(["scripts/agent.sh"]).returncode != 0


# --- eval runner -----------------------------------------------------------------------


def _tasks(tmp_path, checks):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    for i, check in enumerate(checks):
        task = {"name": f"task {i}", "prompt": "noop", "check": check}
        (tasks / f"t{i}.json").write_text(json.dumps(task))
    return tasks


@pytest.mark.parametrize(
    ("checks", "min_rate", "passes"),
    [
        (["true", "true"], "1.0", True),
        (["true", "false"], "0.5", True),
        (["true", "false"], "0.8", False),
        (["test -f Makefile"], "1.0", True),  # checks run inside a copy of the repo
    ],
)
def test_eval_runner_pass_rate(tmp_path, checks, min_rate, passes):
    env = {
        "AGENT": "echo",
        "EVAL_TASKS_DIR": str(_tasks(tmp_path, checks)),
        "EVAL_MIN_PASS_RATE": min_rate,
    }
    result = run(["evals/run.sh"], env=env)
    assert (result.returncode == 0) is passes, result.stdout


# --- bootstrap -------------------------------------------------------------------------


def test_bootstrap_help_and_bad_args():
    assert run(["scripts/bootstrap-github.sh", "--help"]).returncode == 0
    assert run(["scripts/bootstrap-github.sh", "--bogus"]).returncode == 2


# --- next-version ----------------------------------------------------------------------


def _next_version(repo):
    result = run(["bash", str(REPO / "scripts/next-version.sh"), "--explain"], cwd=repo)
    return result.returncode, result.stdout.strip()


@pytest.fixture
def released(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(repo, "chore: initial")
    git(repo, "tag", "v0.4.2")
    return repo


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


# --- release notes ---------------------------------------------------------------------


def _notes(repo, version="v0.5.0"):
    result = run(["bash", str(REPO / "scripts/release-notes.sh"), version, "o/r"], cwd=repo)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_release_notes_group_by_type(released):
    commit(released, "Merge pull request #11 from a/b\n\nfeat: add migrate skill")
    commit(released, "fix(hooks): gate false positive (#12)")
    commit(released, "ci: faster checks (#13)")
    commit(released, "feat!: rename validate target (#14)")
    notes = _notes(released)
    assert notes.startswith("# v0.5.0 (")
    assert "This release has breaking changes" in notes
    order = ["## ⚠ Breaking changes", "## Features", "## Fixes", "## Pipeline, docs and chores"]
    positions = [notes.index(heading) for heading in order]
    assert positions == sorted(positions)
    assert "- rename validate target (#14)" in notes
    assert "- add migrate skill (#11)" in notes
    assert "- gate false positive (#12)" in notes
    assert "- faster checks (#13)" in notes
    assert "make sync-sdlc REF=v0.5.0" in notes
    assert "compare/v0.4.2...v0.5.0" in notes


def test_release_notes_omit_empty_sections(released):
    commit(released, "fix: only a fix (#3)")
    notes = _notes(released, "v0.4.3")
    assert "## Fixes" in notes
    assert "## Features" not in notes
    assert "breaking" not in notes.lower()


def test_release_notes_first_release_has_no_compare_link(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(repo, "feat: first (#1)")
    notes = _notes(repo, "v0.1.0")
    assert "- first (#1)" in notes
    assert "compare/" not in notes


def test_merge_commits_after_the_first_are_parsed(released):
    commit(released, "Merge pull request #1 from a/b\n\nfeat: older feature")
    commit(released, "Merge pull request #2 from a/b\n\nfix: newer fix")
    assert _next_version(released) == (0, "v0.5.0")
    notes = _notes(released)
    assert "- older feature (#1)" in notes
    assert "- newer fix (#2)" in notes
