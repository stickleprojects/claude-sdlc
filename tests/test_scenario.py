"""Layer 2: the framework installed into a fresh consumer repo, end to end, without Claude.

The consumer starts with only its own Makefile (a no-op stack) and the sync script, then
pulls the framework from a snapshot of this working tree, as `make sync-sdlc` would.
"""

import json
import os
import re
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


def artifact(sections):
    """Each section with a stand-in body; Requirements gets a requirement validate can read."""
    return "".join(f"## {s}\n\n{'- R1. x' if s == 'Requirements' else 'x'}\n\n" for s in sections)


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
        ".claude/skills/sdlc/SKILL.md",
        ".claude/skills/routing.md",
        "templates/build.md",
        "templates/adr.md",
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


def test_sync_copies_the_frameworks_executable_bit(consumer, framework_snapshot):
    # #79: the framework's mode decides, not the extension.
    assert git(consumer, "ls-files", "-s", "scripts/create-agent-apps.py").startswith("100755")
    assert git(consumer, "ls-files", "-s", "REVIEW.md").startswith("100644")
    # A consumer's own script isn't touched, whatever its name.
    commit(consumer, "chore: own script", {"scripts/ours.sh": "echo ours\n"})
    git(consumer, "update-index", "--chmod=-x", "scripts/ours.sh")
    commit(consumer, "chore: not executable")
    # Like NTFS: git can't see modes on disk, so only the sync can set the bit.
    git(consumer, "config", "core.fileMode", "false")
    hook_py = framework_snapshot / ".claude/hooks/new-hook.py"
    hook_py.write_text("print('hi')\n")
    hook_py.chmod(0o755)
    commit(framework_snapshot, "feat: python hook")
    result = sync(consumer, framework_snapshot, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(consumer, "ls-files", "-s", ".claude/hooks/new-hook.py").startswith("100755")
    assert git(consumer, "ls-files", "-s", "scripts/ours.sh").startswith("100644")


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
        (change / name).write_text("# T\n\n" + artifact(sections))
    plan = change / "plan.md"
    text = plan.read_text().replace("## Descopes\n\nx", "## Descopes\n\nNone.")
    plan.write_text(
        text.replace("## Verification\n\n", "## Verification\n\n- **Definition of done:** UI\n\n")
    )
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


def test_plan_descopes_in_consumer(consumer):
    """A new plan copied from the template fails until its Descopes is filled, and an entry
    needs a person's approval (#95)."""
    assert make(consumer, "new-change", "NAME=dock").returncode == 0
    change = consumer / "changes" / "0001-dock"
    for name in ("intent.md", "spec.md"):
        (change / name).write_text("# T\n\n" + artifact(CHAIN[name]))
    template = (consumer / "templates" / "plan.md").read_text()
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
    assert (consumer / "templates" / "definition-of-done.md").exists()
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
    template = (consumer / "templates" / "adr.md").read_text()
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
    assert (consumer / "tools/sdlc/src/sdlc/placeholders.toml").exists()
    adrs = consumer / "docs" / "adr"
    adrs.mkdir(parents=True)
    template = (consumer / "templates" / "adr.md").read_text()
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
  *) exit 1 ;;
esac
"""


def sync_with_gh(consumer, framework_snapshot, tmp_path, secrets="", variables="", **env):
    fake = tmp_path / "fakebin"
    fake.mkdir(exist_ok=True)
    (fake / "gh").write_text(FAKE_GH)
    (fake / "gh").chmod(0o755)
    git(consumer, "remote", "add", "origin", "git@github.com:o/r.git")
    commit(framework_snapshot, "fix: change", {"REVIEW.md": "changed\n"})
    return run(
        ["bash", "scripts/sync-sdlc.sh", "main"],
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
    script = (REPO / "scripts" / "sync-sdlc.sh").read_text()
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


# --- opt-in auto-merge (#89) ----------------------------------------------------------------

ALL_SET = {"secrets": "CLAUDE_CODE_OAUTH_TOKEN SDLC_AGENT_APP_KEY"}
APP_VARS = "SDLC_AGENT_APP_ID SDLC_AGENT_APP_SLUG"


def _protection(dismiss):
    return json.dumps(
        {
            "required_status_checks": {"contexts": ["check", "pr-title", "review"]},
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
    staged = git(consumer, "ls-files", "-s", "scripts/auto-merge.sh")
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
    spec = (consumer / "templates" / "spec.md").read_text()
    (folder / "spec.md").write_text(spec.replace("- AC1 (R1): ", "1. "))
    broken = make(consumer, "validate")
    assert broken.returncode != 0
    assert "numbered list" in broken.stderr
    (folder / "spec.md").write_text(spec)
    assert make(consumer, "validate").returncode == 0
    assert (consumer / ".claude" / "skills" / "scope.md").exists()


def test_clause_check_in_consumer(consumer, framework_snapshot):
    """The clause check (#47) arrives with the sync and splits a consumer's spec, and a
    consumer without the `clauses` target is told it's optional."""
    script = consumer / "scripts" / "clause-check.sh"
    assert os.access(script, os.X_OK)
    assert (consumer / "prompts" / "clause-check.md").exists()
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

    shutil.rmtree(folder)
    makefile = (consumer / "Makefile").read_text().replace("clauses", "noclauses")
    commit(consumer, "chore: drop clauses target", {"Makefile": makefile})
    commit(framework_snapshot, "fix: change", {"REVIEW.md": "changed\n"})
    assert "make clauses  (optional" in sync(consumer, framework_snapshot, "main").stdout


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
        ["scripts/clause-check.sh", "--changed-since", "main"],
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
    assert (consumer / "prompts" / "delivery-check.md").exists()
    fixture = REPO / "evals" / "fixtures" / "delivery-gap" / "0001-floor-mode"
    shutil.copytree(fixture, consumer / "changes" / "0001-floor-mode")
    out = make(consumer, "clauses", "CHANGE=0001")
    assert out.returncode == 0, out.stderr
    [r1, _] = json.loads(out.stdout)["requirements"]
    assert "- **Goal:** Show a whole floor as the game places it" in [
        b["text"] for b in r1["build"]
    ]
    dry = run(
        ["scripts/clause-check.sh", "--stage", "build", "0001"],
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
        ["scripts/clause-check.sh", "--stage", "build", "0001"],
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
    """#105: the review skills call scripts/request-review.sh, so the sync installs it runnable."""
    script = consumer / "scripts" / "request-review.sh"
    assert os.access(script, os.X_OK)
    assert "scripts/request-review.sh" in (consumer / ".sdlc-files").read_text()
    skill = (consumer / ".claude" / "skills" / "review-findings" / "SKILL.md").read_text()
    assert "scripts/request-review.sh <N>" in skill


@pytest.mark.parametrize("value", ["off", "OFF", ""])
def test_sync_says_nothing_about_auto_merge_when_it_is_off(
    consumer, framework_snapshot, tmp_path, value
):
    # #101 finding 7: `off` is off (THE RULE in scripts/auto-merge.sh), so no warnings.
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
