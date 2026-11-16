import re

import pytest

from conftest import REPO

# --- review skills -----------------------------------------------------------------------

REVIEW_SKILLS = [".sdlc/skills/po-review/SKILL.md", ".sdlc/skills/review-findings/SKILL.md"]


@pytest.mark.parametrize("path", REVIEW_SKILLS)
def test_review_skills_sign_replies_and_avoid_graphql_pr_commands(path):
    # Replies go out under the person's account; `gh pr edit`/`gh pr view` can fail in orgs
    # hit by the Projects (classic) GraphQL deprecation.
    skill = (REPO / path).read_text()
    assert "(posted from Claude Code)" in skill
    commands = re.findall(r"^\s*(gh pr \w+|git add -A|git add \.)", skill, re.MULTILINE)
    commands += re.findall(r"`(gh pr (?:edit|view|checkout) [^`]*)`", skill)
    assert commands == []


def test_review_findings_resolves_threads_and_checks_for_bot_commits():
    skill = (REPO / ".sdlc/skills/review-findings/SKILL.md").read_text()
    assert "resolveReviewThread" in skill
    assert "HEAD..origin/<branch>" in skill


def test_pr_title_accepts_bug_artifact_prs():
    script = (REPO / ".sdlc/scripts/check-pr-title.sh").read_text()
    assert "|intent|bug|spec|plan'" in script
    workflow = (REPO / ".github/workflows/sdlc-pr-title.yml").read_text()
    assert '.sdlc/scripts/check-pr-title.sh "$TITLE"' in workflow and "pulls/$PR/files" in workflow
