from pathlib import Path

import pytest

from sdlc.cli import main

# --- a framework upgrade left half done (#20) -------------------------------------------------


def test_check_fails_while_a_syncs_upgrade_steps_are_pending(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pending = tmp_path / ".sdlc" / "upgrade-pending.md"
    pending.parent.mkdir(parents=True)
    pending.write_text("# Upgrade steps to do\n\n# v0.12.0\n\n## Upgrade steps\n\n# v0.13.0\n")
    assert main(["--root", str(tmp_path), "check"]) == 1
    err = capsys.readouterr().err
    assert "upgrade-pending.md" in err
    assert "upgrade steps from v0.12.0, v0.13.0 to do: run /sdlc" in err


def test_check_passes_once_the_upgrade_steps_file_is_deleted(tmp_path: Path) -> None:
    (tmp_path / ".sdlc").mkdir()
    assert main(["--root", str(tmp_path), "check"]) == 0
