"""The tooling-path evals (#221) without a model: their consumer builds with `Tooling paths:`
on, and their check passes what tooling-path.md promises and fails what it rules out. Each
test acts out an agent's work by hand."""

import json
import os
import shutil
from pathlib import Path

import pytest

from conftest import REPO, copy_working_tree, git, run

SLUG = "0001-price-table"
CHECK = REPO / "evals/checks/tooling-path.sh"
TASKS = {
    "tooling": REPO / "evals/tasks/intent-proposes-the-tooling-path.json",
    "full": REPO / "evals/tasks/intent-keeps-product-code-on-the-full-path.json",
}


def intent(kind_line: str = "Kind: tooling") -> str:
    return f"""# Intent: a price table for eyeballing formats

Originator: Alex
Product owner: Alex
{kind_line}

## Problem

Checking how prices format means calling format_price by hand.

## Proposed outcome

- `scripts/price-table.sh` prints format_price for 0 to 500 cents in steps of 50.

## Affected users and systems

Engineers only; nothing in app/ changes.

## Constraints

None.

## Open questions

None.
"""


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """One consumer built the way the tasks' setup builds it, copied for each test."""
    work = tmp_path_factory.mktemp("eval") / "work"
    work.mkdir()
    copy_working_tree(work)
    setup = json.loads(TASKS["tooling"].read_text())["setup"]
    assert setup == json.loads(TASKS["full"].read_text())["setup"], "both run in one consumer"
    result = run(["bash", "-c", setup], cwd=work, env={**os.environ, "EVAL_ROOT": str(REPO)})
    assert result.returncode == 0, result.stdout + result.stderr
    return work


@pytest.fixture
def consumer(built, tmp_path) -> Path:
    repo = tmp_path / "consumer"
    shutil.copytree(built, repo, symlinks=True)
    return repo


def commit(repo: Path, message: str, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git(repo, "add", *files)
    git(repo, "commit", "-q", "-m", message)


def check(repo: Path, mode: str):
    return run(["bash", str(CHECK), mode], cwd=repo, env={**os.environ, "EVAL_ROOT": str(REPO)})


def tooling_path(repo: Path, kind_line: str = "Kind: tooling") -> None:
    git(repo, "switch", "-q", "-c", f"build/{SLUG}")
    commit(repo, f"chore({SLUG}): intent", {f"changes/{SLUG}/intent.md": intent(kind_line)})


def full_path(repo: Path, kind_line: str = "") -> None:
    git(repo, "switch", "-q", "-c", f"intent/{SLUG}")
    commit(repo, f"intent({SLUG}): a price table", {f"changes/{SLUG}/intent.md": intent(kind_line)})
    (repo / "pr-title.txt").write_text(f"intent({SLUG}): a price table\n")


PLAN = """# Plan: a price table for eyeballing formats

Spec: none (tooling path)

## Approach

A bash script that calls format_price through python3.

## Steps

1. Add `scripts/price-table.sh` and a test that runs it.

## Verification

- **Definition of done:** Any code, Command or CLI
- The outcome statement: `bash scripts/price-table.sh` prints 11 lines, `$0.00` to `$5.00`.

## Risks

None.

## Descopes

None.
"""


def test_the_consumer_turns_the_tooling_path_on(built):
    assert "Tooling paths: scripts/" in (built / "CLAUDE.md").read_text()
    assert git(built, "status", "--porcelain") == "", "committed before eval-base"
    assert git(built, "rev-parse", "eval-base") == git(built, "rev-parse", "HEAD")


# --- tooling ---------------------------------------------------------------------------------


def test_tooling_passes_the_tooling_path(consumer):
    tooling_path(consumer)
    result = check(consumer, "tooling")
    assert result.returncode == 0, result.stdout
    assert f"check: {SLUG} took the tooling path" in result.stdout


def test_tooling_passes_when_the_agent_went_on_to_plan(consumer):
    tooling_path(consumer)
    commit(consumer, f"chore({SLUG}): plan", {f"changes/{SLUG}/plan.md": PLAN})
    assert check(consumer, "tooling").returncode == 0


@pytest.mark.parametrize(
    ("act", "why"),
    [
        (lambda r: tooling_path(r, ""), "isn't marked 'Kind: tooling'"),
        (lambda r: tooling_path(r, "<!-- Kind: tooling -->"), "isn't marked 'Kind: tooling'"),
        (lambda r: full_path(r, "Kind: tooling"), f"isn't committed on build/{SLUG}"),
    ],
    ids=["no Kind line", "Kind line in a comment", "on its own intent branch"],
)
def test_tooling_fails_an_intent_off_the_tooling_path(consumer, act, why):
    act(consumer)
    result = check(consumer, "tooling")
    assert result.returncode == 1 and why in result.stdout, result.stdout


def test_tooling_fails_an_intent_pr(consumer):
    tooling_path(consumer)
    (consumer / "pr-title.txt").write_text(f"intent({SLUG}): a price table\n")
    result = check(consumer, "tooling")
    assert result.returncode == 1 and "the tooling path has one PR" in result.stdout


def test_tooling_fails_a_spec(consumer):
    tooling_path(consumer)
    commit(consumer, f"spec({SLUG}): spec", {f"changes/{SLUG}/spec.md": "# Spec\n"})
    result = check(consumer, "tooling")
    assert result.returncode == 1 and "a spec.md was committed" in result.stdout


def test_tooling_fails_product_code(consumer):
    tooling_path(consumer)
    commit(consumer, f"chore({SLUG}): sneak", {"app/extra.py": "X = 1\n"})
    result = check(consumer, "tooling")
    assert result.returncode == 1 and "app or tests changed" in result.stdout


# --- full ------------------------------------------------------------------------------------


def test_full_passes_a_plain_intent_pr(consumer):
    full_path(consumer)
    result = check(consumer, "full")
    assert result.returncode == 0, result.stdout
    assert f"check: {SLUG} took the full path" in result.stdout


@pytest.mark.parametrize(
    ("act", "why"),
    [
        (lambda r: full_path(r, "Kind: tooling"), "the intent is marked 'tooling'"),
        (tooling_path, "the intent is marked 'tooling'"),
        (lambda r: (full_path(r), (r / "pr-title.txt").unlink()), "no intent PR title"),
    ],
    ids=["marked tooling", "on the tooling path", "no PR title"],
)
def test_full_fails_what_the_full_path_rules_out(consumer, act, why):
    act(consumer)
    result = check(consumer, "full")
    assert result.returncode == 1 and why in result.stdout, result.stdout


def test_full_fails_a_build_branch(consumer):
    full_path(consumer)
    git(consumer, "branch", f"build/{SLUG}")
    result = check(consumer, "full")
    assert result.returncode == 1 and f"a build/{SLUG} branch exists" in result.stdout


def test_both_tasks_run_the_check_in_their_mode():
    for mode, task in TASKS.items():
        assert json.loads(task.read_text())["check"].endswith(f'tooling-path.sh" {mode}')
