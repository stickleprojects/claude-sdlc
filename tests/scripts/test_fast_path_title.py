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
    assert "run the product owner's walkthrough first" in skill
    assert "still needs the product owner's approval on the bug and spec" in skill  # until #151


def test_review_rules_know_the_fast_path_and_never_exempt_a_scoped_fix():
    review = (REPO / ".sdlc/REVIEW.md").read_text()
    assert "**The bug fast path** (#148)" in review and "needs no `plan.md`" in review
    assert "a `test(<slug>): …` commit before the fix" in review
    assert "too big for one PR" in review
    assert "Until #151, GitHub doesn't require the product owner's approval" in review
    assert "a `fix(<slug>)` names a change and is never exempt" in review


def test_intent_offers_the_fast_path_unless_the_repo_turns_it_off():
    """#160: the fast path is the default for a bug, `Bug path: full` turns it off, and the
    settings page documents the line the skill reads."""
    intent = (REPO / ".sdlc/skills/intent/SKILL.md").read_text()
    assert "If the repo's `CLAUDE.md` has the line `Bug path: full`" in intent
    assert "**The fast path (the default" in intent
    assert "Size and file count don't count against it" in intent
    assert "`sdlc-build` skill (its **Bug fast path** section)" in intent
    assert "from any branch but `build/<slug>`" in intent, "else routing reads it as the fix"
    settings = (REPO / ".sdlc/docs/settings.md").read_text()
    row = next(line for line in settings.splitlines() if line.startswith("| `Bug path:`"))
    assert "`fast`, `full` | `fast`" in row


def test_build_sizes_by_session_fit_and_builds_a_fast_path_bug_from_its_spec():
    """#160: new assets or a data format no longer make a build large on their own."""
    build = (REPO / ".sdlc/skills/build/SKILL.md").read_text()
    assert "not by how many files or artefacts it adds" in build
    assert "it adds no new dependency, service, screen or data format" not in build
    assert "### 3c. Bug fast path (no plan.md)" in build
    assert "The spec's acceptance criteria are the steps." in build
    assert "approving the PR ships the fix" in build
    verifier = (REPO / ".sdlc/agents/verifier.md").read_text()
    assert "A bug on the fast path" in verifier and "read `bug.md` in its place" in verifier
