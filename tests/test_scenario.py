"""Layer 2: the framework installed into a fresh consumer repo, end to end, without Claude.

The consumer starts with only its own Makefile (a no-op stack) and the sync script, then
pulls the framework from a snapshot of this working tree, as `make sync-sdlc` would.
"""

import json
import os
import re
import shutil

import pytest

from conftest import REPO, commit, copy_working_tree, git, hook, init_repo, run
from sdlc.artifacts import BUG_CHAIN, CHAIN

FIXTURE = REPO / "tests" / "fixtures" / "consumer"


def sync(consumer, source, *ref):
    return run(
        ["bash", ".sdlc/scripts/sync-sdlc.sh", *ref], cwd=consumer, env={"SDLC_SOURCE": str(source)}
    )


@pytest.fixture
def consumer(tmp_path, framework_snapshot):
    repo = init_repo(tmp_path / "consumer")
    shutil.copy(FIXTURE / "Makefile", repo / "Makefile")
    (repo / ".sdlc" / "scripts").mkdir(parents=True)
    shutil.copy(
        REPO / ".sdlc" / "scripts" / "sync-sdlc.sh", repo / ".sdlc" / "scripts" / "sync-sdlc.sh"
    )
    commit(repo, "chore: consumer skeleton")
    result = sync(repo, framework_snapshot)
    assert result.returncode == 0, result.stdout + result.stderr
    commit(repo, "chore: sync pipeline")
    return repo


def artifact(sections):
    """Each section with a stand-in body; Requirements gets a requirement validate can read."""
    return "".join(f"## {s}\n\n{'- R1. x' if s == 'Requirements' else 'x'}\n\n" for s in sections)


def make(repo, *args):
    return run(["make", "-s", *args], cwd=repo)


def test_sync_installs_framework_owned_files(consumer):
    for rel in [
        ".sdlc/hooks/production-gate.sh",
        ".sdlc/skills/intent/SKILL.md",
        ".sdlc/skills/review-findings/SKILL.md",
        ".sdlc/skills/build/SKILL.md",
        ".sdlc/skills/pr/SKILL.md",
        ".sdlc/skills/next/SKILL.md",
        ".sdlc/skills/sdlc/SKILL.md",
        ".sdlc/skills/routing.md",
        ".sdlc/templates/build.md",
        ".sdlc/templates/adr.md",
        ".claude/settings.json",
        ".github/workflows/sdlc-claude-review.yml",
        ".github/workflows/sdlc-pr-title.yml",
        ".sdlc/templates/intent.md",
        ".sdlc/REVIEW.md",
        ".sdlc/src/sdlc/cli.py",
        ".sdlc/scripts/sync-sdlc.sh",
        ".sdlc/scripts/spec-pr.sh",
        ".sdlc/scripts/agent-identity.sh",
        ".sdlc/scripts/tests-locked.sh",
    ]:
        assert (consumer / rel).exists(), rel
    assert not (consumer / ".github/workflows/release.yml").exists(), "framework-only workflow"
    assert not (consumer / "scripts/next-version.sh").exists(), "framework-only script"
    assert not (consumer / ".vscode").exists(), "framework's own editor colours"


def test_sync_records_version_and_keeps_consumer_files(consumer, framework_snapshot):
    repo_line, sha = (consumer / ".sdlc/version").read_text().split()
    assert repo_line.endswith("@v0.0.1"), "defaults to the latest release tag"
    assert sha == git(framework_snapshot, "rev-parse", "v0.0.1")
    assert (consumer / "Makefile").read_text() == (FIXTURE / "Makefile").read_text()


def test_sync_marks_scripts_executable(consumer):
    modes = git(consumer, "ls-files", "-s", "*.sh").splitlines()
    assert modes and all(line.startswith("100755") for line in modes)


def test_sync_copies_the_frameworks_executable_bit(consumer, framework_snapshot):
    # #79: the framework's mode decides, not the extension.
    assert git(consumer, "ls-files", "-s", ".sdlc/scripts/create-agent-apps.py").startswith(
        "100755"
    )
    assert git(consumer, "ls-files", "-s", ".sdlc/REVIEW.md").startswith("100644")
    # A consumer's own script isn't touched, whatever its name.
    commit(consumer, "chore: own script", {"scripts/ours.sh": "echo ours\n"})
    git(consumer, "update-index", "--chmod=-x", "scripts/ours.sh")
    commit(consumer, "chore: not executable")
    # Like NTFS: git can't see modes on disk, so only the sync can set the bit.
    git(consumer, "config", "core.fileMode", "false")
    hook_py = framework_snapshot / ".sdlc/hooks/new-hook.py"
    hook_py.write_text("print('hi')\n")
    hook_py.chmod(0o755)
    commit(framework_snapshot, "feat: python hook")
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(consumer, "ls-files", "-s", ".sdlc/hooks/new-hook.py").startswith("100755")
    assert git(consumer, "ls-files", "-s", "scripts/ours.sh").startswith("100644")


def test_sync_defaults_to_tag_not_main(consumer, framework_snapshot):
    commit(framework_snapshot, "feat: unreleased", {".sdlc/REVIEW.md": "unreleased\n"})
    assert sync(consumer, framework_snapshot).returncode == 0
    assert "unreleased" not in (consumer / ".sdlc/REVIEW.md").read_text()
    assert "already up to date" in sync(consumer, framework_snapshot).stdout


def test_sync_ref_main_pulls_unreleased(consumer, framework_snapshot):
    commit(framework_snapshot, "feat: unreleased", {".sdlc/REVIEW.md": "unreleased\n"})
    assert sync(consumer, framework_snapshot, "main").returncode == 0
    assert (consumer / ".sdlc/REVIEW.md").read_text() == "unreleased\n"


LINES = "".join(f"line {i}\n" for i in range(1, 11))


def synced_with(consumer, framework_snapshot, files):
    """Framework commits `files`, the consumer syncs to it and commits: the merge base."""
    commit(framework_snapshot, "fix: base", files)
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    commit(consumer, "chore: sync")


def test_sync_takes_new_version_of_files_unchanged_locally(consumer, framework_snapshot):
    synced_with(consumer, framework_snapshot, {".sdlc/REVIEW.md": LINES})
    commit(framework_snapshot, "fix: change", {".sdlc/REVIEW.md": LINES.replace("line 9", "new 9")})
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "new 9" in (consumer / ".sdlc/REVIEW.md").read_text()
    assert "kept your local changes" not in result.stdout


def test_sync_keeps_local_edits_and_merges_framework_changes(consumer, framework_snapshot):
    synced_with(consumer, framework_snapshot, {".sdlc/REVIEW.md": LINES})
    commit(consumer, "chore: local tweak", {".sdlc/REVIEW.md": LINES.replace("line 2", "mine 2")})
    commit(framework_snapshot, "fix: change", {".sdlc/REVIEW.md": LINES.replace("line 9", "new 9")})
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    text = (consumer / ".sdlc/REVIEW.md").read_text()
    assert "mine 2" in text and "new 9" in text
    assert "kept your local changes" in result.stdout and ".sdlc/REVIEW.md" in result.stdout


def test_sync_keeps_local_edits_the_framework_did_not_change(consumer, framework_snapshot):
    commit(
        consumer, "chore: local tweak", {".sdlc/REVIEW.md": "local edit\n", "notes.md": "mine\n"}
    )
    commit(framework_snapshot, "fix: other file", {"NOTES.md": "x\n"})
    assert sync(consumer, framework_snapshot, "main").returncode == 0
    assert (consumer / ".sdlc/REVIEW.md").read_text() == "local edit\n"
    assert (consumer / "notes.md").read_text() == "mine\n"


def test_sync_conflict_keeps_both_sides_and_fails(consumer, framework_snapshot):
    synced_with(consumer, framework_snapshot, {".sdlc/REVIEW.md": LINES})
    commit(consumer, "chore: local tweak", {".sdlc/REVIEW.md": LINES.replace("line 5", "mine 5")})
    commit(framework_snapshot, "fix: change", {".sdlc/REVIEW.md": LINES.replace("line 5", "new 5")})
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 1
    assert "CONFLICT" in result.stderr and ".sdlc/REVIEW.md" in result.stderr
    text = (consumer / ".sdlc/REVIEW.md").read_text()
    assert "<<<<<<< yours" in text and "mine 5" in text and "new 5" in text
    staged = git(consumer, "diff", "--cached", "--name-only").split()
    assert ".sdlc/REVIEW.md" not in staged, "a conflicted file stays unstaged"
    assert ".sdlc/version" in staged, "the rest of the sync is staged"


def test_sync_unmergeable_file_is_left_alone_with_new_version_beside_it(
    consumer, framework_snapshot
):
    binary = "\x00base\n"
    synced_with(consumer, framework_snapshot, {".sdlc/REVIEW.md": binary})
    commit(consumer, "chore: local tweak", {".sdlc/REVIEW.md": "\x00mine\n"})
    commit(framework_snapshot, "fix: change", {".sdlc/REVIEW.md": "\x00new\n"})
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 1
    assert (consumer / ".sdlc/REVIEW.md").read_text() == "\x00mine\n", "local file untouched"
    assert (consumer / ".sdlc/REVIEW.md.sdlc-new").read_text() == "\x00new\n"
    assert ".sdlc/REVIEW.md.sdlc-new" in result.stderr and "by hand" in result.stderr
    staged = git(consumer, "diff", "--cached", "--name-only").split()
    assert ".sdlc/REVIEW.md.sdlc-new" not in staged and ".sdlc/REVIEW.md" not in staged


def test_first_sync_never_overwrites_a_file_the_consumer_has(tmp_path, framework_snapshot):
    repo = init_repo(tmp_path / "existing")
    shutil.copy(FIXTURE / "Makefile", repo / "Makefile")
    (repo / ".sdlc" / "scripts").mkdir(parents=True)
    shutil.copy(
        REPO / ".sdlc" / "scripts" / "sync-sdlc.sh", repo / ".sdlc" / "scripts" / "sync-sdlc.sh"
    )
    commit(repo, "chore: existing repo", {".github/workflows/sdlc-ci.yml": "name: our own ci\n"})
    result = sync(repo, framework_snapshot)
    assert result.returncode == 1
    assert ".github/workflows/sdlc-ci.yml" in result.stderr
    text = (repo / ".github/workflows/sdlc-ci.yml").read_text()
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
    assert (consumer / ".sdlc" / "templates" / "bug-spec.md").exists()


def test_build_plan_in_consumer(consumer):
    """A large build's draft build.md validates, an approval with open questions doesn't,
    and make status shows milestone progress."""
    assert make(consumer, "new-change", "NAME=role-list").returncode == 0
    change = consumer / "changes" / "0001-role-list"
    for name, sections in CHAIN.items():
        (change / name).write_text("# T\n\n" + artifact(sections))
    plan = change / "plan.md"
    text = plan.read_text().replace("## Descopes\n\nx", "## Descopes\n\nNone.")
    plan.write_text(
        text.replace("## Verification\n\n", "## Verification\n\n- **Definition of done:** UI\n\n")
    )
    draft = (consumer / ".sdlc" / "templates" / "build.md").read_text()
    (change / "build.md").write_text(draft)
    assert make(consumer, "validate").returncode == 0
    assert make(consumer, "status").stdout.strip() == (
        "0001-role-list\tbuild\tdraft, awaiting approval, 0/2 milestones done"
    )
    assert make(consumer, "next", "CHANGE=0001").stdout.strip() == (
        "0001-role-list\tbuild\tsdlc-build\tapprove the build plan (build.md)"
    )

    approved = draft.replace("draft, awaiting approval", "in progress", 1)
    (change / "build.md").write_text(approved.replace("None.\n", "1. Split it?\n", 1))
    refused = make(consumer, "validate")
    assert refused.returncode != 0
    assert "Questions before approval" in refused.stderr


def test_plan_descopes_in_consumer(consumer):
    """A new plan copied from the template fails until its Descopes is filled, and an entry
    needs a person's approval (#95)."""
    assert make(consumer, "new-change", "NAME=dock").returncode == 0
    change = consumer / "changes" / "0001-dock"
    for name in ("intent.md", "spec.md"):
        (change / name).write_text("# T\n\n" + artifact(CHAIN[name]))
    template = (consumer / ".sdlc" / "templates" / "plan.md").read_text()
    plan = change / "plan.md"
    plan.write_text(template)
    refused = make(consumer, "validate")
    assert "Definition of done names no kind" in refused.stderr
    template = template.replace("<the kinds of work that apply, e.g. Any code, UI>", "Any code, UI")
    assert refused.returncode != 0
    assert "Descopes still has the template's text" in refused.stderr

    entry = "- Descope: dock widget tests because the editor can't run headless."
    plan.write_text(template.replace("<None., or each descope and human check, as below>", entry))
    refused = make(consumer, "validate")
    assert refused.returncode != 0
    assert "no 'Approved: <name>, <date>'" in refused.stderr

    plan.write_text(plan.read_text().replace(entry, entry + " Approved: Sam, 2026-11-10."))
    assert make(consumer, "validate").returncode == 0


def test_definition_of_done_in_consumer(consumer, framework_snapshot):
    """The framework's rows arrive with the sync, the consumer's own file adds a kind a plan can
    name, and a later sync leaves that file alone (#95)."""
    assert (consumer / ".sdlc" / "templates" / "definition-of-done.md").exists()
    own = consumer / "docs" / "definition-of-done.md"
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_text("| Kind of work | Done means |\n|---|---|\n| Godot scene | Loads headless. |\n")
    git(consumer, "add", "docs/definition-of-done.md")
    git(consumer, "commit", "-q", "-m", "docs: our definition of done")

    assert make(consumer, "new-change", "NAME=scene").returncode == 0
    change = consumer / "changes" / "0001-scene"
    for name, sections in CHAIN.items():
        (change / name).write_text("# T\n\n" + artifact(sections))
    plan = change / "plan.md"
    text = plan.read_text().replace("## Descopes\n\nx", "## Descopes\n\nNone.")
    line = "## Verification\n\n- **Definition of done:** {}\n\n"
    plan.write_text(text.replace("## Verification\n\n", line.format("Godot scene, Any code")))
    assert make(consumer, "validate").returncode == 0
    plan.write_text(text.replace("## Verification\n\n", line.format("Godot level")))
    refused = make(consumer, "validate")
    assert refused.returncode != 0
    assert "names Godot level, not in the definition of done" in refused.stderr

    plan.unlink()
    git(consumer, "add", "-A")
    git(consumer, "commit", "-q", "-m", "wip")
    assert sync(consumer, framework_snapshot).returncode == 0
    assert "Godot scene" in own.read_text()


def test_adr_in_consumer(consumer, framework_snapshot):
    """The consumer's ADRs are validated by make validate, and the sync never touches them."""
    adrs = consumer / "docs" / "adr"
    adrs.mkdir(parents=True)
    template = (consumer / ".sdlc" / "templates" / "adr.md").read_text()
    accepted = template.replace("proposed <!--", "accepted (Sam, 2026-11-06) <!--", 1)
    (adrs / "0001-client-stack.md").write_text(
        accepted.replace("- <trigger>", "- a plan hand-builds navigation state")
    )
    assert make(consumer, "validate").returncode == 0
    commit(consumer, "docs: ADR 0001")

    assert sync(consumer, framework_snapshot, "main").returncode == 0
    assert "accepted" in (adrs / "0001-client-stack.md").read_text()

    (adrs / "0001-client-stack.md").write_text(accepted.replace("- <trigger>", "None."))
    refused = make(consumer, "validate")
    assert refused.returncode != 0
    assert "Revisit when" in refused.stderr


def test_placeholder_words_in_consumer(consumer, framework_snapshot):
    """The framework's words arrive with the CLI; the repo's .sdlc.toml overrides them and the
    sync leaves it alone."""
    assert (consumer / ".sdlc/src/sdlc/placeholders.toml").exists()
    adrs = consumer / "docs" / "adr"
    adrs.mkdir(parents=True)
    template = (consumer / ".sdlc" / "templates" / "adr.md").read_text()
    accepted = template.replace("proposed <!--", "accepted (Sam, 2026-11-06) <!--", 1)
    (adrs / "0001-client-stack.md").write_text(accepted.replace("- <trigger>", "- pending"))
    assert make(consumer, "validate").returncode == 0, "'pending' isn't a framework placeholder"

    (consumer / ".sdlc.toml").write_text(
        '[placeholders.nothing_written]\nadditional_keywords = ["pending"]\n'
    )
    commit(consumer, "chore: ADR and placeholder words")
    assert sync(consumer, framework_snapshot, "main").returncode == 0
    assert "pending" in (consumer / ".sdlc.toml").read_text()
    refused = make(consumer, "validate")
    assert refused.returncode != 0
    assert "names no trigger" in refused.stderr


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
        ".sdlc/skills/streaming-policy/SKILL.md": "consumer skill\n",
    }
    commit(consumer, "ci: consumer's own workflow and skill", own)
    commit(framework_snapshot, "fix: change", {".sdlc/REVIEW.md": "changed\n"})
    assert sync(consumer, framework_snapshot, "main").returncode == 0
    for rel, content in own.items():
        assert (consumer / rel).read_text() == content, rel
    assert (consumer / ".sdlc/REVIEW.md").read_text() == "changed\n"


def test_sync_removes_files_the_framework_dropped(consumer, framework_snapshot):
    dropped = ".sdlc/skills/po-review/SKILL.md"
    assert (consumer / dropped).exists()
    (framework_snapshot / dropped).unlink()
    commit(framework_snapshot, "feat!: drop po-review skill")
    assert sync(consumer, framework_snapshot, "main").returncode == 0
    assert not (consumer / dropped).exists()
    assert dropped not in (consumer / ".sdlc/files").read_text()


def test_sync_keeps_a_dropped_file_the_consumer_changed(consumer, framework_snapshot):
    dropped = ".sdlc/skills/po-review/SKILL.md"
    commit(consumer, "chore: our po-review", {dropped: "our version\n"})
    (framework_snapshot / dropped).unlink()
    commit(framework_snapshot, "feat!: drop po-review skill")
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (consumer / dropped).read_text() == "our version\n"
    assert dropped not in (consumer / ".sdlc/files").read_text(), "it's the consumer's now"
    assert "kept (the framework dropped these" in result.stdout


def test_sync_reports_make_targets_the_consumer_lacks(consumer, framework_snapshot):
    makefile = (consumer / "Makefile").read_text().replace(" fmt ", " ")  # its rule and .PHONY
    commit(consumer, "chore: drop fmt target", {"Makefile": makefile})
    commit(framework_snapshot, "fix: change", {".sdlc/REVIEW.md": "changed\n"})
    out = sync(consumer, framework_snapshot, "main").stdout
    assert "make fmt  (stack contract" in out
    assert "make coverage  (optional" in out
    assert "make check  (" not in out
    assert "make status" not in out, ".sdlc/sdlc.mk brings it"
    assert "include the pipeline's targets" not in out


def test_sync_asks_for_the_include_and_names_targets_it_replaces(consumer, framework_snapshot):
    makefile = (consumer / "Makefile").read_text().replace("include .sdlc/sdlc.mk\n", "")
    makefile += "\nstatus:\n\t@echo ours\n"
    commit(consumer, "chore: an older Makefile", {"Makefile": makefile})
    commit(framework_snapshot, "fix: change", {".sdlc/REVIEW.md": "changed\n"})
    out = sync(consumer, framework_snapshot, "main").stdout
    assert "your Makefile doesn't include the pipeline's targets" in out
    assert "  include .sdlc/sdlc.mk\n" in out
    assert (
        "your Makefile defines targets .sdlc/sdlc.mk now provides; delete yours:\n  status\n" in out
    )


def test_sdlc_files_lists_what_was_installed(consumer):
    files = (consumer / ".sdlc/files").read_text().split()
    assert ".sdlc/hooks/production-gate.sh" in files
    assert ".sdlc/src/sdlc/cli.py" in files
    assert ".github/workflows/release.yml" not in files
    assert "Makefile" not in files
    assert all((consumer / f).is_file() for f in files)


def test_sync_overwrites_files_in_place(consumer, framework_snapshot):
    # The sync script replaces itself while running; deleting it first leaves a
    # .fuse_hidden* file behind on NTFS-over-FUSE checkouts. Same inode = no delete.
    script = consumer / ".sdlc" / "scripts" / "sync-sdlc.sh"
    before = script.stat().st_ino
    commit(framework_snapshot, "fix: change", {".sdlc/REVIEW.md": "changed\n"})
    assert sync(consumer, framework_snapshot, "main").returncode == 0
    assert script.stat().st_ino == before


def test_a_new_framework_file_arrives_in_the_same_sync(consumer, framework_snapshot):
    # The file list lives in the sync script, so a version that adds a path must be run by
    # its own (new) script, or the new file only arrives on the next sync.
    script = framework_snapshot / ".sdlc" / "scripts" / "sync-sdlc.sh"
    text = script.read_text().replace(
        '    ".sdlc:.sdlc"\n',
        '    ".sdlc:.sdlc"\n    "NEW.md:NEW.md"\n',
    )
    commit(
        framework_snapshot,
        "feat: new file",
        {"NEW.md": "new\n", ".sdlc/scripts/sync-sdlc.sh": text},
    )
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "running the new one" in result.stdout
    assert (consumer / "NEW.md").read_text() == "new\n"
    assert "command not found" not in result.stderr


# --- secrets and variables the workflows use (#80) ------------------------------------------

FAKE_GH = """#!/usr/bin/env bash
case "$1 $2" in
  "auth status") exit "${FAKE_GH_AUTH:-0}" ;;
  "secret list") [[ "$FAKE_GH_SECRETS" == forbidden ]] && exit 1; printf '%s\\n' $FAKE_GH_SECRETS ;;
  "variable list") printf '%s\\n' $FAKE_GH_VARS ;;
  "api --paginate")
    # Org-level names shared with the repo; unset means a personal account's repo (422).
    org="${FAKE_GH_ORG_VARS-user}"
    [[ "$3" == */organization-secrets ]] && org="${FAKE_GH_ORG_SECRETS-user}"
    case "$org" in
      user) echo "gh: Validation Failed (HTTP 422)" >&2; exit 1 ;;
      forbidden) echo "gh: Resource not accessible (HTTP 403)" >&2; exit 1 ;;
    esac
    printf '%s\\n' $org ;;
  "api repos/o/r/actions/variables/SDLC_AUTO_MERGE")
    value="${FAKE_GH_AUTO_MERGE-merge}"
    [[ "$value" != unreadable ]] || exit 1; echo "$value" ;;
  "api repos/o/r/branches/main/protection")
    [[ -n "${FAKE_GH_PROTECTION:-}" ]] || exit 1; echo "$FAKE_GH_PROTECTION" ;;
  "api repos/o/r") echo "${FAKE_GH_PRIVATE-false}" ;;
  "api repos/o/r/actions/permissions")
    [[ "${FAKE_GH_ACTIONS-}" != unreadable ]] || exit 1
    echo "{\\"allowed_actions\\": \\"${FAKE_GH_ACTIONS:-all}\\"}" ;;
  "api repos/o/r/actions/permissions/selected-actions")
    [[ -n "${FAKE_GH_SELECTED:-}" ]] || exit 1; echo "$FAKE_GH_SELECTED" ;;
  "api repos/o/r/actions/variables/SDLC_REVIEW_EXTRA_BOTS")
    [[ "${FAKE_GH_EXTRA_BOTS-}" != unreadable ]] || exit 1; echo "${FAKE_GH_EXTRA_BOTS-}" ;;
  "api repos/o/r/dependabot/secrets")
    [[ "${FAKE_GH_DEPENDABOT_SECRETS-}" != forbidden ]] || exit 1
    printf '%s\\n' $FAKE_GH_DEPENDABOT_SECRETS ;;
  "api repos/o/r/actions/permissions/fork-pr-contributor-approval")
    [[ -n "${FAKE_GH_FORK_POLICY:-}" ]] || exit 1; echo "$FAKE_GH_FORK_POLICY" ;;
  *) exit 1 ;;
esac
"""


def sync_with_gh(consumer, framework_snapshot, tmp_path, secrets="", variables="", **env):
    fake = tmp_path / "fakebin"
    fake.mkdir(exist_ok=True)
    (fake / "gh").write_text(FAKE_GH)
    (fake / "gh").chmod(0o755)
    git(consumer, "remote", "add", "origin", "git@github.com:o/r.git")
    commit(framework_snapshot, "fix: change", {".sdlc/REVIEW.md": "changed\n"})
    return run(
        ["bash", ".sdlc/scripts/sync-sdlc.sh", "main"],
        cwd=consumer,
        env={
            "SDLC_SOURCE": str(framework_snapshot),
            "PATH": f"{fake}:{os.environ['PATH']}",
            "FAKE_GH_SECRETS": secrets,
            "FAKE_GH_VARS": variables,
            **env,
        },
    )


def test_sync_lists_every_secret_and_variable_the_workflows_use():
    script = (REPO / ".sdlc" / "scripts" / "sync-sdlc.sh").read_text()
    for wf in (REPO / ".github" / "workflows").glob("*.yml"):
        if wf.name == "release.yml":  # framework-only, never synced
            continue
        for kind, name in re.findall(r"\b(secrets|vars)\.([A-Z0-9_]+)", wf.read_text()):
            if name == "GITHUB_TOKEN":
                continue
            entry = f'"{"secret" if kind == "secrets" else "variable"} {name}'
            assert entry in script, f"{wf.name} uses {kind}.{name}; list it in sync-sdlc.sh"


def test_sync_reports_missing_required_secret_and_optional_app(
    consumer, framework_snapshot, tmp_path
):
    out = sync_with_gh(consumer, framework_snapshot, tmp_path).stdout
    assert "in o/r (its own and its organization's):" in out
    assert "MISSING (required): secret CLAUDE_CODE_OAUTH_TOKEN" in out
    assert "not set (optional): the agent App" in out
    assert "half set up" not in out


def test_sync_reports_a_half_set_up_app(consumer, framework_snapshot, tmp_path):
    # #82: an App ID and key without the slug opens spec PRs the review then rejects.
    out = sync_with_gh(
        consumer,
        framework_snapshot,
        tmp_path,
        secrets="CLAUDE_CODE_OAUTH_TOKEN SDLC_AGENT_APP_KEY",
        variables="SDLC_AGENT_APP_ID",
    ).stdout
    assert "ERROR: the agent App is half set up" in out
    assert "SDLC_AGENT_APP_SLUG missing" in out
    assert "MISSING (required)" not in out


def test_sync_is_quiet_when_everything_is_set(consumer, framework_snapshot, tmp_path):
    out = sync_with_gh(
        consumer,
        framework_snapshot,
        tmp_path,
        secrets="CLAUDE_CODE_OAUTH_TOKEN SDLC_AGENT_APP_KEY",
        variables="SDLC_AGENT_APP_ID SDLC_AGENT_APP_SLUG",
    ).stdout
    assert "secrets and variables" not in out


def test_sync_says_when_it_cant_read_secrets(consumer, framework_snapshot, tmp_path):
    # Fail safe: unreadable secret names are "not checked", never "missing".
    out = sync_with_gh(
        consumer,
        framework_snapshot,
        tmp_path,
        secrets="forbidden",
        variables="SDLC_AGENT_APP_ID SDLC_AGENT_APP_SLUG",
    ).stdout
    assert "not checked: can't read o/r's secret names" in out
    assert "MISSING" not in out
    assert "half set up" not in out


def test_sync_skips_the_check_without_gh_login(consumer, framework_snapshot, tmp_path):
    result = sync_with_gh(consumer, framework_snapshot, tmp_path, FAKE_GH_AUTH="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "secrets and variables" not in result.stdout


def test_sync_counts_org_level_secrets_and_variables(consumer, framework_snapshot, tmp_path):
    # Review on #84: a token shared from the organization isn't missing.
    out = sync_with_gh(
        consumer,
        framework_snapshot,
        tmp_path,
        FAKE_GH_ORG_SECRETS="CLAUDE_CODE_OAUTH_TOKEN SDLC_AGENT_APP_KEY",
        FAKE_GH_ORG_VARS="SDLC_AGENT_APP_ID SDLC_AGENT_APP_SLUG",
    ).stdout
    assert "secrets and variables" not in out


def test_sync_says_when_it_cant_read_org_secrets(consumer, framework_snapshot, tmp_path):
    out = sync_with_gh(
        consumer,
        framework_snapshot,
        tmp_path,
        variables="SDLC_AGENT_APP_ID SDLC_AGENT_APP_SLUG",
        FAKE_GH_ORG_SECRETS="forbidden",
    ).stdout
    assert "not checked: can't read o/r's secret names" in out
    assert "MISSING" not in out


# --- SDLC_RUNNER: framework jobs on a self-hosted runner (#126) ------------------------------


def runner_sync(consumer, framework_snapshot, tmp_path, runner=True, **env):
    variables = f"{APP_VARS} SDLC_RUNNER" if runner else APP_VARS
    return sync_with_gh(
        consumer, framework_snapshot, tmp_path, variables=variables, **ALL_SET, **env
    ).stdout


@pytest.mark.parametrize(
    "policy", ["first_time_contributors", "first_time_contributors_new_to_github"]
)
def test_sync_warns_when_a_public_repo_runs_fork_prs_on_the_runner_without_approval(
    consumer, framework_snapshot, tmp_path, policy
):
    out = runner_sync(consumer, framework_snapshot, tmp_path, FAKE_GH_FORK_POLICY=policy)
    assert (
        "WARNING: SDLC_RUNNER is set on a public repo, but some fork PRs run their workflows "
        f"without approval ({policy})" in out
    )
    assert "Require approval for all external contributors" in out
    assert (consumer / ".sdlc/docs/self-hosted-runner.md").is_file()


def test_sync_is_quiet_when_every_fork_pr_needs_approval(consumer, framework_snapshot, tmp_path):
    out = runner_sync(
        consumer, framework_snapshot, tmp_path, FAKE_GH_FORK_POLICY="all_external_contributors"
    )
    assert "SDLC_RUNNER" not in out


def test_sync_skips_the_fork_check_on_a_private_repo(consumer, framework_snapshot, tmp_path):
    out = runner_sync(
        consumer,
        framework_snapshot,
        tmp_path,
        FAKE_GH_PRIVATE="true",
        FAKE_GH_FORK_POLICY="first_time_contributors",
    )
    assert "SDLC_RUNNER" not in out


def test_sync_says_when_it_cant_read_the_fork_approval_policy(
    consumer, framework_snapshot, tmp_path
):
    out = runner_sync(consumer, framework_snapshot, tmp_path)  # no policy: the API call fails
    assert (
        "not checked: SDLC_RUNNER is set, but can't read whether fork PR workflows need approval"
        in out
    )


def test_sync_says_nothing_about_the_runner_when_sdlc_runner_is_unset(
    consumer, framework_snapshot, tmp_path
):
    out = runner_sync(
        consumer,
        framework_snapshot,
        tmp_path,
        runner=False,
        FAKE_GH_FORK_POLICY="first_time_contributors",
    )
    assert "SDLC_RUNNER" not in out


# --- allowed actions: a missing one stops a workflow at startup (#157) -----------------------

FRAMEWORK_ACTIONS = [
    "actions/checkout@*",
    "actions/create-github-app-token@*",
    "actions/upload-artifact@*",
    "anthropics/claude-code-action@*",
    "oven-sh/setup-bun@*",
]


def actions_sync(consumer, framework_snapshot, tmp_path, allowed="selected", patterns=None, **env):
    selected = (
        {}
        if patterns is None
        else {
            "FAKE_GH_SELECTED": json.dumps(
                {
                    "github_owned_allowed": False,
                    "verified_allowed": False,
                    "patterns_allowed": patterns,
                }
            )
        }
    )
    return sync_with_gh(
        consumer,
        framework_snapshot,
        tmp_path,
        variables=APP_VARS,
        **ALL_SET,
        FAKE_GH_ACTIONS=allowed,
        **selected,
        **env,
    ).stdout


def test_sync_names_an_action_the_allowlist_leaves_out(consumer, framework_snapshot, tmp_path):
    before_157 = [p for p in FRAMEWORK_ACTIONS if "upload-artifact" not in p]
    out = actions_sync(consumer, framework_snapshot, tmp_path, patterns=before_157)
    assert "ERROR: o/r's allowed actions leave out actions/upload-artifact, so the workflows" in out
    assert "fail at startup" in out and "<name>@*" in out


@pytest.mark.parametrize(
    "patterns",
    [
        FRAMEWORK_ACTIONS,
        ["actions/*", "anthropics/claude-code-action@v1", "oven-sh/*"],  # wider patterns
        ["*"],
    ],
    ids=["each", "wider", "everything"],
)
def test_sync_is_quiet_when_the_allowlist_has_every_action(
    consumer, framework_snapshot, tmp_path, patterns
):
    out = actions_sync(consumer, framework_snapshot, tmp_path, patterns=patterns)
    assert "allowed actions" not in out and "secrets and variables" not in out


def test_sync_counts_github_owned_actions_when_allowed(consumer, framework_snapshot, tmp_path):
    selected = json.dumps(
        {
            "github_owned_allowed": True,
            "verified_allowed": False,
            "patterns_allowed": ["anthropics/claude-code-action@*", "oven-sh/setup-bun@*"],
        }
    )
    out = actions_sync(consumer, framework_snapshot, tmp_path, FAKE_GH_SELECTED=selected)
    assert "leave out" not in out


def test_sync_says_local_only_blocks_every_framework_action(consumer, framework_snapshot, tmp_path):
    out = actions_sync(consumer, framework_snapshot, tmp_path, allowed="local_only")
    assert "leave out actions/checkout actions/create-github-app-token" in out


def test_sync_says_when_it_cant_read_the_allowlist(consumer, framework_snapshot, tmp_path):
    out = actions_sync(consumer, framework_snapshot, tmp_path)  # selected, list unreadable
    assert "not checked: o/r allows only selected actions, but can't read which" in out
    assert "actions/upload-artifact" in out


def test_sync_says_when_it_cant_read_the_actions_setting(consumer, framework_snapshot, tmp_path):
    unreadable = actions_sync(consumer, framework_snapshot, tmp_path, allowed="unreadable")
    assert "not checked: can't read which actions o/r allows (needs admin)" in unreadable
    assert "ERROR" not in unreadable


# --- SDLC_REVIEW_EXTRA_BOTS: dependency-bot PRs get reviewed (#142) -------------------------


def bots_sync(consumer, framework_snapshot, tmp_path, bots, **env):
    return sync_with_gh(
        consumer,
        framework_snapshot,
        tmp_path,
        variables=f"{APP_VARS} SDLC_REVIEW_EXTRA_BOTS",
        FAKE_GH_EXTRA_BOTS=bots,
        **ALL_SET,
        **env,
    ).stdout


@pytest.mark.parametrize("bots", ["dependabot", "renovate, dependabot", "dependabot[bot]"])
def test_sync_warns_when_dependabot_is_reviewed_without_its_own_token(
    consumer, framework_snapshot, tmp_path, bots
):
    out = bots_sync(consumer, framework_snapshot, tmp_path, bots, FAKE_GH_DEPENDABOT_SECRETS="")
    assert "WARNING: SDLC_REVIEW_EXTRA_BOTS names Dependabot, but CLAUDE_CODE_OAUTH_TOKEN" in out
    assert "gh secret set CLAUDE_CODE_OAUTH_TOKEN --app dependabot" in out


def test_sync_is_quiet_when_dependabot_has_the_token(consumer, framework_snapshot, tmp_path):
    out = bots_sync(
        consumer,
        framework_snapshot,
        tmp_path,
        "renovate,dependabot",
        FAKE_GH_DEPENDABOT_SECRETS="OTHER CLAUDE_CODE_OAUTH_TOKEN",
    )
    assert "secrets and variables" not in out


@pytest.mark.parametrize("bots", ["renovate", "dependabot-preview-ish", ""])
def test_sync_skips_the_dependabot_check_for_other_bots(
    consumer, framework_snapshot, tmp_path, bots
):
    out = bots_sync(consumer, framework_snapshot, tmp_path, bots, FAKE_GH_DEPENDABOT_SECRETS="")
    assert "SDLC_REVIEW_EXTRA_BOTS" not in out


def test_sync_says_when_it_cant_read_the_bots_or_dependabot_secrets(
    consumer, framework_snapshot, tmp_path
):
    out = bots_sync(consumer, framework_snapshot, tmp_path, "unreadable")
    assert "not checked: SDLC_REVIEW_EXTRA_BOTS is set, but can't read its value" in out
    assert "WARNING" not in out


def test_sync_says_when_it_cant_read_dependabot_secrets(consumer, framework_snapshot, tmp_path):
    out = bots_sync(
        consumer, framework_snapshot, tmp_path, "dependabot", FAKE_GH_DEPENDABOT_SECRETS="forbidden"
    )
    assert "not checked: SDLC_REVIEW_EXTRA_BOTS names Dependabot, but can't read" in out
    assert "WARNING" not in out


def test_sync_says_nothing_about_bots_when_the_variable_is_unset(
    consumer, framework_snapshot, tmp_path
):
    out = sync_with_gh(
        consumer,
        framework_snapshot,
        tmp_path,
        variables=APP_VARS,
        FAKE_GH_EXTRA_BOTS="dependabot",
        **ALL_SET,
    ).stdout
    assert "SDLC_REVIEW_EXTRA_BOTS" not in out


# --- opt-in auto-merge (#89) ----------------------------------------------------------------

ALL_SET = {"secrets": "CLAUDE_CODE_OAUTH_TOKEN SDLC_AGENT_APP_KEY"}
APP_VARS = "SDLC_AGENT_APP_ID SDLC_AGENT_APP_SLUG"


def _protection(dismiss):
    return json.dumps(
        {
            "required_status_checks": {"contexts": ["check", "pr-title", "claude-review"]},
            "required_pull_request_reviews": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews": dismiss,
            },
        }
    )


def test_sync_installs_auto_merge_and_is_quiet_when_not_opted_in(
    consumer, framework_snapshot, tmp_path
):
    out = sync_with_gh(consumer, framework_snapshot, tmp_path, variables=APP_VARS, **ALL_SET)
    assert "SDLC_AUTO_MERGE" not in out.stdout
    staged = git(consumer, "ls-files", "-s", ".sdlc/scripts/auto-merge.sh")
    assert staged.startswith("100755"), staged


def test_sync_warns_when_main_no_longer_qualifies_for_auto_merge(
    consumer, framework_snapshot, tmp_path
):
    out = sync_with_gh(
        consumer,
        framework_snapshot,
        tmp_path,
        variables=f"{APP_VARS} SDLC_AUTO_MERGE SDLC_AUTO_MERGE_CONFIRMED",
        FAKE_GH_PROTECTION=_protection(False),
        **ALL_SET,
    ).stdout
    assert "WARNING: SDLC_AUTO_MERGE is set, but main doesn't qualify" in out
    assert "stale approvals are not dismissed" in out
    assert "ERROR: SDLC_AUTO_MERGE_CONFIRMED is set but no longer true" in out


def test_sync_is_quiet_when_main_qualifies_for_auto_merge(consumer, framework_snapshot, tmp_path):
    out = sync_with_gh(
        consumer,
        framework_snapshot,
        tmp_path,
        variables=f"{APP_VARS} SDLC_AUTO_MERGE",
        FAKE_GH_PROTECTION=_protection(True),
        **ALL_SET,
    ).stdout
    assert "secrets and variables" not in out


def test_sync_says_when_it_cant_check_auto_merge(consumer, framework_snapshot, tmp_path):
    out = sync_with_gh(
        consumer, framework_snapshot, tmp_path, variables=f"{APP_VARS} SDLC_AUTO_MERGE", **ALL_SET
    ).stdout
    assert "not checked: SDLC_AUTO_MERGE is set, but can't read main's branch protection" in out


def test_numbered_criteria_fail_on_the_consumer_spec_pr(consumer):
    """#90: a generated spec with a numbered list of criteria fails at the spec stage, and the
    scope rules (#95) reach the consumer with the skills that read them."""
    assert make(consumer, "new-change", "NAME=menus").returncode == 0
    folder = consumer / "changes" / "0001-menus"
    spec = (consumer / ".sdlc" / "templates" / "spec.md").read_text()
    (folder / "spec.md").write_text(spec.replace("- AC1 (R1): ", "1. "))
    broken = make(consumer, "validate")
    assert broken.returncode != 0
    assert "numbered list" in broken.stderr
    (folder / "spec.md").write_text(spec)
    assert make(consumer, "validate").returncode == 0
    assert (consumer / ".sdlc" / "skills" / "scope.md").exists()


def test_clause_check_in_consumer(consumer, framework_snapshot):
    """The clause check (#47) arrives with the sync and splits a consumer's spec, and a
    consumer without the `clauses` target is told it's optional."""
    script = consumer / ".sdlc" / "scripts" / "clause-check.sh"
    assert os.access(script, os.X_OK)
    assert (consumer / ".sdlc" / "prompts" / "clause-check.md").exists()
    fixture = REPO / "evals" / "fixtures" / "clause-coverage" / "0001-role-search"
    folder = consumer / "changes" / "0001-role-search"
    folder.mkdir(parents=True)
    for name in ("spec.md", "plan.md"):
        shutil.copy(fixture / name, folder / name)
    out = make(consumer, "clauses", "CHANGE=0001")
    assert out.returncode == 0, out.stderr
    assert [b["id"] for b in json.loads(out.stdout)["requirements"]] == ["R1", "R2"]
    dry = run([str(script), "--stage", "plan", "0001"], cwd=consumer, env={"AGENT": "echo"})
    assert dry.returncode == 0, dry.stderr
    assert [f["requirement"] for f in json.loads(dry.stdout)] == ["R1", "R2"]


def test_clause_check_finds_the_changed_specs_and_plans_in_consumer(consumer):
    """The review's mode: each change whose spec or plan the branch changed, at the right stage,
    with only its changed requirements; an unreadable spec doesn't stop the others."""
    fixture = REPO / "evals" / "fixtures" / "clause-coverage" / "0001-role-search"
    spec, plan = (fixture / "spec.md").read_text(), (fixture / "plan.md").read_text()
    commit(
        consumer,
        "spec and plan",
        {"changes/0001-search/spec.md": spec, "changes/0001-search/plan.md": plan},
    )
    git(consumer, "checkout", "-q", "-b", "amend")
    commit(
        consumer,
        "amend",
        {
            # 0001: the plan changes R2's row only, so it's checked at stage plan, R2 only.
            "changes/0001-search/plan.md": plan.replace("box holds", "box still holds"),
            # 0002: new, at stage spec; its R2 is in a form the check can't read.
            "changes/0002-export/spec.md": spec.replace("search box", "export button").replace(
                "- R2. When", "- Requirement 2: When"
            ),
            "changes/0003-broken/spec.md": "# Spec\n\n## Requirements\n\nTBD\n",
        },
    )
    git(consumer, "checkout", "-q", "main")
    commit(consumer, "later on main", {"changes/0004-later/spec.md": spec})
    git(consumer, "checkout", "-q", "amend")

    result = run(
        [".sdlc/scripts/clause-check.sh", "--changed-since", "main"],
        cwd=consumer,
        env={"AGENT": "echo"},
    )
    assert result.returncode == 0, result.stderr
    found = [(f["change"], f["stage"], f.get("requirement")) for f in json.loads(result.stdout)]
    assert found == [
        ("0001-search", "plan", "R2"),
        ("0002-export", "spec", "R1"),
        ("0002-export", "spec", None),  # unreadable, so unchecked, never dropped
        ("0003-broken", "spec", None),
    ]
    broken = json.loads(result.stdout)[-1]
    assert "no requirements could be read" in broken["unchecked"]
    assert not list(consumer.glob(".clause-check*")), "nothing left in the repo"


def test_delivery_check_in_consumer(consumer):
    """Stage build (#106) arrives with the sync and reads the consumer's build.md."""
    assert (consumer / ".sdlc" / "prompts" / "delivery-check.md").exists()
    fixture = REPO / "evals" / "fixtures" / "delivery-gap" / "0001-floor-mode"
    shutil.copytree(fixture, consumer / "changes" / "0001-floor-mode")
    out = make(consumer, "clauses", "CHANGE=0001")
    assert out.returncode == 0, out.stderr
    [r1, _] = json.loads(out.stdout)["requirements"]
    assert "- **Goal:** Show a whole floor as the game places it" in [
        b["text"] for b in r1["build"]
    ]
    dry = run(
        [".sdlc/scripts/clause-check.sh", "--stage", "build", "0001"],
        cwd=consumer,
        env={"AGENT": "echo"},
    )
    assert dry.returncode == 0, dry.stderr
    assert [(f["stage"], f["requirement"]) for f in json.loads(dry.stdout)] == [
        ("build", "R1"),
        ("build", "R2"),
    ]


def test_delivery_check_reads_approvals_from_a_change_named_by_number(consumer, tmp_path):
    """`--stage build 0001` finds changes/0001-* to check approval quotes against (#109 review)."""
    fixture = REPO / "evals" / "fixtures" / "delivery-gap" / "0002-floor-mode-approved"
    shutil.copytree(fixture, consumer / "changes" / "0001-floor-mode")
    real = "Descope: R1's 3D scene opened in the editor"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    answer = json.dumps(
        [
            {"clause": "a 3D scene", "delivered": "x", "gap": "large", "approved": real},
            {"clause": "opened", "delivered": "x", "gap": "large", "approved": "Approved: Lee"},
        ]
    )
    (tmp_path / "answer.txt").write_text(f"CLAUSES: {answer}\n")
    (bin_dir / "claude").write_text(f"#!/usr/bin/env bash\ncat '{tmp_path / 'answer.txt'}'\n")
    (bin_dir / "claude").chmod(0o755)
    result = run(
        [".sdlc/scripts/clause-check.sh", "--stage", "build", "0001"],
        cwd=consumer,
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    r1 = [f for f in json.loads(result.stdout) if f["requirement"] == "R1"]
    assert [(f["approved"], f.get("approval_not_found")) for f in r1] == [
        (real, None),
        (None, "Approved: Lee"),
    ]


def test_readable_requirements_hold_new_specs_and_leave_merged_ones(consumer):
    """v0.9.0's breaking rule: a spec the branch adds or edits needs `- R<n>.` requirements;
    one already on main stays valid until it's edited."""
    old_form = (
        "# Spec\n\n## Summary\n\nx\n\n## Requirements\n\n- R1. Search the list.\n"
        "- Requirement 2: Export the list.\n\n"
        "## Acceptance criteria\n\n- AC1 (R1): x\n\n## Policy concerns\n\nNone.\n\n"
        "## Out of scope\n\nNone.\n"
    )
    intent = "# I\n\n" + artifact(CHAIN["intent.md"])
    commit(
        consumer,
        "merged before the rule",
        {"changes/0001-done/intent.md": intent, "changes/0001-done/spec.md": old_form},
    )
    assert make(consumer, "validate").returncode == 0, "done work is left alone"
    git(consumer, "checkout", "-q", "-b", "spec/0002-new")
    commit(
        consumer,
        "new spec",
        {"changes/0002-new/intent.md": intent, "changes/0002-new/spec.md": old_form},
    )
    broken = make(consumer, "validate")
    assert broken.returncode != 0
    assert "0002-new/spec.md: can't read this as a requirement" in broken.stderr
    assert "0001-done" not in broken.stderr
    fixed = old_form.replace("- Requirement 2: Export", "- R2. Export")
    (consumer / "changes/0002-new/spec.md").write_text(fixed)
    assert make(consumer, "validate").returncode == 0


def test_request_review_arrives_with_the_sync(consumer):
    """#105: the review skills call .sdlc/scripts/request-review.sh, so the sync installs it
    runnable."""
    script = consumer / ".sdlc" / "scripts" / "request-review.sh"
    assert os.access(script, os.X_OK)
    assert ".sdlc/scripts/request-review.sh" in (consumer / ".sdlc/files").read_text()
    skill = (consumer / ".sdlc" / "skills" / "review-findings" / "SKILL.md").read_text()
    assert ".sdlc/scripts/request-review.sh <N>" in skill


def test_sync_reports_the_repos_own_scripts_that_arent_executable(consumer, framework_snapshot):
    """#101 finding 10: the sync sets modes only on framework files, so a repo-owned script that
    lost its bit (NTFS) is reported with the fix, not changed."""
    commit(
        consumer,
        "chore: own scripts",
        {".github/actions/deploy.sh": "echo hi\n", "tools/ok.sh": "echo ok\n"},
    )
    (consumer / "tools/ok.sh").chmod(0o755)  # executable on disk and in git, as on Linux
    git(consumer, "update-index", "--chmod=+x", "tools/ok.sh")
    commit(consumer, "chore: ok.sh is executable")
    commit(framework_snapshot, "fix: change", {".sdlc/REVIEW.md": "changed\n"})
    out = sync(consumer, framework_snapshot, "main").stdout
    report = out[out.index("your own scripts that aren't executable") :]
    assert "  .github/actions/deploy.sh" in report
    assert "tools/ok.sh" not in report and ".sdlc/scripts/sync-sdlc.sh" not in report
    assert "git update-index --chmod=+x" in report
    mode = git(consumer, "ls-files", "-s", ".github/actions/deploy.sh").split()[0]
    assert mode == "100644", "reported, not changed"


def test_sync_is_quiet_when_the_repos_scripts_are_executable(consumer, framework_snapshot):
    commit(framework_snapshot, "fix: change", {".sdlc/REVIEW.md": "changed\n"})
    assert "aren't executable" not in sync(consumer, framework_snapshot, "main").stdout


@pytest.mark.parametrize("value", ["off", "OFF", ""])
def test_sync_says_nothing_about_auto_merge_when_it_is_off(
    consumer, framework_snapshot, tmp_path, value
):
    # #101 finding 7: `off` is off (THE RULE in .sdlc/scripts/auto-merge.sh), so no warnings.
    out = sync_with_gh(
        consumer,
        framework_snapshot,
        tmp_path,
        variables=f"{APP_VARS} SDLC_AUTO_MERGE SDLC_AUTO_MERGE_CONFIRMED",
        FAKE_GH_PROTECTION=_protection(False),
        FAKE_GH_AUTO_MERGE=value,
        **ALL_SET,
    ).stdout
    assert "SDLC_AUTO_MERGE is set" not in out and "SDLC_AUTO_MERGE_CONFIRMED is set" not in out


def test_sync_still_checks_auto_merge_when_its_value_cant_be_read(
    consumer, framework_snapshot, tmp_path
):
    out = sync_with_gh(
        consumer,
        framework_snapshot,
        tmp_path,
        variables=f"{APP_VARS} SDLC_AUTO_MERGE",
        FAKE_GH_PROTECTION=_protection(False),
        FAKE_GH_AUTO_MERGE="unreadable",
        **ALL_SET,
    ).stdout
    assert "WARNING: SDLC_AUTO_MERGE is set, but main doesn't qualify" in out


def test_next_shows_a_merged_small_build_as_done_in_consumer(consumer):
    """#122: a small build has no build.md, so `make next` reads its PR's merge from history."""
    folder = consumer / "changes" / "0001-tidy"
    for name in CHAIN:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text("# T\n\n" + artifact(CHAIN[name]))
    commit(consumer, "plan(0001-tidy): plan it")
    assert "0001-tidy\tplan\tsdlc-build\tbuild it" in make(consumer, "next").stdout
    git(consumer, "checkout", "-q", "-b", "build/0001-tidy")
    commit(consumer, "feat(0001-tidy): tidy", {"src.txt": "tidy\n"})
    git(consumer, "checkout", "-q", "main")
    git(
        consumer,
        "merge",
        "-q",
        "--no-ff",
        "-m",
        "Merge pull request #3 from o/build/0001-tidy",
        "build/0001-tidy",
    )
    assert "0001-tidy\tplan\tdone\tbuilt and merged (#3)" in make(consumer, "next").stdout


def test_next_shows_a_merged_fast_path_bug_as_done_in_consumer(consumer):
    """#148, #160: a fast-path bug's one PR brings its spec.md with the fix, and no plan.md."""
    folder = consumer / "changes" / "0002-crash"
    folder.mkdir(parents=True)
    (folder / "bug.md").write_text("# T\n\n" + artifact(BUG_CHAIN["bug.md"]))
    commit(consumer, "bug(0002-crash): the report")
    git(consumer, "checkout", "-q", "-b", "build/0002-crash")
    (folder / "spec.md").write_text("# T\n\n" + artifact(BUG_CHAIN["spec.md"]))
    commit(consumer, "bug(0002-crash): the spec")
    commit(consumer, "fix(0002-crash): stop it", {"src.txt": "fixed\n"})
    git(consumer, "checkout", "-q", "main")
    git(
        consumer,
        "merge",
        "-q",
        "--no-ff",
        "-m",
        "Merge pull request #4 from o/build/0002-crash",
        "build/0002-crash",
    )
    out = make(consumer, "next").stdout
    assert "0002-crash\tspec\tdone\tfixed on the fast path and merged (#4)" in out


def test_stale_review_and_title_checks_arrive_with_the_sync(consumer):
    """#46: the workflows call these scripts, so the sync installs them runnable."""
    scripts = ("review-current.sh", "review-posted.sh", "review-findings.sh", "check-pr-title.sh")
    for name in scripts:
        assert os.access(consumer / ".sdlc" / "scripts" / name, os.X_OK), name
    bad = run(
        [".sdlc/scripts/check-pr-title.sh", "docs: tidy"],
        cwd=consumer,
        input="changes/0001-x/spec.md\n",
    )
    assert bad.returncode == 1 and "use spec" in bad.stdout
    assert (
        run(
            [".sdlc/scripts/check-pr-title.sh", "spec(0001-x): amend"],
            cwd=consumer,
            input="changes/0001-x/spec.md\n",
        ).returncode
        == 0
    )


def test_a_consumers_review_rules_survive_the_sync(consumer, framework_snapshot):
    """The project's docs/review-rules.md is its own: a sync that changes .sdlc/REVIEW.md
    leaves it."""
    assert (consumer / ".sdlc" / "templates" / "review-rules.md").exists()
    rules = "# Review rules\n\n- **Architecture:** core/ never touches scenes. Important.\n"
    commit(consumer, "docs: our review rules", {"docs/review-rules.md": rules})
    commit(framework_snapshot, "fix: review", {".sdlc/REVIEW.md": "changed\n"})
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (consumer / "docs" / "review-rules.md").read_text() == rules
    assert "docs/review-rules.md" not in (consumer / ".sdlc/files").read_text()


def test_a_consumer_adopts_a_roadmap_and_validate_checks_it(consumer, framework_snapshot):
    """#81: no roadmap, no check; once docs/roadmap.md exists, intents and rows must agree,
    and the sync leaves the project's roadmap alone."""
    assert (consumer / ".sdlc" / "docs" / "roadmap-format.md").is_file()
    assert make(consumer, "new-change", "NAME=phone-access").returncode == 0
    intent = consumer / "changes" / "0001-phone-access" / "intent.md"
    intent.write_text(intent.read_text().replace("<name>", "Sam"))
    assert make(consumer, "validate").returncode == 0, "no roadmap: nothing to check"

    roadmap = (consumer / ".sdlc" / "templates" / "roadmap.md").read_text()
    (consumer / "docs").mkdir(exist_ok=True)  # the framework's docs are in .sdlc/docs now
    (consumer / "docs" / "roadmap.md").write_text(roadmap)
    result = make(consumer, "validate")
    assert result.returncode != 0
    assert "changes/0001-phone-access: intent.md has no Milestone: line" in result.stderr
    assert "no row in docs/roadmap.md" in result.stderr

    intent.write_text(
        intent.read_text().replace("Product owner: Sam\n", "Product owner: Sam\nMilestone: M1\n")
    )
    row = "| [0001-phone-access](../changes/0001-phone-access/) | Phone access | planned |\n"
    (consumer / "docs" / "roadmap.md").write_text(
        roadmap.replace("|---|---|---|\n", "|---|---|---|\n" + row)
    )
    result = make(consumer, "validate")
    assert result.returncode == 0, result.stdout + result.stderr

    commit(consumer, "intent(0001-phone-access): phone access")
    kept = (consumer / "docs" / "roadmap.md").read_text()
    commit(framework_snapshot, "fix: roadmap template", {".sdlc/templates/roadmap.md": "changed\n"})
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (consumer / "docs" / "roadmap.md").read_text() == kept
    assert "docs/roadmap.md\n" not in (consumer / ".sdlc/files").read_text()


# --- the move into .sdlc/ (#133) -------------------------------------------------------------

OLD = "v0.10.1"  # the last release with the framework spread across the repo


@pytest.fixture
def framework_history(tmp_path):
    """A framework repo whose history is the real OLD release, then this working tree."""
    snap = init_repo(tmp_path / "framework")
    run(["bash", "-c", f'git archive {OLD} | tar -x -C "$0"', str(snap)], check=True)
    commit(snap, f"release {OLD}")
    git(snap, "tag", OLD)
    git(snap, "rm", "-rq", ".")
    copy_working_tree(snap)
    commit(snap, "the move into .sdlc/")
    return snap


@pytest.fixture
def old_consumer(tmp_path, framework_history):
    """A consumer on OLD, with local edits to two framework files."""
    repo = init_repo(tmp_path / "consumer")
    makefile = git(REPO, "show", f"{OLD}:tests/fixtures/consumer/Makefile") + "\n"
    old_sync = git(REPO, "show", f"{OLD}:scripts/sync-sdlc.sh") + "\n"
    commit(
        repo, "chore: consumer skeleton", {"Makefile": makefile, "scripts/sync-sdlc.sh": old_sync}
    )
    env = {"SDLC_SOURCE": str(framework_history)}
    result = run(["bash", "scripts/sync-sdlc.sh", OLD], cwd=repo, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    commit(repo, f"chore: sync {OLD}")
    for rel, line in [
        ("templates/intent.md", "\nOur own line in the intent template.\n"),
        (".claude/skills/build/SKILL.md", "\nOur own build rule.\n"),
        (".claude/skills/security-policy/SKILL.md", "\nNo secrets in Godot scenes.\n"),
    ]:
        path = repo / rel
        path.write_text(path.read_text() + line)
    commit(repo, "chore: our edits")
    return repo


def test_an_old_consumer_moves_into_sdlc_in_one_sync(old_consumer, framework_history):
    # The consumer's own copy of the old sync script finds the new one through the shim.
    env = {"SDLC_SOURCE": str(framework_history)}
    result = run(["bash", "scripts/sync-sdlc.sh", "main"], cwd=old_consumer, env=env)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "running the new one" in out

    for gone in (
        "templates",
        "prompts",
        "tools",
        ".claude/hooks",
        "REVIEW.md",
        "evals",
        ".sdlc-files",
        ".sdlc-version",
        "docs/roles.md",
    ):
        assert not (old_consumer / gone).exists(), gone
    assert not (old_consumer / "scripts").exists(), "the old sync script went too"
    assert "kept (the framework dropped these" not in out, "nothing was left behind"

    # Local edits moved with their files, merged into the new versions.
    intent = (old_consumer / ".sdlc/templates/intent.md").read_text()
    assert "Our own line in the intent template." in intent
    build = (old_consumer / ".sdlc/skills/build/SKILL.md").read_text()
    assert "Our own build rule." in build and not build.startswith("---"), (
        "frontmatter is in the stub"
    )
    stub = old_consumer / ".claude/skills/sdlc-build/SKILL.md"
    assert stub.read_text() == (REPO / ".claude/skills/sdlc-build/SKILL.md").read_text()
    assert not (old_consumer / ".claude/skills/build").exists(), "the old skill went"

    # The security policy is the project's: it becomes the override, not a merge.
    policy = (old_consumer / ".sdlc-local/skills/security-policy/SKILL.md").read_text()
    assert "No secrets in Godot scenes." in policy and not policy.startswith("---")
    framework_policy = REPO / ".sdlc/skills/security-policy/SKILL.md"
    assert (old_consumer / ".sdlc/skills/security-policy/SKILL.md").read_text() == (
        framework_policy.read_text()
    )
    assert "your security policy is the project's own" in out
    resolved = run(
        [".sdlc/scripts/resolve.sh", "skills/security-policy/SKILL.md"], cwd=old_consumer
    )
    assert "No secrets in Godot scenes." in resolved.stdout

    files = (old_consumer / ".sdlc/files").read_text().splitlines()
    assert ".sdlc/scripts/agent.sh" in files and ".claude/skills/sdlc-build/SKILL.md" in files
    assert (old_consumer / ".sdlc/version").read_text().split("\n")[1] == git(
        framework_history, "rev-parse", "HEAD"
    ).strip()
    modes = git(old_consumer, "ls-files", "-s", ".sdlc/scripts/agent.sh", ".sdlc/hooks/format.sh")
    assert all(line.startswith("100755") for line in modes.splitlines()), modes

    # The consumer's Makefile is theirs: the sync names the line to change, never edits it.
    assert "these lines of yours still use the old paths" in out
    assert "Makefile:" in out and "tools/sdlc/src" in out
    assert "tools/sdlc/src" in (old_consumer / "Makefile").read_text()
    makefile = old_consumer / "Makefile"
    makefile.write_text(makefile.read_text().replace("tools/sdlc/src", ".sdlc/src"))

    # #20: the upgrade steps of the releases since OLD, and only those, wait for /sdlc.
    pending = (old_consumer / ".sdlc/upgrade-pending.md").read_text()
    releases = re.findall(r"^# (v\S+)$", pending, re.MULTILINE)
    assert releases[:2] == ["v0.11.0", "v0.11.1"] and "v0.10.1" not in releases, releases
    assert "upgrade steps to do, from v0.11.0 v0.11.1" in out
    assert "upgrade steps from v0.11.0, v0.11.1" in make(old_consumer, "validate").stderr
    (old_consumer / ".sdlc/upgrade-pending.md").unlink()
    assert make(old_consumer, "validate").returncode == 0


def test_the_next_sync_after_the_move_has_nothing_to_move(old_consumer, framework_history):
    env = {"SDLC_SOURCE": str(framework_history)}
    assert run(["bash", "scripts/sync-sdlc.sh", "main"], cwd=old_consumer, env=env).returncode == 0
    makefile = old_consumer / "Makefile"
    makefile.write_text(makefile.read_text().replace("tools/sdlc/src", ".sdlc/src"))
    commit(old_consumer, "chore: sync the move")
    again = sync(old_consumer, framework_history, "main")
    assert again.returncode == 0, again.stdout + again.stderr
    assert "already up to date" in again.stdout
    assert "old paths" not in again.stdout


def test_a_projects_override_shapes_new_changes_and_the_sync_flags_it(consumer, framework_snapshot):
    """#133: .sdlc-local/ wins over .sdlc/, the sync never writes it, and when the framework
    changes the file under an override, the sync says so and validate checks it still applies."""
    override = consumer / ".sdlc-local/templates/intent.md"
    override.parent.mkdir(parents=True)
    override.write_text(
        "<!-- extends -->\n<!-- append: header -->\nMilestone: M<n>\n<!-- /append -->\n"
    )
    commit(consumer, "chore: our intent header")
    assert make(consumer, "new-change", "NAME=phone-access").returncode == 0
    intent = (consumer / "changes/0001-phone-access/intent.md").read_text()
    assert intent.index("Product owner: <name>") < intent.index("\nMilestone: M<n>\n")
    assert intent.index("Milestone: M<n>") < intent.index("## Problem") and "block:" not in intent
    shutil.rmtree(consumer / "changes")  # never committed: the sync needs a clean tree

    # The framework renames the block the override aims at.
    template = framework_snapshot / ".sdlc/templates/intent.md"
    template.write_text(template.read_text().replace("block: header", "block: top"))
    commit(framework_snapshot, "feat: rename the header block")
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "your overrides of files this update changed" in result.stdout
    assert ".sdlc-local/templates/intent.md" in result.stdout
    assert "these overrides no longer apply" in result.stdout
    assert override.read_text().startswith("<!-- extends -->"), "the sync never writes it"
    check = make(consumer, "validate")
    assert check.returncode != 0
    assert (
        ".sdlc-local/templates/intent.md: the base file has no block named 'header'" in check.stderr
    )


def test_a_projects_hook_runs_after_the_framework_through_the_settings_it_already_has(
    consumer,
):
    settings_before = (consumer / ".claude/settings.json").read_text()
    local = consumer / ".sdlc-local/hooks"
    local.mkdir(parents=True)
    (local / "hooks.tsv").write_text("PreToolUse\tBash\t.sdlc-local/hooks/no-curl.sh\n")
    (local / "no-curl.sh").write_text(
        '#!/usr/bin/env bash\ngrep -q curl && { echo "no curl" >&2; exit 2; }\nexit 0\n'
    )
    (local / "no-curl.sh").chmod(0o755)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "curl example.com"}})
    env = {"CLAUDE_PROJECT_DIR": str(consumer)}
    blocked = run([".sdlc/hooks/dispatch.sh", "PreToolUse"], cwd=consumer, env=env, input=payload)
    assert blocked.returncode == 2 and "no curl" in blocked.stderr
    assert (consumer / ".claude/settings.json").read_text() == settings_before


# --- upgrades: scripts and upgrade steps per release (#20) ----------------------------------

MIGRATION = 'mkdir -p moved && echo "from=$SDLC_UPGRADE_FROM to=$SDLC_UPGRADE_TO" > moved/note\n'
STEPS = "## Breaking: x\n\nWhat changed.\n\n## Upgrade steps\n\n1. Rename the thing.\n"


def test_a_first_install_has_no_upgrade_to_do(consumer):
    # The snapshot carries every past release's notes, upgrade steps included.
    assert not (consumer / ".sdlc/upgrade-pending.md").exists()
    assert make(consumer, "validate").returncode == 0


def test_an_upgrade_runs_new_releases_scripts_and_lists_their_steps(consumer, framework_snapshot):
    commit(
        framework_snapshot,
        "feat!: rename",
        {
            ".sdlc/migrations/v9.0.0.sh": MIGRATION,
            "docs/release-notes/v9.0.0.md": STEPS,
            "docs/release-notes/v9.1.0.md": "## Optional: y\n\nNo steps here.\n",
        },
    )
    result = sync(consumer, framework_snapshot, "main")
    out = result.stdout + result.stderr
    assert result.returncode == 0, out

    # The script ran from the consumer's root, and what it changed is staged.
    assert (consumer / "moved/note").read_text() == "from=v0.0.1 to=main\n"
    assert "moved/note" in git(consumer, "diff", "--cached", "--name-only")
    assert "ran the upgrade scripts" in out and ".sdlc/migrations/v9.0.0.sh" in out

    # Only the new release with upgrade steps is listed; the older notes were there at the base.
    pending = (consumer / ".sdlc/upgrade-pending.md").read_text()
    assert "# v9.0.0\n" in pending and "1. Rename the thing." in pending
    assert "v9.1.0" not in pending and "# v0.11.0" not in pending
    assert "upgrade steps to do, from v9.0.0" in out

    # A half-done upgrade fails the check until the steps are done and the file is deleted.
    check = make(consumer, "validate")
    assert check.returncode != 0
    assert "upgrade steps from v9.0.0 to do" in check.stderr
    (consumer / ".sdlc/upgrade-pending.md").unlink()
    assert make(consumer, "validate").returncode == 0


def test_an_unfinished_upgrade_keeps_its_steps_when_the_next_sync_adds_more(
    consumer, framework_snapshot
):
    commit(framework_snapshot, "feat!: one", {"docs/release-notes/v9.0.0.md": STEPS})
    assert sync(consumer, framework_snapshot, "main").returncode == 0
    commit(consumer, "chore: sync, steps not done yet")
    commit(framework_snapshot, "feat!: two", {"docs/release-notes/v9.1.0.md": STEPS})
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    pending = (consumer / ".sdlc/upgrade-pending.md").read_text()
    assert pending.count("# v9.0.0\n") == 1 and "# v9.1.0\n" in pending
    assert pending.index("# v9.0.0") < pending.index("# v9.1.0")


def test_a_failed_upgrade_script_stops_the_sync_with_the_rest_staged(consumer, framework_snapshot):
    commit(
        framework_snapshot,
        "feat!: rename",
        {
            ".sdlc/migrations/v9.0.0.sh": "echo 'no override to move' >&2; exit 3\n",
            ".sdlc/REVIEW.md": "new review rules\n",
        },
    )
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 1
    assert "no override to move" in result.stdout
    assert "these upgrade scripts failed" in result.stderr
    assert ".sdlc/migrations/v9.0.0.sh" in result.stderr
    assert ".sdlc/REVIEW.md" in git(consumer, "diff", "--cached", "--name-only")


def test_an_upgrade_from_an_unknown_commit_counts_from_its_release_tag(
    consumer, framework_snapshot
):
    version = consumer / ".sdlc/version"
    repo_line = version.read_text().splitlines()[0]
    commit(consumer, "chore: history rewritten", {".sdlc/version": f"{repo_line}\n{'0' * 40}\n"})
    commit(framework_snapshot, "feat!: rename", {"docs/release-notes/v9.0.0.md": STEPS})
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    pending = (consumer / ".sdlc/upgrade-pending.md").read_text()
    assert "# v9.0.0\n" in pending and "# v0.11.0" not in pending


# --- the sdlc- prefix (#23) -----------------------------------------------------------------

PREFIXED = "v0.11.1"  # the last release before the prefix
RENAMED = {
    ".claude/skills/intent/SKILL.md": ".claude/skills/sdlc-intent/SKILL.md",
    ".claude/skills/po-review/SKILL.md": ".claude/skills/sdlc-po-review/SKILL.md",
    ".claude/agents/verifier.md": ".claude/agents/sdlc-verifier.md",
    ".github/workflows/ci.yml": ".github/workflows/sdlc-ci.yml",
    ".github/workflows/claude-review.yml": ".github/workflows/sdlc-claude-review.yml",
}


@pytest.fixture
def unprefixed_consumer(tmp_path):
    """A consumer on PREFIXED, a framework whose history is PREFIXED then this working tree."""
    fw = init_repo(tmp_path / "framework")
    run(["bash", "-c", f'git archive {PREFIXED} | tar -x -C "$0"', str(fw)], check=True)
    commit(fw, f"release {PREFIXED}")
    git(fw, "tag", PREFIXED)
    git(fw, "rm", "-rq", ".")
    copy_working_tree(fw)
    commit(fw, "the sdlc- prefix")
    repo = init_repo(tmp_path / "consumer")
    files = {
        "Makefile": git(REPO, "show", f"{PREFIXED}:tests/fixtures/consumer/Makefile") + "\n",
        ".sdlc/scripts/sync-sdlc.sh": git(REPO, "show", f"{PREFIXED}:.sdlc/scripts/sync-sdlc.sh")
        + "\n",
    }
    commit(repo, "chore: consumer skeleton", files)
    assert sync(repo, fw, PREFIXED).returncode == 0
    commit(repo, f"chore: sync {PREFIXED}")
    return repo, fw


def test_an_upgrade_renames_the_frameworks_commands_agent_and_workflows(unprefixed_consumer):
    repo, fw = unprefixed_consumer
    ci = repo / ".github/workflows/ci.yml"
    commit(
        repo, "chore: our own CI step", {".github/workflows/ci.yml": ci.read_text() + "# ours\n"}
    )
    result = sync(repo, fw, "main")
    out = result.stdout + result.stderr
    assert result.returncode == 0, out

    for old, new in RENAMED.items():
        assert (repo / new).read_text() == (REPO / new).read_text(), new
        if old != ".github/workflows/ci.yml":
            assert not (repo / old).exists(), old
    # An edited old file is the project's now: kept and listed, for the upgrade step to merge.
    assert ci.exists() and "kept (the framework dropped these" in out
    assert ".github/workflows/ci.yml" in out.split("kept (the framework dropped these", 1)[1]
    # The skill bodies didn't move, so a project's overrides still find them.
    assert (repo / ".sdlc/skills/intent/SKILL.md").exists()
    assert "sdlc-intent" in (repo / ".claude/skills/sdlc-intent/SKILL.md").read_text()

    # The release's upgrade steps wait for /sdlc, and the check holds the PR until they're done.
    pending = (repo / ".sdlc/upgrade-pending.md").read_text()
    assert "# v0.12.0\n" in pending and "carry the edit across" in pending
    assert "upgrade steps from v0.12.0" in make(repo, "validate").stderr
    (repo / ".sdlc/upgrade-pending.md").unlink()
    assert make(repo, "validate").returncode == 0


def test_the_v0_12_0_upgrade_steps_search_finds_the_old_names(unprefixed_consumer):
    """The grep in upgrade step 2 finds old commands and workflow links, not paths."""
    repo, _ = unprefixed_consumer
    notes = (REPO / "docs/release-notes/v0.12.0.md").read_text()
    assert "## Upgrade steps" in notes
    search = re.search(r"```\n\s*(git grep .+)\n", notes).group(1)
    commit(
        repo,
        "docs: ours",
        {
            "CLAUDE.md": "Run /intent, then /build all.\nThe verifier subagent checks it.\n",
            "README.md": "![CI](https://x/actions/workflows/ci.yml/badge.svg)\n",
            "docs/paths.md": "See changes/0001-x/plan.md and src/build/out.js and */intent.md\n",
        },
    )
    hits = run(["bash", "-c", search], cwd=repo).stdout
    assert "CLAUDE.md:1:" in hits and "CLAUDE.md:2:" in hits and "README.md:1:" in hits
    assert "docs/paths.md" not in hits


def test_a_declined_feature_survives_a_sync(consumer, framework_snapshot):
    """#74: the decline lives in the project's .sdlc.toml, which the sync never writes."""
    declined = (
        '[[features.declined]]\nfeature = "architecture decision records (ADRs)"\n'
        'reason = "a short-lived prototype"\nby = "Sam"\ndate = 2026-11-13\n'
    )
    commit(consumer, "chore: not for us", {".sdlc.toml": declined})
    commit(framework_snapshot, "fix: a change", {".sdlc/REVIEW.md": "new rules\n"})
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (consumer / ".sdlc.toml").read_text() == declined
    assert ".sdlc.toml" not in git(consumer, "diff", "--cached", "--name-only")
    assert make(consumer, "validate").returncode == 0


def test_the_plan_gate_guards_the_consumer(consumer):
    """#44: through the synced dispatcher, code waits for a committed plan."""
    code = {"tool_name": "Edit", "tool_input": {"file_path": str(consumer / "src/app.ts")}}
    env = {"CLAUDE_PROJECT_DIR": str(consumer), "SDLC_PLAN_GATE": "", "SDLC_CHANGE": ""}

    def edit(payload=code):
        return run(
            [".sdlc/hooks/dispatch.sh", "PreToolUse"],
            cwd=consumer,
            env=env,
            input=json.dumps(payload),
        )

    on_main = edit()
    assert on_main.returncode == 2 and "code isn't written on main" in on_main.stderr
    spec = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(consumer / "changes/0001-a/spec.md")},
    }
    assert edit(spec).returncode == 0
    commit(consumer, "spec(0001-a): spec", {"changes/0001-a/spec.md": "# spec\n"})
    git(consumer, "switch", "-q", "-c", "build/0001-a")
    waiting = edit()
    assert waiting.returncode == 2 and "/sdlc-plan" in waiting.stderr
    commit(consumer, "plan(0001-a): plan", {"changes/0001-a/plan.md": "# plan\n"})
    assert edit().returncode == 0


def test_ci_holds_the_plan_rule_in_the_consumer(consumer):
    """#44: the synced check fails a change's code PR without its plan, then passes with it."""
    commit(consumer, "spec(0001-a): spec", {"changes/0001-a/spec.md": "# spec\n"})
    check = [".sdlc/scripts/check-plan-first.sh", "build/0001-a"]
    assert run(check, cwd=consumer, input="src/app.ts\n").returncode == 1
    commit(consumer, "plan(0001-a): plan", {"changes/0001-a/plan.md": "# plan\n"})
    assert run(check, cwd=consumer, input="src/app.ts\n").returncode == 0


def test_bug_path_full_turns_the_fast_path_off_in_the_consumer(consumer):
    """#160: the synced plan check honours the consumer's `Bug path: full` line."""
    commit(
        consumer,
        "bug(0002-b): report and spec",
        {"changes/0002-b/bug.md": "# bug\n", "changes/0002-b/spec.md": "# spec\n"},
    )
    check = [".sdlc/scripts/check-plan-first.sh", "build/0002-b"]
    assert run(check, cwd=consumer, input="src/app.ts\n").returncode == 0
    claude = consumer / "CLAUDE.md"
    claude.write_text((claude.read_text() if claude.exists() else "") + "\nBug path: full\n")
    refused = run(check, cwd=consumer, input="src/app.ts\n")
    assert refused.returncode == 1 and "Bug path: full" in refused.stdout


def test_a_fast_path_fix_title_passes_in_the_consumer(consumer):
    """#154: the synced title check accepts fix(<slug>) for a bug, its spec and its fix."""
    files = "changes/0002-b/bug.md\nchanges/0002-b/spec.md\nsrc/app.ts\n"
    check = [".sdlc/scripts/check-pr-title.sh"]
    assert run([*check, "fix(0002-b): stop the crash"], cwd=consumer, input=files).returncode == 0
    refused = run([*check, "feat(0002-b): stop the crash"], cwd=consumer, input=files)
    assert refused.returncode == 1 and "title it 'fix(0002-b): <summary>'" in refused.stdout


def test_the_descope_check_reaches_the_consumer(consumer):
    """#132: the workflow and both scripts sync, and the scripts run there."""
    assert (consumer / ".github/workflows/sdlc-descopes.yml").is_file()
    modes = git(
        consumer,
        "ls-files",
        "-s",
        ".sdlc/scripts/descopes-decided.sh",
        ".sdlc/scripts/descopes-status.sh",
    )
    assert modes.count("100755") == 2, modes
    usage = run([".sdlc/scripts/descopes-decided.sh"], cwd=consumer)
    assert usage.returncode == 2 and "Descope: needs approval" in usage.stderr


def test_check_after_review_reaches_the_consumer(consumer):
    """#163: the workflow and the gate script sync, the script runs there, and CI's `check`
    hands same-repo PRs over only when the consumer sets SDLC_CHECK_AFTER_REVIEW."""
    assert (consumer / ".github/workflows/sdlc-check-after-review.yml").is_file()
    modes = git(consumer, "ls-files", "-s", ".sdlc/scripts/check-gate.sh")
    assert modes.startswith("100755"), modes
    usage = run([".sdlc/scripts/check-gate.sh"], cwd=consumer)
    assert usage.returncode == 2 and "SDLC_CHECK_AFTER_REVIEW" in usage.stderr
    ci = (consumer / ".github/workflows/sdlc-ci.yml").read_text()
    assert "'check (runs after the Claude review)' || 'check'" in ci
