"""Layer 2: the framework installed into a fresh consumer repo, end to end, without Claude.

The consumer starts with only its own Makefile (a no-op stack) and the sync script, then
pulls the framework from a snapshot of this working tree, as `make sync-sdlc` would.
"""

import shutil

import pytest

from conftest import REPO, commit, git, hook, init_repo, run
from sdlc.artifacts import CHAIN

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
        ".claude/skills/review-findings/SKILL.md",
        ".claude/skills/build/SKILL.md",
        ".claude/skills/pr/SKILL.md",
        ".claude/skills/next/SKILL.md",
        ".claude/skills/routing.md",
        "templates/build.md",
        ".claude/settings.json",
        ".github/workflows/claude-review.yml",
        ".github/workflows/pr-title.yml",
        "templates/intent.md",
        "REVIEW.md",
        "tools/sdlc/src/sdlc/cli.py",
        "scripts/sync-sdlc.sh",
        "scripts/spec-pr.sh",
        "scripts/agent-identity.sh",
        "scripts/tests-locked.sh",
    ]:
        assert (consumer / rel).exists(), rel
    assert not (consumer / ".github/workflows/release.yml").exists(), "framework-only workflow"
    assert not (consumer / "scripts/next-version.sh").exists(), "framework-only script"
    assert not (consumer / ".vscode").exists(), "framework's own editor colours"


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


LINES = "".join(f"line {i}\n" for i in range(1, 11))


def synced_with(consumer, framework_snapshot, files):
    """Framework commits `files`, the consumer syncs to it and commits: the merge base."""
    commit(framework_snapshot, "fix: base", files)
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    commit(consumer, "chore: sync")


def test_sync_takes_new_version_of_files_unchanged_locally(consumer, framework_snapshot):
    synced_with(consumer, framework_snapshot, {"REVIEW.md": LINES})
    commit(framework_snapshot, "fix: change", {"REVIEW.md": LINES.replace("line 9", "new 9")})
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "new 9" in (consumer / "REVIEW.md").read_text()
    assert "kept your local changes" not in result.stdout


def test_sync_keeps_local_edits_and_merges_framework_changes(consumer, framework_snapshot):
    synced_with(consumer, framework_snapshot, {"REVIEW.md": LINES})
    commit(consumer, "chore: local tweak", {"REVIEW.md": LINES.replace("line 2", "mine 2")})
    commit(framework_snapshot, "fix: change", {"REVIEW.md": LINES.replace("line 9", "new 9")})
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    text = (consumer / "REVIEW.md").read_text()
    assert "mine 2" in text and "new 9" in text
    assert "kept your local changes" in result.stdout and "REVIEW.md" in result.stdout


def test_sync_keeps_local_edits_the_framework_did_not_change(consumer, framework_snapshot):
    commit(consumer, "chore: local tweak", {"REVIEW.md": "local edit\n", "notes.md": "mine\n"})
    commit(framework_snapshot, "fix: other file", {"NOTES.md": "x\n"})
    assert sync(consumer, framework_snapshot, "main").returncode == 0
    assert (consumer / "REVIEW.md").read_text() == "local edit\n"
    assert (consumer / "notes.md").read_text() == "mine\n"


def test_sync_conflict_keeps_both_sides_and_fails(consumer, framework_snapshot):
    synced_with(consumer, framework_snapshot, {"REVIEW.md": LINES})
    commit(consumer, "chore: local tweak", {"REVIEW.md": LINES.replace("line 5", "mine 5")})
    commit(framework_snapshot, "fix: change", {"REVIEW.md": LINES.replace("line 5", "new 5")})
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 1
    assert "CONFLICT" in result.stderr and "REVIEW.md" in result.stderr
    text = (consumer / "REVIEW.md").read_text()
    assert "<<<<<<< yours" in text and "mine 5" in text and "new 5" in text
    staged = git(consumer, "diff", "--cached", "--name-only").split()
    assert "REVIEW.md" not in staged, "a conflicted file stays unstaged"
    assert ".sdlc-version" in staged, "the rest of the sync is staged"


def test_sync_unmergeable_file_is_left_alone_with_new_version_beside_it(
    consumer, framework_snapshot
):
    binary = "\x00base\n"
    synced_with(consumer, framework_snapshot, {"REVIEW.md": binary})
    commit(consumer, "chore: local tweak", {"REVIEW.md": "\x00mine\n"})
    commit(framework_snapshot, "fix: change", {"REVIEW.md": "\x00new\n"})
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 1
    assert (consumer / "REVIEW.md").read_text() == "\x00mine\n", "local file untouched"
    assert (consumer / "REVIEW.md.sdlc-new").read_text() == "\x00new\n"
    assert "REVIEW.md.sdlc-new" in result.stderr and "by hand" in result.stderr
    staged = git(consumer, "diff", "--cached", "--name-only").split()
    assert "REVIEW.md.sdlc-new" not in staged and "REVIEW.md" not in staged


def test_first_sync_never_overwrites_a_file_the_consumer_has(tmp_path, framework_snapshot):
    repo = init_repo(tmp_path / "existing")
    shutil.copy(FIXTURE / "Makefile", repo / "Makefile")
    (repo / "scripts").mkdir()
    shutil.copy(REPO / "scripts" / "sync-sdlc.sh", repo / "scripts" / "sync-sdlc.sh")
    commit(repo, "chore: existing repo", {".github/workflows/ci.yml": "name: our own ci\n"})
    result = sync(repo, framework_snapshot)
    assert result.returncode == 1
    assert ".github/workflows/ci.yml" in result.stderr
    text = (repo / ".github/workflows/ci.yml").read_text()
    assert "name: our own ci" in text and "<<<<<<< yours" in text


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


def test_bug_change_in_consumer(consumer):
    # The consumer's Makefile passes only NAME; TYPE reaches the CLI through make's environment.
    assert make(consumer, "new-change", "NAME=export-hangs", "TYPE=bug").returncode == 0
    folder = consumer / "changes" / "0001-export-hangs"
    assert (folder / "bug.md").exists()
    assert not (folder / "intent.md").exists()
    assert make(consumer, "validate").returncode == 0
    assert make(consumer, "status").stdout.strip() == "0001-export-hangs\tbug"
    assert (consumer / "templates" / "bug-spec.md").exists()


def test_build_plan_in_consumer(consumer):
    """A large build's draft build.md validates, an approval with open questions doesn't,
    and make status shows milestone progress."""
    assert make(consumer, "new-change", "NAME=role-list").returncode == 0
    change = consumer / "changes" / "0001-role-list"
    for name, sections in CHAIN.items():
        (change / name).write_text("# T\n\n" + "".join(f"## {s}\n\nx\n\n" for s in sections))
    draft = (consumer / "templates" / "build.md").read_text()
    (change / "build.md").write_text(draft)
    assert make(consumer, "validate").returncode == 0
    assert make(consumer, "status").stdout.strip() == (
        "0001-role-list\tbuild\tdraft, awaiting approval, 0/2 milestones done"
    )
    assert make(consumer, "next", "CHANGE=0001").stdout.strip() == (
        "0001-role-list\tbuild\tbuild\tapprove the build plan (build.md)"
    )

    approved = draft.replace("draft, awaiting approval", "in progress", 1)
    (change / "build.md").write_text(approved.replace("None.\n", "1. Split it?\n", 1))
    refused = make(consumer, "validate")
    assert refused.returncode != 0
    assert "Questions before approval" in refused.stderr


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


def test_sync_keeps_a_dropped_file_the_consumer_changed(consumer, framework_snapshot):
    dropped = ".claude/skills/po-review/SKILL.md"
    commit(consumer, "chore: our po-review", {dropped: "our version\n"})
    (framework_snapshot / dropped).unlink()
    commit(framework_snapshot, "feat!: drop po-review skill")
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (consumer / dropped).read_text() == "our version\n"
    assert dropped not in (consumer / ".sdlc-files").read_text(), "it's the consumer's now"
    assert "kept (the framework dropped these" in result.stdout


def test_sync_reports_make_targets_the_consumer_lacks(consumer, framework_snapshot):
    makefile = (consumer / "Makefile").read_text().replace("status", "nostatus")
    commit(consumer, "chore: drop status target", {"Makefile": makefile})
    commit(framework_snapshot, "fix: change", {"REVIEW.md": "changed\n"})
    out = sync(consumer, framework_snapshot, "main").stdout
    assert "make status  (stack contract" in out
    assert "make evals  (optional" in out
    assert "make check  (" not in out


def test_sdlc_files_lists_what_was_installed(consumer):
    files = (consumer / ".sdlc-files").read_text().split()
    assert ".claude/hooks/production-gate.sh" in files
    assert "tools/sdlc/src/sdlc/cli.py" in files
    assert ".github/workflows/release.yml" not in files
    assert "Makefile" not in files
    assert all((consumer / f).is_file() for f in files)


def test_sync_overwrites_files_in_place(consumer, framework_snapshot):
    # The sync script replaces itself while running; deleting it first leaves a
    # .fuse_hidden* file behind on NTFS-over-FUSE checkouts. Same inode = no delete.
    script = consumer / "scripts" / "sync-sdlc.sh"
    before = script.stat().st_ino
    commit(framework_snapshot, "fix: change", {"REVIEW.md": "changed\n"})
    assert sync(consumer, framework_snapshot, "main").returncode == 0
    assert script.stat().st_ino == before


def test_a_new_framework_file_arrives_in_the_same_sync(consumer, framework_snapshot):
    # The file list lives in the sync script, so a version that adds a path must be run by
    # its own (new) script, or the new file only arrives on the next sync.
    script = framework_snapshot / "scripts" / "sync-sdlc.sh"
    text = script.read_text().replace(
        '    "REVIEW.md:REVIEW.md"\n', '    "REVIEW.md:REVIEW.md"\n    "NEW.md:NEW.md"\n'
    )
    commit(framework_snapshot, "feat: new file", {"NEW.md": "new\n", "scripts/sync-sdlc.sh": text})
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "running the new one" in result.stdout
    assert (consumer / "NEW.md").read_text() == "new\n"
    assert "command not found" not in result.stderr
