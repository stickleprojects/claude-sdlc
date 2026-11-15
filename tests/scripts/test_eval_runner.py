import json

import pytest

from conftest import run

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
    result = run([".sdlc/evals/run.sh"], env=env)
    assert (result.returncode == 0) is passes, result.stdout


@pytest.mark.parametrize("make_dir", [True, False], ids=["empty", "missing"])
def test_eval_runner_without_tasks_passes_and_says_so(tmp_path, make_dir):
    tasks = tmp_path / "tasks"
    if make_dir:
        tasks.mkdir()
    result = run([".sdlc/evals/run.sh"], env={"AGENT": "echo", "EVAL_TASKS_DIR": str(tasks)})
    assert result.returncode == 0, result.stderr
    assert "no tasks" in result.stdout
