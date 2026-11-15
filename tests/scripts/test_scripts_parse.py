import pytest

from conftest import REPO, run

SCRIPTS = sorted(
    p.relative_to(REPO)
    for p in [
        *REPO.glob("scripts/*.sh"),
        *REPO.glob(".sdlc/scripts/*.sh"),
        *REPO.glob(".sdlc/hooks/*.sh"),
    ]
) + [REPO.joinpath(".sdlc/evals/run.sh").relative_to(REPO)]


@pytest.mark.parametrize("script", SCRIPTS, ids=str)
def test_scripts_parse(script):
    assert run(["bash", "-n", str(script)]).returncode == 0
