import re

import pytest

from conftest import REPO, run


def install_claude(env):
    return run(["bash", str(REPO / ".sdlc/scripts/install-claude.sh")], env=env)


def test_install_claude_installs_into_the_job_temp_folder(runner):
    tmp_path, env = runner
    before = sorted(p.relative_to(tmp_path / "home") for p in (tmp_path / "home").rglob("*"))
    r = install_claude(env)
    assert r.returncode == 0, r.stderr
    bin_dir = tmp_path / "runner-temp/claude-code/node_modules/.bin"
    assert r.stdout == f"{bin_dir}\n"  # stdout is only the folder
    # Pinned, local to the job, and never global.
    args = (tmp_path / "npm.log").read_text().split()
    assert args[:3] == ["install", "--prefix", str(tmp_path / "runner-temp/claude-code")]
    assert re.fullmatch(r"@anthropic-ai/claude-code@\d+\.\d+\.\d+", args[-1])
    assert "-g" not in args and "--global" not in args
    # Later steps find the job's claude before the one in the runner's home, which is untouched.
    assert (tmp_path / "github_path").read_text() == f"{bin_dir}\n"
    found = run(["sh", "-c", "command -v claude"], env={**env, "PATH": f"{bin_dir}:{env['PATH']}"})
    assert found.stdout.strip() == str(bin_dir / "claude")
    after = sorted(p.relative_to(tmp_path / "home") for p in (tmp_path / "home").rglob("*"))
    assert after == before


def test_install_claude_takes_the_version_from_the_environment(runner):
    tmp_path, env = runner
    assert install_claude({**env, "CLAUDE_CODE_VERSION": "9.9.9"}).returncode == 0
    assert (tmp_path / "npm.log").read_text().split()[-1] == "@anthropic-ai/claude-code@9.9.9"


def test_install_claude_fails_when_npm_leaves_no_claude(runner):
    tmp_path, env = runner
    r = install_claude({**env, "NPM_NO_BIN": "1"})
    assert r.returncode == 1
    assert "no claude" in r.stderr
    assert r.stdout == ""
    assert not (tmp_path / "github_path").exists()


# A global install writes outside the job's workspace: on a persistent runner it leaks between
# jobs and repos, and collides with what the runner already has (#136).
GLOBAL_INSTALL = re.compile(
    r"\b(?:npm|pnpm|yarn|bun)\b[^\n]*\s(?:-g|--global|global)\b"
    r"|\bpip3?\s+install\b[^\n]*--user\b"
    r"|\bgo\s+install\b|\bcargo\s+install\b|\bgem\s+install\b"
)


@pytest.mark.parametrize(
    "path",
    sorted(
        str(p.relative_to(REPO))
        for p in [*REPO.glob(".github/workflows/*.yml"), *REPO.glob(".github/actions/*/action.yml")]
    ),
)
def test_no_workflow_installs_anything_globally(path):
    text = (REPO / path).read_text()
    assert not GLOBAL_INSTALL.search(text), GLOBAL_INSTALL.search(text).group(0)
    # Claude Code comes from install-claude.sh, which pins it and keeps it in the job.
    assert "@anthropic-ai/claude-code" not in text


@pytest.mark.parametrize(
    "line",
    [
        "npm install -g @anthropic-ai/claude-code",
        "npm i --global x",
        "pnpm add -g x",
        "yarn global add x",
        "bun add -g x",
        "pip install --user x",
        "cargo install x",
    ],
)
def test_the_global_install_check_catches(line):
    assert GLOBAL_INSTALL.search(f"      - run: {line}\n")


def test_workflows_that_run_claude_install_it_first():
    for name in ["sdlc-spec-from-intent", "sdlc-agent-evals", "release", "sdlc-claude-review"]:
        assert "install-claude.sh" in (REPO / f".github/workflows/{name}.yml").read_text(), name
