import pytest

from .helpers import REPO

# --- descopes and test level (#95) ----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ".sdlc/agents/verifier.md",
        ".sdlc/skills/plan/SKILL.md",
        ".sdlc/skills/build/SKILL.md",
        ".sdlc/skills/spec/SKILL.md",
        ".sdlc/skills/review-findings/SKILL.md",
        ".sdlc/REVIEW.md",
    ],
)
def test_guardrails_read_the_scope_rules(path: str) -> None:
    assert "scope.md" in (REPO / path).read_text()


def test_worker_blocks_on_an_unapproved_descope() -> None:
    build = (REPO / ".sdlc/skills/build/SKILL.md").read_text()
    worker = build[build.index("## Worker mode") :]
    assert "return `BLOCKED`" in worker
    assert "Descopes:" in worker  # the report carries them back to the orchestrator


def test_plan_template_says_how_a_descope_is_approved() -> None:
    text = (REPO / ".sdlc/templates/plan.md").read_text()
    assert "Descope: <what> because <reason>. Approved: <name>, <date>." in text
