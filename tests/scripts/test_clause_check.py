import json
import re

import pytest

from conftest import REPO, run

from .helpers import CLAUSE_FIXTURE


def answer_for(**clauses):
    """A CLAUSES line answering for each requirement named, e.g. R1=[...]."""
    return "CLAUSES: " + json.dumps([{"requirement": r, "clauses": c} for r, c in clauses.items()])


BUTTON = {"clause": "offers a button", "missing": ["criterion"]}


def test_clause_check_makes_one_small_model_call_for_the_whole_change(fake_claude):
    # #257: one cold start a change, not one a requirement (15 took 5 min on spellbound3d #263).
    answer = "Thinking...\\n" + answer_for(R1=[], R2=[BUTTON])
    result, calls = fake_claude(answer, "--stage", "spec", CLAUSE_FIXTURE)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1, "one call for every requirement of the change"
    assert all("--model haiku" in c and "--max-turns 1" in c for c in calls)
    assert '"id":"R1"' in calls[0] and '"id":"R2"' in calls[0]
    found = json.loads(result.stdout)
    assert [(f["requirement"], f["stage"], f["clause"], f["missing"]) for f in found] == [
        ("R2", "spec", "offers a button", ["criterion"]),
    ]
    assert found[0]["text"].startswith("When no roles match")


def test_clause_check_reads_a_requirement_the_answer_leaves_out_as_unchecked(fake_claude):
    # R2 has no entry, and R9 wasn't sent: R2 is unchecked, never covered, and R9 is dropped.
    answer = answer_for(R1=[BUTTON], R9=[BUTTON])
    result, _ = fake_claude(answer, "--stage", "plan", CLAUSE_FIXTURE)
    found = json.loads(result.stdout)
    assert [(f["requirement"], f.get("clause"), f.get("unchecked")) for f in found] == [
        ("R1", "offers a button", None),
        ("R2", None, "the clause check gave no answer for this requirement"),
    ]


def test_clause_check_reports_nothing_when_every_clause_is_covered(fake_claude):
    result, _ = fake_claude(answer_for(R1=[], R2=[]), "--stage", "plan", CLAUSE_FIXTURE)
    assert result.returncode == 0 and json.loads(result.stdout) == []


@pytest.mark.parametrize(
    ("answer", "fail"),
    [
        ("every clause is covered", False),  # no CLAUSES line
        ("CLAUSES: none", False),  # not JSON
        ('CLAUSES: {"clause": "x"}', False),  # not a list
        ('CLAUSES: [{"clause": "offers a button"}]', False),  # no requirement: the old shape
        ('CLAUSES: [{"requirement": "R1", "clauses": ["x"]}]', False),  # clauses not objects
        ('CLAUSES: [{"requirement": "R1"}]', False),  # no clauses list
        (answer_for(R1=[], R2=[]), True),  # the call itself failed
    ],
)
def test_clause_check_fails_safe_on_an_answer_it_cant_read(fake_claude, answer, fail):
    result, _ = fake_claude(answer, "--stage", "spec", CLAUSE_FIXTURE, fail=fail)
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    assert [f["requirement"] for f in found] == ["R1", "R2"], "unchecked, never covered"
    assert all(f["unchecked"] and "clause" not in f for f in found)


def test_clause_check_reads_as_covered_only_what_the_answer_names(fake_claude):
    # The old answer shape, `CLAUSES: []`, names no requirement, so nothing reads as covered.
    result, _ = fake_claude("CLAUSES: []", "--stage", "spec", CLAUSE_FIXTURE)
    assert [f.get("unchecked", "") != "" for f in json.loads(result.stdout)] == [True, True]


def test_clause_check_takes_the_last_clauses_line_and_a_single_missing_value(fake_claude):
    final = answer_for(R1=[{"clause": "final", "missing": "design"}], R2=[])
    answer = answer_for(R1=[{"clause": "draft"}], R2=[]) + "\\n" + final
    result, _ = fake_claude(answer, "--stage", "plan", CLAUSE_FIXTURE)
    found = json.loads(result.stdout)
    assert {(f["clause"], tuple(f["missing"])) for f in found} == {("final", ("design",))}


def test_clause_check_makes_no_call_when_no_requirement_changed(fake_claude):
    # The fixture is committed and unchanged since HEAD, so there is nothing to send.
    result, calls = fake_claude(
        answer_for(R1=[BUTTON]), "--stage", "plan", CLAUSE_FIXTURE, "--ref", "HEAD"
    )
    assert result.returncode == 0, result.stderr
    assert calls == [] and json.loads(result.stdout) == []


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
    # Main's tool over the PR's specs and plans as data (ADR 0001): a copy of main with the PR's
    # changed changes/<slug>/ folders put in, never the PR's Makefile.
    assert '.sdlc/scripts/overlay-changes.sh "$copy" HEAD "$HEAD_SHA"' in step
    in_copy = '(cd "$copy" && PATH="$bin:$PATH" .sdlc/scripts/clause-check.sh --changed-since HEAD)'
    assert in_copy in step
    assert "claude -p" not in workflow
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
