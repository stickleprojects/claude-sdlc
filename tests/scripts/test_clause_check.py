import json
import re

import pytest

from conftest import REPO, run

from .helpers import CLAUSE_FIXTURE


def test_clause_check_calls_a_small_model_once_per_requirement(fake_claude):
    answer = 'Thinking...\\nCLAUSES: [{"clause": "offers a button", "missing": ["criterion"]}]'
    result, calls = fake_claude(answer, "--stage", "spec", CLAUSE_FIXTURE)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 2, "one call per requirement, never the whole spec"
    assert all("--model haiku" in c and "--max-turns 1" in c for c in calls)
    assert '"id":"R1"' in calls[0] and '"id":"R2"' not in calls[0]
    found = json.loads(result.stdout)
    assert [(f["requirement"], f["stage"], f["clause"], f["missing"]) for f in found] == [
        ("R1", "spec", "offers a button", ["criterion"]),
        ("R2", "spec", "offers a button", ["criterion"]),
    ]
    assert found[1]["text"].startswith("When no roles match")


def test_clause_check_reports_nothing_when_every_clause_is_covered(fake_claude):
    result, _ = fake_claude("CLAUSES: []", "--stage", "plan", CLAUSE_FIXTURE)
    assert result.returncode == 0 and json.loads(result.stdout) == []


@pytest.mark.parametrize(
    ("answer", "fail"),
    [
        ("every clause is covered", False),  # no CLAUSES line
        ("CLAUSES: none", False),  # not JSON
        ('CLAUSES: {"clause": "x"}', False),  # not a list
        ('CLAUSES: ["offers a button"]', False),  # not objects with a clause
        ("CLAUSES: []", True),  # the call itself failed
    ],
)
def test_clause_check_fails_safe_on_an_answer_it_cant_read(fake_claude, answer, fail):
    result, _ = fake_claude(answer, "--stage", "spec", CLAUSE_FIXTURE, fail=fail)
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    assert [f["requirement"] for f in found] == ["R1", "R2"], "unchecked, never covered"
    assert all(f["unchecked"] and "clause" not in f for f in found)


def test_clause_check_takes_the_last_clauses_line_and_a_single_missing_value(fake_claude):
    answer = 'CLAUSES: [{"clause": "draft"}]\\nCLAUSES: [{"clause": "final", "missing": "design"}]'
    result, _ = fake_claude(answer, "--stage", "plan", CLAUSE_FIXTURE)
    found = json.loads(result.stdout)
    assert {(f["clause"], tuple(f["missing"])) for f in found} == {("final", ("design",))}


def test_clause_check_dry_run_reads_as_unchecked():
    # The echo adapter prints the prompt; its example answer must not read as a real one.
    result = run(
        [".sdlc/scripts/clause-check.sh", "--stage", "spec", CLAUSE_FIXTURE], env={"AGENT": "echo"}
    )
    assert result.returncode == 0, result.stderr
    assert all("unchecked" in f for f in json.loads(result.stdout))
    prompt = (REPO / ".sdlc/prompts/clause-check.md").read_text()
    assert not re.search(r"^CLAUSES: ", prompt, re.M)


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--stage", "spec"],
        ["--stage", "code", "0001"],
        ["--stage", "spec", "a", "b"],
        ["-x"],
        ["--changed-since", "main", "--stage", "spec"],
        ["--changed-since", "main", "0001"],
    ],
)
def test_clause_check_usage(args):
    result = run([".sdlc/scripts/clause-check.sh", *args], env={"AGENT": "echo"})
    assert result.returncode == 2 and "usage" in result.stderr


def test_clause_check_fails_when_the_spec_cant_be_split(tmp_path):
    result = run(
        [".sdlc/scripts/clause-check.sh", "--stage", "spec", str(tmp_path)], env={"AGENT": "echo"}
    )
    assert result.returncode != 0
    assert "spec.md doesn't exist" in result.stderr


def test_review_runs_the_clause_check_before_the_review_and_never_fails_on_it():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    check = workflow.index("- name: Clause check")
    assert workflow.index("- name: Find the changed specs and plans") < check
    assert check < workflow.index("- name: Review\n")
    step = workflow[check : workflow.index("- name: Review\n")]
    # AI only through the adapter (CLAUDE.md): the script calls agent.sh, the step never claude -p.
    assert '.sdlc/scripts/clause-check.sh --changed-since "$BASE"' in step
    assert "claude -p" not in workflow
    assert "BASE: ${{ github.event.pull_request.base.sha }}" in step
    assert "could not run" in step, "a failed check is reported to the review, not dropped"
    assert "if: steps.artifacts.outputs.changed == 'true'" in step
    setup = workflow[workflow.index("- uses: ./.github/actions/setup-stack") : check]
    assert "continue-on-error: true" in setup
    assert (
        ".clause-check.json" in step
        and ".clause-check.json" in workflow[check:].split("prompt: |", 1)[1]
    )
    assert "Where the clauses come from" in workflow
    assert "Where the clauses come from" in (REPO / ".sdlc/REVIEW.md").read_text()
