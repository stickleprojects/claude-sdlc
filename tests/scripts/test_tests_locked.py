import json

import pytest

from conftest import REPO, commit, git, init_repo, run

from .helpers import identity

# --- tests-locked: bug fixes lock their tests automatically -------------------------------------


@pytest.fixture
def bug_branch(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(
        repo,
        "bug: 0003-overlap",
        {"changes/0003-overlap/bug.md": "# bug\n", "changes/0004-feat/intent.md": "# i\n"},
    )
    git(repo, "switch", "-q", "-c", "build/0003-overlap")
    return repo


def locked(repo, path="", env=None):
    args = ["bash", str(REPO / ".sdlc/scripts/tests-locked.sh")] + ([path] if path else [])
    clean = {"SDLC_LOCK_TESTS": "", "SDLC_CHANGE": "", **(env or {})}
    return run(args, cwd=repo, env=clean).returncode == 0


def test_bug_tests_stay_editable_until_the_failing_test_is_committed(bug_branch):
    assert not locked(bug_branch, "tests/test_overlap.py")
    commit(
        bug_branch,
        "test(0003-overlap): failing test for overlap",
        {"tests/test_overlap.py": "x\n", "app/src/__tests__/overlap.test.tsx": "x\n"},
    )
    assert locked(bug_branch, "tests/test_overlap.py")
    assert locked(bug_branch, "app/src/__tests__/overlap.test.tsx")
    assert not locked(bug_branch, "src/overlap.py"), "code stays editable"


def test_only_the_failing_test_files_are_locked(bug_branch):
    # /sdlc-build writes more tests after the failing one (coverage, regression guards); those
    # stay editable, only what the test(<slug>) commit touched is locked.
    commit(bug_branch, "test(0003-overlap): failing test", {"tests/test_overlap.py": "x\n"})
    assert locked(bug_branch, "tests/test_overlap.py")
    assert not locked(bug_branch, "tests/test_coverage_extra.py")
    assert not locked(bug_branch, "app/e2e/screens.spec.ts")
    assert locked(bug_branch, "app/e2e/screens.spec.ts", {"SDLC_LOCK_TESTS": "1"})


def test_features_are_not_locked_by_a_test_commit(bug_branch):
    git(bug_branch, "switch", "-q", "-c", "build/0004-feat")
    commit(bug_branch, "test(0004-feat): add tests", {"tests/t.py": "x\n"})
    assert not locked(bug_branch, "tests/t.py")


def test_explicit_setting_wins(bug_branch):
    assert locked(bug_branch, "tests/t.py", {"SDLC_LOCK_TESTS": "1"})
    commit(bug_branch, "test(0003-overlap): failing test", {"tests/t.py": "x\n"})
    assert not locked(bug_branch, "tests/t.py", {"SDLC_LOCK_TESTS": "0"})


def test_change_can_be_named_explicitly(bug_branch):
    git(bug_branch, "switch", "-q", "-c", "wip")
    commit(bug_branch, "test(0003-overlap): failing test", {"tests/t.py": "x\n"})
    assert not locked(bug_branch, "tests/t.py")
    assert locked(bug_branch, "tests/t.py", {"SDLC_CHANGE": "0003-overlap"})


def test_a_later_commit_by_another_type_does_not_lock(bug_branch):
    commit(bug_branch, "feat(0003-overlap): fix it", {"tests/t.py": "x\n"})
    assert not locked(bug_branch, "tests/t.py")


def test_agent_session_locks_tests_for_a_bug_fix(bug_branch):
    commit(bug_branch, "test(0003-overlap): failing test", {"tests/t.py": "x\n"})
    out = run(
        ["bash", str(REPO / ".sdlc/scripts/agent-session.sh")],
        cwd=bug_branch,
        env={"SDLC_CLAUDE": "env", "SDLC_LOCK_TESTS": "", "XDG_CONFIG_HOME": str(bug_branch)},
    )
    assert out.returncode == 0, out.stderr
    assert "SDLC_LOCK_TESTS=1" not in out.stdout, "the hook locks just the failing test's files"
    assert "tests locked" in out.stderr and "tests/t.py" in out.stderr


def test_every_session_loads_the_agent_identity():
    settings = json.loads((REPO / ".claude/settings.json").read_text())
    commands = [h["command"] for e in settings["hooks"]["SessionStart"] for h in e["hooks"]]
    assert commands == ['"$CLAUDE_PROJECT_DIR"/.sdlc/hooks/dispatch.sh SessionStart']
    table = (REPO / ".sdlc/hooks/hooks.tsv").read_text()  # the dispatcher runs it (#133)
    assert "SessionStart\t*\t.sdlc/scripts/agent-session.sh --hook\n" in table


def test_session_hook_is_a_no_op_without_setup(tmp_path):
    env_file = tmp_path / "env"
    out = run(
        ["bash", str(REPO / ".sdlc/scripts/agent-session.sh"), "--hook"],
        env={"CLAUDE_ENV_FILE": str(env_file), "XDG_CONFIG_HOME": str(tmp_path)},
    )
    assert out.returncode == 0
    assert not env_file.exists() or env_file.read_text() == ""


def test_repos_share_one_app_and_one_key_with_use(agent_env):
    tmp, env = agent_env
    shared = tmp / "shared" / "claude.env"
    shared.parent.mkdir()
    key = env["SDLC_AGENT_KEY_FILE"]
    shared.write_text(
        f"SDLC_AGENT_APP_ID=55\nSDLC_AGENT_APP_SLUG=one-claude\nSDLC_AGENT_KEY=file:{key}\n"
    )
    no_key_env = {k: v for k, v in env.items() if k != "SDLC_AGENT_KEY_FILE"} | {
        "SDLC_AGENT_KEY_FILE": ""
    }
    for repo in ["o/jobhunt-app", "o/sandbox"]:
        e = {**no_key_env, "SDLC_AGENT_REPO": repo}
        linked = identity(e, "use", str(shared))
        assert linked.returncode == 0, linked.stderr
        assert identity(e, "show").stdout.strip() == "55 one-claude"
        assert identity(e, "token").stdout.strip() == "ghs_test", "key read from the shared file"
    assert shared.read_text().count("SDLC_AGENT_APP_ID=55") == 1, "the shared config is untouched"


def test_use_and_setup_refuse_to_replace_an_existing_config(agent_env):
    tmp, env = agent_env
    other = tmp / "other.env"
    other.write_text("SDLC_AGENT_APP_ID=9\nSDLC_AGENT_APP_SLUG=other\n")
    refused = identity(env, "use", str(other))
    assert refused.returncode == 1 and "already exists" in refused.stderr
    assert "stickle-claude" in (tmp / "config/sdlc/o_r/agent.env").read_text()
    assert identity(env, "use", str(other), "--force").returncode == 0
    setup = identity(env, "setup", "--app-id", "1", "--key", env["SDLC_AGENT_KEY_FILE"])
    assert setup.returncode == 1 and "already exists" in setup.stderr


def test_a_worktree_named_by_the_number_locks_too(bug_branch):
    commit(bug_branch, "test(0003-overlap): failing test", {"tests/test_overlap.py": "x\n"})
    worktree = bug_branch.parent / "0003"
    git(bug_branch, "worktree", "add", "-q", "-b", "wip", str(worktree))
    assert locked(worktree, "tests/test_overlap.py")
