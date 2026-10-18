"""Layer 2: the framework installed into a fresh consumer repo, end to end, without Claude.

The consumer starts with only its own Makefile (a no-op stack) and the sync script, then
pulls the framework from a snapshot of this working tree, as `make sync-sdlc` would.
"""

import shutil

import pytest

from conftest import REPO, commit, git, hook, init_repo, run

FIXTURE = REPO / "tests" / "fixtures" / "consumer"


def sync(consumer, source, *ref):
    return run(
        ["bash", "scripts/sync-sdlc.sh", *ref], cwd=consumer, env={"SDLC_SOURCE": str(source)}
    )


@pytest.fixture
def consumer(tmp_path, framework_snapshot):
    repo = init_repo(tmp_path / "consumer")
    shutil.copy(FIXTURE / "Makefile", repo / "Makefile")
    (repo / "scripts").mkdir()
    shutil.copy(REPO / "scripts" / "sync-sdlc.sh", repo / "scripts" / "sync-sdlc.sh")
    commit(repo, "chore: consumer skeleton")
    result = sync(repo, framework_snapshot)
    assert result.returncode == 0, result.stdout + result.stderr
    commit(repo, "chore: sync pipeline")
    return repo


def make(repo, *args):
    return run(["make", "-s", *args], cwd=repo)


def test_sync_installs_framework_owned_files(consumer):
    for rel in [
        ".claude/hooks/production-gate.sh",
        ".claude/skills/intent/SKILL.md",
        ".claude/settings.json",
        ".github/workflows/claude-review.yml",
        ".github/workflows/pr-title.yml",
        "templates/intent.md",
        "REVIEW.md",
        "tools/sdlc/src/sdlc/cli.py",
        "scripts/sync-sdlc.sh",
    ]:
        assert (consumer / rel).exists(), rel
    assert not (consumer / ".github/workflows/release.yml").exists(), "framework-only workflow"
    assert not (consumer / "scripts/next-version.sh").exists(), "framework-only script"


def test_sync_records_version_and_keeps_consumer_files(consumer, framework_snapshot):
    repo_line, sha = (consumer / ".sdlc-version").read_text().split()
    assert repo_line.endswith("@v0.0.1"), "defaults to the latest release tag"
    assert sha == git(framework_snapshot, "rev-parse", "v0.0.1")
    assert (consumer / "Makefile").read_text() == (FIXTURE / "Makefile").read_text()


def test_sync_marks_scripts_executable(consumer):
    modes = git(consumer, "ls-files", "-s", "*.sh").splitlines()
    assert modes and all(line.startswith("100755") for line in modes)


def test_sync_defaults_to_tag_not_main(consumer, framework_snapshot):
    commit(framework_snapshot, "feat: unreleased", {"REVIEW.md": "unreleased\n"})
    assert sync(consumer, framework_snapshot).returncode == 0
    assert "unreleased" not in (consumer / "REVIEW.md").read_text()
    assert "already up to date" in sync(consumer, framework_snapshot).stdout


def test_sync_ref_main_pulls_unreleased(consumer, framework_snapshot):
    commit(framework_snapshot, "feat: unreleased", {"REVIEW.md": "unreleased\n"})
    assert sync(consumer, framework_snapshot, "main").returncode == 0
    assert (consumer / "REVIEW.md").read_text() == "unreleased\n"


def test_sync_overwrites_local_edits_to_framework_files(consumer, framework_snapshot):
    commit(consumer, "chore: local tweak", {"REVIEW.md": "local edit\n", "notes.md": "mine\n"})
    assert sync(consumer, framework_snapshot).returncode == 0
    assert (consumer / "REVIEW.md").read_text() == (REPO / "REVIEW.md").read_text()
    assert (consumer / "notes.md").read_text() == "mine\n"


def test_sync_refuses_dirty_tree(consumer, framework_snapshot):
    (consumer / "dirty.txt").write_text("x")
    result = sync(consumer, framework_snapshot)
    assert result.returncode == 1
    assert "uncommitted" in result.stderr


def test_change_lifecycle_in_consumer(consumer):
    assert make(consumer, "check").returncode == 0
    assert make(consumer, "new-change", "NAME=browse-catalogue").returncode == 0
    intent = consumer / "changes" / "0001-browse-catalogue" / "intent.md"
    assert intent.exists()
    assert make(consumer, "validate").returncode == 0
    assert make(consumer, "status").stdout.strip() == "0001-browse-catalogue\tintent"

    intent.write_text(intent.read_text().replace("## Constraints", "## Something else"))
    broken = make(consumer, "validate")
    assert broken.returncode != 0
    assert "Constraints" in broken.stderr


def test_hooks_guard_the_consumer(consumer):
    blocked = hook(
        "production-gate.sh", {"tool_input": {"command": "git push origin main"}}, cwd=consumer
    )
    assert blocked.returncode == 2
    settings = {"tool_input": {"file_path": str(consumer / ".claude/settings.json")}}
    assert hook("protect-paths.sh", settings, cwd=consumer).returncode == 2
    app = {"tool_input": {"file_path": str(consumer / "src/app.ts")}}
    assert hook("protect-paths.sh", app, cwd=consumer).returncode == 0


def test_sync_keeps_files_the_consumer_added(consumer, framework_snapshot):
    own = {
        ".github/workflows/deploy.yml": "name: deploy\n",
        ".claude/skills/streaming-policy/SKILL.md": "consumer skill\n",
    }
    commit(consumer, "ci: consumer's own workflow and skill", own)
    commit(framework_snapshot, "fix: change", {"REVIEW.md": "changed\n"})
    assert sync(consumer, framework_snapshot, "main").returncode == 0
    for rel, content in own.items():
        assert (consumer / rel).read_text() == content, rel
    assert (consumer / "REVIEW.md").read_text() == "changed\n"


def test_sync_removes_files_the_framework_dropped(consumer, framework_snapshot):
    dropped = ".claude/skills/po-review/SKILL.md"
    assert (consumer / dropped).exists()
    (framework_snapshot / dropped).unlink()
    commit(framework_snapshot, "feat!: drop po-review skill")
    assert sync(consumer, framework_snapshot, "main").returncode == 0
    assert not (consumer / dropped).exists()
    assert dropped not in (consumer / ".sdlc-files").read_text()


def test_sdlc_files_lists_what_was_installed(consumer):
    files = (consumer / ".sdlc-files").read_text().split()
    assert ".claude/hooks/production-gate.sh" in files
    assert "tools/sdlc/src/sdlc/cli.py" in files
    assert ".github/workflows/release.yml" not in files
    assert "Makefile" not in files
    assert all((consumer / f).is_file() for f in files)
