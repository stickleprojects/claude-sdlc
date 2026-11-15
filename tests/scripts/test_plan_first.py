import os

import pytest

from conftest import REPO, run

# --- CI: no code before the plan (#44) -------------------------------------------------------


@pytest.fixture
def plan_tree(tmp_path):
    """A PR checkout: change 0003-x with a spec, bug 0005-z with bug.md and spec.md."""
    for rel in ("changes/0003-x/spec.md", "changes/0005-z/bug.md", "changes/0005-z/spec.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x\n")
    return tmp_path


def plan_first(tree, branch, files):
    return run(
        ["bash", str(REPO / ".sdlc/scripts/check-plan-first.sh"), branch],
        cwd=tree,
        input="".join(f"{f}\n" for f in files),
    )


@pytest.mark.parametrize("branch", ["build/0003-x", "plan/0003-x", "fix/0003-x"])
def test_plan_first_fails_a_change_branch_with_code_and_no_plan(plan_tree, branch):
    result = plan_first(plan_tree, branch, ["changes/0003-x/build.md", "src/a.py"])
    assert result.returncode == 1
    assert "::error::This PR changes code (src/a.py, …) for 0003-x, which has no plan.md" in (
        result.stdout
    )
    assert "/sdlc-plan" in result.stdout


def test_plan_first_passes_once_the_plan_is_in_the_tree(plan_tree):
    (plan_tree / "changes/0003-x/plan.md").write_text("# plan\n")  # on the branch, or merged
    result = plan_first(plan_tree, "build/0003-x", ["src/a.py"])
    assert result.returncode == 0 and "has its plan.md" in result.stdout


@pytest.mark.parametrize(
    "files",
    [
        ["changes/0003-x/plan.md"],
        ["changes/0003-x/spec.md", "docs/roadmap.md", "readme.md"],
        [],
    ],
    ids=["plan PR", "docs", "nothing"],
)
def test_plan_first_passes_artifacts_and_docs(plan_tree, files):
    assert plan_first(plan_tree, "plan/0003-x", files).returncode == 0


def test_plan_first_counts_nested_markdown_as_code(plan_tree):
    assert plan_first(plan_tree, "build/0003-x", ["src/README.md"]).returncode == 1


def test_plan_first_allows_the_bug_fast_path_only_on_build(plan_tree):
    ok = plan_first(plan_tree, "build/0005-z", ["tests/test_z.py", "src/z.py"])
    assert ok.returncode == 0 and "fast path" in ok.stdout
    assert plan_first(plan_tree, "fix/0005-z", ["src/z.py"]).returncode == 1
    (plan_tree / "changes/0005-z/spec.md").unlink()
    assert plan_first(plan_tree, "build/0005-z", ["src/z.py"]).returncode == 1, "no spec yet"


@pytest.mark.parametrize("branch", ["chore/bump", "fix/flaky", "build/0009-gone", ""])
def test_plan_first_skips_branches_that_arent_a_change(plan_tree, branch):
    result = plan_first(plan_tree, branch, ["src/a.py"])
    assert result.returncode == 0 and "isn't a change's branch" in result.stdout


def test_the_pr_title_job_runs_the_plan_check():
    workflow = (REPO / ".github/workflows/sdlc-pr-title.yml").read_text()
    assert "HEAD_REF: ${{ github.event.pull_request.head.ref }}" in workflow
    assert '.sdlc/scripts/check-plan-first.sh "$HEAD_REF" < "$RUNNER_TEMP/files.txt"' in workflow
    assert 'git show "$BASE_SHA:CLAUDE.md"' in workflow, "main's setting, not the PR's (#160)"
    assert 'SDLC_CLAUDE_MD="$RUNNER_TEMP/base-claude.md"' in workflow


@pytest.mark.parametrize("line", ["Bug path: full", "- Bug path: full", "Bug path: full  "])
def test_plan_first_refuses_the_fast_path_when_the_repo_turns_it_off(plan_tree, line):
    """#160: `Bug path: full` in CLAUDE.md means a bug needs its plan.md, CI included."""
    (plan_tree / "CLAUDE.md").write_text(f"# Project\n\n{line}\n")
    result = plan_first(plan_tree, "build/0005-z", ["src/z.py"])
    assert result.returncode == 1 and "says 'Bug path: full'" in result.stdout
    (plan_tree / "changes/0005-z/plan.md").write_text("x\n")
    assert plan_first(plan_tree, "build/0005-z", ["src/z.py"]).returncode == 0, "planned is fine"


@pytest.mark.parametrize("text", ["Bug path: fast\n", "Bug paths: full are described\n", ""])
def test_plan_first_keeps_the_fast_path_unless_full_is_set(plan_tree, text):
    (plan_tree / "CLAUDE.md").write_text(text)
    assert plan_first(plan_tree, "build/0005-z", ["src/z.py"]).returncode == 0


def test_plan_first_reads_the_claude_md_ci_gives_it(plan_tree, tmp_path):
    """CI passes main's CLAUDE.md: a PR whose own CLAUDE.md drops the line is still refused."""
    (plan_tree / "CLAUDE.md").write_text("Bug path: fast\n")
    main_copy = tmp_path / "base-claude.md"
    main_copy.write_text("Bug path: full\n")
    result = run(
        ["bash", str(REPO / ".sdlc/scripts/check-plan-first.sh"), "build/0005-z"],
        cwd=plan_tree,
        input="src/z.py\n",
        env={**os.environ, "SDLC_CLAUDE_MD": str(main_copy)},
    )
    assert result.returncode == 1 and "Bug path: full" in result.stdout


@pytest.mark.parametrize("prefix", ["build", "plan", "spec", "bug"])
def test_plan_first_fails_a_change_branch_without_its_number(plan_tree, prefix):
    """#185: build/z for changes/0005-z matched nothing, so its code passed unchecked."""
    result = plan_first(plan_tree, f"{prefix}/z", ["changes/0005-z/bug.md", "src/z.py"])
    assert result.returncode == 1
    assert f"The branch {prefix}/z leaves out the change number" in result.stdout
    assert f"Push it as {prefix}/0005-z" in result.stdout


@pytest.mark.parametrize(
    ("branch", "files"),
    [
        ("build/z", ["changes/0005-z/bug.md"]),  # no code: nothing for the plan check to miss
        ("build/other", ["src/z.py"]),  # no change folder ends in -other
        ("fix/z", ["src/z.py"]),  # maintenance prefixes aren't a change's branches
        ("build/z-more", ["src/z.py"]),  # 0005-z doesn't match a longer name
    ],
)
def test_plan_first_leaves_other_unnumbered_branches_alone(plan_tree, branch, files):
    result = plan_first(plan_tree, branch, files)
    assert result.returncode == 0 and "isn't a change's branch" in result.stdout
