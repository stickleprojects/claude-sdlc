import pytest

from conftest import REPO, run

# --- make check reports each prompt's size against its word budget (#201) --------------------

BUDGET = REPO / "scripts/prompt-budget.sh"


@pytest.fixture
def prompts(tmp_path):
    """A tree with one prompt of each kind, and a budget row for each."""
    files = {
        ".sdlc/REVIEW.md": "one two three\n",
        ".sdlc/skills/build/SKILL.md": "a b c d\n",
        ".sdlc/skills/scope.md": "a b\n",
        ".sdlc/agents/verifier.md": "a\n",
        ".sdlc/prompts/clause-check.md": "a b\n",
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    rows = ["# comment", "", *(f"{name}\t{len(t.split())}" for name, t in files.items())]
    (tmp_path / "budget.tsv").write_text("\n".join(rows) + "\n")
    return tmp_path


def budget(root, env=None):
    return run(["bash", str(BUDGET), "budget.tsv"], cwd=root, env=env)


def test_every_prompt_within_budget_is_ok(prompts):
    result = budget(prompts)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "prompt budget: ok, 5 prompts within budget, 12 words\n"


def test_a_prompt_over_budget_warns_but_passes(prompts):
    (prompts / ".sdlc/skills/build/SKILL.md").write_text("a b c d e\n")
    result = budget(prompts)
    assert result.returncode == 0
    assert "warning: .sdlc/skills/build/SKILL.md is 5 words, over its budget of 4" in result.stdout
    assert "prompt budget: 1 warning(s)" in result.stdout


def test_strict_mode_fails_on_a_warning(prompts):
    (prompts / ".sdlc/REVIEW.md").write_text("one two three four\n")
    assert budget(prompts, env={"PROMPT_BUDGET_STRICT": "1"}).returncode == 1
    (prompts / ".sdlc/REVIEW.md").write_text("one two three\n")
    assert budget(prompts, env={"PROMPT_BUDGET_STRICT": "1"}).returncode == 0


def test_rule_markers_do_not_count(prompts):
    (prompts / ".sdlc/REVIEW.md").write_text(
        "one two <!-- rule: review.a -->\nthree <!-- rule: review.b-c -->\n"
    )
    result = budget(prompts)
    assert "warning" not in result.stdout
    assert "12 words" in result.stdout


def test_a_prompt_with_no_budget_warns(prompts):
    new = prompts / ".sdlc/skills/new/SKILL.md"
    new.parent.mkdir()
    new.write_text("a b\n")
    result = budget(prompts)
    assert result.returncode == 0
    assert "warning: .sdlc/skills/new/SKILL.md has no word budget in budget.tsv (2 words)" in (
        result.stdout
    )


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (".sdlc/skills/gone/SKILL.md\t10", "names .sdlc/skills/gone/SKILL.md, which doesn't exist"),
        (".sdlc/REVIEW.md\tlots", "gives .sdlc/REVIEW.md the budget 'lots'"),
        (".sdlc/REVIEW.md", "gives .sdlc/REVIEW.md the budget ''"),
    ],
)
def test_a_stale_or_broken_budget_row_fails(prompts, row, message):
    with (prompts / "budget.tsv").open("a") as f:
        f.write(row + "\n")
    result = budget(prompts)
    assert result.returncode == 1
    assert message in result.stderr


def test_a_missing_budget_file_fails(prompts):
    result = run(["bash", str(BUDGET), "nope.tsv"], cwd=prompts)
    assert result.returncode == 1
    assert "no budget file nope.tsv" in result.stderr


def test_the_framework_has_a_budget_for_every_prompt():
    """A new prompt gets its budget row when it's added: no 'no word budget' warning here."""
    result = run(["bash", str(BUDGET)], cwd=REPO)
    assert result.returncode == 0, result.stderr
    assert "has no word budget" not in result.stdout


def test_make_check_runs_the_budget():
    makefile = (REPO / "Makefile").read_text()
    check = next(line for line in makefile.splitlines() if line.startswith("check:"))
    assert "prompt-budget" in check.split()
    assert "scripts/prompt-budget.sh" in makefile
