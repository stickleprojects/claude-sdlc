"""The tooling path (#221): one chore(<slug>) or ci(<slug>) PR carries a change's intent
(`Kind: tooling`), plan and code, with no spec, and its code stays inside main's
`Tooling paths:` line."""

import pytest

from conftest import REPO, run

from .helpers import spec_pr

INTENT = "# Intent: smoke test\n\nKind: tooling\n\n## Problem\n\nx\n"
TOOLING = ["changes/0004-t/intent.md", "changes/0004-t/plan.md", "scripts/smoke.sh"]


@pytest.fixture
def tree(tmp_path):
    """A PR checkout: tooling change 0004-t with its plan, feature 0003-x with its plan, and
    main's CLAUDE.md turning the tooling path on."""
    for rel, text in {
        "changes/0004-t/intent.md": INTENT,
        "changes/0004-t/plan.md": "# plan\n",
        "changes/0003-x/intent.md": "# Intent\n\n<!-- Kind: tooling -->\n",
        "changes/0003-x/spec.md": "# spec\n",
        "changes/0003-x/plan.md": "# plan\n",
    }.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    (tmp_path / "main-claude.md").write_text(
        "# CLAUDE.md\n\nTooling paths: scripts/ .github/ Makefile\n"
    )
    return tmp_path


def plan_first(tree, files, branch="build/0004-t", claude="main-claude.md"):
    return run(
        ["bash", str(REPO / ".sdlc/scripts/check-plan-first.sh"), branch],
        cwd=tree,
        env={"SDLC_CLAUDE_MD": str(tree / claude)},
        input="".join(f"{f}\n" for f in files),
    )


def title(tree, text, files):
    return run(
        ["bash", str(REPO / ".sdlc/scripts/check-pr-title.sh"), text],
        cwd=tree,
        input="".join(f"{f}\n" for f in files),
    )


# --- check-plan-first.sh: the code stays inside the allowlist --------------------------------


@pytest.mark.parametrize(
    "code",
    [
        ["scripts/smoke.sh"],
        ["scripts/a/b.sh", ".github/workflows/smoke.yml"],
        ["Makefile"],
        ["Makefile/inner"],  # an entry without / is a file or a folder
        ["changes/0004-t/build.md", "docs/smoke.md", "readme.md"],  # not code
    ],
)
def test_a_tooling_change_inside_the_allowlist_passes(tree, code):
    result = plan_first(tree, ["changes/0004-t/intent.md", "changes/0004-t/plan.md", *code])
    assert result.returncode == 0, result.stdout


def test_a_tooling_change_says_which_paths_held_it(tree):
    result = plan_first(tree, TOOLING)
    assert "tooling change inside 'Tooling paths: scripts/ .github/ Makefile'" in result.stdout


@pytest.mark.parametrize(
    ("code", "named"),
    [
        (["scripts/smoke.sh", "src/app.py"], "src/app.py"),
        (["scriptsx/a.sh"], "scriptsx/a.sh"),  # a prefix ending in / is a folder, not a stem
        (["Makefile.inc"], "Makefile.inc"),
        (["src/README.md"], "src/README.md"),  # nested markdown is code, as for any change
    ],
)
def test_a_tooling_change_outside_the_allowlist_fails(tree, code, named):
    result = plan_first(tree, ["changes/0004-t/plan.md", *code])
    assert result.returncode == 1
    assert (
        "::error::0004-t is a tooling change (Kind: tooling), but it changes code" in result.stdout
    )
    assert named in result.stdout and "take the full path with a spec" in result.stdout


def test_a_long_list_of_outside_paths_is_cut_short(tree):
    code = [f"src/{n}.py" for n in "abcde"]
    result = plan_first(tree, code)
    assert result.returncode == 1
    assert "src/a.py src/b.py src/c.py …" in result.stdout and "src/d.py" not in result.stdout


@pytest.mark.parametrize(
    "claude",
    ["# CLAUDE.md\n\nBug path: fast\n", "Tooling paths:   \n", "<missing>"],
    ids=["no line", "empty line", "no CLAUDE.md"],
)
def test_without_a_tooling_paths_line_the_path_is_off(tree, claude):
    if claude != "<missing>":
        (tree / "main-claude.md").write_text(claude)
    else:
        (tree / "main-claude.md").unlink()
    result = plan_first(tree, TOOLING)
    assert result.returncode == 1
    assert "has no 'Tooling paths:' line, so the tooling path is off" in result.stdout


def test_the_allowlist_comes_from_mains_claude_md_not_the_prs(tree):
    """CI passes main's file; a PR that widens its own CLAUDE.md gains nothing."""
    (tree / "CLAUDE.md").write_text("Tooling paths: src/\n")
    assert plan_first(tree, ["changes/0004-t/plan.md", "src/app.py"]).returncode == 1


def test_a_tooling_change_still_needs_its_plan(tree):
    (tree / "changes/0004-t/plan.md").unlink()
    result = plan_first(tree, ["changes/0004-t/intent.md", "scripts/smoke.sh"])
    assert result.returncode == 1 and "which has no plan.md yet" in result.stdout


def test_a_feature_is_untouched_by_the_allowlist(tree):
    """Its intent has the marker only inside a comment, so it's a feature with its plan."""
    result = plan_first(tree, ["src/app.py"], branch="build/0003-x")
    assert result.returncode == 0 and "has its plan.md" in result.stdout


def test_the_lines_last_value_wins_and_a_list_marker_is_allowed(tree):
    (tree / "main-claude.md").write_text("Tooling paths: scripts/\n- Tooling paths: tools/\n")
    assert plan_first(tree, ["changes/0004-t/plan.md", "tools/a.sh"]).returncode == 0
    assert plan_first(tree, ["changes/0004-t/plan.md", "scripts/a.sh"]).returncode == 1


# --- check-pr-title.sh: titled chore(<slug>) or ci(<slug>) -----------------------------------


@pytest.mark.parametrize(
    ("text", "files", "ok"),
    [
        ("chore(0004-t): runner smoke test", TOOLING, True),
        ("ci(0004-t): runner smoke test", TOOLING, True),
        ("chore(0004-t): with a build plan", [*TOOLING, "changes/0004-t/build.md"], True),
        ("chore(0004-t): plan amended", ["changes/0004-t/plan.md", "scripts/smoke.sh"], True),
        ("feat(0004-t): runner smoke test", TOOLING, False),
        ("plan(0004-t): runner smoke test", TOOLING, False),
        ("chore: no scope", TOOLING, False),
        ("chore(0003-x): wrong scope", TOOLING, False),
        ("intent(0004-t): the intent only", ["changes/0004-t/intent.md"], True),  # no code
        ("chore(0004-t): two changes", [*TOOLING, "changes/0003-x/plan.md"], False),
        ("chore(0004-t): with a spec", [*TOOLING, "changes/0004-t/spec.md"], False),
    ],
)
def test_a_tooling_pr_is_titled_chore_or_ci_with_its_slug(tree, text, files, ok):
    result = title(tree, text, files)
    assert (result.returncode == 0) == ok, result.stdout


def test_a_mistitled_tooling_pr_is_told_the_title_to_use(tree):
    result = title(tree, "feat(0004-t): smoke test", TOOLING)
    assert result.returncode == 1
    assert "(the tooling path, Kind: tooling), so title it 'chore(0004-t): <summary>'" in (
        result.stdout
    )


def test_a_feature_with_intent_plan_and_code_is_not_the_tooling_path(tree):
    """0003-x only mentions the marker in a comment: the usual gate-type rule applies."""
    files = ["changes/0003-x/intent.md", "changes/0003-x/plan.md", "src/app.py"]
    assert title(tree, "chore(0003-x): sneak", files).returncode == 1
    assert title(tree, "plan(0003-x): amend", files).returncode == 0


# --- spec-pr.sh: merging a tooling intent generates no spec ----------------------------------


def test_spec_pr_pending_skips_a_tooling_change(spec_repo):
    repo, _, _, env = spec_repo
    (repo / "changes/0001-a/intent.md").write_text(INTENT)
    result = spec_pr(repo, env, "pending")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["changes/0002-b"]
    assert "skip changes/0001-a: a tooling change, which has no spec" in result.stderr
