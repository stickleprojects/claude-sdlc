"""Layer 1: the guardrail hooks block and allow exactly what they should."""

import pytest

from conftest import REPO, hook

DEPLOY = "deploy" + "-prod"  # split so this file's own text never trips the gate


@pytest.mark.parametrize(
    ("command", "blocked"),
    [
        (f"make {DEPLOY}", True),
        (f"make {DEPLOY} RELEASE_AUTHORIZED_BY=me", True),
        ("make deploy-dev", False),
        ("git push origin main", True),
        ("git push origin HEAD:main", True),
        ("git push origin master", True),
        ("git push --force origin feat", True),
        ("git push -f origin feat", True),
        ("git push --force-with-lease origin feat", True),
        ("git fetch && git push origin main", True),
        ("cd repo; git push origin main", True),
        ("git push -u origin feat/x", False),
        ("git push -u origin feat/main-fix", False),
        ("git push", False),
        ("git merge -q --no-edit main && git push -q", False),
        ("git switch main && git pull", False),
        ("make check", False),
    ],
)
def test_production_gate(command, blocked):
    result = hook("production-gate.sh", {"tool_input": {"command": command}})
    assert result.returncode == (2 if blocked else 0), result.stderr
    if blocked:
        assert "Blocked" in result.stderr


@pytest.mark.parametrize(
    ("rel_path", "env", "blocked"),
    [
        (".claude/settings.json", {}, True),
        (".claude/hooks/production-gate.sh", {}, True),
        (".git/config", {}, True),
        ("uv.lock", {}, True),
        (".env", {}, True),
        (".env.local", {}, True),
        ("certs/server.pem", {}, True),
        ("tests/test_x.py", {"SDLC_LOCK_TESTS": "1"}, True),
        ("tests/test_x.py", {}, False),
        ("src/sdlc/cli.py", {"SDLC_LOCK_TESTS": "1"}, False),
        (".claude/skills/intent/SKILL.md", {}, False),
        ("docs/roles.md", {}, False),
    ],
)
def test_protect_paths(rel_path, env, blocked):
    payload = {"tool_input": {"file_path": str(REPO / rel_path)}}
    result = hook("protect-paths.sh", payload, env=env)
    assert result.returncode == (2 if blocked else 0), result.stderr


def test_protect_paths_reads_notebook_path():
    payload = {"tool_input": {"notebook_path": str(REPO / ".env")}}
    assert hook("protect-paths.sh", payload).returncode == 2


def test_protect_paths_ignores_tools_without_a_path():
    assert hook("protect-paths.sh", {"tool_input": {}}).returncode == 0


def test_format_hook_never_fails():
    payload = {"tool_input": {"file_path": str(REPO / "does-not-exist.py")}}
    assert hook("format.sh", payload).returncode == 0


MERGE = "gh pr " + "merge"  # split so this file's text never trips the gate


@pytest.mark.parametrize(
    ("command", "blocked"),
    [
        (f"{MERGE} 21", True),
        (f"{MERGE} 21 --merge --admin --delete-branch", True),
        (f"git fetch && {MERGE} 21 --squash", True),
        ("gh pr review 21 --approve", True),
        ("gh pr review 21 -a -b lgtm", True),
        ("gh api -X PUT repos/o/r/pulls/21/merge", True),
        ("gh api repos/o/r/pulls/21/reviews -f event=APPROVE", True),
        ("gh pr review 21 --comment -b 'see inline'", False),
        ("gh pr review 21 --request-changes -b 'fix x'", False),
        ("gh pr create --fill", False),
        ("gh pr view 21 --json mergeable", False),
        ("gh pr checks 21", False),
        ("gh api repos/o/r/pulls/21/comments", False),
        ("git merge --no-edit main", False),
    ],
)
def test_agent_cannot_merge_or_approve(command, blocked):
    result = hook("production-gate.sh", {"tool_input": {"command": command}})
    assert result.returncode == (2 if blocked else 0), result.stderr
    if blocked:
        assert "human decision" in result.stderr
