import json
import re

import pytest

from conftest import REPO

# --- the stack contract (#169) ----------------------------------------------------------------
# Hooks, CI and evals call only make targets. The language toolchain is named only in the
# Makefile and in .github/actions/setup-stack/, so a consumer switches language by changing
# those two. The framework's own tools (python3 for .sdlc/src, npm for Claude Code) aren't the
# consumer's stack and are allowed.

STACK_CALL = re.compile(
    r"(?<![\w./-])(?:uvx?|pytest|ruff|pip3?|pipx|poetry)(?![\w.-])"
    r"|python3?\s+-m\s+(?:pytest|ruff|pip)\b"
    r"|uses:\s*(?:astral-sh/setup-uv|actions/setup-python|actions/setup-node)@"
)


def stack_calls(text):
    """Lines that call the stack directly, ignoring comment lines."""
    return [
        line.strip()
        for line in text.splitlines()
        if not line.lstrip().startswith("#") and STACK_CALL.search(line)
    ]


def stack_contract_files():
    files = [*(REPO / ".github" / "workflows").glob("*.yml")]
    files += [p for p in (REPO / ".sdlc" / "hooks").iterdir() if p.is_file()]
    files += [*(REPO / ".sdlc" / "scripts").glob("*.sh")]
    files += [
        p
        for p in (REPO / ".github" / "actions").glob("*/action.yml")
        if p.parent.name != "setup-stack"  # the CI half of the contract
    ]
    files += [*(REPO / ".sdlc" / "evals").glob("*.sh"), *(REPO / "evals").glob("**/*.sh")]
    return files


def eval_commands():
    """Each eval task's setup and check commands (its prompt is prose, not a command)."""
    for task in sorted((REPO / "evals" / "tasks").glob("*.json")):
        data = json.loads(task.read_text())
        text = "\n".join(data.get(key) or "" for key in ("setup", "check"))
        yield task, text


def test_ci_hooks_scripts_and_evals_call_only_make_targets():
    found = {
        str(p.relative_to(REPO)): calls
        for p in stack_contract_files()
        if (calls := stack_calls(p.read_text()))
    }
    found |= {
        str(p.relative_to(REPO)): calls
        for p, text in eval_commands()
        if (calls := stack_calls(text))
    }
    assert not found, f"call a make target instead (the stack contract): {found}"
    assert list(eval_commands()), "no eval tasks found to check"


@pytest.mark.parametrize(
    "line",
    [
        "      run: uv run pytest -q",
        "      run: uvx ruff check .",
        "  pytest tests/",
        "      - run: ruff format --check",
        "pip install -r requirements.txt",
        "python3 -m pytest",
        "python -m pip install x",
        "      - uses: astral-sh/setup-uv@v6",
        "      - uses: actions/setup-python@v5",
        "      - run: make test && poetry run lint",
    ],
)
def test_the_stack_contract_check_catches_a_direct_call(line):
    assert stack_calls(f"steps:\n{line}\n") == [line.strip()]


@pytest.mark.parametrize(
    "line",
    [
        "      run: make check",
        "# a Python project might use `uv run sdlc` instead",
        "exec python3 -m sdlc.cli --root x",
        'npm install --prefix "$prefix" @anthropic-ai/claude-code',
        "  cp .ruff_cache/x y",
        "  echo pytest.ini changed",
        "  ls ~/.local/share/uv/tools",
    ],
)
def test_the_stack_contract_check_allows_make_and_the_frameworks_own_tools(line):
    assert stack_calls(line) == []
