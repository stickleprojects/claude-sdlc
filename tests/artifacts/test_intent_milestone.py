from pathlib import Path

from sdlc.cli import main

from .helpers import REPO

# --- a new intent names its milestone when the repo has a roadmap (#187) ---------------------
# spellbound3d kept an override of the intent template only to make its Milestone: line live.


def new_intent(tmp_path: Path, roadmap: bool, kind: str = "feature") -> str:
    (tmp_path / ".sdlc" / "templates").mkdir(parents=True)
    for name in ("intent.md", "bug.md"):
        template = (REPO / ".sdlc" / "templates" / name).read_text()
        (tmp_path / ".sdlc" / "templates" / name).write_text(template)
    if roadmap:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "roadmap.md").write_text("# Roadmap\n")
    assert main(["--root", str(tmp_path), "new", "add-login", "--type", kind]) == 0
    first = "intent.md" if kind == "feature" else "bug.md"
    return (tmp_path / "changes" / "0001-add-login" / first).read_text()


def live_lines(text: str, name: str) -> list[str]:
    from sdlc.roadmap import lines_named

    return lines_named(text, name)


def test_new_intent_has_a_live_milestone_line_with_a_roadmap(tmp_path: Path) -> None:
    text = new_intent(tmp_path, roadmap=True)
    assert live_lines(text, "Milestone") == ["M<n>"]
    lines = text.splitlines()
    owner = next(i for i, line in enumerate(lines) if line.startswith("Product owner:"))
    assert lines[owner + 1] == "Milestone: M<n>", "right under Product owner:"


def test_new_intent_keeps_only_the_hint_without_a_roadmap(tmp_path: Path) -> None:
    text = new_intent(tmp_path, roadmap=False)
    assert live_lines(text, "Milestone") == []
    assert "Milestone: M<n>" in text, "the commented hint stays"


def test_new_bug_gets_no_milestone_line(tmp_path: Path) -> None:
    assert live_lines(new_intent(tmp_path, roadmap=True, kind="bug"), "Milestone") == []


def test_the_intent_skill_fills_in_the_milestone_line_new_change_wrote() -> None:
    skill = (REPO / ".sdlc/skills/intent/SKILL.md").read_text()
    assert "`make new-change` writes it as `Milestone: M<n>`" in skill
