"""`make local-check` (#253): the local check before a push or a PR. A repo's `Local check:` line
in CLAUDE.md names its targets, and coverage runs locally only when the line names it."""

import shutil

import pytest

from conftest import REPO, run

from .helpers import CLEAN_MAKE

SCRIPT = REPO / ".sdlc/scripts/local-check.sh"
MAKEFILE = """\
.PHONY: check preflight coverage
check:
\t@echo "ran check"
preflight:
\t@echo "ran preflight"
coverage:
\t@echo "ran coverage"
include .sdlc/sdlc.mk
"""


@pytest.fixture
def repo(tmp_path):
    """A project with check, preflight and coverage targets, and the framework's make file."""
    (tmp_path / "Makefile").write_text(MAKEFILE)
    (tmp_path / ".sdlc/scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, tmp_path / ".sdlc/scripts/local-check.sh")
    shutil.copy2(REPO / ".sdlc/sdlc.mk", tmp_path / ".sdlc/sdlc.mk")
    return tmp_path


def local_check(repo, line=None, *args):
    """Run `make local-check` (or the script with args) with `line` in CLAUDE.md."""
    if line is not None:
        (repo / "CLAUDE.md").write_text(f"# Project\n\n{line}\n")
    command = [".sdlc/scripts/local-check.sh", *args] if args else ["make", "-s", "local-check"]
    return run(command, cwd=repo, env=CLEAN_MAKE)


def ran(result):
    return [
        line.removeprefix("ran ") for line in result.stdout.splitlines() if line.startswith("ran ")
    ]


def coverage_line(result):
    return result.stdout.strip().splitlines()[-1]


def test_without_the_line_it_runs_check_then_coverage(repo):
    result = local_check(repo)
    assert result.returncode == 0, result.stderr
    assert ran(result) == ["check", "coverage"]
    assert coverage_line(result) == "coverage: ran (make coverage)"


def test_without_the_line_or_a_coverage_target_it_runs_check(repo):
    (repo / "Makefile").write_text(MAKEFILE.replace('coverage:\n\t@echo "ran coverage"\n', ""))
    result = local_check(repo)
    assert result.returncode == 0, result.stderr
    assert ran(result) == ["check"]
    assert coverage_line(result) == "coverage: none (the Makefile has no coverage target)"


@pytest.mark.parametrize(
    "line",
    [
        "Local check: preflight",
        "Local check: make preflight",
        "- Local check: `make preflight`",
        "Local check:   preflight  ",
    ],
)
def test_a_line_runs_only_what_it_names_and_leaves_coverage_to_ci(repo, line):
    result = local_check(repo, line)
    assert result.returncode == 0, result.stderr
    assert ran(result) == ["preflight"], "coverage is off unless the line names it"
    assert coverage_line(result) == (
        "coverage: in CI (the Local check line leaves make coverage to the PR's CI)"
    )


def test_a_line_that_names_coverage_runs_it_in_order(repo):
    result = local_check(repo, "Local check: preflight coverage")
    assert result.returncode == 0, result.stderr
    assert ran(result) == ["preflight", "coverage"]
    assert coverage_line(result) == "coverage: ran (make coverage)"


def test_targets_prints_what_it_would_run_without_running_it(repo):
    assert local_check(repo, None, "--targets").stdout == "check coverage\n"
    result = local_check(repo, "Local check: preflight", "--targets")
    assert result.stdout == "preflight\n" and "ran" not in result.stdout


def test_a_failing_target_stops_the_check(repo):
    (repo / "Makefile").write_text(MAKEFILE.replace('@echo "ran preflight"', "@exit 3"))
    result = local_check(repo, "Local check: preflight coverage")
    assert result.returncode != 0
    assert ran(result) == [], "coverage doesn't run after preflight failed"
    assert "coverage:" not in result.stdout


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (
            "Local check: check-fast",
            "names 'check-fast', but the Makefile has no 'check-fast' target",
        ),
        ("Local check: check; rm -rf /", "isn't a make target name"),
        ("Local check: $(id)", "isn't a make target name"),
        ("Local check: Preflight", "isn't a make target name"),
        ("Local check: local-check", "would run itself"),
        ("Local check:", "names no target"),
    ],
)
def test_a_bad_line_fails_naming_the_setting(repo, line, message):
    for args in ((), ("--validate",)):
        result = local_check(repo, line, *args)
        # The script exits 1; make reports a failed recipe as 2.
        assert result.returncode == (1 if args else 2), (args, result.stdout)
        assert "CLAUDE.md:" in result.stderr and message in result.stderr
        assert "ran " not in result.stdout, "nothing runs"


def test_validate_passes_a_good_line_or_none(repo):
    assert local_check(repo, None, "--validate").returncode == 0
    assert local_check(repo, "Local check: preflight", "--validate").returncode == 0


def test_the_last_line_wins(repo):
    (repo / "CLAUDE.md").write_text("Local check: check\n\nLocal check: preflight\n")
    assert local_check(repo, None, "--targets").stdout == "preflight\n"


def test_usage(repo):
    result = local_check(repo, None, "--run")
    assert result.returncode == 2 and "usage" in result.stderr


def test_validate_fails_on_a_bad_line_naming_the_setting(repo, capsys):
    """`make validate` (`sdlc check`) holds the line, so a typo fails before anyone runs it."""
    from sdlc.cli import main

    (repo / "CLAUDE.md").write_text("Local check: check-fast\n")
    assert main(["--root", str(repo), "check"]) == 1
    err = capsys.readouterr().err
    assert "CLAUDE.md" in err and "'Local check: check-fast' names 'check-fast'" in err
    (repo / "CLAUDE.md").write_text("Local check: preflight\n")
    assert main(["--root", str(repo), "check"]) == 0
    (repo / "CLAUDE.md").write_text("# no setting\n")
    assert main(["--root", str(repo), "check"]) == 0


def test_the_skills_template_and_verifier_run_the_local_check():
    """Wiring: each prompt that runs the local check names the target, and the target exists."""
    assert (
        "\nlocal-check:\n\t@bash .sdlc/scripts/local-check.sh\n"
        in (REPO / ".sdlc/sdlc.mk").read_text()
    )
    for prompt in (
        ".sdlc/skills/build/SKILL.md",
        ".sdlc/templates/build.md",
        ".sdlc/agents/verifier.md",
        ".sdlc/skills/review-findings/SKILL.md",
        ".sdlc/skills/agent-identity/SKILL.md",
        ".sdlc/skills/plan/SKILL.md",
    ):
        text = (REPO / prompt).read_text()
        assert "`make local-check`" in text or "make local-check" in text, prompt
        # The old instructions, which ran coverage locally whatever the repo said.
        for old in (
            "`make check`, then `make coverage`",
            "`make check` and `make coverage`",
            "`make check`, `make coverage`",
            "  - `make coverage`",
        ):
            assert old not in text, (prompt, old)
    assert "| `Local check:` |" in (REPO / ".sdlc/docs/settings.md").read_text()
