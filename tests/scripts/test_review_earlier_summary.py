"""review-earlier-summary.sh (#242): the summary a re-review replaces, and the PR's commits,
written for the review before it runs."""

import json
import os
import textwrap

import pytest

from conftest import REPO, run

SCRIPT = REPO / ".sdlc/scripts/review-earlier-summary.sh"
WORKFLOW = REPO / ".github/workflows/sdlc-claude-review.yml"
FAKE_GH = r"""#!/usr/bin/env bash
# Answers `gh api --paginate <path>` from files: comments for issues/, commits for pulls/.
echo "$*" >> "$D/calls"
[[ -e "$D/fail-$1-$3" || -e "$D/fail" ]] && { echo "HTTP 502" >&2; exit 1; }
case "$3" in
  */issues/*/comments*) cat "$D/comments.json" ;;
  */pulls/*/commits*) cat "$D/commits.json" ;;
  *) echo "unexpected: $*" >&2; exit 1 ;;
esac
"""
HIDDEN = "<!-- review-findings: important=0 nit=1 -->"


def comment(body, login="claude[bot]", kind="Bot", updated="2026-11-20T01:00:00Z"):
    return {"user": {"login": login, "type": kind}, "body": body, "updated_at": updated}


def commit(sha, subject, date="2026-11-20T02:00:00Z"):
    return {
        "sha": sha * 40,
        "commit": {"message": f"{subject}\n\nbody", "committer": {"date": date}},
    }


@pytest.fixture
def earlier(tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH)
    (fake / "gh").chmod(0o755)

    def go(comments, commits=(), fail=False, pr="31"):
        (tmp_path / "comments.json").write_text(json.dumps(list(comments)))
        (tmp_path / "commits.json").write_text(json.dumps(list(commits)))
        if fail:
            (tmp_path / "fail").write_text("")
        env = {
            "PATH": f"{fake}:{os.environ['PATH']}",
            "D": str(tmp_path),
            "GITHUB_REPOSITORY": "o/r",
        }
        return run(["bash", str(SCRIPT), pr], env=env)

    return go


def test_it_prints_the_newest_bot_summary_and_the_commits(earlier):
    result = earlier(
        [
            comment(f"Old summary.\n{HIDDEN}", updated="2026-11-19T01:00:00Z"),
            comment("A person's comment."),
            comment(f"Newest summary: the PR body is out of date.\n{HIDDEN}"),
        ],
        [commit("a", "feat: the export"), commit("b", "docs: changelog")],
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert out.startswith(
        "# The summary this review replaces\n\nLast edited: 2026-11-20T01:00:00Z\n"
    )
    assert "Newest summary: the PR body is out of date." in out and "Old summary" not in out
    assert out.endswith(
        "# The PR's commits, oldest first\n\n"
        "aaaaaaa 2026-11-20T02:00:00Z feat: the export\n"
        "bbbbbbb 2026-11-20T02:00:00Z docs: changelog\n"
    )


def test_a_person_quoting_the_count_line_is_not_the_summary(earlier):
    """Only a bot's comment counts: a person can paste the hidden line into their own."""
    result = earlier([comment(f"Quoting it:\n{HIDDEN}", login="kieron", kind="User")])
    assert result.returncode == 0
    assert result.stdout.startswith("# No earlier summary\n")


def test_a_bot_comment_without_the_count_line_is_not_the_summary(earlier):
    result = earlier([comment("Auto-merge is on.", login="github-actions[bot]")])
    assert result.stdout.startswith("# No earlier summary\n")
    assert "This is the PR's first review" in result.stdout


def test_a_pr_with_no_comments_or_commits_is_a_first_review(earlier):
    result = earlier([])
    assert result.returncode == 0
    assert "first review" in result.stdout and result.stdout.endswith("(none)\n")


def test_unreadable_github_fails_closed_with_nothing_on_stdout(earlier):
    result = earlier([], fail=True)
    assert result.returncode == 3 and result.stdout == ""
    assert "can't read PR #31's comments" in result.stderr


@pytest.mark.parametrize("pr", ["", "31; rm", "seven"])
def test_bad_arguments_print_usage(earlier, pr):
    result = earlier([], pr=pr)
    assert result.returncode == 2 and "Usage:" in result.stderr


def test_the_script_arrives_executable():
    from conftest import git

    assert git(REPO, "ls-files", "-s", str(SCRIPT.relative_to(REPO))).startswith("100755")


def test_the_review_reads_the_earlier_summary_from_the_base_copy():
    text = WORKFLOW.read_text()
    step = text[text.index("- name: Read the earlier summary") :][:900]
    assert 'git show "$BASE:.sdlc/scripts/review-earlier-summary.sh"' in step
    assert "> .review-earlier-summary.md" in step and "could not be read" in step
    assert text.index("- name: Read the earlier summary") < text.index("- name: Review\n")
    # Both review prompts are told to read it before replacing the summary.
    assert text.count("but first read .review-earlier-summary.md") == 2


@pytest.mark.parametrize(
    ("summary", "edit"),
    [
        ([], ""),
        ([comment(f"Earlier.\n{HIDDEN}")], "--edit-last "),
        (None, "--edit-last "),  # unreadable: never a second comment
    ],
)
def test_the_review_is_told_whether_to_create_or_edit_its_summary(tmp_path, summary, edit):
    """#266: a first review told to try --edit-last put a stub in the fallback. Runs the step."""
    text = WORKFLOW.read_text()
    step = text[text.index("- name: Read the earlier summary") :]
    body = step[step.index("run: |\n") + 7 : step.index("\n      - name: Review\n")]
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH)
    (fake / "gh").chmod(0o755)
    (tmp_path / "comments.json").write_text(json.dumps(summary or []))
    (tmp_path / "commits.json").write_text("[]")
    if summary is None:
        (tmp_path / "fail").write_text("")
    (tmp_path / ".sdlc").symlink_to(REPO / ".sdlc")
    env = {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "D": str(tmp_path),
        "GITHUB_REPOSITORY": "o/r",
        "PR": "31",
        "BASE": "none",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "out"),
    }
    result = run(["bash", "-e", "-c", textwrap.dedent(body)], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "out").read_text() == f"edit={edit}\n"
    # Both prompts post with it, and neither offers --edit-last as a first try.
    command = "${{ steps.earlier.outputs.edit }}--body"
    assert text.count(command) == 2 and "--edit-last --body" not in text
