"""scripts/check-trial-sha.sh: a release's consumer trial must be of the commit it tags (#200)."""

import pytest

from conftest import REPO, run

SHA = "5df79ee90488efb923fe6aa16b9cc6151d514c81"


def check(line, sha=SHA):
    return run([str(REPO / "scripts/check-trial-sha.sh"), line, sha])


@pytest.mark.parametrize(
    "line",
    [
        "stickleprojects/sdlc-sandbox#15 (claude-sdlc 5df79ee): sync clean, CI passed",
        "stickleprojects/sdlc-sandbox#15: sync clean (v0.14.1 to 5df79ee), CI passed",
        "sdlc-sandbox#15 of 5DF79EE9: passed",  # case, and a longer prefix
        f"trial of {SHA}",
    ],
)
def test_a_line_naming_the_released_commit_passes(line):
    result = check(line)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok: the trial is of 5df79ee\n"


def test_a_trial_of_an_older_main_fails_naming_both():
    # v0.17.1's real case: had main moved after the trial, the line would still have said 5df79ee.
    line = "stickleprojects/sdlc-sandbox#15 (claude-sdlc 5df79ee): passed"
    result = check(line, "4b043c0" + "0" * 33)
    assert result.returncode == 1
    assert "names 5df79ee, but this release tags 4b043c0" in result.stderr
    assert "Re-run the trial from step 2" in result.stderr


@pytest.mark.parametrize(
    "line",
    [
        "stickleprojects/sdlc-sandbox#15: sync clean, make check passed",
        "sdlc-sandbox#15 (claude-sdlc 5df79e): passed",  # 6 characters is too short to count
        "sdlc-sandbox#15 (claude-sdlc x5df79ee): passed",  # part of a longer word
    ],
)
def test_a_line_without_the_commit_fails(line):
    result = check(line)
    assert result.returncode == 1
    assert "names no commit" in result.stderr or "names " in result.stderr


def test_usage():
    assert run([str(REPO / "scripts/check-trial-sha.sh")]).returncode != 0
