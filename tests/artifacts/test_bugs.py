from pathlib import Path

from sdlc.artifacts import BUG_CHAIN, CHAIN, check_change, stage
from sdlc.cli import main

from .helpers import REPO, write

# --- bugs --------------------------------------------------------------------------------


def test_bug_with_short_spec_and_plan_is_valid(change: Path) -> None:
    write(change / "bug.md", BUG_CHAIN["bug.md"])
    assert check_change(change) == []
    assert stage(change) == "bug"
    write(change / "spec.md", ["Requirements", "Acceptance criteria"])
    write(change / "plan.md", CHAIN["plan.md"])
    assert check_change(change) == []
    assert stage(change) == "plan"


def test_bug_spec_still_needs_requirements_and_criteria(change: Path) -> None:
    write(change / "bug.md", BUG_CHAIN["bug.md"])
    write(change / "spec.md", ["Requirements"])
    [problem] = check_change(change)
    assert "Acceptance criteria" in problem.message


def test_feature_spec_still_needs_every_section(change: Path) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    write(change / "spec.md", ["Requirements", "Acceptance criteria"])
    [problem] = check_change(change)
    assert "Policy concerns" in problem.message


def test_intent_and_bug_together_are_reported(change: Path) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    write(change / "bug.md", BUG_CHAIN["bug.md"])
    assert any("both intent.md and bug.md" in p.message for p in check_change(change))


def _templates(root: Path) -> None:
    (root / ".sdlc" / "templates").mkdir(parents=True)
    for name in ("intent.md", "bug.md"):
        (root / ".sdlc" / "templates" / name).write_text(
            (REPO / ".sdlc" / "templates" / name).read_text()
        )


def test_new_bug_round_trip(tmp_path: Path) -> None:
    _templates(tmp_path)
    assert main(["--root", str(tmp_path), "new", "export-hangs", "--type", "bug"]) == 0
    folder = tmp_path / "changes" / "0001-export-hangs"
    assert (folder / "bug.md").exists()
    assert not (folder / "intent.md").exists()
    assert main(["--root", str(tmp_path), "check"]) == 0


def test_new_reads_type_from_the_environment(tmp_path: Path, monkeypatch) -> None:
    # `make new-change NAME=x TYPE=bug` reaches the CLI as $TYPE.
    _templates(tmp_path)
    monkeypatch.setenv("TYPE", "bug")
    assert main(["--root", str(tmp_path), "new", "export-hangs"]) == 0
    assert (tmp_path / "changes" / "0001-export-hangs" / "bug.md").exists()


def test_new_rejects_unknown_type(tmp_path: Path) -> None:
    _templates(tmp_path)
    assert main(["--root", str(tmp_path), "new", "x", "--type", "chore"]) == 2
