"""Layer 1: the pipeline's shell scripts."""

import json
import os
import re
import shutil

import pytest

from conftest import REPO, commit, git, init_repo, run

SCRIPTS = sorted(
    p.relative_to(REPO) for p in [*REPO.glob("scripts/*.sh"), *REPO.glob(".claude/hooks/*.sh")]
) + [REPO.joinpath("evals/run.sh").relative_to(REPO)]


@pytest.mark.parametrize("script", SCRIPTS, ids=str)
def test_scripts_parse(script):
    assert run(["bash", "-n", str(script)]).returncode == 0


# --- agent adapter ---------------------------------------------------------------------


def test_agent_echo_reads_stdin():
    result = run(["scripts/agent.sh", "-"], env={"AGENT": "echo"}, input="hello agent")
    assert result.returncode == 0
    assert result.stdout.strip() == "hello agent"


def test_agent_echo_reads_prompt_file(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("from a file")
    result = run(["scripts/agent.sh", str(prompt)], env={"AGENT": "echo"})
    assert result.stdout.strip() == "from a file"


def test_agent_rejects_unknown_adapter():
    result = run(["scripts/agent.sh", "-"], env={"AGENT": "nope"}, input="x")
    assert result.returncode == 2
    assert "unknown AGENT" in result.stderr


def test_agent_requires_a_prompt():
    assert run(["scripts/agent.sh"]).returncode != 0


# --- eval runner -----------------------------------------------------------------------


def _tasks(tmp_path, checks):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    for i, check in enumerate(checks):
        task = {"name": f"task {i}", "prompt": "noop", "check": check}
        (tasks / f"t{i}.json").write_text(json.dumps(task))
    return tasks


@pytest.mark.parametrize(
    ("checks", "min_rate", "passes"),
    [
        (["true", "true"], "1.0", True),
        (["true", "false"], "0.5", True),
        (["true", "false"], "0.8", False),
        (["test -f Makefile"], "1.0", True),  # checks run inside a copy of the repo
    ],
)
def test_eval_runner_pass_rate(tmp_path, checks, min_rate, passes):
    env = {
        "AGENT": "echo",
        "EVAL_TASKS_DIR": str(_tasks(tmp_path, checks)),
        "EVAL_MIN_PASS_RATE": min_rate,
    }
    result = run(["evals/run.sh"], env=env)
    assert (result.returncode == 0) is passes, result.stdout


@pytest.mark.parametrize("make_dir", [True, False], ids=["empty", "missing"])
def test_eval_runner_without_tasks_passes_and_says_so(tmp_path, make_dir):
    tasks = tmp_path / "tasks"
    if make_dir:
        tasks.mkdir()
    result = run(["evals/run.sh"], env={"AGENT": "echo", "EVAL_TASKS_DIR": str(tasks)})
    assert result.returncode == 0, result.stderr
    assert "no tasks" in result.stdout


# --- bootstrap -------------------------------------------------------------------------


def test_bootstrap_help_and_bad_args():
    assert run(["scripts/bootstrap-github.sh", "--help"]).returncode == 0
    assert run(["scripts/bootstrap-github.sh", "--bogus"]).returncode == 2


def test_bootstrap_creates_the_review_label_the_workflow_listens_for():
    script = (REPO / "scripts/bootstrap-github.sh").read_text()
    workflow = (REPO / ".github/workflows/claude-review.yml").read_text()
    assert "\nreview|" in script
    assert "github.event.label.name == 'review'" in workflow


def test_review_reruns_on_push_only_while_labelled():
    # Reviews use subscription limits (#11): a push is reviewed only if the PR has the label.
    workflow = (REPO / ".github/workflows/claude-review.yml").read_text()
    assert "types: [opened, ready_for_review, labeled, synchronize]" in workflow
    assert (
        "github.event.action == 'synchronize' && "
        "contains(github.event.pull_request.labels.*.name, 'review')"
    ) in workflow
    assert "cancel-in-progress: true" in workflow


def test_review_label_is_sticky():
    # Clearing the label after each review meant fix pushes went unreviewed when people forgot
    # to re-add it.
    workflow = (REPO / ".github/workflows/claude-review.yml").read_text()
    assert "remove-label" not in workflow
    assert "labels/review" not in workflow


# --- next-version ----------------------------------------------------------------------


def _next_version(repo):
    result = run(["bash", str(REPO / "scripts/next-version.sh"), "--explain"], cwd=repo)
    return result.returncode, result.stdout.strip()


@pytest.fixture
def released(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(repo, "chore: initial")
    git(repo, "tag", "v0.4.2")
    return repo


def test_first_release_is_0_1_0(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(repo, "chore: initial")
    assert _next_version(repo) == (0, "v0.1.0")


def test_nothing_to_release(released):
    assert _next_version(released)[0] == 1


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        (["fix: a bug"], "v0.4.3"),
        (["ci: tweak", "docs: words"], "v0.4.3"),
        (["fix: a", "feat: new skill"], "v0.5.0"),
        (["feat(hooks): scoped"], "v0.5.0"),
        (["feat!: drop make target"], "v0.5.0"),  # breaking while 0.x bumps minor
        (["fix: x\n\nBREAKING CHANGE: renamed"], "v0.5.0"),
        (["Merge pull request #7 from a/b\n\nfeat: via merge commit"], "v0.5.0"),
        (["Merge pull request #8 from a/b\n\nfix: via merge commit"], "v0.4.3"),
    ],
)
def test_bump_from_titles(released, messages, expected):
    for message in messages:
        commit(released, message)
    assert _next_version(released) == (0, expected)


def test_breaking_change_after_1_0_bumps_major(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(repo, "chore: initial")
    git(repo, "tag", "v1.2.3")
    commit(repo, "feat!: new contract")
    assert _next_version(repo) == (0, "v2.0.0")


# --- release notes ---------------------------------------------------------------------


def _notes(repo, version="v0.5.0"):
    result = run(["bash", str(REPO / "scripts/release-notes.sh"), version, "o/r"], cwd=repo)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_release_notes_group_by_type(released):
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
    result = run(["scripts/bootstrap-github.sh", "--mode", mode, "--print-protection"])
    assert result.returncode == 0, result.stderr
    protection = json.loads(result.stdout)
    assert protection["enforce_admins"] is True, "nobody bypasses required checks"
    assert sorted(protection["required_status_checks"]["contexts"]) == ["check", "pr-title"]
    assert protection["required_status_checks"]["strict"] is True, "PRs must be up to date"
    reviews = protection["required_pull_request_reviews"]
    assert reviews["required_approving_review_count"] == approvals
    assert reviews["require_code_owner_reviews"] is code_owners
    assert protection["allow_force_pushes"] is False


def test_bootstrap_defaults_to_solo_and_rejects_unknown_mode():
    default = json.loads(run(["scripts/bootstrap-github.sh", "--print-protection"]).stdout)
    assert default["required_pull_request_reviews"]["required_approving_review_count"] == 0
    assert run(["scripts/bootstrap-github.sh", "--mode", "chaos"]).returncode == 2


# --- agents ----------------------------------------------------------------------------


def test_verifier_runs_on_a_set_model():
    # Without a model the verifier inherits the caller's, so an Opus session runs it on Opus.
    agent = (REPO / ".claude/agents/verifier.md").read_text()
    front = agent.split("---")[1]
    assert "\nmodel: sonnet\n" in front


# --- commit guards: .gitignore baseline --------------------------------------------------------


def test_bootstrap_adds_missing_gitignore_lines_once(tmp_path):
    repo = init_repo(tmp_path / "r")
    (repo / "templates").mkdir()
    shutil.copy(REPO / "templates" / "gitignore", repo / "templates" / "gitignore")
    (repo / ".gitignore").write_text("node_modules/\nmy-own-thing/\n")
    first = run(["bash", str(REPO / "scripts/bootstrap-github.sh"), "--gitignore-only"], cwd=repo)
    assert first.returncode == 0, first.stderr
    text = (repo / ".gitignore").read_text()
    assert text.startswith("node_modules/\nmy-own-thing/\n")
    assert text.count("node_modules/") == 1
    for line in [".venv/", "__pycache__/", ".env", "!.env.example", "dist/"]:
        assert f"\n{line}\n" in text
    second = run(["bash", str(REPO / "scripts/bootstrap-github.sh"), "--gitignore-only"], cwd=repo)
    assert second.returncode == 0
    assert (repo / ".gitignore").read_text() == text
    assert "has every baseline line" in second.stdout


def test_bootstrap_turns_on_branch_deletion_idempotently():
    script = (REPO / "scripts/bootstrap-github.sh").read_text()
    assert '-q .delete_branch_on_merge)" == true ]]' in script
    assert "-F delete_branch_on_merge=true" in script
    # The protection comparison includes `strict`, so an existing rule without it is updated.
    assert "strict: .required_status_checks.strict" in script


def test_bootstrap_help_lists_every_step():
    help_text = run(["scripts/bootstrap-github.sh", "--help"]).stdout
    for n in range(1, 11):
        assert f"{n:>2}. " in help_text or f"#   {n}. " in help_text, n
    assert "set -euo" not in help_text


# --- review skills -----------------------------------------------------------------------

REVIEW_SKILLS = [".claude/skills/po-review/SKILL.md", ".claude/skills/review-findings/SKILL.md"]


@pytest.mark.parametrize("path", REVIEW_SKILLS)
def test_review_skills_sign_replies_and_avoid_graphql_pr_commands(path):
    # Replies go out under the person's account; `gh pr edit`/`gh pr view` can fail in orgs
    # hit by the Projects (classic) GraphQL deprecation.
    skill = (REPO / path).read_text()
    assert "(posted from Claude Code)" in skill
    commands = re.findall(r"^\s*(gh pr \w+|git add -A|git add \.)", skill, re.MULTILINE)
    commands += re.findall(r"`(gh pr (?:edit|view|checkout) [^`]*)`", skill)
    assert commands == []


def test_review_findings_resolves_threads_and_checks_for_bot_commits():
    skill = (REPO / ".claude/skills/review-findings/SKILL.md").read_text()
    assert "resolveReviewThread" in skill
    assert "If GraphQL fails" in skill
    assert "HEAD..origin/<branch>" in skill


def test_pr_title_accepts_bug_artifact_prs():
    workflow = (REPO / ".github/workflows/pr-title.yml").read_text()
    assert "|intent|bug|spec|plan'" in workflow


# --- spec-pr: one spec PR per change --------------------------------------------------------

FAKE_GH = """#!/usr/bin/env bash
# Records each call; answers from $FAKE_GH_DIR/<name> files keyed by what the call asks for.
echo "$*" >> "$FAKE_GH_DIR/calls"
case "$*" in
  *"head=$OWNER:spec/"*)
    all="$*"; branch="${all#*head=$OWNER:}"; branch="${branch%% *}"
    f="$FAKE_GH_DIR/open-${branch//\//_}"; [[ -f "$f" ]] && cat "$f"
    [[ -f "$FAKE_GH_DIR/fail" ]] && exit 1 ;;
  *"pulls?state=open&per_page"*) cat "$FAKE_GH_DIR/legacy" 2>/dev/null || true ;;
  *"/files"*) cat "$FAKE_GH_DIR/legacy-files" 2>/dev/null || true ;;
  *"repos/o/r/pulls -f title"*) echo 42 ;;
esac
exit 0
"""


@pytest.fixture
def spec_repo(tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    repo = init_repo(tmp_path / "work")
    commit(
        repo,
        "chore: changes",
        {
            "changes/0001-a/intent.md": "# a\n",
            "changes/0002-b/bug.md": "# b\n",
            "changes/0003-c/intent.md": "# c\n",
            "changes/0003-c/spec.md": "# c spec\n",
        },
    )
    git(repo, "remote", "add", "origin", str(remote))
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH)
    (fake / "gh").chmod(0o755)
    state = tmp_path / "gh"
    state.mkdir()
    env = {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "FAKE_GH_DIR": str(state),
        "OWNER": "o",
        "GITHUB_REPOSITORY": "o/r",
    }
    return repo, remote, state, env


def spec_pr(repo, env, *args):
    return run(["bash", str(REPO / "scripts/spec-pr.sh"), *args], cwd=repo, env=env)


def test_spec_pr_pending_skips_changes_with_an_open_spec_pr(spec_repo):
    repo, _, state, env = spec_repo
    (state / "open-spec_0001-a").write_text("18\n")
    result = spec_pr(repo, env, "pending")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["changes/0002-b"]
    assert "spec PR #18 is already open" in result.stderr


def test_spec_pr_pending_fails_when_github_errors(spec_repo):
    # Treating an API error as "no open PR" would open a duplicate.
    repo, _, state, env = spec_repo
    (state / "fail").write_text("")
    assert spec_pr(repo, env, "pending").returncode != 0


def test_spec_pr_open_pushes_one_branch_per_change_named_after_it(spec_repo):
    repo, remote, state, env = spec_repo
    (repo / "changes/0001-a/spec.md").write_text("# a spec\n")
    (repo / "changes/0002-b/spec.md").write_text("# b spec\n")
    (repo / "stray.txt").write_text("agent leftovers\n")
    result = spec_pr(repo, env, "open", "changes/0001-a", "changes/0002-b")
    assert result.returncode == 0, result.stderr
    for slug, kind in [("0001-a", "intent"), ("0002-b", "bug")]:
        files = git(remote, "show", "--name-only", "--format=%s", f"spec/{slug}").splitlines()
        assert files[0] == f"spec({slug}): generate from accepted {kind}"
        assert [f for f in files[1:] if f] == [f"changes/{slug}/spec.md"]
    calls = (state / "calls").read_text()
    assert "title=spec(0001-a): generate from accepted intent" in calls
    assert "title=spec(0002-b): generate from accepted bug" in calls


def test_spec_pr_open_closes_an_older_run_numbered_pr_it_supersedes(spec_repo):
    repo, _, state, env = spec_repo
    (repo / "changes/0001-a/spec.md").write_text("# a spec\n")
    (state / "legacy").write_text("19\n")
    (state / "legacy-files").write_text("changes/0001-a/spec.md\n")
    result = spec_pr(repo, env, "open", "changes/0001-a")
    assert result.returncode == 0, result.stderr
    calls = (state / "calls").read_text()
    assert "repos/o/r/issues/19/comments" in calls
    assert "-X PATCH repos/o/r/pulls/19 --silent -f state=closed" in calls
    assert "closed #19 (superseded by #42)" in result.stdout


def test_spec_from_intent_queues_runs_and_uses_spec_pr():
    workflow = (REPO / ".github/workflows/spec-from-intent.yml").read_text()
    assert "group: spec-from-intent" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "scripts/spec-pr.sh pending" in workflow
    assert "GITHUB_RUN_ID" not in workflow
