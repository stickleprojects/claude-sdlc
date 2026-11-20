"""SDLC_PR_CHECK_TARGET (#244): a PR's `check` may run a lighter make target, while a push to
main still runs `make check FULL=1`."""

import shutil

import pytest

from conftest import REPO, run
from test_check_after_review import AFTER, CI, load

SCRIPT = REPO / ".sdlc/scripts/pr-check-target.sh"
MAKEFILE = """\
.PHONY: check check-pr
check:
\t@echo "ran check FULL=$(FULL)"
check-pr:
\t@echo "ran check-pr FULL=$(FULL)"
"""


@pytest.fixture
def repo(tmp_path):
    """A project whose Makefile has `check` and a lighter `check-pr`, with the script synced."""
    (tmp_path / "Makefile").write_text(MAKEFILE)
    (tmp_path / ".sdlc/scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, tmp_path / ".sdlc/scripts/pr-check-target.sh")
    return tmp_path


def target(repo, value=None):
    env = {} if value is None else {"SDLC_PR_CHECK_TARGET": value}
    return run([".sdlc/scripts/pr-check-target.sh"], cwd=repo, env={**CLEAN_MAKE, **env})


@pytest.mark.parametrize(
    ("value", "expected"), [(None, "check"), ("", "check"), ("check-pr", "check-pr")]
)
def test_the_target_defaults_to_check(repo, value, expected):
    result = target(repo, value)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{expected}\n"


@pytest.mark.parametrize("value", ["check; rm -rf /", "$(id)", "Check", "-n", "check pr", "1x"])
def test_a_value_that_isnt_a_target_name_fails_before_make_runs(repo, value):
    result = target(repo, value)
    assert result.returncode == 1 and result.stdout == ""
    assert "isn't a make target name" in result.stderr


def test_a_target_the_makefile_lacks_fails_naming_the_variable(repo):
    result = target(repo, "check-fast")
    assert result.returncode == 1
    assert "SDLC_PR_CHECK_TARGET is 'check-fast', but the Makefile has no 'check-fast' target" in (
        result.stderr
    )


def test_finding_the_target_runs_no_recipe(repo):
    """make -q prints its database without running anything, even the default goal."""
    (repo / "Makefile").write_text("first:\n\ttouch ran\n" + MAKEFILE)
    assert target(repo, "check-pr").returncode == 0
    assert not (repo / "ran").exists()


def test_the_script_arrives_executable():
    from conftest import git

    assert git(REPO, "ls-files", "-s", str(SCRIPT.relative_to(REPO))).startswith("100755")


# --- the workflows run it --------------------------------------------------------------------


def step(path, job, name):
    return next(s for s in load(path)["jobs"][job]["steps"] if s.get("name") == name)


# An outer `make check FULL=1` (the release, CI on main) hands FULL=1 to every make below it
# through MAKEFLAGS, where it beats the environment (#165), so the step's make starts with none.
CLEAN_MAKE = {"MAKEFLAGS": "", "MAKELEVEL": "", "FULL": ""}


def run_step(repo, step_, env):
    return run(["bash", "-e", "-c", step_["run"]], cwd=repo, env={**CLEAN_MAKE, **env})


CI_STEP = "make check (a PR runs SDLC_PR_CHECK_TARGET, if set)"


@pytest.mark.parametrize(
    ("event", "value", "ran"),
    [
        ("push", "check-pr", "ran check FULL=1"),  # main is always fully tested
        ("push", None, "ran check FULL=1"),
        ("pull_request", None, "ran check FULL="),
        ("pull_request", "check-pr", "ran check-pr FULL="),
    ],
)
def test_ci_runs_full_check_on_main_and_the_target_on_a_pr(repo, event, value, ran):
    s = step(CI, "check", CI_STEP)
    env = {"EVENT": event, **({"SDLC_PR_CHECK_TARGET": value} if value else {})}
    result = run_step(repo, s, env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{ran}\n"


def test_ci_fails_a_bad_target_without_running_make(repo):
    s = step(CI, "check", CI_STEP)
    result = run_step(repo, s, {"EVENT": "pull_request", "SDLC_PR_CHECK_TARGET": "nope"})
    assert result.returncode != 0 and "ran" not in result.stdout


def test_check_after_review_runs_the_target(repo):
    s = step(AFTER, "make-check", "make check (or SDLC_PR_CHECK_TARGET)")
    result = run_step(repo, s, {"SDLC_PR_CHECK_TARGET": "check-pr"})
    assert result.returncode == 0 and result.stdout == "ran check-pr FULL=\n"
    bad = run_step(repo, s, {"SDLC_PR_CHECK_TARGET": "nope"})
    assert bad.returncode != 0 and "ran" not in bad.stdout


@pytest.mark.parametrize(
    ("path", "job", "name"),
    [(CI, "check", CI_STEP), (AFTER, "make-check", "make check (or SDLC_PR_CHECK_TARGET)")],
)
def test_the_variable_reaches_the_script_through_env_only(path, job, name):
    s = step(path, job, name)
    assert s["env"]["SDLC_PR_CHECK_TARGET"] == "${{ vars.SDLC_PR_CHECK_TARGET }}"
    assert "${{" not in s["run"], "no expression in the script: it could inject shell"
