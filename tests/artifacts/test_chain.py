from pathlib import Path

import pytest

from sdlc.artifacts import BUG_CHAIN, CHAIN, TEMPLATES, check_change, next_slug, stage
from sdlc.cli import main

from .helpers import REPO, write


def test_complete_intent_is_valid(change: Path) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    assert check_change(change) == []
    assert stage(change) == "intent"


def test_missing_sections_are_reported(change: Path) -> None:
    write(change / "intent.md", ["Problem"])
    [problem] = check_change(change)
    assert "Proposed outcome" in problem.message


def test_spec_without_intent_breaks_chain(change: Path) -> None:
    write(change / "spec.md", CHAIN["spec.md"])
    messages = [p.message for p in check_change(change)]
    assert any("earlier artifact" in m for m in messages)
    assert any("no intent.md" in m for m in messages)


def test_bad_folder_name(tmp_path: Path) -> None:
    bad = tmp_path / "changes" / "Example"
    write(bad / "intent.md", CHAIN["intent.md"])
    assert any("folder name" in p.message for p in check_change(bad))


def test_next_slug_increments(tmp_path: Path) -> None:
    (tmp_path / "changes" / "0007-old").mkdir(parents=True)
    assert next_slug(tmp_path, "new-thing") == "0008-new-thing"


@pytest.mark.parametrize(
    ("kind", "name"), [(k, n) for k, c in [("feature", CHAIN), ("bug", BUG_CHAIN)] for n in c]
)
def test_templates_satisfy_their_own_rules(kind: str, name: str) -> None:
    rules = CHAIN if kind == "feature" else BUG_CHAIN
    text = (REPO / ".sdlc" / "templates" / TEMPLATES[kind][name]).read_text()
    for section in rules[name]:
        assert f"## {section}" in text


def test_new_then_check_round_trip(tmp_path: Path) -> None:
    (tmp_path / ".sdlc" / "templates").mkdir(parents=True)
    template = (REPO / ".sdlc" / "templates" / "intent.md").read_text()
    (tmp_path / ".sdlc" / "templates" / "intent.md").write_text(template)
    assert main(["--root", str(tmp_path), "new", "add-login"]) == 0
    assert (tmp_path / "changes" / "0001-add-login" / "intent.md").exists()
    assert main(["--root", str(tmp_path), "check"]) == 0


def test_new_rejects_bad_name(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), "new", "Bad Name"]) == 2
