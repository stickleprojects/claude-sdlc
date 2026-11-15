"""No job's check run may share a name with a status context branch protection requires (#206).

Branch protection matches a required context by name against commit statuses and check runs
alike, and a job's check run is named after the job's `name:` (its id when it has none). A
cancelled run of a job named `check` blocks the merge; a skipped one passes it, without
`make check` having run. So a required context, and any context a workflow or script posts as a
commit status, may be a job's name only where OWNERS says so."""

import re
from pathlib import Path

import pytest

from conftest import REPO
from test_check_after_review import load

WORKFLOWS = sorted((REPO / ".github/workflows").glob("*.yml"))
BOOTSTRAP = REPO / ".sdlc/scripts/bootstrap-github.sh"

# The jobs whose check run IS the required context, and the names each may carry.
# sdlc-ci.yml's `check` is required on pushes to main and fork PRs; when it's skipped, its name
# is never `check` (test_a_skipped_ci_check_never_carries_the_required_name in
# test_check_after_review.py).
OWNERS = {
    ("sdlc-ci.yml", "check"): {"check"},
    ("sdlc-pr-title.yml", "pr-title"): {"pr-title"},
}


def required_contexts() -> set[str]:
    found = re.search(r"checks='\[([^\]]*)\]'", BOOTSTRAP.read_text())
    assert found, f"no checks='[...]' list in {BOOTSTRAP.name}"
    return set(re.findall(r'"([^"]+)"', found.group(1)))


def posted_contexts() -> set[str]:
    sources = [*WORKFLOWS, *(REPO / ".sdlc/scripts").glob("*.sh")]
    return {c for p in sources for c in re.findall(r"-f context=([\w.-]+)", p.read_text())}


def guarded() -> set[str]:
    return {c.casefold() for c in required_contexts() | posted_contexts()}


def check_run_names(job_id: str, job: dict) -> set[str]:
    """Every name the job's check run can get. An expression name may evaluate to any string
    literal in it, and a skipped job shows the expression's text, since GitHub doesn't evaluate
    it then."""
    name = job.get("name")
    if name is None:
        return {job_id}
    if "${{" not in name:
        return {name}
    text = " ".join(name.removeprefix("${{").removesuffix("}}").split())
    return {text, *re.findall(r"'([^']*)'", text)}


def clashes(path: Path) -> list[str]:
    out = []
    for job_id, job in load(path)["jobs"].items():
        allowed = {n.casefold() for n in OWNERS.get((path.name, job_id), set())}
        for name in sorted(check_run_names(job_id, job)):
            if name.casefold() in guarded() and name.casefold() not in allowed:
                out.append(f"{path.name}: job `{job_id}` can be named {name!r}")
    return out


def test_the_required_contexts_are_read():
    assert required_contexts() == {"check", "pr-title", "claude-review"}
    assert {"check", "claude-review"} <= posted_contexts()


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_job_shares_a_name_with_a_required_or_posted_status(path):
    assert not clashes(path), (
        "A check run with a required context's name counts toward it (#206). Rename the job "
        "(id and name:), or add it to OWNERS if its check run is meant to be that context."
    )


def all_check_run_names(paths=WORKFLOWS) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for path in paths:
        for job_id, job in load(path)["jobs"].items():
            for name in check_run_names(job_id, job):
                seen.setdefault(name.casefold(), []).append(f"{path.name}:{job_id}")
    return seen


def test_every_check_run_name_is_unique_across_the_workflows():
    # Two jobs with one name give two check runs of that name on a commit: requiring it later
    # would count both, and whichever is cancelled or skipped decides the result (#206).
    shared = {n: jobs for n, jobs in all_check_run_names().items() if len(set(jobs)) > 1}
    assert not shared, f"jobs share a check-run name: {shared}"


def test_it_catches_a_name_shared_between_workflows(tmp_path):
    for file in ("a.yml", "b.yml"):
        (tmp_path / file).write_text("on: push\njobs:\n  build:\n    runs-on: x\n")
    names = all_check_run_names(sorted(tmp_path.glob("*.yml")))
    assert names["build"] == ["a.yml:build", "b.yml:build"]


def test_every_owner_exists():
    # A stale entry would let a new job of that name through unchecked.
    for (file, job_id), names in OWNERS.items():
        job = load(REPO / ".github/workflows" / file)["jobs"][job_id]
        assert names <= check_run_names(job_id, job), (file, job_id)


def test_the_after_review_check_answers_check_only_as_a_status():
    job = load(REPO / ".github/workflows/sdlc-check-after-review.yml")["jobs"]["make-check"]
    assert "check" not in {n.casefold() for n in check_run_names("make-check", job)}
    assert "-f context=check" in "\n".join(s.get("run", "") for s in job["steps"])


def test_it_catches_the_206_clash(tmp_path):
    # The job as v0.14.0 shipped it: id `check`, no name.
    bad = tmp_path / "sdlc-check-after-review.yml"
    bad.write_text("on: push\njobs:\n  gate:\n    runs-on: x\n  check:\n    runs-on: x\n")
    assert clashes(bad) == ["sdlc-check-after-review.yml: job `check` can be named 'check'"]
    named = tmp_path / "other.yml"
    named.write_text("on: push\njobs:\n  tests:\n    name: claude-review\n    runs-on: x\n")
    assert clashes(named) == ["other.yml: job `tests` can be named 'claude-review'"]
