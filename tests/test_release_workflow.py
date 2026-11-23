"""release.yml: a real release runs every test and every eval before it tags, with no way to
skip either. Only a dry run, which tags nothing, leaves them out."""

from conftest import REPO
from test_check_after_review import load

RELEASE = REPO / ".github/workflows/release.yml"


def steps():
    return load(RELEASE)["jobs"]["release"]["steps"]


def label(step):
    return step.get("name") or step.get("uses") or step["run"]


def test_there_is_no_input_to_skip_a_check():
    inputs = load(RELEASE)["on"]["workflow_dispatch"]["inputs"]
    # trial (#200) skips nothing: a real release needs it (tests/scripts/test_consumer_trial.py).
    assert set(inputs) == {"dry_run", "trial"}
    assert inputs["dry_run"]["default"] is True


def test_full_checks_then_evals_then_tag_and_only_a_dry_run_skips_them():
    names = [label(s) for s in steps()]
    check = names.index("make check FULL=1")
    evals = names.index("Agent evals")
    tag = names.index("Tag and publish")
    assert check < evals < tag
    for i in (check, evals, tag):
        assert steps()[i]["if"] == "${{ !inputs.dry_run }}", names[i]
    # A failed step stops the job: nothing after it may run regardless (always(), failure()...).
    for step in steps()[check:]:
        cond = step.get("if", "")
        assert "always()" not in cond and "failure()" not in cond, label(step)
        assert "continue-on-error" not in step, label(step)
    assert "make evals" in steps()[evals]["run"]


def test_a_real_release_checks_the_trial_is_of_the_commit_it_tags():
    version = next(s for s in steps() if s.get("name") == "Work out the next version")
    run = version["run"]
    call = 'scripts/check-trial-sha.sh "$SDLC_TRIAL" "$GITHUB_SHA"'
    assert f'[[ "$DRY_RUN" == true ]] || {call}' in run
    assert run.index("no consumer trial") < run.index("check-trial-sha.sh")
    skill = (REPO / ".claude/skills/release/SKILL.md").read_text()
    assert "(claude-sdlc 5df79ee)" in skill, "the skill's example line names the SHA"
    assert "trial line starts:" in (REPO / "scripts/consumer-trial.sh").read_text()
