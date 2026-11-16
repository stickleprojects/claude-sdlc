import pytest

from conftest import REPO, run

from .helpers import FAST


@pytest.mark.parametrize(
    ("title", "files", "ok"),
    [
        ("fix(0010-z): export no longer hangs", FAST, True),
        ("fix(0010-z): with its build plan", [*FAST, "changes/0010-z/build.md"], True),
        ("fix(0010-z): with a plan too", [*FAST, "changes/0010-z/plan.md"], True),
        ("bug(0010-z): export hangs", FAST, True),  # still allowed, just not the clear choice
        ("fix(0010-z): spec only", ["changes/0010-z/bug.md", "changes/0010-z/spec.md"], False),
        ("fix(0010-z): docs only", ["changes/0010-z/bug.md", "docs/a.md", "readme.md"], False),
        ("fix(0010-z): no report", ["changes/0010-z/spec.md", "src/z.py"], False),
        ("fix(0010-z): two changes", [*FAST, "changes/0011-w/spec.md"], False),
        ("fix(0010-z): an intent", [*FAST, "changes/0010-z/intent.md"], False),
        ("fix(0011-w): wrong scope", FAST, False),
        ("fix: no scope", FAST, False),
        ("feat(0007): intent and code", ["changes/0007-x/intent.md", "src/a.py"], False),
    ],
)
def test_pr_title_lets_a_fast_path_bug_be_a_fix(title, files, ok):
    result = run(
        ["bash", ".sdlc/scripts/check-pr-title.sh", title], input="".join(f"{f}\n" for f in files)
    )
    assert (result.returncode == 0) == ok, result.stdout


@pytest.mark.parametrize("title", ["feat(0010-z): fix it", "fix: no scope", "test(0010-z): x"])
def test_pr_title_suggests_fix_for_a_fast_path_pr(title):
    result = run(
        ["bash", ".sdlc/scripts/check-pr-title.sh", title], input="".join(f"{f}\n" for f in FAST)
    )
    assert result.returncode == 1
    assert "the bug fast path), so title it 'fix(0010-z): <summary>'" in result.stdout


def test_sdlc_pr_runs_both_walkthroughs_on_a_fast_path_pr():
    """#154: the product owner signs off the bug and spec, the engineer the code, in that order."""
    skill = (REPO / ".sdlc/skills/pr/SKILL.md").read_text()
    row = next(line for line in skill.splitlines() if line.startswith("| `fix(<slug>)`"))
    assert "`sdlc-po-review`, then `sdlc-review-findings`" in row
    assert skill.index(row) < skill.index("| anything else"), "matched before plain fix"


def test_review_rules_name_the_failing_test_commit_the_lock_reads():
    """tests-locked.sh finds the failing tests by their `test(<slug>): ` commit."""
    assert "test(" in (REPO / ".sdlc/scripts/tests-locked.sh").read_text()
    assert "a `test(<slug>): …` commit before the fix" in (REPO / ".sdlc/REVIEW.md").read_text()


def test_intent_offers_the_fast_path_unless_the_repo_turns_it_off():
    """#160: the fast path is the default for a bug, `Bug path: full` turns it off, and the
    settings page documents the line the skill reads."""
    intent = (REPO / ".sdlc/skills/intent/SKILL.md").read_text()
    assert "If the repo's `CLAUDE.md` has the line `Bug path: full`" in intent
    assert "`sdlc-build` skill (its **Bug fast path** section)" in intent
    settings = (REPO / ".sdlc/docs/settings.md").read_text()
    row = next(line for line in settings.splitlines() if line.startswith("| `Bug path:`"))
    assert "`fast`, `full` | `fast`" in row


def test_build_has_the_fast_path_section_intent_and_its_anchor_name():
    """intent names the build skill's **Bug fast path** section, and build links to its anchor."""
    build = (REPO / ".sdlc/skills/build/SKILL.md").read_text()
    assert "### 3c. Bug fast path (no plan.md)" in build
    assert "(#3c-bug-fast-path-no-planmd)" in build
