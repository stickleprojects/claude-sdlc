"""The bug-path evals (#160) without a model: their consumer builds, and their checks pass what
the docs promise and fail what they rule out. Each test acts out an agent's work by hand."""

import json
import os
import shutil
from pathlib import Path

import pytest

from conftest import REPO, copy_working_tree, git, run

SLUG = "0001-price-decimals"
FAST = REPO / "evals/checks/bug-fast-path.sh"
FULL = REPO / "evals/checks/bug-full-path.sh"

BUG = """# Bug: a price whose cents end in zero loses a digit

Found by: Sam
Product owner: Sam
Came from: none

## What happens

150 cents shows as $1.5 on the checkout page.

## What should happen

It shows as $1.50: always two digits of cents.

## Steps to reproduce

1. Put one item at 150 cents in the cart.
2. Open the checkout page. It happens every time.

## Where seen

main, today, with a made-up cart.
"""

SPEC = """# Spec: a price shows two digits of cents

Bug: ./bug.md

## Requirements

- R1. A price shows two digits of cents: 150 cents shows as $1.50.

## Acceptance criteria

- AC1 (R1): `format_price(150)` returns `$1.50`; it returns `$1.5` today.

## Policy concerns

None.
"""

FIXED = '''"""Prices for the checkout page. Amounts are whole cents."""


def format_price(cents: int) -> str:
    """The price as the checkout page shows it, in dollars."""
    return f"${cents // 100}.{cents % 100:02d}"
'''

NEW_TEST = """

class TwoDigitCentsTest(unittest.TestCase):
    def test_cents_ending_in_zero(self) -> None:
        self.assertEqual(format_price(150), "$1.50")
"""


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """One consumer built the way the evals build it, copied for each test."""
    work = tmp_path_factory.mktemp("eval") / "work"
    work.mkdir()
    copy_working_tree(work)
    result = run(
        ["bash", str(REPO / "evals/consumer.sh"), "bug-path"],
        cwd=work,
        env={**os.environ, "EVAL_ROOT": str(REPO)},
    )
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


def report_and_spec(repo: Path, spec: bool = True) -> None:
    files = {f"changes/{SLUG}/bug.md": BUG}
    if spec:
        files[f"changes/{SLUG}/spec.md"] = SPEC
    commit(repo, f"bug({SLUG}): 150 cents shows as $1.5", files)


def failing_test(repo: Path, text: str = NEW_TEST) -> None:
    tests = (repo / "tests/test_prices.py").read_text()
    body = tests.replace("\n\nif __name__", text + "\n\nif __name__")
    commit(repo, f"test({SLUG}): failing test for $1.5", {"tests/test_prices.py": body})


def fix(repo: Path) -> None:
    commit(repo, f"fix({SLUG}): show two digits of cents", {"app/prices.py": FIXED})


def title(repo: Path, text: str = f"fix({SLUG}): show two digits of cents") -> None:
    (repo / "pr-title.txt").write_text(text + "\n")


def check(repo: Path, script: Path):
    return run(["bash", str(script)], cwd=repo, env={**os.environ, "EVAL_ROOT": str(REPO)})


def fast_path(repo: Path) -> None:
    git(repo, "switch", "-q", "-c", f"build/{SLUG}")
    report_and_spec(repo)
    failing_test(repo)
    fix(repo)
    title(repo)


# --- the consumer -----------------------------------------------------------------------------


def test_the_consumer_has_the_bug_and_this_framework(built):
    assert git(built, "branch", "--show-current").strip() == "main"
    assert git(built, "tag", "--list", "eval-base").strip() == "eval-base"
    assert "Bug path: full" in (built / ".sdlc/skills/intent/SKILL.md").read_text(), "synced"
    assert (built / ".sdlc/docs/bug-fast-path.md").is_file()
    assert run(["make", "-s", "check"], cwd=built).returncode == 0
    shown = run(
        ["python3", "-c", "from app.prices import format_price as f; print(f(150))"], cwd=built
    )
    assert shown.stdout.strip() == "$1.5", "the bug the evals report"
    assert not git(built, "status", "--porcelain").strip()


def test_the_consumer_keeps_the_frameworks_executable_bits(built):
    modes = git(built, "ls-files", "-s", ".sdlc/scripts/check-plan-first.sh", ".sdlc/hooks")
    assert modes and all(line.startswith("100755") for line in modes.splitlines() if ".sh" in line)


# --- the fast-path check ----------------------------------------------------------------------


def test_fast_path_check_passes_what_the_docs_promise(consumer):
    fast_path(consumer)
    result = check(consumer, FAST)
    assert result.returncode == 0, result.stdout
    assert f"check: {SLUG} took the fast path" in result.stdout


def test_fast_path_check_fails_a_fix_before_its_tests(consumer):
    git(consumer, "switch", "-q", "-c", f"build/{SLUG}")
    report_and_spec(consumer)
    fix(consumer)
    failing_test(consumer)
    title(consumer)
    assert "the fix comes before the failing tests" in check(consumer, FAST).stdout


def test_fast_path_check_fails_tests_that_dont_show_the_bug(consumer):
    git(consumer, "switch", "-q", "-c", f"build/{SLUG}")
    report_and_spec(consumer)
    passing = NEW_TEST.replace('format_price(150), "$1.50"', 'format_price(100)[0], "$"')
    failing_test(consumer, passing)
    fix(consumer)
    title(consumer)
    assert "they don't show the bug" in check(consumer, FAST).stdout


def test_fast_path_check_fails_a_change_with_a_plan(consumer):
    fast_path(consumer)
    commit(consumer, f"plan({SLUG}): plan", {f"changes/{SLUG}/plan.md": "# plan\n"})
    assert "the fast path has no plan" in check(consumer, FAST).stdout


def test_fast_path_check_fails_a_title_ci_refuses(consumer):
    fast_path(consumer)
    title(consumer, f"feat({SLUG}): show two digits of cents")
    assert "CI's title check refuses" in check(consumer, FAST).stdout


def test_fast_path_check_fails_off_the_build_branch(consumer):
    git(consumer, "switch", "-q", "-c", f"fix/{SLUG}")
    report_and_spec(consumer)
    failing_test(consumer)
    fix(consumer)
    title(consumer)
    assert f"not build/{SLUG}" in check(consumer, FAST).stdout


def test_fast_path_check_fails_when_the_bug_is_still_there(consumer):
    git(consumer, "switch", "-q", "-c", f"build/{SLUG}")
    report_and_spec(consumer)
    failing_test(consumer)
    commit(consumer, f"fix({SLUG}): not really", {"README.md": "x\n"})
    title(consumer)
    assert "make check fails at HEAD" in check(consumer, FAST).stdout


# --- the full-path check ----------------------------------------------------------------------


def test_full_path_check_passes_a_report_only(consumer):
    git(consumer, "switch", "-q", "-c", f"bug/{SLUG}")
    report_and_spec(consumer, spec=False)
    title(consumer, f"bug({SLUG}): 150 cents shows as $1.5")
    result = check(consumer, FULL)
    assert result.returncode == 0, result.stdout
    assert f"check: {SLUG} took the full path" in result.stdout


def test_full_path_check_accepts_an_intent_for_a_decision(consumer):
    intent = (REPO / ".sdlc/templates/intent.md").read_text()
    commit(consumer, f"intent({SLUG}): big prices", {f"changes/{SLUG}/intent.md": intent})
    assert check(consumer, FULL).returncode == 0


@pytest.mark.parametrize(
    "act",
    [
        lambda repo: report_and_spec(repo),  # a spec with the report
        lambda repo: (report_and_spec(repo, spec=False), fix(repo)),  # the fix committed
        lambda repo: (
            report_and_spec(repo, spec=False),
            (repo / "app/prices.py").write_text(FIXED),
        ),
        lambda repo: (
            git(repo, "switch", "-q", "-c", f"build/{SLUG}"),
            report_and_spec(repo, False),
        ),
    ],
    ids=["spec", "fix-committed", "fix-uncommitted", "build-branch"],
)
def test_full_path_check_fails_anything_past_the_report(consumer, act):
    act(consumer)
    assert check(consumer, FULL).returncode == 1


# --- the runner and the tasks -----------------------------------------------------------------


def test_eval_tasks_for_the_bug_paths_are_wired_to_the_checks():
    tasks = {p.name: json.loads(p.read_text()) for p in (REPO / "evals/tasks").glob("bug-*.json")}
    assert set(tasks) == {
        "bug-fast-path.json",
        "bug-path-full-setting.json",
        "bug-needs-decision-full-path.json",
    }
    assert "bug-fast-path.sh" in tasks["bug-fast-path.json"]["check"]
    for name in ("bug-path-full-setting.json", "bug-needs-decision-full-path.json"):
        assert "bug-full-path.sh" in tasks[name]["check"]
    assert "Bug path: full" in tasks["bug-path-full-setting.json"]["setup"]
    for task in tasks.values():
        assert 'consumer.sh" bug-path' in task["setup"]
        assert "Bash(git:*)" in task["tools"] and "pr-title.txt" in task["prompt"]
        assert "don't push" in task["prompt"]


def test_the_runner_runs_setup_and_passes_tools_and_turns(tmp_path):
    """A task's setup runs in the copy before the agent, with EVAL_ROOT; tools and max_turns
    reach agent.sh. The echo adapter prints the prompt instead of calling a model."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    task = {
        "name": "setup and settings",
        "setup": 'test -n "$EVAL_ROOT" && echo made > from-setup.txt',
        "prompt": "hello",
        "check": 'test "$(cat from-setup.txt)" = made && test -n "$EVAL_ROOT"',
        "tools": "Read",
        "max_turns": 7,
    }
    (tasks / "a.json").write_text(json.dumps(task))
    (tasks / "b.json").write_text(json.dumps({**task, "name": "failing setup", "setup": "false"}))
    result = run(
        ["bash", str(REPO / ".sdlc/evals/run.sh")],
        env={
            **os.environ,
            "EVAL_TASKS_DIR": str(tasks),
            "AGENT": "echo",
            "EVAL_MIN_PASS_RATE": "0.5",
        },
    )
    assert "PASS  setup and settings" in result.stdout, result.stdout + result.stderr
    assert "FAIL  failing setup" in result.stdout
    assert result.returncode == 0 and "evals: 1/2 passed" in result.stdout
