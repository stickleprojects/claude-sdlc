import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def run(cmd, cwd=REPO, env=None, input=None, check=False):
    """Run a command, returning CompletedProcess with text output."""
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        cmd, cwd=cwd, env=full_env, input=input, text=True, capture_output=True, check=check
    )


def hook(name, payload, env=None, cwd=REPO):
    """Invoke a Claude Code hook script with a JSON payload on stdin."""
    return run(
        ["bash", str(REPO / ".claude" / "hooks" / name)],
        cwd=cwd,
        env={"CLAUDE_PROJECT_DIR": str(cwd), **(env or {})},
        input=json.dumps(payload),
    )


def git(cwd, *args):
    return run(["git", *args], cwd=cwd, check=True).stdout.strip()


def init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "test")
    git(path, "config", "commit.gpgsign", "false")
    return path


def commit(path, message, files=None):
    for name, content in (files or {}).items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    git(path, "add", "-A")
    git(path, "commit", "-q", "--allow-empty", "-m", message)


@pytest.fixture
def framework_snapshot(tmp_path):
    """A git repo holding the framework's current working tree, tagged v0.0.1."""
    snap = init_repo(tmp_path / "framework")
    files = run(["git", "ls-files", "-co", "--exclude-standard", "-z"], check=True).stdout
    for rel in filter(None, files.split("\0")):
        src = REPO / rel
        if src.is_file():
            dst = snap / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    commit(snap, "snapshot")
    git(snap, "tag", "v0.0.1")
    return snap
