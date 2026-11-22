import json
import os
import re
import shutil

import pytest

from conftest import REPO, commit, git, init_repo, run

from .helpers import CLAUSE_FIXTURE

# --- delivery check, stage build (#106) ---------------------------------------------------

DELIVERY_FIXTURE = "evals/fixtures/delivery-gap/0001-floor-mode"


def test_delivery_check_reads_the_code_with_a_larger_model(fake_claude):
    clauses = [
        {
            "clause": "generates a 3D scene",
            "delivered": "draws boxes",
            "gap": "large",
            "approved": None,
        },
        {"clause": "drawn", "gap": "tiny", "approved": ""},
        {"clause": "snaps", "gap": "small", "approved": "Approved: Sam"},
    ]
    answer = "CLAUSES: " + json.dumps(
        [{"requirement": "R1", "clauses": clauses}, {"requirement": "R2", "clauses": []}]
    )
    result, calls = fake_claude(answer, "--stage", "build", DELIVERY_FIXTURE)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1, "one run for the whole change (#257)"
    # 15 turns a requirement, two requirements.
    assert all("--model sonnet" in c and "--max-turns 30" in c for c in calls)
    assert all("--allowedTools Read,Grep,Glob" in c for c in calls)
    assert "You compare what a change delivers" in calls[0]
    assert "- **Demo:** the dock's floor tab shows a floor with doorway lines" in calls[0]
    assert '"id":"R2"' in calls[0]
    found = [f for f in json.loads(result.stdout) if f["requirement"] == "R1"]
    assert [(f["stage"], f["clause"], f["gap"], f["approved"]) for f in found] == [
        ("build", "generates a 3D scene", "large", None),
        ("build", "drawn", "large", None),  # a gap it can't read counts as large
        ("build", "snaps", "small", "Approved: Sam"),
    ]
    assert found[1]["delivered"] == "" and "missing" not in found[0]


def test_delivery_check_names_the_branchs_changed_files(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(REPO, work, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"))
    init_repo(work)
    commit(work, "base")
    git(work, "checkout", "-q", "-b", "build/x")
    commit(work, "code", {"src/floor_view.py": "x = 1\n", "changes/0001-x/notes.md": "n\n"})
    (work / "src/untracked_view.py").write_text("y = 2\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    (bin_dir / "claude").write_text(
        '#!/usr/bin/env bash\nprintf "%s" "$*" >> "$FAKE_LOG"\n'
        'echo \'CLAUSES: [{"requirement": "R1", "clauses": []},'
        ' {"requirement": "R2", "clauses": []}]\'\n'
    )
    (bin_dir / "claude").chmod(0o755)
    result = run(
        [".sdlc/scripts/clause-check.sh", "--stage", "build", DELIVERY_FIXTURE],
        cwd=work,
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_LOG": str(log)},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
    calls = log.read_text()
    assert '"changed_files":["src/floor_view.py","src/untracked_view.py"]' in calls
    assert "changes/0001-x/notes.md" not in calls


def test_delivery_check_runs_when_the_branch_changes_only_its_change_folder(tmp_path):
    # Found in #133: with nothing changed outside changes/, `grep -v` matched nothing and exited
    # 1, and under pipefail the check died with no output.
    work = tmp_path / "work"
    shutil.copytree(REPO, work, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"))
    init_repo(work)
    commit(work, "base")
    git(work, "checkout", "-q", "-b", "build/x")
    commit(work, "notes", {"changes/0001-x/notes.md": "n\n"})
    result = run(
        [".sdlc/scripts/clause-check.sh", "--stage", "build", DELIVERY_FIXTURE],
        cwd=work,
        env={"AGENT": "echo"},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout), "a row per requirement, unchecked by the echo agent"


def test_delivery_prompt_example_is_not_an_answer():
    prompt = (REPO / ".sdlc/prompts/delivery-check.md").read_text()
    assert not re.search(r"^CLAUSES: ", prompt, re.M)
    assert "main verb or noun" in prompt


def test_clause_check_reports_unreadable_requirement_lines_as_unchecked(fake_claude, tmp_path):
    change = tmp_path / "0001-search"
    shutil.copytree(REPO / CLAUSE_FIXTURE, change)
    spec = change / "spec.md"
    spec.write_text(spec.read_text().replace("- R2. When", "- Requirement 2: When"))
    answer = 'CLAUSES: [{"requirement": "R1", "clauses": []}]'
    result, calls = fake_claude(answer, "--stage", "spec", str(change))
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1 and '"id":"R1"' in calls[0], "R1 is still checked"
    [entry] = json.loads(result.stdout)
    assert entry["requirement"] is None and entry["stage"] == "spec"
    assert entry["text"].startswith("- Requirement 2: When no roles match")
    assert "could not be read as a requirement" in entry["unchecked"]


@pytest.mark.parametrize(
    ("quote", "kept"),
    [
        # The fixture plan has no Descopes entry, but its spec has an Out of scope line.
        ("Editing doorways by hand.", True),
        ("  Editing   doorways  by hand. ", True),  # whitespace differs
        ("and snaps moved rooms to the grid", True),  # wraps across lines in plan.md
        ("**Editing doorways** by `hand`.", True),  # markdown differs
        ("Descope: the 3D scene. Approved: Sam, 2026-11-01.", False),  # made up
        ("**", False),  # nothing left once markdown is stripped
    ],
)
def test_delivery_check_keeps_an_approval_only_if_its_quote_is_there(fake_claude, quote, kept):
    # PR #109 review: a made-up approval quote turned a large gap into an approved one.
    clause = {"clause": "generates a 3D scene", "delivered": "x", "gap": "large", "approved": quote}
    answer = "CLAUSES: " + json.dumps(
        [{"requirement": "R1", "clauses": [clause]}, {"requirement": "R2", "clauses": []}]
    )
    result, _ = fake_claude(answer, "--stage", "build", DELIVERY_FIXTURE)
    assert result.returncode == 0, result.stderr
    entry = json.loads(result.stdout)[0]
    if kept:
        assert entry["approved"] == quote and "approval_not_found" not in entry
    else:
        assert entry["approved"] is None and entry["approval_not_found"] == quote


def test_review_skips_the_clause_check_quietly_without_a_clauses_target():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    find = workflow[workflow.index("- name: Find the changed specs and plans") :]
    find = find[: find.index("- uses: ./.github/actions/setup-stack")]
    assert "make -n clauses CHANGE=probe" in find, "probes the target before any stack setup"
    assert "could not run" in (REPO / ".sdlc/REVIEW.md").read_text()


def test_release_notes_give_the_clauses_recipe_the_makefile_uses():
    # v0.9.0's upgrade step told consumers' Claude to copy the recipe into their Makefile. Since
    # #133 the target arrives with the sync in .sdlc/sdlc.mk, so the notes stay as released and
    # only the old recipe's call must still work: STAGE (#257) is optional.
    notes = (REPO / "docs/release-notes/v0.9.0.md").read_text()
    makefile = (REPO / ".sdlc/sdlc.mk").read_text()
    recipe = makefile[makefile.index("\nclauses:\n") + 1 :].split("\n\n", 1)[0]
    assert "$(if $(STAGE),--stage $(STAGE))" in recipe, "STAGE stays optional"
    assert "$(SDLC) clauses $(CHANGE) $(if $(REF),--ref $(REF))" in notes
    assert "## Upgrade steps" in notes and "## Optional: the `clauses` make target" in notes
    skill = (REPO / ".sdlc/skills/sdlc/SKILL.md").read_text()
    assert "`Upgrade steps`" in skill


@pytest.fixture
def eval_check(tmp_path):
    """Run an eval task's check in a copy of the repo with report.md and a fake `claude`."""
    work = tmp_path / "work"
    shutil.copytree(REPO, work, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"))
    init_repo(work)
    commit(work, "base")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def check(task, report, entries):
        (work / "report.md").write_text(report)
        answer = [{"requirement": "R1", "clauses": entries}, {"requirement": "R2", "clauses": []}]
        (tmp_path / "answer.txt").write_text("CLAUSES: " + json.dumps(answer) + "\n")
        (bin_dir / "claude").write_text(f"#!/usr/bin/env bash\ncat '{tmp_path / 'answer.txt'}'\n")
        (bin_dir / "claude").chmod(0o755)
        command = json.loads((REPO / "evals/tasks" / task).read_text())["check"]
        return run(
            ["bash", "-c", command], cwd=work, env={"PATH": f"{bin_dir}:{os.environ['PATH']}"}
        )

    return check


APPROVED_TASK = "verifier-passes-an-approved-delivery-gap.json"
FLAGGED_TASK = "verifier-flags-unapproved-delivery-gap.json"
REAL_QUOTE = "Descope: R1's 3D scene opened in the editor"


@pytest.mark.parametrize(
    ("report", "passes"),
    [
        # The release run's report (v0.9.0): right, but it says "needs approval" in prose.
        ("Nothing needs approval, so there is no heading. Approved: Sam, 2026-11-01.", True),
        ("## Descope: needs approval\n\n- R1. Approved: Sam, 2026-11-01.", False),
        ("**Descope: needs approval**\n\nApproved: Sam", False),
        ("R1's gap is covered.", False),  # doesn't quote the approval
    ],
)
def test_approved_gap_eval_reads_the_heading_not_the_phrase(eval_check, report, passes):
    entry = {"clause": "a 3D scene", "delivered": "x", "gap": "large", "approved": REAL_QUOTE}
    result = eval_check(APPROVED_TASK, report, [entry])
    assert (result.returncode == 0) == passes, result.stdout + result.stderr
    if not passes:
        assert result.stdout.startswith("check: "), "a failure says which part failed"


def test_approved_gap_eval_shows_the_script_output_when_it_fails(eval_check):
    made_up = {
        "clause": "a 3D scene",
        "delivered": "x",
        "gap": "large",
        "approved": "Approved: Lee",
    }
    result = eval_check(APPROVED_TASK, "Approved: Sam, 2026-11-01.", [made_up])
    assert result.returncode != 0
    assert "left a large gap unapproved" in result.stdout and "approval_not_found" in result.stdout


@pytest.mark.parametrize(
    ("report", "passes"),
    [
        ("## Descope: needs approval\n\n- R1 generates a 3D scene: only a diagram.", True),
        ("R1 generates a 3D scene, which needs approval.", False),  # no heading
    ],
)
def test_unapproved_gap_eval_needs_the_heading(eval_check, report, passes):
    entry = {"clause": "generates a 3D scene", "delivered": "x", "gap": "large", "approved": None}
    result = eval_check(FLAGGED_TASK, report, [entry])
    assert (result.returncode == 0) == passes, result.stdout + result.stderr
