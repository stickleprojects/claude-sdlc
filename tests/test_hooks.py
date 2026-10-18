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
