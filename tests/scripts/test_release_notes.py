import json

import pytest

from conftest import REPO, commit, init_repo, run

from .helpers import _next_version

# --- release notes ---------------------------------------------------------------------


def _notes(repo, version="v0.5.0"):
    result = run(["bash", str(REPO / "scripts/release-notes.sh"), version, "o/r"], cwd=repo)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_release_notes_group_by_type(released):
    upgrade = {"docs/release-notes/v0.5.0.md": "## Upgrade steps\n\n1. Rename it.\n"}
    commit(released, "docs: upgrade steps", upgrade)
    commit(released, "Merge pull request #11 from a/b\n\nfeat: add migrate skill")
    commit(released, "fix(hooks): gate false positive (#12)")
    commit(released, "ci: faster checks (#13)")
    commit(released, "feat!: rename validate target (#14)")
    notes = _notes(released)
    assert notes.startswith("# v0.5.0 (")
    assert "This release has breaking changes" in notes
    order = ["## ⚠ Breaking changes", "## Features", "## Fixes", "## Pipeline, docs and chores"]
    positions = [notes.index(heading) for heading in order]
    assert positions == sorted(positions)
    assert "- rename validate target (#14)" in notes
    assert "- add migrate skill (#11)" in notes
    assert "- gate false positive (#12)" in notes
    assert "- faster checks (#13)" in notes
    assert "make sync-sdlc REF=v0.5.0" in notes
    assert "compare/v0.4.2...v0.5.0" in notes


def test_release_notes_include_the_versions_hand_written_notes(released):
    notes_dir = released / "docs" / "release-notes"
    notes_dir.mkdir(parents=True)
    (notes_dir / "v0.5.0.md").write_text("## Optional: ADRs\n\nHow to adopt them.\n")
    (notes_dir / "v0.4.3.md").write_text("## Older\n")
    commit(released, "feat: adrs (#9)")
    notes = _notes(released)
    assert notes.index("## Features") < notes.index("## Optional: ADRs")
    assert notes.index("How to adopt them.") < notes.index("## Upgrading a consumer repo")
    assert "## Older" not in notes


def _notes_result(repo, version="v0.5.0"):
    return run(["bash", str(REPO / "scripts/release-notes.sh"), version, "o/r"], cwd=repo)


def test_a_breaking_release_without_upgrade_steps_fails(released):
    """#20: a breaking release tells consumers what to change, or it isn't released."""
    commit(released, "feat!: rename validate target (#14)")
    commit(released, "fix: unrelated (#15)")
    result = _notes_result(released)
    assert result.returncode == 1
    assert "docs/release-notes/v0.5.0.md has no '## Upgrade steps' section" in result.stderr
    assert "- rename validate target (#14)" in result.stderr
    assert "unrelated" not in result.stderr


def test_a_breaking_change_in_the_body_needs_upgrade_steps_too(released):
    commit(released, "feat: new contract (#16)\n\nBREAKING CHANGE: the target is renamed")
    assert _notes_result(released).returncode == 1


def test_notes_without_upgrade_steps_dont_count_for_a_breaking_release(released):
    notes = {"docs/release-notes/v0.5.0.md": "## Optional: ADRs\n\nNo steps.\n"}
    commit(released, "feat!: rename (#14)", notes)
    assert _notes_result(released).returncode == 1


def test_a_breaking_release_with_upgrade_steps_is_released(released):
    notes = {"docs/release-notes/v0.5.0.md": "## Upgrade steps\n\n1. Rename it.\n"}
    commit(released, "feat!: rename (#14)", notes)
    result = _notes_result(released)
    assert result.returncode == 0, result.stderr
    assert "1. Rename it." in result.stdout


def test_a_release_without_breaking_changes_needs_no_upgrade_steps(released):
    commit(released, "feat: add a thing (#17)")
    assert _notes_result(released).returncode == 0


def test_release_notes_omit_empty_sections(released):
    commit(released, "fix: only a fix (#3)")
    notes = _notes(released, "v0.4.3")
    assert "## Fixes" in notes
    assert "## Features" not in notes
    assert "breaking" not in notes.lower()


def test_release_notes_first_release_has_no_compare_link(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(repo, "feat: first (#1)")
    notes = _notes(repo, "v0.1.0")
    assert "- first (#1)" in notes
    assert "compare/" not in notes


def test_merge_commits_after_the_first_are_parsed(released):
    commit(released, "Merge pull request #1 from a/b\n\nfeat: older feature")
    commit(released, "Merge pull request #2 from a/b\n\nfix: newer fix")
    assert _next_version(released) == (0, "v0.5.0")
    notes = _notes(released)
    assert "- older feature (#1)" in notes
    assert "- newer fix (#2)" in notes


@pytest.mark.parametrize(
    ("mode", "approvals", "code_owners"),
    [("solo", 0, False), ("team", 1, True)],
)
def test_bootstrap_protection_modes(mode, approvals, code_owners):
    result = run([".sdlc/scripts/bootstrap-github.sh", "--mode", mode, "--print-protection"])
    assert result.returncode == 0, result.stderr
    protection = json.loads(result.stdout)
    assert protection["enforce_admins"] is True, "nobody bypasses required checks"
    assert sorted(protection["required_status_checks"]["contexts"]) == [
        "check",
        "claude-review",
        "pr-title",
    ], "every repo requires the review of the latest commit (#46)"
    assert protection["required_status_checks"]["strict"] is True, "PRs must be up to date"
    reviews = protection["required_pull_request_reviews"]
    assert reviews["required_approving_review_count"] == approvals
    assert reviews["require_code_owner_reviews"] is code_owners
    assert protection["allow_force_pushes"] is False


def test_bootstrap_defaults_to_solo_and_rejects_unknown_mode():
    default = json.loads(run([".sdlc/scripts/bootstrap-github.sh", "--print-protection"]).stdout)
    assert default["required_pull_request_reviews"]["required_approving_review_count"] == 0
    assert run([".sdlc/scripts/bootstrap-github.sh", "--mode", "chaos"]).returncode == 2
