"""SDLC_STACK_NEEDS (#239): every synced workflow's setup-stack call says what its job needs,
so a consumer's action can skip what a light job doesn't use, without guessing from names."""

import re

import pytest

from conftest import REPO
from test_check_after_review import load

LEVELS = ("none", "validate", "commit", "full")
DOC = REPO / ".sdlc/docs/stack-needs.md"
EXPECTED = {
    ("sdlc-claude-review.yml", "review"): "validate",
    ("sdlc-claude-mention.yml", "respond"): "commit",
    ("sdlc-spec-from-intent.yml", "spec"): "commit",
    ("sdlc-ci.yml", "check"): "full",
    ("sdlc-check-after-review.yml", "make-check"): "full",
    ("sdlc-agent-evals.yml", "evals"): "full",
    ("release.yml", "release"): "full",
}


def calls():
    """(workflow, job) -> the setup-stack step, for every call in every workflow."""
    found = {}
    for path in sorted((REPO / ".github/workflows").glob("*.yml")):
        for job, spec in load(path)["jobs"].items():
            for step in spec.get("steps", []):
                if step.get("uses") == "./.github/actions/setup-stack":
                    found[(path.name, job)] = step
    return found


def test_every_setup_stack_call_says_what_its_job_needs():
    found = calls()
    assert set(found) == set(EXPECTED), "a new call needs a level here and in stack-needs.md"
    for key, step in found.items():
        assert step.get("env", {}).get("SDLC_STACK_NEEDS") == EXPECTED[key], key


@pytest.mark.parametrize("need", sorted(set(EXPECTED.values())))
def test_each_level_used_is_one_the_doc_defines(need):
    assert need in LEVELS
    assert f"| `{need}` |" in DOC.read_text()


def test_the_doc_lists_each_job_under_its_level():
    rows = {
        m.group(1): m.group(2)
        for m in re.finditer(r"^\| `(\w+)` \|[^|]*\|([^|]*)\|$", DOC.read_text(), re.M)
    }
    for (workflow, job), need in EXPECTED.items():
        if workflow == "release.yml":
            continue  # the framework's own release isn't synced
        assert f"`{workflow}` / `{job}`" in rows[need], (workflow, job)


def test_the_doc_says_unknown_means_full():
    text = DOC.read_text()
    assert "| unset, or anything else | treat it as `full` |" in text
    assert '"${SDLC_STACK_NEEDS:-full}"' in text and "*) make setup ;;" in text
