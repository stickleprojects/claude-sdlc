"""Layer 1: the pipeline's shell scripts."""

import json
import os
import re
import shutil

import pytest

from conftest import REPO, commit, git, init_repo, run


def synced(path: str) -> bool:
    """The sync installs everything under .sdlc/ (#133), so a file there reaches consumers."""
    sync = (REPO / ".sdlc/scripts/sync-sdlc.sh").read_text()
    return '".sdlc:.sdlc"' in sync and path.startswith(".sdlc/") and (REPO / path).is_file()


SCRIPTS = sorted(
    p.relative_to(REPO)
    for p in [
        *REPO.glob("scripts/*.sh"),
        *REPO.glob(".sdlc/scripts/*.sh"),
        *REPO.glob(".sdlc/hooks/*.sh"),
    ]
) + [REPO.joinpath(".sdlc/evals/run.sh").relative_to(REPO)]


@pytest.mark.parametrize("script", SCRIPTS, ids=str)
def test_scripts_parse(script):
    assert run(["bash", "-n", str(script)]).returncode == 0


# --- agent adapter ---------------------------------------------------------------------


def test_agent_echo_reads_stdin():
    result = run([".sdlc/scripts/agent.sh", "-"], env={"AGENT": "echo"}, input="hello agent")
    assert result.returncode == 0
    assert result.stdout.strip() == "hello agent"


def test_agent_echo_reads_prompt_file(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("from a file")
    result = run([".sdlc/scripts/agent.sh", str(prompt)], env={"AGENT": "echo"})
    assert result.stdout.strip() == "from a file"


def test_agent_rejects_unknown_adapter():
    result = run([".sdlc/scripts/agent.sh", "-"], env={"AGENT": "nope"}, input="x")
    assert result.returncode == 2
    assert "unknown AGENT" in result.stderr


def test_agent_requires_a_prompt():
    assert run([".sdlc/scripts/agent.sh"]).returncode != 0


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
    result = run([".sdlc/evals/run.sh"], env=env)
    assert (result.returncode == 0) is passes, result.stdout


@pytest.mark.parametrize("make_dir", [True, False], ids=["empty", "missing"])
def test_eval_runner_without_tasks_passes_and_says_so(tmp_path, make_dir):
    tasks = tmp_path / "tasks"
    if make_dir:
        tasks.mkdir()
    result = run([".sdlc/evals/run.sh"], env={"AGENT": "echo", "EVAL_TASKS_DIR": str(tasks)})
    assert result.returncode == 0, result.stderr
    assert "no tasks" in result.stdout


# --- bootstrap -------------------------------------------------------------------------


def test_bootstrap_help_and_bad_args():
    assert run([".sdlc/scripts/bootstrap-github.sh", "--help"]).returncode == 0
    assert run([".sdlc/scripts/bootstrap-github.sh", "--bogus"]).returncode == 2


def test_bootstrap_creates_the_review_label_the_workflow_listens_for():
    script = (REPO / ".sdlc/scripts/bootstrap-github.sh").read_text()
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    assert "\nreview|" in script
    assert "github.event.label.name == 'review'" in workflow


def test_review_runs_on_every_push_only_with_auto_merge():
    # Each review uses subscription limits (#11). With auto-merge on, `review` is a required
    # check, and required checks belong to the head commit, so then every push needs one (#89).
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    assert "types: [opened, ready_for_review, labeled, synchronize]" in workflow
    assert "(github.event.action != 'synchronize' ||" in workflow
    assert "(vars.SDLC_AUTO_MERGE != '' && vars.SDLC_AUTO_MERGE != 'off'))" in workflow


def test_review_runs_once_per_pr_at_a_time():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    job = workflow.split("\njobs:", 1)[1]
    assert "group: claude-review-${{ github.event.pull_request.number }}" in job
    assert "cancel-in-progress: true" in job
    assert "\nconcurrency:" not in workflow, "workflow-level: any label would cancel a review"


def test_review_clears_its_label_through_the_rest_api():
    # `gh pr edit` fails in orgs hit by the Projects (classic) GraphQL deprecation.
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    assert "gh pr edit" not in workflow
    assert 'gh api -X DELETE "repos/$GITHUB_REPOSITORY/issues/$PR/labels/review"' in workflow


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


# --- agents ----------------------------------------------------------------------------


def test_verifier_runs_on_a_set_model():
    # Without a model the verifier inherits the caller's, so an Opus session runs it on Opus.
    agent = (REPO / ".claude/agents/sdlc-verifier.md").read_text()  # the stub holds the frontmatter
    front = agent.split("---")[1]
    assert "\nmodel: sonnet\n" in front


# --- commit guards: .gitignore baseline --------------------------------------------------------


def test_bootstrap_adds_missing_gitignore_lines_once(tmp_path):
    repo = init_repo(tmp_path / "r")
    (repo / ".sdlc" / "templates").mkdir(parents=True)
    shutil.copy(
        REPO / ".sdlc" / "templates" / "gitignore", repo / ".sdlc" / "templates" / "gitignore"
    )
    (repo / ".gitignore").write_text("node_modules/\nmy-own-thing/\n")
    first = run(
        ["bash", str(REPO / ".sdlc/scripts/bootstrap-github.sh"), "--gitignore-only"], cwd=repo
    )
    assert first.returncode == 0, first.stderr
    text = (repo / ".gitignore").read_text()
    assert text.startswith("node_modules/\nmy-own-thing/\n")
    assert text.count("node_modules/") == 1
    for line in [".venv/", "__pycache__/", ".env", "!.env.example", "dist/"]:
        assert f"\n{line}\n" in text
    second = run(
        ["bash", str(REPO / ".sdlc/scripts/bootstrap-github.sh"), "--gitignore-only"], cwd=repo
    )
    assert second.returncode == 0
    assert (repo / ".gitignore").read_text() == text
    assert "has every baseline line" in second.stdout


def test_bootstrap_turns_on_branch_deletion_idempotently():
    script = (REPO / ".sdlc/scripts/bootstrap-github.sh").read_text()
    assert '-q .delete_branch_on_merge)" == true ]]' in script
    assert "-F delete_branch_on_merge=true" in script
    # The protection comparison includes `strict`, so an existing rule without it is updated.
    assert "strict: .required_status_checks.strict" in script


def test_bootstrap_can_refresh_the_app_key_secret():
    script = (REPO / ".sdlc/scripts/bootstrap-github.sh").read_text()
    assert "--update-agent-key) update_agent_key=1" in script
    assert "((update_agent_key == 0)) && gh secret list" in script


def test_bootstrap_help_lists_every_step():
    help_text = run([".sdlc/scripts/bootstrap-github.sh", "--help"]).stdout
    for n in range(1, 12):
        assert f"{n:>2}. " in help_text or f"#   {n}. " in help_text, n
    assert "set -euo" not in help_text


# --- review skills -----------------------------------------------------------------------

REVIEW_SKILLS = [".sdlc/skills/po-review/SKILL.md", ".sdlc/skills/review-findings/SKILL.md"]


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
    skill = (REPO / ".sdlc/skills/review-findings/SKILL.md").read_text()
    assert "resolveReviewThread" in skill
    assert "If GraphQL fails" in skill
    assert "HEAD..origin/<branch>" in skill


def test_pr_title_accepts_bug_artifact_prs():
    script = (REPO / ".sdlc/scripts/check-pr-title.sh").read_text()
    assert "|intent|bug|spec|plan'" in script
    workflow = (REPO / ".github/workflows/sdlc-pr-title.yml").read_text()
    assert '.sdlc/scripts/check-pr-title.sh "$TITLE"' in workflow and "pulls/$PR/files" in workflow


# --- spec-pr: one spec PR per change --------------------------------------------------------

FAKE_GH = r"""#!/usr/bin/env bash
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
    return run(["bash", str(REPO / ".sdlc/scripts/spec-pr.sh"), *args], cwd=repo, env=env)


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
    workflow = (REPO / ".github/workflows/sdlc-spec-from-intent.yml").read_text()
    assert "group: spec-from-intent" in workflow
    assert "cancel-in-progress: false" in workflow
    assert ".sdlc/scripts/spec-pr.sh pending" in workflow
    assert "GITHUB_RUN_ID" not in workflow


# --- auto-merge: opt-in, only where a person's approval is still required (#89) -------------

FAKE_GH_AUTO_MERGE = r"""#!/usr/bin/env bash
# Answers from $D/<name> files; records each call. Applies --jq like gh does.
echo "$*" >> "$D/calls"
args=("$@") jqf=""
for ((i = 0; i < ${#args[@]}; i++)); do [[ "${args[i]}" == --jq ]] && jqf="${args[i+1]}"; done
out() { if [[ -n "$jqf" ]]; then jq -r "$jqf"; else cat; fi; }
# Like gh api: a failed call prints the response body on stdout and the status on stderr.
fail() { printf '{"message":"%s","status":"%s"}' "$2" "$1"; echo "gh: $2 (HTTP $1)" >&2; exit 1; }
case "$1 $2" in
  "api repos/o/r/actions/variables/"*)
    [[ -f "$D/vars-forbidden" ]] && fail 403 "Resource not accessible by integration"
    f="$D/var-${2##*/}"; [[ -f "$f" ]] && { out < "$f"; exit 0; }
    fail 404 "Not Found" ;;
  "api repos/o/r/actions/organization-variables")
    [[ -f "$D/personal-account" ]] && fail 422 "Validation Failed"
    out < "$D/org-vars.json" ;;
  "api graphql")
    if [[ "$*" == *mutation* ]]; then
      [[ -f "$D/mutation-fails" ]] && { echo "Pull request is in clean status" >&2; exit 1; }
      exit 0
    fi
    out < "$D/pr.json" ;;
  "api repos/o/r") out < "$D/repo.json" ;;
  "api repos/o/r/branches/main") out < "$D/branch.json" ;;
  "api repos/o/r/branches/main/protection")
    [[ -f "$D/no-classic-protection" ]] && fail 404 "Branch not protected"
    [[ -f "$D/protection.json" ]] || { echo "Not accessible (HTTP 403)" >&2; exit 1; }
    out < "$D/protection.json" ;;
  "api repos/o/r/rules/branches/main") cat "$D/rules.json" 2>/dev/null || echo '[]' ;;
  "api repos/o/r/pulls/7/files")
    [[ -f "$D/pr-files.json" ]] || echo '[]' > "$D/pr-files.json"; out < "$D/pr-files.json" ;;
  *) exit 1 ;;
esac
"""
MUTATION = "enablePullRequest" + "AutoMerge"


def _pr(decision):
    pr = {"id": "PR_kw1", "reviewDecision": decision, "baseRefName": "main"}
    return json.dumps({"data": {"repository": {"pullRequest": pr}}})


@pytest.fixture
def auto_merge(tmp_path):
    """A repo that qualifies: team-mode protection with the review check required."""
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_AUTO_MERGE)
    (fake / "gh").chmod(0o755)
    state = tmp_path / "gh"
    state.mkdir()
    files = {
        "repo.json": {"allow_auto_merge": True, "allow_merge_commit": True},
        "branch.json": {
            "protection": {"required_status_checks": {"contexts": ["check", "claude-review"]}}
        },
        "protection.json": {
            "required_pull_request_reviews": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews": True,
            }
        },
    }
    for name, data in files.items():
        (state / name).write_text(json.dumps(data))
    (state / "pr.json").write_text(_pr("REVIEW_REQUIRED"))
    (state / "org-vars.json").write_text(json.dumps({"variables": []}))
    env = {"PATH": f"{fake}:{os.environ['PATH']}", "D": str(state), "GITHUB_REPOSITORY": "o/r"}

    def go(**extra):
        result = run(["bash", str(REPO / ".sdlc/scripts/auto-merge.sh"), "7"], env={**env, **extra})
        calls = (state / "calls").read_text() if (state / "calls").exists() else ""
        return result, MUTATION in calls, calls

    return state, go


def test_auto_merge_is_off_unless_the_repo_opts_in(auto_merge):
    _, go = auto_merge
    result, mutated, calls = go()
    assert result.returncode == 0 and not mutated
    assert result.stdout == result.stderr == ""
    assert "actions/variables/SDLC_AUTO_MERGE" in calls  # a session reads the repo variable
    result, mutated, _ = go(SDLC_AUTO_MERGE="")  # CI passes an unset variable as empty
    assert result.returncode == 0 and not mutated


def test_auto_merge_enables_with_the_chosen_method(auto_merge):
    _, go = auto_merge
    result, mutated, calls = go(SDLC_AUTO_MERGE="merge")
    assert result.returncode == 0, result.stderr
    assert mutated and "method=MERGE" in calls
    assert "auto-merge enabled for #7 (merge)" in result.stdout


def test_auto_merge_reads_the_repo_variable_in_a_session(auto_merge):
    state, go = auto_merge
    (state / "var-SDLC_AUTO_MERGE").write_text(json.dumps({"value": "squash"}))
    (state / "repo.json").write_text(json.dumps({"allow_auto_merge": True}))
    _, mutated, calls = go()
    assert mutated and "method=SQUASH" in calls


def test_auto_merge_reads_an_organization_variable(auto_merge):
    state, go = auto_merge
    org = {"variables": [{"name": "SDLC_AUTO_MERGE", "value": "merge"}]}
    (state / "org-vars.json").write_text(json.dumps(org))
    _, mutated, _ = go()
    assert mutated


def test_auto_merge_warns_when_it_cant_read_the_variable(auto_merge):
    # spellbound3d: an App without Variables: read gets 403, which isn't "not opted in".
    state, go = auto_merge
    (state / "vars-forbidden").write_text("")
    result, mutated, _ = go()
    assert result.returncode == 0 and not mutated
    assert "can't read the repo variable SDLC_AUTO_MERGE" in result.stderr
    assert "Variables: read" in result.stderr


def test_auto_merge_is_silent_on_a_personal_accounts_repo(auto_merge):
    # spellbound3d: the repo lookup's 404 body and the org lookup's 422 body came back as the
    # variable's value ("SDLC_AUTO_MERGE is '{"message":...}'"), instead of "not opted in".
    state, go = auto_merge
    (state / "personal-account").write_text("")
    result, mutated, calls = go()
    assert result.returncode == 0 and not mutated
    assert result.stdout == result.stderr == ""
    assert "organization-variables" in calls


def test_auto_merge_prints_a_setting_for_bootstrap(auto_merge):
    state, _ = auto_merge
    env = {"PATH": f"{state.parent / 'fakebin'}:{os.environ['PATH']}", "D": str(state)}
    env["GITHUB_REPOSITORY"] = "o/r"

    def setting(name="SDLC_AUTO_MERGE"):
        return run(["bash", str(REPO / ".sdlc/scripts/auto-merge.sh"), "--setting", name], env=env)

    (state / "personal-account").write_text("")
    unset = setting()
    assert (unset.returncode, unset.stdout) == (0, "")
    (state / "var-SDLC_AUTO_MERGE_CONFIRMED").write_text(json.dumps({"value": "true"}))
    assert setting("SDLC_AUTO_MERGE_CONFIRMED").stdout == "true"
    (state / "vars-forbidden").write_text("")
    forbidden = setting()
    assert forbidden.returncode == 1 and forbidden.stdout == ""
    assert (
        run(["bash", str(REPO / ".sdlc/scripts/auto-merge.sh"), "--setting", "a;b"]).returncode == 2
    )


def test_bootstrap_reads_the_variables_like_auto_merge_does():
    # spellbound3d: `gh variable get` doesn't exist before gh 2.48 (Ubuntu ships 2.46), and its
    # error was thrown away, so bootstrap skipped auto-merge without a word.
    script = (REPO / ".sdlc/scripts/bootstrap-github.sh").read_text()
    assert "gh variable get" not in script.replace("Not `gh variable get`", "")
    assert 'bash "$auto_merge_sh" --setting' in script
    assert 'bash "$auto_merge_sh" --method' in script
    assert "can't read the SDLC_AUTO_MERGE variable" in script
    assert synced(".sdlc/scripts/auto-merge.sh")


def _write(name, data):
    return lambda state: (state / name).write_text(json.dumps(data))


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        (lambda s: (s / "pr.json").write_text(_pr(None)), "solo mode"),
        (_write("branch.json", {"protection": {}}), "claude-review status isn't required"),
        (
            _write(
                "protection.json",
                {"required_pull_request_reviews": {"dismiss_stale_reviews": False}},
            ),
            "doesn't dismiss stale approvals",
        ),
        (lambda s: (s / "protection.json").unlink(), "can't read main's protection"),
        (_write("repo.json", {"allow_auto_merge": False}), "doesn't allow auto-merge"),
        (_write("repo.json", {"allow_merge_commit": False}), "doesn't allow 'merge' merges"),
    ],
    ids=["no-approval", "no-review-check", "stale-kept", "protection-403", "repo-off", "method"],
)
def test_auto_merge_skips_and_warns_unless_an_approval_gates_the_merge(auto_merge, setup, reason):
    state, go = auto_merge
    setup(state)
    result, mutated, _ = go(SDLC_AUTO_MERGE="merge")
    assert result.returncode == 0, "a skip never fails the caller"
    assert not mutated
    assert "auto-merge not enabled for #7" in result.stderr and reason in result.stderr


def test_auto_merge_rejects_an_unknown_method(auto_merge):
    _, go = auto_merge
    result, mutated, _ = go(SDLC_AUTO_MERGE="yes")
    assert result.returncode == 0 and not mutated
    assert "use merge, squash or rebase" in result.stderr


def test_auto_merge_with_unreadable_protection_relies_on_bootstraps_confirmation(auto_merge):
    # An App token without Administration: read gets 403 on the protection (spellbound3d).
    state, go = auto_merge
    (state / "protection.json").unlink()
    _, mutated, _ = go(SDLC_AUTO_MERGE="merge", SDLC_AUTO_MERGE_CONFIRMED="true")
    assert mutated


def test_auto_merge_reads_rulesets_too(auto_merge):
    state, go = auto_merge
    (state / "protection.json").unlink()
    (state / "branch.json").write_text("{}")
    checks = {"required_status_checks": [{"context": "claude-review"}]}
    rules = [
        {"type": "required_status_checks", "parameters": checks},
        {"type": "pull_request", "parameters": {"dismiss_stale_reviews_on_push": True}},
    ]
    (state / "rules.json").write_text(json.dumps(rules))
    _, mutated, _ = go(SDLC_AUTO_MERGE="merge")
    assert mutated


def test_auto_merge_only_warns_when_github_refuses(auto_merge):
    state, go = auto_merge
    (state / "mutation-fails").write_text("")
    result, _, calls = go(SDLC_AUTO_MERGE="merge")
    assert result.returncode == 0
    assert "GitHub refused: Pull request is in clean status" in result.stderr
    assert "/merge" not in calls, "never falls back to merging directly"


def test_spec_pr_open_offers_each_new_pr_to_auto_merge(spec_repo):
    repo, _, state, env = spec_repo
    (repo / "changes/0001-a/spec.md").write_text("# a spec\n")
    result = spec_pr(repo, env, "open", "changes/0001-a")
    assert result.returncode == 0, result.stderr
    calls = (state / "calls").read_text()
    assert "repos/o/r/actions/variables/SDLC_AUTO_MERGE" in calls
    workflow = (REPO / ".github/workflows/sdlc-spec-from-intent.yml").read_text()
    assert "SDLC_AUTO_MERGE: ${{ vars.SDLC_AUTO_MERGE }}" in workflow


def test_bootstrap_requires_the_review_status_in_every_mode():
    def contexts(*args):
        result = run([".sdlc/scripts/bootstrap-github.sh", *args, "--print-protection"])
        assert result.returncode == 0, result.stderr
        return sorted(json.loads(result.stdout)["required_status_checks"]["contexts"])

    assert contexts("--mode", "team", "--auto-merge", "merge") == [
        "check",
        "claude-review",
        "pr-title",
    ]
    # #46: every push after a review needs a new one, whatever the mode or auto-merge.
    every = ["check", "claude-review", "pr-title"]
    assert contexts("--mode", "team", "--auto-merge", "off") == every
    assert contexts("--mode", "solo", "--auto-merge", "merge") == every


def test_bootstrap_requires_resolved_conversations_and_compares_every_setting():
    # #92 and #91: a setting bootstrap applies but doesn't compare drifts unnoticed.
    for mode in ("solo", "team"):
        result = run([".sdlc/scripts/bootstrap-github.sh", "--mode", mode, "--print-protection"])
        protection = json.loads(result.stdout)
        assert protection["required_conversation_resolution"] is True
    script = (REPO / ".sdlc/scripts/bootstrap-github.sh").read_text()
    shape = script.split("shape='", 1)[1].split("'", 1)[0]
    for field in (
        "dismiss_stale_reviews",
        "required_conversation_resolution",
        "require_code_owner",
    ):
        assert field in shape, field


def test_bootstrap_keeps_protection_added_by_hand():
    have = {
        "required_status_checks": {"contexts": ["check", "review", "e2e"]},
        "required_linear_history": {"enabled": True},
        "required_pull_request_reviews": {"require_last_push_approval": True},
    }
    result = run(
        [".sdlc/scripts/bootstrap-github.sh", "--print-protection"],
        env={"SDLC_HAVE_PROTECTION": json.dumps(have)},
    )
    protection = json.loads(result.stdout)
    contexts = sorted(protection["required_status_checks"]["contexts"])
    # A hand-added `e2e` is kept; `review` only while auto-merge is on (#101 finding 2).
    assert contexts == ["check", "claude-review", "e2e", "pr-title"]
    assert protection["required_linear_history"] is True
    assert protection["required_pull_request_reviews"]["require_last_push_approval"] is True


def test_bootstrap_and_sync_never_write_the_auto_merge_setting():
    # It's the project's choice; re-running bootstrap or syncing must not reset it.
    for path in (".sdlc/scripts/bootstrap-github.sh", ".sdlc/scripts/sync-sdlc.sh"):
        text = (REPO / path).read_text()
        assert not re.search(r"variable (set|delete) SDLC_AUTO_MERGE\b(?!_)", text), path


# --- agent identity -------------------------------------------------------------------------


def test_one_identity_and_no_personas():
    # One App serves every session; Claude never acts as the person. Personas were taken out
    # (claude-sdlc #61) and adding Apps back goes through the identity name.
    assert not (REPO / ".claude/personas.conf").exists()
    skill = (REPO / ".sdlc/skills/agent-identity/SKILL.md").read_text()
    assert "persona" not in skill.lower()
    assert "`— Claude`" in skill and "Requested-by:" in skill
    for script in ["agent-identity.sh", "agent-session.sh"]:
        assert "--persona" not in (REPO / ".sdlc" / "scripts" / script).read_text(), script


@pytest.fixture
def agent_env(tmp_path):
    key = tmp_path / "app.pem"
    run(["openssl", "genrsa", "-out", str(key), "2048"], check=True)
    run(
        ["openssl", "rsa", "-in", str(key), "-pubout", "-out", str(tmp_path / "pub.pem")],
        check=True,
    )
    cfg = tmp_path / "config"
    (cfg / "sdlc" / "o_r").mkdir(parents=True)
    (cfg / "sdlc" / "o_r" / "agent.env").write_text(
        "SDLC_AGENT_APP_ID=123\nSDLC_AGENT_APP_SLUG=stickle-claude\nSDLC_AGENT_BOT_ID=999\n"
    )
    fake = tmp_path / "bin"
    fake.mkdir()
    # curl stub that answers like GitHub; see the fixture for how tests steer it.
    shutil.copy(REPO / "tests/fixtures/fake-github-curl.sh", fake / "curl")
    (fake / "curl").chmod(0o755)
    env = {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "XDG_CONFIG_HOME": str(cfg),
        "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        "SDLC_AGENT_KEY_FILE": str(key),
        "SDLC_AGENT_REPO": "o/r",
        "LOG": str(tmp_path),
        "SDLC_RETRY_DELAY": "0",
    }
    return tmp_path, env


def identity(env, *args, stdin=None):
    return run(["bash", str(REPO / ".sdlc/scripts/agent-identity.sh"), *args], env=env, input=stdin)


def test_token_is_minted_with_a_valid_jwt_and_cached(agent_env):
    tmp, env = agent_env
    first = identity(env, "token")
    assert first.returncode == 0, first.stderr
    assert first.stdout.strip() == "ghs_test"
    header, payload, sig = (tmp / "jwt").read_text().strip().split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
    import base64

    claims = json.loads(base64.urlsafe_b64decode(pad(payload)))
    assert claims["iss"] == "123" and claims["exp"] - claims["iat"] <= 600
    (tmp / "sig").write_bytes(base64.urlsafe_b64decode(pad(sig)))
    (tmp / "msg").write_text(f"{header}.{payload}")
    verify = run(
        [
            "openssl",
            "dgst",
            "-sha256",
            "-verify",
            str(tmp / "pub.pem"),
            "-signature",
            str(tmp / "sig"),
            str(tmp / "msg"),
        ]
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr
    calls = (tmp / "curl").read_text().count("\n")
    assert identity(env, "token").stdout.strip() == "ghs_test"
    assert (tmp / "curl").read_text().count("\n") == calls, "second call uses the cache"


def test_token_fails_rather_than_printing_null(agent_env):
    tmp, env = agent_env
    (tmp / "body-token").write_text('{"expires_at": "2099-01-01T00:00:00Z"}')
    out = identity(env, "token")
    assert out.returncode != 0 and "null" not in out.stdout


def test_git_credential_answers_only_for_github(agent_env):
    _, env = agent_env
    gh = identity(env, "git-credential", "get", stdin="protocol=https\nhost=github.com\n\n")
    assert gh.stdout == "username=x-access-token\npassword=ghs_test\n"
    other = identity(env, "git-credential", "get", stdin="protocol=https\nhost=gitlab.com\n\n")
    assert other.stdout == ""


def test_env_makes_git_act_as_the_bot(agent_env):
    _, env = agent_env
    out = identity(env, "env")
    assert out.returncode == 0, out.stderr
    assert "GIT_AUTHOR_NAME='stickle-claude[bot]'" in out.stdout
    assert "999+stickle-claude[bot]@users.noreply.github.com" in out.stdout
    assert "SDLC_AGENT_PERSONA" not in out.stdout
    assert "insteadOf" in out.stdout


def test_env_rejects_options(agent_env):
    _, env = agent_env
    assert identity(env, "env", "--persona", "build").returncode == 1


def test_env_without_setup_falls_back_to_the_person(agent_env, tmp_path):
    _, env = agent_env
    out = identity({**env, "XDG_CONFIG_HOME": str(tmp_path / "empty")}, "env")
    assert out.returncode == 0 and out.stdout == ""
    assert "acts as you" in out.stderr


def test_agent_session_starts_claude_with_the_identity(agent_env):
    _, env = agent_env
    out = run(
        ["bash", str(REPO / ".sdlc/scripts/agent-session.sh")],
        env={**env, "SDLC_CLAUDE": "env"},
    )
    assert out.returncode == 0, out.stderr
    assert "GIT_COMMITTER_NAME=stickle-claude[bot]" in out.stdout


def test_each_repo_has_its_own_apps(agent_env):
    # An App made for o/r doesn't leak into another repo on the same machine.
    _, env = agent_env
    assert identity(env, "show").stdout.strip() == "123 stickle-claude"
    other = identity({**env, "SDLC_AGENT_REPO": "o/jobhunt-app"}, "show")
    assert other.returncode == 1
    assert identity({**env, "SDLC_AGENT_REPO": "o/jobhunt-app"}, "env").stdout == ""


def test_workflows_guard_against_agent_loops():
    mention = (REPO / ".github/workflows/sdlc-claude-mention.yml").read_text()
    assert "github.event.comment.user.type == 'User'" in mention
    review = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    # The App's bot, without an App the default token's bot (#82), and the dependency bots the
    # project names (#142); never a wildcard.
    assert (
        "allowed_bots: ${{ format('{0},github-actions,{1}', vars.SDLC_AGENT_APP_SLUG, "
        "vars.SDLC_REVIEW_EXTRA_BOTS) }}" in review
    )
    assert "allowed_bots: '*'" not in review
    spec = (REPO / ".github/workflows/sdlc-spec-from-intent.yml").read_text()
    assert "actions/create-github-app-token" in spec


# #126: SDLC_RUNNER picks the runner. Fork PRs, PRs whose fork was deleted and comments on any
# PR never get it (they check out code the repo's people didn't write), and unset means GitHub's.
RUNS_ON = (
    "runs-on: ${{ vars.SDLC_RUNNER && !github.event.issue.pull_request && "
    "(!github.event.pull_request || "
    "github.event.pull_request.head.repo.full_name == github.repository) "
    "&& vars.SDLC_RUNNER || 'ubuntu-latest' }}"
)


def gh_expr(expr, ctx):
    """Evaluate a GitHub Actions expression made of what RUNS_ON uses: property paths, 'strings',
    !, ==, &&, || and parentheses. Like Actions, a missing property is null, && and || return
    an operand, and null, false, 0 and '' are falsy."""
    tokens = re.findall(r"'[^']*'|&&|\|\||==|!|\(|\)|[A-Za-z_][\w.-]*", expr)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def take():
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def operand():
        tok = take()
        if tok == "!":
            return not operand()
        if tok == "(":
            value = either()
            assert take() == ")"
            return value
        if tok.startswith("'"):
            return tok[1:-1]
        value = ctx
        for part in tok.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        return value

    def equality():
        left = operand()
        while peek() == "==":
            take()
            left = left == operand()
        return left

    def both():
        left = equality()
        while peek() == "&&":
            take()
            right = equality()
            left = right if left else left
        return left

    def either():
        left = both()
        while peek() == "||":
            take()
            right = both()
            left = left if left else right
        return left

    value = either()
    assert pos == len(tokens), tokens[pos:]
    return value


REPO_NAME = "o/r"
SAME = {"head": {"repo": {"full_name": REPO_NAME}}}
FORK = {"head": {"repo": {"full_name": "stranger/r"}}}
DELETED_FORK = {"head": {"repo": None}}


@pytest.mark.parametrize(
    "event, runner",
    [
        ({"pull_request": SAME}, "self-hosted"),
        ({"pull_request": FORK}, "ubuntu-latest"),
        ({"pull_request": DELETED_FORK}, "ubuntu-latest"),
        ({"pull_request": FORK, "comment": {}}, "ubuntu-latest"),  # review comment on a fork PR
        ({"issue": {"pull_request": {"url": "x"}}, "comment": {}}, "ubuntu-latest"),  # on a PR
        ({"issue": {}, "comment": {}}, "self-hosted"),  # a comment on an issue
        ({"ref": "refs/heads/main"}, "self-hosted"),  # push, workflow_dispatch
    ],
    ids=[
        "same-repo PR",
        "fork PR",
        "deleted fork",
        "fork review comment",
        "PR comment",
        "issue comment",
        "push",
    ],
)
def test_runs_on_sends_only_the_repo_own_code_to_sdlc_runner(event, runner):
    expr = RUNS_ON.removeprefix("runs-on: ${{").removesuffix("}}")
    ctx = {"github": {"repository": REPO_NAME, "event": event}}
    assert gh_expr(expr, {**ctx, "vars": {"SDLC_RUNNER": "self-hosted"}}) == runner
    assert gh_expr(expr, {**ctx, "vars": {}}) == "ubuntu-latest"  # unset: GitHub's, always


@pytest.mark.parametrize(
    "workflow", sorted(p.name for p in REPO.glob(".github/workflows/*.yml")), ids=str
)
def test_every_job_runs_on_sdlc_runner_with_the_fork_guard(workflow):
    text = (REPO / ".github/workflows" / workflow).read_text()
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("runs-on:")]
    assert lines, f"{workflow} has no jobs"
    # A job pinned to a literal runner stays queued in an outage and blocks the merge.
    assert all(line == RUNS_ON for line in lines), lines
    jobs = re.findall(r"^  [a-z][a-z0-9_-]*:\n(?:    .*\n|\n)*?    steps:", text, re.M)
    assert len(lines) == len(jobs), f"{workflow}: a job without runs-on"


# --- tests-locked: bug fixes lock their tests automatically -------------------------------------


@pytest.fixture
def bug_branch(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(
        repo,
        "bug: 0003-overlap",
        {"changes/0003-overlap/bug.md": "# bug\n", "changes/0004-feat/intent.md": "# i\n"},
    )
    git(repo, "switch", "-q", "-c", "build/0003-overlap")
    return repo


def locked(repo, path="", env=None):
    args = ["bash", str(REPO / ".sdlc/scripts/tests-locked.sh")] + ([path] if path else [])
    clean = {"SDLC_LOCK_TESTS": "", "SDLC_CHANGE": "", **(env or {})}
    return run(args, cwd=repo, env=clean).returncode == 0


def test_bug_tests_stay_editable_until_the_failing_test_is_committed(bug_branch):
    assert not locked(bug_branch, "tests/test_overlap.py")
    commit(
        bug_branch,
        "test(0003-overlap): failing test for overlap",
        {"tests/test_overlap.py": "x\n", "app/src/__tests__/overlap.test.tsx": "x\n"},
    )
    assert locked(bug_branch, "tests/test_overlap.py")
    assert locked(bug_branch, "app/src/__tests__/overlap.test.tsx")
    assert not locked(bug_branch, "src/overlap.py"), "code stays editable"


def test_only_the_failing_test_files_are_locked(bug_branch):
    # /sdlc-build writes more tests after the failing one (coverage, regression guards); those
    # stay editable, only what the test(<slug>) commit touched is locked.
    commit(bug_branch, "test(0003-overlap): failing test", {"tests/test_overlap.py": "x\n"})
    assert locked(bug_branch, "tests/test_overlap.py")
    assert not locked(bug_branch, "tests/test_coverage_extra.py")
    assert not locked(bug_branch, "app/e2e/screens.spec.ts")
    assert locked(bug_branch, "app/e2e/screens.spec.ts", {"SDLC_LOCK_TESTS": "1"})


def test_features_are_not_locked_by_a_test_commit(bug_branch):
    git(bug_branch, "switch", "-q", "-c", "build/0004-feat")
    commit(bug_branch, "test(0004-feat): add tests", {"tests/t.py": "x\n"})
    assert not locked(bug_branch, "tests/t.py")


def test_explicit_setting_wins(bug_branch):
    assert locked(bug_branch, "tests/t.py", {"SDLC_LOCK_TESTS": "1"})
    commit(bug_branch, "test(0003-overlap): failing test", {"tests/t.py": "x\n"})
    assert not locked(bug_branch, "tests/t.py", {"SDLC_LOCK_TESTS": "0"})


def test_change_can_be_named_explicitly(bug_branch):
    git(bug_branch, "switch", "-q", "-c", "wip")
    commit(bug_branch, "test(0003-overlap): failing test", {"tests/t.py": "x\n"})
    assert not locked(bug_branch, "tests/t.py")
    assert locked(bug_branch, "tests/t.py", {"SDLC_CHANGE": "0003-overlap"})


def test_a_later_commit_by_another_type_does_not_lock(bug_branch):
    commit(bug_branch, "feat(0003-overlap): fix it", {"tests/t.py": "x\n"})
    assert not locked(bug_branch, "tests/t.py")


def test_agent_session_locks_tests_for_a_bug_fix(bug_branch):
    commit(bug_branch, "test(0003-overlap): failing test", {"tests/t.py": "x\n"})
    out = run(
        ["bash", str(REPO / ".sdlc/scripts/agent-session.sh")],
        cwd=bug_branch,
        env={"SDLC_CLAUDE": "env", "SDLC_LOCK_TESTS": "", "XDG_CONFIG_HOME": str(bug_branch)},
    )
    assert out.returncode == 0, out.stderr
    assert "SDLC_LOCK_TESTS=1" not in out.stdout, "the hook locks just the failing test's files"
    assert "tests locked" in out.stderr and "tests/t.py" in out.stderr


def test_every_session_loads_the_agent_identity():
    settings = json.loads((REPO / ".claude/settings.json").read_text())
    commands = [h["command"] for e in settings["hooks"]["SessionStart"] for h in e["hooks"]]
    assert commands == ['"$CLAUDE_PROJECT_DIR"/.sdlc/hooks/dispatch.sh SessionStart']
    table = (REPO / ".sdlc/hooks/hooks.tsv").read_text()  # the dispatcher runs it (#133)
    assert "SessionStart\t*\t.sdlc/scripts/agent-session.sh --hook\n" in table


def test_session_hook_is_a_no_op_without_setup(tmp_path):
    env_file = tmp_path / "env"
    out = run(
        ["bash", str(REPO / ".sdlc/scripts/agent-session.sh"), "--hook"],
        env={"CLAUDE_ENV_FILE": str(env_file), "XDG_CONFIG_HOME": str(tmp_path)},
    )
    assert out.returncode == 0
    assert not env_file.exists() or env_file.read_text() == ""


def test_repos_share_one_app_and_one_key_with_use(agent_env):
    tmp, env = agent_env
    shared = tmp / "shared" / "claude.env"
    shared.parent.mkdir()
    key = env["SDLC_AGENT_KEY_FILE"]
    shared.write_text(
        f"SDLC_AGENT_APP_ID=55\nSDLC_AGENT_APP_SLUG=one-claude\nSDLC_AGENT_KEY=file:{key}\n"
    )
    no_key_env = {k: v for k, v in env.items() if k != "SDLC_AGENT_KEY_FILE"} | {
        "SDLC_AGENT_KEY_FILE": ""
    }
    for repo in ["o/jobhunt-app", "o/sandbox"]:
        e = {**no_key_env, "SDLC_AGENT_REPO": repo}
        linked = identity(e, "use", str(shared))
        assert linked.returncode == 0, linked.stderr
        assert identity(e, "show").stdout.strip() == "55 one-claude"
        assert identity(e, "token").stdout.strip() == "ghs_test", "key read from the shared file"
    assert shared.read_text().count("SDLC_AGENT_APP_ID=55") == 1, "the shared config is untouched"


def test_use_and_setup_refuse_to_replace_an_existing_config(agent_env):
    tmp, env = agent_env
    other = tmp / "other.env"
    other.write_text("SDLC_AGENT_APP_ID=9\nSDLC_AGENT_APP_SLUG=other\n")
    refused = identity(env, "use", str(other))
    assert refused.returncode == 1 and "already exists" in refused.stderr
    assert "stickle-claude" in (tmp / "config/sdlc/o_r/agent.env").read_text()
    assert identity(env, "use", str(other), "--force").returncode == 0
    setup = identity(env, "setup", "--app-id", "1", "--key", env["SDLC_AGENT_KEY_FILE"])
    assert setup.returncode == 1 and "already exists" in setup.stderr


# --- what GitHub can answer, and how the identity copes --------------------------------------


def _codes(tmp, endpoint, *codes):
    (tmp / f"codes-{endpoint}").write_text("\n".join(map(str, codes)) + "\n")


def test_app_not_installed_says_where_to_install_it(agent_env):
    tmp, env = agent_env
    _codes(tmp, "installation", 404)
    out = identity(env, "token")
    assert out.returncode == 1
    assert "isn't installed on o/r" in out.stderr
    assert "https://github.com/apps/stickle-claude/installations/new" in out.stderr


def test_rejected_credentials_point_to_doctor(agent_env):
    tmp, env = agent_env
    _codes(tmp, "installation", 401)
    (tmp / "body-installation").write_text('{"message": "A JSON web token could not be decoded"}')
    out = identity(env, "token")
    assert out.returncode == 1
    assert "rejected stickle-claude's credentials" in out.stderr
    assert "could not be decoded" in out.stderr and "doctor" in out.stderr


def test_clock_skew_is_called_out(agent_env):
    tmp, env = agent_env
    _codes(tmp, "installation", 401)
    (tmp / "body-installation").write_text(
        "{\"message\": \"'Issued at' claim ('iat') must be an Integer representing the time\"}"
    )
    assert "clock looks wrong" in identity(env, "token").stderr


def test_suspended_installation_explained(agent_env):
    tmp, env = agent_env
    _codes(tmp, "token", 403)
    (tmp / "body-token").write_text('{"message": "This installation has been suspended"}')
    out = identity(env, "token")
    assert out.returncode == 1 and "suspended" in out.stderr
    assert "settings/installations" in out.stderr


def test_outages_and_timeouts_are_retried(agent_env):
    tmp, env = agent_env
    _codes(tmp, "installation", 502, "timeout", 200)
    out = identity(env, "token")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ghs_test"


def test_gives_up_after_three_tries(agent_env):
    tmp, env = agent_env
    _codes(tmp, "installation", "timeout")
    out = identity(env, "token")
    assert out.returncode == 1 and "didn't answer after 3 tries" in out.stderr
    assert (tmp / "curl").read_text().count("/installation") == 3
    _codes(tmp, "installation", 503)
    assert "had an error (503) after 3 tries" in identity(env, "token").stderr


def test_weird_replies_fail_clearly(agent_env):
    tmp, env = agent_env
    (tmp / "body-installation").write_text("<html>proxy error</html>")
    out = identity(env, "token")
    assert out.returncode == 1 and "has no id" in out.stderr
    (tmp / "body-installation").write_text('{"id": 77}')
    (tmp / "body-token").write_text("not json")
    out = identity(env, "token")
    assert out.returncode == 1 and "has no token" in out.stderr


def test_doctor_walks_every_link(agent_env):
    _, env = agent_env
    out = identity(env, "doctor")
    assert out.returncode == 0, out.stdout + out.stderr
    for step in [
        "config",
        "private key readable",
        "accepts the key",
        "installed on o/r",
        "token issued",
    ]:
        assert step in out.stdout


def test_doctor_on_rejected_key_explains_rekey(agent_env):
    tmp, env = agent_env
    _codes(tmp, "app", 401)
    out = identity(env, "doctor")
    assert out.returncode == 1
    assert "FAIL: GitHub doesn't accept the key" in out.stdout
    assert "Generate a private key" in out.stdout and "rekey --key" in out.stdout
    assert "create --force" in out.stdout, "the App may have been deleted"


def test_doctor_on_mismatched_key_and_app(agent_env):
    tmp, env = agent_env
    (tmp / "body-app").write_text('{"id": 123, "slug": "someone-else"}')
    out = identity(env, "doctor")
    assert out.returncode == 1 and "belong to 'someone-else'" in out.stdout


def test_doctor_on_missing_install_gives_the_link(agent_env):
    tmp, env = agent_env
    _codes(tmp, "installation", 404)
    out = identity(env, "doctor")
    assert out.returncode == 1
    assert "isn't installed on o/r" in out.stdout and "installations/new" in out.stdout


def test_doctor_without_config_says_create_or_use(agent_env, tmp_path):
    _, env = agent_env
    out = identity({**env, "SDLC_AGENT_REPO": "o/elsewhere"}, "doctor")
    assert out.returncode == 1 and "create" in out.stdout and "use <its config file>" in out.stdout


@pytest.fixture
def file_keyed(agent_env):
    """The App's config keeps its key in a file, so rekey can be checked end to end."""
    tmp, env = agent_env
    stored = tmp / "stored.pem"
    shutil.copy(env["SDLC_AGENT_KEY_FILE"], stored)
    cfg = tmp / "config/sdlc/o_r/agent.env"
    cfg.write_text(cfg.read_text() + f"SDLC_AGENT_KEY=file:{stored}\n")
    new = tmp / "new.pem"
    run(["openssl", "genrsa", "-out", str(new), "2048"], check=True)
    return tmp, {**env, "SDLC_AGENT_KEY_FILE": ""}, stored, new


def test_rekey_without_a_key_explains_how_to_get_one(file_keyed):
    _, env, stored, _ = file_keyed
    before = stored.read_text()
    out = identity(env, "rekey")
    assert out.returncode == 2 and "Generate a private key" in out.stdout
    assert stored.read_text() == before


def test_rekey_needs_confirmation(file_keyed):
    _, env, stored, new = file_keyed
    before = stored.read_text()
    out = identity(env, "rekey", "--key", str(new))
    assert out.returncode == 1 and "add --yes" in out.stderr
    assert stored.read_text() == before, "nothing replaced by accident"


def test_rekey_refuses_a_key_github_rejects(file_keyed):
    tmp, env, stored, new = file_keyed
    before = stored.read_text()
    _codes(tmp, "app", 401)
    out = identity(env, "rekey", "--key", str(new), "--yes")
    assert out.returncode == 1 and "nothing changed" in out.stderr
    assert stored.read_text() == before


def test_rekey_refuses_another_apps_key(file_keyed):
    tmp, env, stored, new = file_keyed
    before = stored.read_text()
    (tmp / "body-app").write_text('{"id": 999, "slug": "other-app"}')
    out = identity(env, "rekey", "--key", str(new), "--yes")
    assert out.returncode == 1 and "is for 'other-app'" in out.stderr
    assert stored.read_text() == before


def test_rekey_replaces_the_key_and_says_what_next(file_keyed):
    _, env, stored, new = file_keyed
    out = identity(env, "rekey", "--key", str(new), "--yes")
    assert out.returncode == 0, out.stderr
    assert stored.read_text() == new.read_text()
    assert "--update-agent-key" in out.stdout and "delete the old key" in out.stdout
    assert identity(env, "token").stdout.strip() == "ghs_test"


# --- the /sdlc skill reads the sync's output -----------------------------------------------


def test_sdlc_skill_matches_what_the_sync_prints():
    """/sdlc acts on the sync's messages and lists the stack contract; keep them in step."""
    sync = (REPO / ".sdlc/scripts/sync-sdlc.sh").read_text()
    skill = (REPO / ".sdlc/skills/sdlc/SKILL.md").read_text()
    for message in [
        "kept your local changes",
        "CONFLICT",
        ".sdlc-new",
        "kept (the framework dropped these",
        "your Makefile doesn't define these targets",
        "your Makefile doesn't include the pipeline's targets",
        "your Makefile defines targets .sdlc/sdlc.mk now provides",
    ]:
        assert message in sync, f"the sync no longer prints {message!r}"
        assert message in skill, f"/sdlc doesn't handle {message!r}"
    block = sync.split("local contract_targets=(")[1].split(")")[0]
    contract = re.findall(r'^\s*"([a-z-]+) ', block, re.MULTILINE)
    assert contract, "couldn't read contract_targets from the sync"
    assert f"`{' '.join(contract)}`" in skill, "the stack contract in /sdlc differs from the sync's"


def test_agent_allows_the_make_targets_the_skills_run_first():
    """CI ignores .claude/settings.json's allow list, so agent.sh's own list must cover what the
    skills run unprompted: the routing check (`make next`) and the scaffold. Without `make next`
    the intent eval stopped for approval and failed the v0.7.1 release."""
    allowed = (REPO / ".sdlc/scripts/agent.sh").read_text()
    routing = (REPO / ".sdlc/skills/routing.md").read_text()
    assert "make next" in routing
    for target in ("make next:*", "make new-change:*", "make validate"):
        assert f"Bash({target})" in allowed

    # Every stub starts by running the resolver (#133): without it no skill loads in CI.
    assert "Bash(.sdlc/scripts/resolve.sh:*)" in allowed
    settings = json.loads((REPO / ".claude/settings.json").read_text())
    assert "Bash(.sdlc/scripts/resolve.sh:*)" in settings["permissions"]["allow"]
    for stub in [*REPO.glob(".claude/skills/*/SKILL.md"), *REPO.glob(".claude/agents/*.md")]:
        assert "`.sdlc/scripts/resolve.sh " in stub.read_text(), stub


# --- clause check (#47) -------------------------------------------------------------------

CLAUSE_FIXTURE = "evals/fixtures/clause-coverage/0001-role-search"


@pytest.fixture
def fake_claude(tmp_path):
    """A `claude` on PATH that answers each call with $FAKE_ANSWER and logs its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "claude"
    script.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\036" "$*" >> "$FAKE_LOG"\n'
        '[[ -z "${FAKE_FAIL:-}" ]] || exit 1\nprintf "%b\\n" "$FAKE_ANSWER"\n'
    )
    script.chmod(0o755)
    log = tmp_path / "calls.log"

    def check(answer, *args, fail=False):
        env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_LOG": str(log),
            "FAKE_ANSWER": answer,
            **({"FAKE_FAIL": "1"} if fail else {}),
        }
        result = run([".sdlc/scripts/clause-check.sh", *args], env=env)
        calls = log.read_text().split("\036")[:-1] if log.exists() else []
        log.unlink(missing_ok=True)
        return result, calls

    return check


def test_clause_check_calls_a_small_model_once_per_requirement(fake_claude):
    answer = 'Thinking...\\nCLAUSES: [{"clause": "offers a button", "missing": ["criterion"]}]'
    result, calls = fake_claude(answer, "--stage", "spec", CLAUSE_FIXTURE)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 2, "one call per requirement, never the whole spec"
    assert all("--model haiku" in c and "--max-turns 1" in c for c in calls)
    assert '"id":"R1"' in calls[0] and '"id":"R2"' not in calls[0]
    found = json.loads(result.stdout)
    assert [(f["requirement"], f["stage"], f["clause"], f["missing"]) for f in found] == [
        ("R1", "spec", "offers a button", ["criterion"]),
        ("R2", "spec", "offers a button", ["criterion"]),
    ]
    assert found[1]["text"].startswith("When no roles match")


def test_clause_check_reports_nothing_when_every_clause_is_covered(fake_claude):
    result, _ = fake_claude("CLAUSES: []", "--stage", "plan", CLAUSE_FIXTURE)
    assert result.returncode == 0 and json.loads(result.stdout) == []


@pytest.mark.parametrize(
    ("answer", "fail"),
    [
        ("every clause is covered", False),  # no CLAUSES line
        ("CLAUSES: none", False),  # not JSON
        ('CLAUSES: {"clause": "x"}', False),  # not a list
        ('CLAUSES: ["offers a button"]', False),  # not objects with a clause
        ("CLAUSES: []", True),  # the call itself failed
    ],
)
def test_clause_check_fails_safe_on_an_answer_it_cant_read(fake_claude, answer, fail):
    result, _ = fake_claude(answer, "--stage", "spec", CLAUSE_FIXTURE, fail=fail)
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    assert [f["requirement"] for f in found] == ["R1", "R2"], "unchecked, never covered"
    assert all(f["unchecked"] and "clause" not in f for f in found)


def test_clause_check_takes_the_last_clauses_line_and_a_single_missing_value(fake_claude):
    answer = 'CLAUSES: [{"clause": "draft"}]\\nCLAUSES: [{"clause": "final", "missing": "design"}]'
    result, _ = fake_claude(answer, "--stage", "plan", CLAUSE_FIXTURE)
    found = json.loads(result.stdout)
    assert {(f["clause"], tuple(f["missing"])) for f in found} == {("final", ("design",))}


def test_clause_check_dry_run_reads_as_unchecked():
    # The echo adapter prints the prompt; its example answer must not read as a real one.
    result = run(
        [".sdlc/scripts/clause-check.sh", "--stage", "spec", CLAUSE_FIXTURE], env={"AGENT": "echo"}
    )
    assert result.returncode == 0, result.stderr
    assert all("unchecked" in f for f in json.loads(result.stdout))
    prompt = (REPO / ".sdlc/prompts/clause-check.md").read_text()
    assert not re.search(r"^CLAUSES: ", prompt, re.M)


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--stage", "spec"],
        ["--stage", "code", "0001"],
        ["--stage", "spec", "a", "b"],
        ["-x"],
        ["--changed-since", "main", "--stage", "spec"],
        ["--changed-since", "main", "0001"],
    ],
)
def test_clause_check_usage(args):
    result = run([".sdlc/scripts/clause-check.sh", *args], env={"AGENT": "echo"})
    assert result.returncode == 2 and "usage" in result.stderr


def test_clause_check_fails_when_the_spec_cant_be_split(tmp_path):
    result = run(
        [".sdlc/scripts/clause-check.sh", "--stage", "spec", str(tmp_path)], env={"AGENT": "echo"}
    )
    assert result.returncode != 0
    assert "spec.md doesn't exist" in result.stderr


def test_review_runs_the_clause_check_before_the_review_and_never_fails_on_it():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    check = workflow.index("- name: Clause check")
    assert workflow.index("- name: Find the changed specs and plans") < check
    assert check < workflow.index("- uses: anthropics/claude-code-action@v1")
    step = workflow[check : workflow.index("- uses: anthropics/claude-code-action@v1")]
    # AI only through the adapter (CLAUDE.md): the script calls agent.sh, the step never claude -p.
    assert '.sdlc/scripts/clause-check.sh --changed-since "$BASE"' in step
    assert "claude -p" not in workflow
    assert "BASE: ${{ github.event.pull_request.base.sha }}" in step
    assert "could not run" in step, "a failed check is reported to the review, not dropped"
    assert "if: steps.artifacts.outputs.changed == 'true'" in step
    setup = workflow[workflow.index("- uses: ./.github/actions/setup-stack") : check]
    assert "continue-on-error: true" in setup
    assert (
        ".clause-check.json" in step
        and ".clause-check.json" in workflow[check:].split("prompt: |", 1)[1]
    )
    assert "Where the clauses come from" in workflow
    assert "Where the clauses come from" in (REPO / ".sdlc/REVIEW.md").read_text()


# --- delivery check, stage build (#106) ---------------------------------------------------

DELIVERY_FIXTURE = "evals/fixtures/delivery-gap/0001-floor-mode"


def test_delivery_check_reads_the_code_with_a_larger_model(fake_claude):
    answer = (
        'CLAUSES: [{"clause": "generates a 3D scene", "delivered": "draws boxes", '
        '"gap": "large", "approved": null}, {"clause": "drawn", "gap": "tiny", "approved": ""}, '
        '{"clause": "snaps", "gap": "small", "approved": "Approved: Sam"}]'
    )
    result, calls = fake_claude(answer, "--stage", "build", DELIVERY_FIXTURE)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 2
    assert all("--model sonnet" in c and "--max-turns 15" in c for c in calls)
    assert all("--allowedTools Read,Grep,Glob" in c for c in calls)
    assert "You compare what a change delivers" in calls[0]
    assert "- **Demo:** the dock's floor tab shows a floor with doorway lines" in calls[0]
    found = [f for f in json.loads(result.stdout) if f["requirement"] == "R1"]
    assert [(f["stage"], f["clause"], f["gap"], f["approved"]) for f in found] == [
        ("build", "generates a 3D scene", "large", None),
        ("build", "drawn", "large", None),  # a gap it can't read counts as large
        ("build", "snaps", "small", "Approved: Sam"),
    ]
    assert found[1]["delivered"] == "" and "missing" not in found[0]


def test_delivery_check_names_the_branchs_changed_files(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(REPO, work, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"))
    init_repo(work)
    commit(work, "base")
    git(work, "checkout", "-q", "-b", "build/x")
    commit(work, "code", {"src/floor_view.py": "x = 1\n", "changes/0001-x/notes.md": "n\n"})
    (work / "src/untracked_view.py").write_text("y = 2\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    (bin_dir / "claude").write_text(
        '#!/usr/bin/env bash\nprintf "%s" "$*" >> "$FAKE_LOG"\necho "CLAUSES: []"\n'
    )
    (bin_dir / "claude").chmod(0o755)
    result = run(
        [".sdlc/scripts/clause-check.sh", "--stage", "build", DELIVERY_FIXTURE],
        cwd=work,
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_LOG": str(log)},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
    calls = log.read_text()
    assert '"changed_files":["src/floor_view.py","src/untracked_view.py"]' in calls
    assert "changes/0001-x/notes.md" not in calls


def test_delivery_check_runs_when_the_branch_changes_only_its_change_folder(tmp_path):
    # Found in #133: with nothing changed outside changes/, `grep -v` matched nothing and exited
    # 1, and under pipefail the check died with no output.
    work = tmp_path / "work"
    shutil.copytree(REPO, work, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"))
    init_repo(work)
    commit(work, "base")
    git(work, "checkout", "-q", "-b", "build/x")
    commit(work, "notes", {"changes/0001-x/notes.md": "n\n"})
    result = run(
        [".sdlc/scripts/clause-check.sh", "--stage", "build", DELIVERY_FIXTURE],
        cwd=work,
        env={"AGENT": "echo"},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout), "a row per requirement, unchecked by the echo agent"


def test_delivery_prompt_example_is_not_an_answer():
    prompt = (REPO / ".sdlc/prompts/delivery-check.md").read_text()
    assert not re.search(r"^CLAUSES: ", prompt, re.M)
    assert "main verb or noun" in prompt


def test_clause_check_reports_unreadable_requirement_lines_as_unchecked(fake_claude, tmp_path):
    change = tmp_path / "0001-search"
    shutil.copytree(REPO / CLAUSE_FIXTURE, change)
    spec = change / "spec.md"
    spec.write_text(spec.read_text().replace("- R2. When", "- Requirement 2: When"))
    result, calls = fake_claude("CLAUSES: []", "--stage", "spec", str(change))
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1, "R1 is still checked"
    [entry] = json.loads(result.stdout)
    assert entry["requirement"] is None and entry["stage"] == "spec"
    assert entry["text"].startswith("- Requirement 2: When no roles match")
    assert "could not be read as a requirement" in entry["unchecked"]


@pytest.mark.parametrize(
    ("quote", "kept"),
    [
        # The fixture plan has no Descopes entry, but its spec has an Out of scope line.
        ("Editing doorways by hand.", True),
        ("  Editing   doorways  by hand. ", True),  # whitespace differs
        ("and snaps moved rooms to the grid", True),  # wraps across lines in plan.md
        ("**Editing doorways** by `hand`.", True),  # markdown differs
        ("Descope: the 3D scene. Approved: Sam, 2026-11-01.", False),  # made up
        ("**", False),  # nothing left once markdown is stripped
    ],
)
def test_delivery_check_keeps_an_approval_only_if_its_quote_is_there(fake_claude, quote, kept):
    # PR #109 review: a made-up approval quote turned a large gap into an approved one.
    answer = "CLAUSES: " + json.dumps(
        [{"clause": "generates a 3D scene", "delivered": "x", "gap": "large", "approved": quote}]
    )
    result, _ = fake_claude(answer, "--stage", "build", DELIVERY_FIXTURE)
    assert result.returncode == 0, result.stderr
    entry = json.loads(result.stdout)[0]
    if kept:
        assert entry["approved"] == quote and "approval_not_found" not in entry
    else:
        assert entry["approved"] is None and entry["approval_not_found"] == quote


def test_review_skips_the_clause_check_quietly_without_a_clauses_target():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    find = workflow[workflow.index("- name: Find the changed specs and plans") :]
    find = find[: find.index("- uses: ./.github/actions/setup-stack")]
    assert "make -n clauses CHANGE=probe" in find, "probes the target before any stack setup"
    assert "could not run" in (REPO / ".sdlc/REVIEW.md").read_text()


def test_release_notes_give_the_clauses_recipe_the_makefile_uses():
    # The upgrade step tells consumers' Claude what to add; keep it in step with ours.
    notes = (REPO / "docs/release-notes/v0.9.0.md").read_text()
    makefile = (REPO / ".sdlc/sdlc.mk").read_text()  # where the target lives since #133
    recipe = makefile[makefile.index("\nclauses:\n") + 1 :].split("\n\n", 1)[0]
    in_notes = {line.lstrip(" ") for line in notes.splitlines()}  # indented inside a list
    assert all(line in in_notes for line in recipe.splitlines()), recipe
    assert "## Upgrade steps" in notes and "## Optional: the `clauses` make target" in notes
    skill = (REPO / ".sdlc/skills/sdlc/SKILL.md").read_text()
    assert "`Upgrade steps`" in skill and "never in the sync PR" in skill


@pytest.fixture
def eval_check(tmp_path):
    """Run an eval task's check in a copy of the repo with report.md and a fake `claude`."""
    work = tmp_path / "work"
    shutil.copytree(REPO, work, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"))
    init_repo(work)
    commit(work, "base")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def check(task, report, entries):
        (work / "report.md").write_text(report)
        (tmp_path / "answer.txt").write_text("CLAUSES: " + json.dumps(entries) + "\n")
        (bin_dir / "claude").write_text(f"#!/usr/bin/env bash\ncat '{tmp_path / 'answer.txt'}'\n")
        (bin_dir / "claude").chmod(0o755)
        command = json.loads((REPO / "evals/tasks" / task).read_text())["check"]
        return run(
            ["bash", "-c", command], cwd=work, env={"PATH": f"{bin_dir}:{os.environ['PATH']}"}
        )

    return check


APPROVED_TASK = "verifier-passes-an-approved-delivery-gap.json"
FLAGGED_TASK = "verifier-flags-unapproved-delivery-gap.json"
REAL_QUOTE = "Descope: R1's 3D scene opened in the editor"


@pytest.mark.parametrize(
    ("report", "passes"),
    [
        # The release run's report (v0.9.0): right, but it says "needs approval" in prose.
        ("Nothing needs approval, so there is no heading. Approved: Sam, 2026-11-01.", True),
        ("## Descope: needs approval\n\n- R1. Approved: Sam, 2026-11-01.", False),
        ("**Descope: needs approval**\n\nApproved: Sam", False),
        ("R1's gap is covered.", False),  # doesn't quote the approval
    ],
)
def test_approved_gap_eval_reads_the_heading_not_the_phrase(eval_check, report, passes):
    entry = {"clause": "a 3D scene", "delivered": "x", "gap": "large", "approved": REAL_QUOTE}
    result = eval_check(APPROVED_TASK, report, [entry])
    assert (result.returncode == 0) == passes, result.stdout + result.stderr
    if not passes:
        assert result.stdout.startswith("check: "), "a failure says which part failed"


def test_approved_gap_eval_shows_the_script_output_when_it_fails(eval_check):
    made_up = {
        "clause": "a 3D scene",
        "delivered": "x",
        "gap": "large",
        "approved": "Approved: Lee",
    }
    result = eval_check(APPROVED_TASK, "Approved: Sam, 2026-11-01.", [made_up])
    assert result.returncode != 0
    assert "left a large gap unapproved" in result.stdout and "approval_not_found" in result.stdout


@pytest.mark.parametrize(
    ("report", "passes"),
    [
        ("## Descope: needs approval\n\n- R1 generates a 3D scene: only a diagram.", True),
        ("R1 generates a 3D scene, which needs approval.", False),  # no heading
    ],
)
def test_unapproved_gap_eval_needs_the_heading(eval_check, report, passes):
    entry = {"clause": "generates a 3D scene", "delivered": "x", "gap": "large", "approved": None}
    result = eval_check(FLAGGED_TASK, report, [entry])
    assert (result.returncode == 0) == passes, result.stdout + result.stderr


# --- asking for a review after a push (#105) ------------------------------------------------

FAKE_GH_REQUEST_REVIEW = r"""#!/usr/bin/env bash
# Serves $D/<file> for each API path and logs every call to $D/calls.
printf '%s\n' "$*" >> "$D/calls"
path="$2" jq_filter="" post=0
shift 2
while (($#)); do
  case "$1" in --jq) jq_filter="$2"; shift 2 ;; -f) post=1; shift 2 ;; *) shift ;; esac
done
serve() { if [[ -n "$jq_filter" ]]; then jq -r "$jq_filter" "$D/$1"; else cat "$D/$1"; fi; }
case "$path" in
  repos/o/r/pulls/7)
    # Each call takes the next head from $D/heads (the push shows up after a while).
    head="$(head -n 1 "$D/heads")"
    (($(wc -l < "$D/heads") > 1)) && sed -i 1d "$D/heads"
    echo "{\"head\": {\"sha\": \"$head\"}}" > "$D/pull.json"; serve pull.json ;;
  repos/o/r/issues/7/labels)
    if ((post)); then [[ ! -e "$D/label-fails" ]] || exit 1; else serve labels.json; fi ;;
  repos/o/r/actions/variables/SDLC_AUTO_MERGE)
    status="$(cat "$D/var-status")"
    [[ "$status" == 200 ]] || { echo "gh: HTTP $status" >&2; exit 1; }
    serve var.json ;;
  repos/o/r/actions/organization-variables)
    echo '{"variables": []}' > "$D/org.json"; serve org.json ;;
  repos/o/r/actions/runs*) serve runs.json ;;
  *) echo "unexpected: $path" >&2; exit 1 ;;
esac
"""

PUSHED = "abc1234def5678abc1234def5678abc1234def56"


def review_run(conclusion=None, path=".github/workflows/sdlc-claude-review.yml"):
    status = "completed" if conclusion else "in_progress"
    return {"path": path, "status": status, "conclusion": conclusion}


@pytest.fixture
def request_review(tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_REQUEST_REVIEW)
    (fake / "gh").chmod(0o755)
    state = tmp_path / "gh"
    state.mkdir()

    def go(
        variable="", status=200, heads=(PUSHED,), runs=(), labels=(), label_fails=False, sha=PUSHED
    ):
        (state / "heads").write_text("\n".join(heads) + "\n")
        (state / "var-status").write_text(str(status))
        (state / "var.json").write_text(json.dumps({"value": variable}))
        (state / "runs.json").write_text(json.dumps({"workflow_runs": list(runs)}))
        (state / "labels.json").write_text(json.dumps([{"name": n} for n in labels]))
        (state / "label-fails").unlink(missing_ok=True)
        if label_fails:
            (state / "label-fails").write_text("")
        (state / "calls").unlink(missing_ok=True)
        env = {
            "PATH": f"{fake}:{os.environ['PATH']}",
            "D": str(state),
            "GITHUB_REPOSITORY": "o/r",
            "REQUEST_REVIEW_WAIT": "2",
            "REQUEST_REVIEW_POLL": "1",
        }
        args = [] if sha is None else [sha]
        result = run(["bash", str(REPO / ".sdlc/scripts/request-review.sh"), "7", *args], env=env)
        calls = (state / "calls").read_text()
        labelled = any(c.startswith("api repos/o/r/issues/7/labels -f") for c in calls.splitlines())
        return result, labelled, calls

    return go


def test_request_review_adds_the_label_when_auto_merge_is_off(request_review):
    result, labelled, _ = request_review(variable="")
    assert result.returncode == 0 and labelled
    assert result.stdout == (
        "Added the review label: auto-merge is off, so pushes don't start a review.\n"
    )


def test_request_review_leaves_the_push_review_alone_when_auto_merge_is_on(request_review):
    # spellbound3d PR #95: the label cancelled the review the push had started.
    result, labelled, calls = request_review(variable="merge", runs=[review_run()])
    assert result.returncode == 0 and not labelled
    assert "SDLC_AUTO_MERGE=merge" in result.stdout and "abc1234" in result.stdout
    assert f"actions/runs?head_sha={PUSHED}&event=pull_request" in calls
    # No label to add, so no waiting for GitHub to show the push: even an old head is fine.
    assert "api repos/o/r/pulls/7 " not in calls
    result, labelled, _ = request_review(variable="merge", runs=[review_run()], heads=("0ld0000",))
    assert not labelled and "already started a review" in result.stdout


@pytest.mark.parametrize(
    "runs",
    [
        [],  # no run yet
        [review_run("skipped")],  # the job's condition skipped it
        [review_run("cancelled")],  # a newer run replaced it
        [review_run(path=".github/workflows/sdlc-ci.yml")],  # another workflow
    ],
)
def test_request_review_adds_the_label_when_no_review_started_on_the_push(request_review, runs):
    result, labelled, _ = request_review(variable="squash", runs=runs)
    assert result.returncode == 0 and labelled
    assert "no review run started on abc1234" in result.stdout


def test_request_review_counts_a_finished_review_of_the_push(request_review):
    result, labelled, _ = request_review(variable="merge", runs=[review_run("success")])
    assert not labelled and "already started a review" in result.stdout


@pytest.mark.parametrize("status", [403, 500])
def test_request_review_falls_back_to_the_runs_when_the_variable_cant_be_read(
    request_review, status
):
    result, labelled, _ = request_review(status=status, runs=[review_run()])
    assert not labelled
    assert "couldn't read SDLC_AUTO_MERGE, but a review run already started" in result.stdout
    result, labelled, _ = request_review(status=status)
    assert labelled
    assert result.stdout == (
        "Added the review label: couldn't read SDLC_AUTO_MERGE, and no review run had started "
        "on abc1234.\n"
    )


def test_request_review_reads_an_unset_variable_as_off(request_review):
    # A 404 means the variable isn't set (auto-merge.sh --setting); not an unreadable one.
    result, labelled, _ = request_review(status=404)
    assert labelled and "auto-merge is off" in result.stdout


def test_request_review_waits_for_github_to_show_the_push(request_review):
    result, labelled, calls = request_review(heads=("0ld0000", "0ld0000", PUSHED))
    assert labelled, result.stdout
    assert calls.count("api repos/o/r/pulls/7 ") == 3


def test_request_review_never_labels_the_old_head(request_review):
    result, labelled, _ = request_review(heads=("0ld0000",))
    assert result.returncode == 0 and not labelled
    assert result.stdout.startswith("Not adding the review label (auto-merge is off, ")
    assert "still 0ld0000, not the pushed abc1234" in result.stdout


def test_request_review_leaves_a_label_that_is_already_on(request_review):
    result, labelled, _ = request_review(labels=["bug", "review"])
    assert not labelled and "already on" in result.stdout


def test_request_review_says_when_it_couldnt_add_the_label(request_review):
    result, labelled, _ = request_review(label_fails=True)
    assert result.returncode == 0
    assert result.stdout.startswith("Couldn't add the review label")


def test_request_review_usage():
    assert run(["bash", ".sdlc/scripts/request-review.sh"]).returncode == 2
    assert run(["bash", ".sdlc/scripts/request-review.sh", "7", "not-a-sha"]).returncode == 2


def test_skills_ask_for_a_review_through_request_review():
    for path in (
        ".sdlc/skills/review-findings/SKILL.md",
        ".sdlc/skills/po-review/SKILL.md",
        ".sdlc/skills/build/SKILL.md",
    ):
        text = (REPO / path).read_text()
        assert ".sdlc/scripts/request-review.sh <N>" in text, path
        assert 'labels[]=review"' not in text, f"{path} adds the label directly"
    assert synced(".sdlc/scripts/request-review.sh")


def test_request_review_expands_the_checkouts_head_for_the_runs_api(request_review):
    full = git(REPO, "rev-parse", "HEAD")
    for sha in (None, full[:7]):  # no sha means the checkout's HEAD; a short one is expanded
        _, _, calls = request_review(variable="merge", runs=[review_run()], sha=sha)
        assert f"actions/runs?head_sha={full}&" in calls


def test_baseline_gitignore_keeps_the_build_skill_while_ignoring_build_output(tmp_path):
    # #103: a bare `build/` also matched .claude/skills/build/, so a file a sync added there
    # was ignored and the sync PR silently left it out. Since #133 the framework's own
    # .gitignore files carry the exception, so the project's root file never changes for it.
    # Since #23 the stub's folder is sdlc-build, so only .sdlc/ needs one.
    repo = init_repo(tmp_path / "r")
    shutil.copy(REPO / ".sdlc" / "templates" / "gitignore", repo / ".gitignore")
    nested = ".sdlc/.gitignore"
    (repo / nested).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / nested, repo / nested)
    paths = [
        ".claude/skills/sdlc-build/new.md",
        ".sdlc/skills/build/SKILL.md",
        "build/out.js",
        "app/build/out.js",
        ".sdlc/src/sdlc/__pycache__/x.pyc",
    ]
    for path in paths:
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text("x\n")
    ignored = run(["git", "check-ignore", *paths], cwd=repo).stdout.split()
    assert ignored == ["build/out.js", "app/build/out.js", ".sdlc/src/sdlc/__pycache__/x.pyc"]


def test_the_build_skill_stays_tracked_under_a_projects_own_build_rule(tmp_path):
    repo = init_repo(tmp_path / "r")
    (repo / ".gitignore").write_text("build/\n")  # the project's file, nothing of ours in it
    nested = ".sdlc/.gitignore"
    (repo / nested).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / nested, repo / nested)
    # The stub's folder is sdlc-build since #23, which a `build/` rule doesn't match.
    for skill in (".claude/skills/sdlc-build/SKILL.md", ".sdlc/skills/build/SKILL.md"):
        (repo / skill).parent.mkdir(parents=True, exist_ok=True)
        (repo / skill).write_text("x\n")
        assert run(["git", "check-ignore", skill], cwd=repo).returncode == 1, skill
    assert "skills/build" not in (REPO / ".sdlc/templates/gitignore").read_text()


def test_v0_9_1_upgrade_steps_name_commands_that_exist():
    notes = (REPO / "docs/release-notes/v0.9.1.md").read_text()
    assert notes.startswith("## Upgrade steps")  # the section /sdlc carries out
    bootstrap = (REPO / ".sdlc/scripts/bootstrap-github.sh").read_text()
    assert (
        "scripts/bootstrap-github.sh --gitignore-only" in notes and "--gitignore-only)" in bootstrap
    )
    identity = (REPO / ".sdlc/scripts/agent-identity.sh").read_text()
    for sub in ("create", "check"):
        assert f"scripts/agent-identity.sh {sub}" in notes and f"  {sub})" in identity
    assert "!.claude/skills/build/" in notes  # since #23 not needed: the stub is sdlc-build/


# --- THE RULE for SDLC_AUTO_MERGE, in every place that reads it (#101) ----------------------

AUTO_MERGE_VALUES = [
    ("", False),
    ("off", False),
    ("OFF", False),
    ("Off", False),
    ("merge", True),
    ("Squash", True),
]


def workflow_reviews_pushes(value: str) -> bool:
    """sdlc-claude-review.yml's push gate, evaluated as GitHub does: `!=` on strings ignores
    case."""
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    assert "(vars.SDLC_AUTO_MERGE != '' && vars.SDLC_AUTO_MERGE != 'off')" in workflow
    return value.lower() != "" and value.lower() != "off"


@pytest.mark.parametrize(("value", "on"), AUTO_MERGE_VALUES)
def test_every_reader_of_sdlc_auto_merge_follows_the_same_rule(request_review, value, on):
    method = run(
        ["bash", ".sdlc/scripts/auto-merge.sh", "--method"], env={"SDLC_AUTO_MERGE": value}
    )
    assert method.returncode == 0
    assert method.stdout == (value.lower() if on else "")

    # (bootstrap's reading of the rule is tested end to end below: it deletes a leftover
    # SDLC_AUTO_MERGE_CONFIRMED only when auto-merge is off)

    # request-review: with the push's review running, it labels only when auto-merge is off.
    _, labelled, _ = request_review(variable=value, runs=[review_run()])
    assert labelled == (not on)

    assert workflow_reviews_pushes(value) == on


def test_auto_merge_method_fails_when_the_variable_cant_be_read(auto_merge):
    state, _ = auto_merge
    (state / "vars-forbidden").write_text("")
    result = run(
        ["bash", str(REPO / ".sdlc/scripts/auto-merge.sh"), "--method"],
        env={
            "PATH": f"{state.parent / 'fakebin'}:{os.environ['PATH']}",
            "D": str(state),
            "GITHUB_REPOSITORY": "o/r",
        },
    )
    assert result.returncode == 1 and result.stdout == ""


def test_auto_merge_reads_every_page_of_organization_variables(auto_merge):
    # #101 finding 5: past the first 30 an org variable read as unset.
    _, go = auto_merge
    _, _, calls = go()
    org = [c for c in calls.splitlines() if "organization-variables" in c]
    assert org and all("--paginate" in c for c in org)


def _rulesets_only(state, dismiss):
    (state / "protection.json").unlink(missing_ok=True)
    (state / "no-classic-protection").write_text("")
    (state / "branch.json").write_text(json.dumps({"protection": {}}))
    rule = {"type": "pull_request", "parameters": {"dismiss_stale_reviews_on_push": dismiss}}
    checks = {
        "type": "required_status_checks",
        "parameters": {"required_status_checks": [{"context": "claude-review"}]},
    }
    (state / "rules.json").write_text(json.dumps([rule, checks]))


def test_auto_merge_ignores_a_stale_confirmation_on_a_rulesets_only_branch(auto_merge):
    # #101 finding 6: "Branch not protected" (404) means rulesets only, so a CONFIRMED=true left
    # from a classic setup mustn't stand in for a ruleset that doesn't dismiss stale approvals.
    state, go = auto_merge
    _rulesets_only(state, dismiss=False)
    result, mutated, _ = go(SDLC_AUTO_MERGE="merge", SDLC_AUTO_MERGE_CONFIRMED="true")
    assert not mutated
    assert "doesn't dismiss stale approvals on push" in result.stderr
    _rulesets_only(state, dismiss=True)
    _, mutated, _ = go(SDLC_AUTO_MERGE="merge", SDLC_AUTO_MERGE_CONFIRMED="")
    assert mutated, "the rulesets alone decide"


def test_auto_merge_still_trusts_the_confirmation_when_protection_cant_be_read(auto_merge):
    state, go = auto_merge
    (state / "protection.json").unlink()  # 403: a token without Administration: read
    _, mutated, _ = go(SDLC_AUTO_MERGE="merge", SDLC_AUTO_MERGE_CONFIRMED="true")
    assert mutated


FAKE_GH_BOOTSTRAP = r"""#!/usr/bin/env bash
# Enough of GitHub for a whole bootstrap run: logs each call, keeps the protection it's sent.
echo "$*" >> "$D/calls"
case "$*" in
  *actions/variables/SDLC_AUTO_MERGE_CONFIRMED*) echo "${FAKE_CONFIRMED-true}" ;;
  *actions/variables/SDLC_AUTO_MERGE*) echo "gh: Not Found (HTTP 404)" >&2; exit 1 ;;
  *organization-variables*) echo "gh: Validation Failed (HTTP 422)" >&2; exit 1 ;;
  "variable delete"*|"variable set"*) exit 0 ;;
  "api -X PUT repos/o/r/branches/main/protection"*) cat > "$D/put.json" ;;
  *branches/main/protection*) cat "$D/protection.json" ;;
  *) echo '{}' ;;
esac
"""


@pytest.fixture
def bootstrap_run(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_BOOTSTRAP)
    (fake / "gh").chmod(0o755)
    repo = init_repo(tmp_path / "repo")
    protection = {"required_status_checks": {"contexts": ["check", "pr-title", "review"]}}
    (tmp_path / "protection.json").write_text(json.dumps(protection))

    def go(*args, **env):
        (tmp_path / "calls").unlink(missing_ok=True)
        result = run(
            [
                "bash",
                str(REPO / ".sdlc/scripts/bootstrap-github.sh"),
                "--repo",
                "o/r",
                "--mode",
                "team",
                "--skip-token",
                *args,
            ],
            cwd=repo,
            env={"PATH": f"{fake}:{os.environ['PATH']}", "D": str(tmp_path), **env},
            input="",
        )
        out = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout + result.stderr)
        put = tmp_path / "put.json"
        sent = json.loads(put.read_text()) if put.exists() else None
        put.unlink(missing_ok=True)
        return result, out, (tmp_path / "calls").read_text(), sent

    return go


def test_bootstrap_with_auto_merge_off_drops_review_and_the_stale_confirmation(bootstrap_run):
    # #101 findings 2 and 6: `review` can't pass without push reviews, and a CONFIRMED=true left
    # from when auto-merge was on would be trusted if it's turned on again.
    result, out, calls, sent = bootstrap_run()
    assert result.returncode == 0, out
    assert sent["required_status_checks"]["contexts"] == ["check", "claude-review", "pr-title"]
    assert "the old review check is no longer required" in out
    assert "variable delete SDLC_AUTO_MERGE_CONFIRMED -R o/r" in calls
    assert "deleted SDLC_AUTO_MERGE_CONFIRMED (auto-merge is off)" in out


def test_bootstrap_with_auto_merge_off_leaves_no_confirmation_alone(bootstrap_run):
    _, out, calls, _ = bootstrap_run(FAKE_CONFIRMED="")
    assert "variable delete" not in calls and "SDLC_AUTO_MERGE_CONFIRMED" not in out


def test_bootstrap_dry_run_says_it_would_delete_the_confirmation(bootstrap_run):
    _, out, calls, sent = bootstrap_run("--dry-run")
    assert "would delete SDLC_AUTO_MERGE_CONFIRMED (auto-merge is off)" in out
    assert "variable delete" not in calls and sent is None


@pytest.mark.parametrize("value", ["merge", "off"])
def test_bootstrap_requires_claude_review_and_drops_the_old_gate(bootstrap_run, value):
    _, out, calls, sent = bootstrap_run("--auto-merge", value)
    on = value != "off"
    assert "claude-review" in sent["required_status_checks"]["contexts"], "whatever auto-merge"
    assert "review" not in sent["required_status_checks"]["contexts"], "the old gate is dropped"
    if not on:  # (when on, it's deleted only if main doesn't qualify, as before)
        assert "deleted SDLC_AUTO_MERGE_CONFIRMED (auto-merge is off)" in out


def test_bootstrap_keeps_the_claude_review_status_when_auto_merge_is_off(bootstrap_run, tmp_path):
    # #46 reversed #101's "drop it when off": unreviewed pushes are now marked, not left Expected.
    (tmp_path / "protection.json").write_text(
        json.dumps({"required_status_checks": {"contexts": ["check", "pr-title", "claude-review"]}})
    )
    _, out, _, sent = bootstrap_run()
    assert sent["required_status_checks"]["contexts"] == ["check", "claude-review", "pr-title"]
    assert "no longer required (auto-merge is off" not in out


def test_auto_merge_refuses_the_old_review_check_as_the_gate(auto_merge):
    # #101 finding 4: a job skipped by another label satisfies the job's own `review` check.
    state, go = auto_merge
    (state / "branch.json").write_text(
        json.dumps({"protection": {"required_status_checks": {"contexts": ["check", "review"]}}})
    )
    result, mutated, _ = go(SDLC_AUTO_MERGE="merge")
    assert not mutated
    assert "requires the old 'review' check, which a skipped review job satisfies" in result.stderr


def test_auto_merge_never_merges_a_pr_that_changes_a_claude_workflow(auto_merge):
    # The AI review can't run on such a PR (#14), so a person merges it.
    state, go = auto_merge
    # The names since #23, and the ones before it, which a PR renaming them deletes.
    for workflow in ("sdlc-claude-review.yml", "sdlc-claude-mention.yml", "claude-review.yml"):
        files = [{"filename": "README.md"}, {"filename": f".github/workflows/{workflow}"}]
        (state / "pr-files.json").write_text(json.dumps(files))
        result, mutated, calls = go(SDLC_AUTO_MERGE="merge")
        assert not mutated and "sdlc-claude-*.yml" in result.stderr, workflow
        assert "pulls/7/files --paginate" in calls
    (state / "pr-files.json").write_text(json.dumps([{"filename": "README.md"}]))
    _, mutated, _ = go(SDLC_AUTO_MERGE="merge")
    assert mutated


def test_review_posts_its_own_claude_review_status():
    # #101 finding 4: a skipped job posts no status, so it can't satisfy the required gate.
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    assert "\n  statuses: write\n" in workflow
    steps = workflow.split("\n      - ")
    names = [s.split("\n", 1)[0] for s in steps]
    action = next(i for i, n in enumerate(names) if "claude-code-action" in n)
    running = next(i for i, n in enumerate(names) if "Mark the review as running" in n)
    done = next(i for i, n in enumerate(names) if "Mark the review as done" in n)
    failed = next(i for i, n in enumerate(names) if "Mark the review as failed" in n)
    assert running < action < done < failed
    for i, state, when in (
        (running, "pending", None),
        (done, "success", "success()"),
        (failed, "failure", "failure()"),
    ):
        assert f"-f state={state}" in steps[i] and "-f context=claude-review" in steps[i]
        assert "statuses/$HEAD_SHA" in steps[i]
        if when:
            assert f"if: {when}" in steps[i]
    assert "HEAD_SHA: ${{ github.event.pull_request.head.sha }}" in workflow
    assert "No AI review: the PR changes an sdlc-claude-*.yml workflow" in steps[done]


def test_review_notes_a_workflow_change_on_the_push_that_makes_it():
    # #101 finding 3: the note was posted only when the PR opened.
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    note = workflow[workflow.index("- name: Note when the AI review can't run") :]
    note = note[: note.index("\n      - ", 1)]
    assert "if: github.event.action == 'opened'" not in note, "runs on every event"
    assert 'git diff --name-only "$BEFORE" HEAD' in note and "synchronize)" in note
    assert 'echo "skipped=true" >> "$GITHUB_OUTPUT"' in note


def test_v0_10_0_upgrade_steps_match_the_scripts():
    notes = (REPO / "docs/release-notes/v0.10.0.md").read_text()
    assert "## Upgrade steps" in notes
    bootstrap = (REPO / ".sdlc/scripts/bootstrap-github.sh").read_text()
    for quoted in (
        "'check', 'pr-title' and 'claude-review'",
        "the old review check is no longer required",
    ):
        assert quoted in notes and quoted in bootstrap, quoted
    assert "scripts/request-review.sh <N>" in notes and "unreviewed-push" in notes
    assert '"${1:-}" == --method' in (REPO / ".sdlc/scripts/auto-merge.sh").read_text()
    assert "your own scripts that aren't executable in git" in notes


# --- a stale review blocks the merge (#46) --------------------------------------------------

FAKE_GH_REVIEW_CURRENT = r"""#!/usr/bin/env bash
# PR #7's commits from $D/commits (oldest first), each commit's statuses from $D/status-<sha>.
echo "$*" >> "$D/calls"
args=("$@") jqf=""
for ((i = 0; i < ${#args[@]}; i++)); do [[ "${args[i]}" == --jq ]] && jqf="${args[i+1]}"; done
case "$2" in
  repos/o/r/pulls/7/commits)
    jq -Rn '[inputs | {sha: .}]' < "$D/commits" | jq -r "$jqf" ;;
  repos/o/r/commits/*/statuses)
    sha="${2#repos/o/r/commits/}"; sha="${sha%/statuses}"
    f="$D/status-$sha"; [[ -f "$f" ]] || echo '[]' > "$f"
    jq -r "$jqf" < "$f" ;;
  repos/o/r/statuses/*)
    [[ -f "$D/post-fails" ]] && exit 1
    printf '%s\n' "$*" > "$D/posted" ;;
  *) exit 1 ;;
esac
"""


def sha(n: int) -> str:
    return f"{n:040x}"


@pytest.fixture
def review_current(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_REVIEW_CURRENT)
    (fake / "gh").chmod(0o755)

    def go(commits, statuses, post_fails=False):
        for f in tmp_path.glob("status-*"):
            f.unlink()
        for name in ("posted", "post-fails", "calls"):
            (tmp_path / name).unlink(missing_ok=True)
        (tmp_path / "commits").write_text("".join(f"{sha(c)}\n" for c in commits))
        for c, states in statuses.items():
            entries = [{"context": ctx, "state": st} for ctx, st in states]
            (tmp_path / f"status-{sha(c)}").write_text(json.dumps(entries))
        if post_fails:
            (tmp_path / "post-fails").write_text("")
        result = run(
            ["bash", str(REPO / ".sdlc/scripts/review-current.sh"), "7", sha(commits[-1])],
            env={
                "PATH": f"{fake}:{os.environ['PATH']}",
                "D": str(tmp_path),
                "GITHUB_REPOSITORY": "o/r",
            },
        )
        posted = tmp_path / "posted"
        return result, posted.read_text() if posted.exists() else None

    return go


def test_review_current_marks_commits_after_the_review_as_not_reviewed(review_current):
    # jobhunt-app#7: requirements pushed after the review merged unreviewed.
    result, posted = review_current([1, 2, 3, 4], {2: [("claude-review", "success")]})
    assert result.returncode == 0, result.stderr
    assert f"repos/o/r/statuses/{sha(4)}" in posted
    assert "-f state=failure" in posted and "-f context=claude-review" in posted
    assert "Not reviewed: 2 commits since the review of 0000000. Add the review label" in posted


def test_review_current_counts_one_commit_without_a_plural(review_current):
    _, posted = review_current([1, 2], {1: [("claude-review", "success")]})
    assert "Not reviewed: 1 commit since the review of" in posted


def test_review_current_uses_the_newest_review_status_of_each_commit(review_current):
    # Statuses come newest first: a later failure on a commit replaces an earlier success.
    _, posted = review_current(
        [1, 2, 3],
        {
            1: [("claude-review", "success")],
            2: [("claude-review", "failure"), ("claude-review", "success")],
        },
    )
    assert "2 commits since the review of" in posted


def test_review_current_says_when_nothing_was_reviewed(review_current):
    _, posted = review_current([1, 2], {1: [("check", "success")]})
    assert "Not reviewed yet: add the review label" in posted


@pytest.mark.parametrize("state", ["pending", "success", "failure"])
def test_review_current_leaves_a_commit_that_has_a_review_status(review_current, state):
    # A review running on the push (auto-merge on, or the label added already) owns it.
    result, posted = review_current([1, 2], {2: [("claude-review", state)]})
    assert result.returncode == 0 and posted is None
    assert "already has a claude-review status" in result.stdout


def test_review_current_fails_when_it_cant_post(review_current):
    result, _ = review_current([1, 2], {}, post_fails=True)
    assert result.returncode == 1 and "can't post" in result.stderr


def test_review_current_usage():
    assert run(["bash", ".sdlc/scripts/review-current.sh", "7"]).returncode == 2
    assert run(["bash", ".sdlc/scripts/review-current.sh", "x", sha(1)]).returncode == 2


def test_unreviewed_pushes_are_marked_when_the_review_doesnt_run():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    job = workflow[workflow.index("\n  unreviewed-push:") :]
    # The exact complement of the review job's push condition: off means the review skips it.
    assert "github.event.action == 'synchronize'" in job
    assert "(vars.SDLC_AUTO_MERGE == '' || vars.SDLC_AUTO_MERGE == 'off')" in job
    assert "github.event.pull_request.head.repo.full_name == github.repository" in job
    assert '.sdlc/scripts/review-current.sh "$PR" "$HEAD_SHA"' in job
    assert "claude-code-action" not in job and "secrets." not in job, "no model, no secrets"
    for script in ("review-current.sh", "check-pr-title.sh"):
        assert synced(f".sdlc/scripts/{script}"), script


# --- the PR title says which gate artifact it changes (#46) ----------------------------------


@pytest.mark.parametrize(
    ("title", "files", "ok"),
    [
        ("spec(0007): add R33", ["changes/0007-x/spec.md"], True),
        ("docs(0007): add sketches", ["changes/0007-x/spec.md", "changes/0007-x/s.png"], False),
        ("feat(0007): build it", ["changes/0007-x/plan.md", "src/a.py"], False),
        ("plan(0007): amend", ["changes/0007-x/spec.md", "changes/0007-x/plan.md"], True),
        ("spec(0007): amend", ["changes/0007-x/spec.md", "changes/0007-x/plan.md"], True),
        ("intent: new idea", ["changes/0009-y/intent.md"], True),
        ("bug(0010): export hangs", ["changes/0010-z/bug.md"], True),
        ("feat(0007): build it", ["changes/0007-x/build.md", "src/a.py"], True),  # not a gate
        ("docs: readme", ["readme.md", "docs/changes/spec.md"], True),  # not a change folder
        ("chore: sync", [], True),
        ("Update spec", ["changes/0007-x/spec.md"], False),  # not conventional at all
    ],
)
def test_pr_title_type_matches_the_gate_artifacts_it_changes(title, files, ok):
    result = run(
        ["bash", ".sdlc/scripts/check-pr-title.sh", title], input="".join(f"{f}\n" for f in files)
    )
    assert (result.returncode == 0) == ok, result.stdout
    assert ("::error::" in result.stdout) == (not ok)


def test_pr_title_error_names_the_types_to_use():
    result = run(
        ["bash", ".sdlc/scripts/check-pr-title.sh", "docs: tidy"],
        input="changes/0007-x/spec.md\nchanges/0007-x/plan.md\n",
    )
    assert (
        "gate artifact (plan.md, spec.md)" in result.stdout and "use plan or spec" in result.stdout
    )


def test_project_review_rules_live_outside_review_md():
    # spellbound3d added a pass to .sdlc/REVIEW.md, which then clashed with every framework update.
    review = (REPO / ".sdlc/REVIEW.md").read_text()
    passes = re.findall(r"^(\d)\. \*\*([^*]+):\*\*", review, re.M)
    assert [n for n, _ in passes] == ["1", "2", "3", "4", "5", "6"]
    assert passes[-1][1] == "Project rules", "last, so the earlier passes keep their numbers"
    assert "`docs/review-rules.md`" in review and "the sync never touches it" in review
    sync = (REPO / ".sdlc/scripts/sync-sdlc.sh").read_text()
    assert "review-rules" not in sync, "the project's file is never synced"
    assert synced(".sdlc/templates/review-rules.md"), (
        "the starting point arrives with the templates"
    )
    template = (REPO / ".sdlc/templates/review-rules.md").read_text()
    assert "Copy this file to docs/review-rules.md" in template


def test_the_roadmap_is_the_projects_and_its_format_is_synced():
    # #81: the framework ships the format and the templates; docs/roadmap.md is the project's.
    sync = (REPO / ".sdlc/scripts/sync-sdlc.sh").read_text()
    assert synced(".sdlc/docs/roadmap-format.md")
    assert '"docs/roadmap.md:' not in sync and "docs/roadmap/adjustments" not in sync
    for name in ("roadmap.md", "roadmap-adjustment.md"):
        assert "docs/roadmap" in (REPO / ".sdlc" / "templates" / name).read_text(), name
    intent = (REPO / ".sdlc/templates/intent.md").read_text()
    assert "Milestone: M<n>" in intent and "Adjustment: NNNN-<slug>" in intent
    # Only in a comment: a repo with no roadmap gets no Milestone: line in its intents.
    assert "\nMilestone:" not in re.sub(r"<!--.*?-->", "", intent, flags=re.S)


def test_next_and_the_upgrade_steps_know_the_roadmap():
    # #81: /sdlc-next reads the roadmap from main; v0.10.0's upgrade covers both consumers' shapes.
    nxt = (REPO / ".sdlc/skills/next/SKILL.md").read_text()
    assert "git show origin/main:docs/roadmap.md" in nxt
    assert "Never reorder the roadmap" in nxt
    steps = (REPO / "docs/release-notes/v0.10.0.md").read_text().split("## Upgrade steps", 1)[1]
    for case in ("own roadmap check already", "in another shape", "No roadmap"):
        assert case in steps, case
    assert re.findall(r"^(\d)\. ", steps, re.M) == ["1", "2", "3", "4", "5", "6", "7"]


# A gh that serves $FAKE_COMMENTS for the comments call, applying --jq with the real jq.
FAKE_GH_COMMENTS = r"""#!/usr/bin/env bash
[[ "$1" == api ]] || exit 1
echo "$2" >> "$FAKE_CALLS"
[[ -e "$FAKE_COMMENTS" ]] || { echo "gh: HTTP 502" >&2; exit 1; }
jqx=.
while (($#)); do [[ "$1" == --jq ]] && jqx="$2"; shift; done
jq -r "$jqx" "$FAKE_COMMENTS"
"""

SINCE = "2026-11-12T09:00:00Z"


@pytest.fixture
def review_posted(tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_COMMENTS)
    (fake / "gh").chmod(0o755)
    comments = tmp_path / "comments.json"

    def go(found, *args, bot=None):
        if found is None:
            comments.unlink(missing_ok=True)
        else:
            comments.write_text(json.dumps(found))
        env = {
            "PATH": f"{fake}:{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "o/r",
            "FAKE_COMMENTS": str(comments),
            "FAKE_CALLS": str(tmp_path / "calls"),
        }
        if bot:
            env["REVIEW_BOT"] = bot
        return run(
            ["bash", str(REPO / ".sdlc/scripts/review-posted.sh"), *(args or ("7", SINCE))], env=env
        )

    return go


def comment(login="claude[bot]", updated="2026-11-12T09:00:30Z", url="https://x/c/1"):
    return {"user": {"login": login}, "updated_at": updated, "html_url": url}


def test_review_posted_finds_a_summary_posted_or_edited_during_the_job(review_posted, tmp_path):
    result = review_posted([comment(updated="2026-11-12T08:00:00Z", url="old"), comment()])
    assert result.returncode == 0 and "https://x/c/1" in result.stdout
    assert f"repos/o/r/issues/7/comments?since={SINCE}" in (tmp_path / "calls").read_text()
    assert review_posted([comment(updated=SINCE)]).returncode == 0, "at the start counts"


@pytest.mark.parametrize(
    "found",
    [
        [],
        [comment(updated="2026-11-12T08:59:59Z")],  # an older summary, not edited this time
        [comment(login="github-actions[bot]")],  # the "AI review skipped" note
        [comment(login="someone")],
    ],
)
def test_review_posted_fails_with_no_new_summary_from_the_reviewer(review_posted, found):
    # PR #129: the action ended green after refused tool calls, having posted nothing.
    result = review_posted(found)
    assert result.returncode == 1 and "posted no comment on PR #7" in result.stderr


def test_review_posted_reads_another_reviewer_login(review_posted):
    assert (
        review_posted([comment(login="my-reviewer[bot]")], bot="my-reviewer[bot]").returncode == 0
    )


def test_review_posted_fails_when_it_cannot_read_or_is_misused(review_posted):
    assert review_posted(None).returncode == 3
    assert review_posted([], "7", "yesterday").returncode == 2
    assert review_posted([], "x", SINCE).returncode == 2


def test_the_gate_needs_the_summary_not_just_a_green_action():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    steps = workflow.split("\n      - ")
    step = {s.split("\n", 1)[0].removeprefix("name: "): s for s in steps}
    assert "id: start" in step["Mark the review as running"]
    assert 'echo "since=$since" >> "$GITHUB_OUTPUT"' in step["Mark the review as running"]
    done = step["Mark the review as done"]
    assert "SINCE: ${{ steps.start.outputs.since }}" in done
    assert '.sdlc/scripts/review-posted.sh "$PR" "$SINCE"' in done
    # Skipped (an sdlc-claude-*.yml change) is checked first: the action posts nothing then.
    assert done.index('"$SKIPPED" == true') < done.index("review-posted.sh")
    assert "-f state=failure" in done and "posted no summary" in done
    failed = step["Mark the review as failed"]
    assert "if: failure() && steps.done.outputs.reported != 'true'" in failed
    assert synced(".sdlc/scripts/review-posted.sh")


# A gh serving the PR's comments and its review threads (GraphQL), applying --jq with real jq.
FAKE_GH_FINDINGS = r"""#!/usr/bin/env bash
[[ "$1" == api ]] || exit 1
echo "$*" >> "$FAKE_CALLS"
case "$2" in
  graphql) file="$FAKE_THREADS" ;;
  repos/o/r/issues/7/comments) file="$FAKE_COMMENTS" ;;
  *) echo "unexpected: $2" >&2; exit 1 ;;
esac
[[ -e "$file" ]] || { echo "gh: HTTP 502" >&2; exit 1; }
jqx=.
while (($#)); do [[ "$1" == --jq ]] && jqx="$2"; shift; done
jq -r "$jqx" "$file"
"""

# spellbound3d#124's summary (shortened): three Important findings, and no thread for any (#130).
SB124_SUMMARY = (
    "## Review of PR #124\n\n**Findings: 3 Important, 0 Nit.** There were no earlier findings.\n"
    "1. Important: no change folder.\n2. Important: no acceptance criteria.\n"
    "3. Important: the unapproved descopes above.\n"
)


def summary(important=None, nit=0, text="## Review\n"):
    if important is None:
        return text
    return f"{text}\n<!-- review-findings: important={important} nit={nit} -->\n"


def thread(body="**Important:** x", login="claude", resolved=False):
    return {
        "isResolved": resolved,
        "comments": {"nodes": [{"author": {"login": login}, "body": body}]},
    }


@pytest.fixture
def review_findings(tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_FINDINGS)
    (fake / "gh").chmod(0o755)
    comments, threads = tmp_path / "comments.json", tmp_path / "threads.json"

    def go(bodies, found=(), logins=None, read_threads=True):
        logins = logins or ["claude[bot]"] * len(bodies)
        comments.write_text(
            json.dumps(
                [{"user": {"login": u}, "body": b} for u, b in zip(logins, bodies, strict=True)]
            )
        )
        if read_threads:
            page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": list(found)}
            data = {"data": {"repository": {"pullRequest": {"reviewThreads": page}}}}
            threads.write_text(json.dumps(data))
        else:
            threads.unlink(missing_ok=True)
        env = {
            "PATH": f"{fake}:{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "o/r",
            "FAKE_COMMENTS": str(comments),
            "FAKE_THREADS": str(threads),
            "FAKE_CALLS": str(tmp_path / "calls"),
        }
        return run(["bash", str(REPO / ".sdlc/scripts/review-findings.sh"), "7"], env=env)

    return go


def test_review_findings_fails_spellbound3d_124(review_findings):
    # No count line: it fails closed.
    result = review_findings([SB124_SUMMARY])
    assert result.returncode == 1 and "no findings count line" in result.stdout
    # With the count line, three findings against no threads.
    result = review_findings([summary(3, text=SB124_SUMMARY)])
    assert result.returncode == 1
    assert "lists 3 Important finding(s) but 0 open Important thread(s)" in result.stdout
    assert len(result.stdout.strip()) <= 140, "fits a commit status description"


def test_review_findings_passes_when_each_finding_has_an_open_thread(review_findings, tmp_path):
    found = [
        thread("**Important:** no change folder."),
        thread("**Important (product owner decides):** no criteria.", login="claude[bot]"),
        thread("**Important:** fixed earlier.", resolved=True),  # resolved: not counted
        thread("**Nit:** naming."),  # nits never count
        thread("**Important:** a person's own note.", login="kieron"),  # not the reviewer's
    ]
    result = review_findings([summary(2)], found)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 open Important finding(s)" in result.stdout
    calls = (tmp_path / "calls").read_text()
    assert "graphql --paginate" in calls and "owner=o" in calls and "name=r" in calls


def test_review_findings_passes_a_clean_review(review_findings):
    assert review_findings([summary(0)]).returncode == 0


@pytest.mark.parametrize(
    "count, found",
    [
        (0, [thread()]),  # a thread the count leaves out
        (2, [thread()]),  # a finding with no thread
        (1, [thread(resolved=True)]),  # its thread was resolved, the finding still listed
    ],
)
def test_review_findings_fails_when_the_count_and_threads_differ(review_findings, count, found):
    assert review_findings([summary(count)], found).returncode == 1


def test_review_findings_reads_the_latest_summary_from_the_reviewer(review_findings):
    bodies = [summary(2), summary(0), summary(5)]
    logins = ["claude[bot]", "claude[bot]", "someone"]  # someone else's count line is ignored
    assert review_findings(bodies, logins=logins).returncode == 0


def test_review_findings_fails_when_it_cannot_read(review_findings):
    assert review_findings([summary(0)], read_threads=False).returncode == 3


def test_the_gate_checks_what_the_review_found():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    steps = workflow.split("\n      - ")
    step = {s.split("\n", 1)[0].removeprefix("name: "): s for s in steps}
    done = step["Mark the review as done"]
    # In order: the sdlc-claude-*.yml exception, then a summary, then a thread per finding.
    order = ['"$SKIPPED" == true', "review-posted.sh", '.sdlc/scripts/review-findings.sh "$PR"']
    assert [done.index(x) for x in order] == sorted(done.index(x) for x in order)
    assert done.count('echo "reported=true"') == 3 and done.count("exit 1") == 3
    action = next(s for s in steps if s.startswith("uses: anthropics/claude-code-action"))
    assert "classify_inline_comments: false" in action
    assert (
        "pulls/${{ github.event.pull_request.number }}/comments -f subject_type=file:*)" in action
    )
    assert "<!-- review-findings: important=<N> nit=<M> -->" in action
    review = (REPO / ".sdlc/REVIEW.md").read_text()
    assert "## Posting findings" in review
    assert "<!-- review-findings: important=<N> nit=<M> -->" in review
    assert "-f subject_type=file -f path=<file>" in review and "`**Important`" in review
    assert synced(".sdlc/scripts/review-findings.sh")


def test_v0_11_0_upgrade_steps_match_what_the_sync_prints():
    notes = (REPO / "docs/release-notes/v0.11.0.md").read_text()
    steps = notes.split("## Upgrade steps", 1)[1]
    sync = (REPO / ".sdlc/scripts/sync-sdlc.sh").read_text()
    for message in ("still use the old paths", "kept your local changes", "include .sdlc/sdlc.mk"):
        assert message in steps and message in sync, message
    assert "your security policy is the project's own" in sync
    assert ".sdlc-local/skills/security-policy/SKILL.md" in steps
    assert (REPO / ".sdlc/docs/overrides.md").is_file() and ".sdlc/docs/overrides.md" in notes
    assert re.findall(r"^(\d)\. ", steps, re.M) == [str(n) for n in range(1, 9)]


# --- install-claude: Claude Code per job, never globally (#136) --------------------------------

# Records its arguments and, like npm, puts `claude` in <prefix>/node_modules/.bin.
FAKE_NPM = """#!/usr/bin/env bash
echo "$*" >> "$NPM_LOG"
[[ -n "${NPM_NO_BIN:-}" ]] && exit 0
while [[ $# -gt 0 ]]; do [[ "$1" == --prefix ]] && prefix="$2"; shift; done
mkdir -p "$prefix/node_modules/.bin"
printf '#!/bin/sh\\necho job-local\\n' > "$prefix/node_modules/.bin/claude"
chmod +x "$prefix/node_modules/.bin/claude"
"""


@pytest.fixture
def runner(tmp_path):
    """A persistent self-hosted runner: its home already has the `claude` the action left."""
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "npm").write_text(FAKE_NPM)
    (fake / "npm").chmod(0o755)
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    (home / ".local/bin/claude").write_text("#!/bin/sh\necho stale\n")
    (home / ".local/bin/claude").chmod(0o755)
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    env = {
        "PATH": f"{fake}:{home / '.local/bin'}:{os.environ['PATH']}",
        "HOME": str(home),
        "RUNNER_TEMP": str(temp),
        "GITHUB_PATH": str(tmp_path / "github_path"),
        "NPM_LOG": str(tmp_path / "npm.log"),
    }
    return tmp_path, env


def install_claude(env):
    return run(["bash", str(REPO / ".sdlc/scripts/install-claude.sh")], env=env)


def test_install_claude_installs_into_the_job_temp_folder(runner):
    tmp_path, env = runner
    before = sorted(p.relative_to(tmp_path / "home") for p in (tmp_path / "home").rglob("*"))
    r = install_claude(env)
    assert r.returncode == 0, r.stderr
    bin_dir = tmp_path / "runner-temp/claude-code/node_modules/.bin"
    assert r.stdout == f"{bin_dir}\n"  # stdout is only the folder
    # Pinned, local to the job, and never global.
    args = (tmp_path / "npm.log").read_text().split()
    assert args[:3] == ["install", "--prefix", str(tmp_path / "runner-temp/claude-code")]
    assert re.fullmatch(r"@anthropic-ai/claude-code@\d+\.\d+\.\d+", args[-1])
    assert "-g" not in args and "--global" not in args
    # Later steps find the job's claude before the one in the runner's home, which is untouched.
    assert (tmp_path / "github_path").read_text() == f"{bin_dir}\n"
    found = run(["sh", "-c", "command -v claude"], env={**env, "PATH": f"{bin_dir}:{env['PATH']}"})
    assert found.stdout.strip() == str(bin_dir / "claude")
    after = sorted(p.relative_to(tmp_path / "home") for p in (tmp_path / "home").rglob("*"))
    assert after == before


def test_install_claude_takes_the_version_from_the_environment(runner):
    tmp_path, env = runner
    assert install_claude({**env, "CLAUDE_CODE_VERSION": "9.9.9"}).returncode == 0
    assert (tmp_path / "npm.log").read_text().split()[-1] == "@anthropic-ai/claude-code@9.9.9"


def test_install_claude_fails_when_npm_leaves_no_claude(runner):
    tmp_path, env = runner
    r = install_claude({**env, "NPM_NO_BIN": "1"})
    assert r.returncode == 1
    assert "no claude" in r.stderr
    assert r.stdout == ""
    assert not (tmp_path / "github_path").exists()


# A global install writes outside the job's workspace: on a persistent runner it leaks between
# jobs and repos, and collides with what the runner already has (#136).
GLOBAL_INSTALL = re.compile(
    r"\b(?:npm|pnpm|yarn|bun)\b[^\n]*\s(?:-g|--global|global)\b"
    r"|\bpip3?\s+install\b[^\n]*--user\b"
    r"|\bgo\s+install\b|\bcargo\s+install\b|\bgem\s+install\b"
)


@pytest.mark.parametrize(
    "path",
    sorted(
        str(p.relative_to(REPO))
        for p in [*REPO.glob(".github/workflows/*.yml"), *REPO.glob(".github/actions/*/action.yml")]
    ),
)
def test_no_workflow_installs_anything_globally(path):
    text = (REPO / path).read_text()
    assert not GLOBAL_INSTALL.search(text), GLOBAL_INSTALL.search(text).group(0)
    # Claude Code comes from install-claude.sh, which pins it and keeps it in the job.
    assert "@anthropic-ai/claude-code" not in text


@pytest.mark.parametrize(
    "line",
    [
        "npm install -g @anthropic-ai/claude-code",
        "npm i --global x",
        "pnpm add -g x",
        "yarn global add x",
        "bun add -g x",
        "pip install --user x",
        "cargo install x",
    ],
)
def test_the_global_install_check_catches(line):
    assert GLOBAL_INSTALL.search(f"      - run: {line}\n")


def test_workflows_that_run_claude_install_it_first():
    for name in ["sdlc-spec-from-intent", "sdlc-agent-evals", "release", "sdlc-claude-review"]:
        assert "install-claude.sh" in (REPO / f".github/workflows/{name}.yml").read_text(), name


# --- #138: a new push to a PR cancels its stale CI and title runs; main never cancels ----------


def concurrency(workflow):
    """The workflow-level concurrency block's group and cancel-in-progress expressions."""
    text = (REPO / ".github/workflows" / workflow).read_text()
    block = re.search(r"^concurrency:\n  group: (.+)\n  cancel-in-progress: (.+)$", text, re.M)
    assert block, f"{workflow} has no workflow-level concurrency block"
    strip = lambda s: s.removeprefix("${{").removesuffix("}}").strip()  # noqa: E731
    return block.group(1), strip(block.group(2))


def group(template, ctx):
    return re.sub(r"\$\{\{(.+?)\}\}", lambda m: str(gh_expr(m.group(1).strip(), ctx)), template)


PR_PUSH = {
    "github": {
        "event_name": "pull_request",
        "ref": "refs/pull/7/merge",
        "event": {"pull_request": {"number": 7}},
    }
}
MAIN_PUSH = {
    "github": {"event_name": "push", "ref": "refs/heads/main", "sha": "abc123", "event": {}}
}


def test_ci_cancels_a_prs_stale_run_but_never_one_on_main():
    group_expr, cancel = concurrency("sdlc-ci.yml")
    assert group(group_expr, PR_PUSH) == "ci-7"
    assert gh_expr(cancel, PR_PUSH) is True
    # Every commit on main gets its own result. A group keeps one pending run, and a newer one
    # replaces it even without cancel-in-progress, so each push to main has a group of its own.
    assert group(group_expr, MAIN_PUSH) == "ci-abc123"
    assert gh_expr(cancel, MAIN_PUSH) is False
    next_merge = {"github": {**MAIN_PUSH["github"], "sha": "def456"}}
    assert group(group_expr, next_merge) != group(group_expr, MAIN_PUSH)
    # Two PRs never share a group, so one PR's push can't cancel another's CI.
    other = {"github": {**PR_PUSH["github"], "event": {"pull_request": {"number": 8}}}}
    assert group(group_expr, other) != group(group_expr, PR_PUSH)


def test_pr_title_cancels_the_older_check_on_the_same_pr():
    group_expr, cancel = concurrency("sdlc-pr-title.yml")
    assert group(group_expr, PR_PUSH) == "pr-title-7"
    assert cancel == "true"
    on = (REPO / ".github/workflows/sdlc-pr-title.yml").read_text()
    assert "\n  push:" not in on  # only PR events, so cancelling never touches main


# --- make check skips the tests for a docs-only branch (#140) -------------------------------

DOCS_ONLY = REPO / "scripts/docs-only.sh"


@pytest.fixture
def docs_repo(tmp_path):
    """A repo whose `main` is the base, on a branch `work` to change."""
    repo = init_repo(tmp_path / "repo")
    commit(repo, "chore: start", {"readme.md": "x\n", "Makefile": "x\n"})
    git(repo, "switch", "-q", "-c", "work")
    return repo


def docs_only(repo, base="main"):
    return run(["bash", str(DOCS_ONLY), base], cwd=repo)


@pytest.mark.parametrize(
    "files",
    [
        ["readme.md"],
        ["CLAUDE.md", "docs/progress.md"],
        ["docs/assets/logo.svg", "readme.md"],
        ["docs/issue-priorities.md"],
    ],
    ids=str,
)
def test_docs_only_branch_is_recognised(docs_repo, files):
    commit(docs_repo, "docs: change", {f: "changed\n" for f in files})
    result = docs_only(docs_repo)
    assert result.returncode == 0, result.stdout
    assert f"only documentation changed since main ({len(files)} file" in result.stdout


@pytest.mark.parametrize(
    "path",
    [
        ".sdlc/skills/sdlc/SKILL.md",  # skills, templates, prompts and REVIEW.md are tested
        ".sdlc/REVIEW.md",
        ".claude/skills/sdlc-next/SKILL.md",
        ".github/pull_request_template.md",
        "changes/0001-x/spec.md",
        "tests/fixtures/consumer/readme.md",
        "evals/fixtures/a/spec.md",
        "docs/release-notes/v9.9.9.md",  # the release tests read them
        "Makefile",
        "scripts/docs-only.sh",
        "pyproject.toml",
    ],
)
def test_any_other_change_runs_the_tests(docs_repo, path):
    commit(docs_repo, "feat: change", {"readme.md": "changed\n", path: "changed\n"})
    result = docs_only(docs_repo)
    assert result.returncode == 1
    assert f"{path} changed" in result.stdout


def test_uncommitted_and_untracked_changes_count(docs_repo):
    # A local `make check` before committing sees the change CI will.
    (docs_repo / "readme.md").write_text("edited, not committed\n")
    assert docs_only(docs_repo).returncode == 0
    (docs_repo / "new.py").write_text("print()\n")
    result = docs_only(docs_repo)
    assert result.returncode == 1 and "new.py changed" in result.stdout
    (docs_repo / "new.py").unlink()
    (docs_repo / "Makefile").write_text("edited\n")
    assert docs_only(docs_repo).returncode == 1


def test_when_unsure_everything_runs(docs_repo):
    assert "nothing changed since main" in docs_only(docs_repo).stdout
    assert docs_only(docs_repo).returncode == 1
    commit(docs_repo, "docs: change", {"readme.md": "changed\n"})
    missing = docs_only(docs_repo, base="origin/main")  # no such ref
    assert missing.returncode == 1 and "can't find origin/main" in missing.stdout
    git(docs_repo, "switch", "-q", "--orphan", "unrelated")
    commit(docs_repo, "docs: unrelated history", {"readme.md": "y\n"})
    unrelated = docs_only(docs_repo)  # no merge base, as in a shallow clone
    assert unrelated.returncode == 1 and "no merge base with main" in unrelated.stdout


@pytest.fixture
def make_repo(docs_repo, tmp_path):
    """The framework's Makefile in a throwaway repo, with a `uv` that only says it ran."""
    for path in ("Makefile", ".sdlc/sdlc.mk", "scripts/docs-only.sh"):
        target = docs_repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / path, target)
    git(docs_repo, "add", "-A")
    git(docs_repo, "commit", "-q", "-m", "chore: the framework's Makefile")
    git(docs_repo, "branch", "-f", "main")  # the Makefile is on main: not part of the change
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "uv").write_text('#!/bin/sh\necho "uv $*"\n')
    (fake / "uv").chmod(0o755)
    env = {"PATH": f"{fake}:{os.environ['PATH']}", "FULL": ""}
    return docs_repo, env


def test_make_check_test_skips_the_suite_for_docs_only(make_repo):
    repo, env = make_repo
    commit(repo, "docs: change", {"readme.md": "changed\n"})
    result = run(["make", "check-test", "CHECK_BASE=main"], cwd=repo, env=env)
    assert result.returncode == 0, result.stderr
    assert "test: skipped, only documentation changed since main (1 file)" in result.stdout
    assert "(FULL=1 runs it)" in result.stdout
    assert "uv run pytest" not in result.stdout


def test_make_check_test_runs_the_suite_for_code_or_full(make_repo):
    repo, env = make_repo
    commit(repo, "docs: change", {"readme.md": "changed\n"})
    full = run(["make", "check-test", "CHECK_BASE=main", "FULL=1"], cwd=repo, env=env)
    assert "uv run pytest -q" in full.stdout and "skipped" not in full.stdout
    commit(repo, "feat: change", {"src.py": "x = 1\n"})
    code = run(["make", "check-test", "CHECK_BASE=main"], cwd=repo, env=env)
    assert "uv run pytest -q" in code.stdout and "skipped" not in code.stdout


def test_check_runs_the_tests_through_check_test_and_main_runs_them_all():
    makefile = (REPO / "Makefile").read_text()
    assert re.search(r"^check: lint check-test validate exec-bits$", makefile, re.MULTILINE)
    ci = (REPO / ".github/workflows/sdlc-ci.yml").read_text()
    assert "- run: make check ${{ github.event_name == 'push' && 'FULL=1' || '' }}" in ci
    assert "fetch-depth: 0" in ci
    release = (REPO / ".github/workflows/release.yml").read_text()
    assert "- run: make check FULL=1" in release


# --- CI: no code before the plan (#44) -------------------------------------------------------


@pytest.fixture
def plan_tree(tmp_path):
    """A PR checkout: change 0003-x with a spec, bug 0005-z with bug.md and spec.md."""
    for rel in ("changes/0003-x/spec.md", "changes/0005-z/bug.md", "changes/0005-z/spec.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x\n")
    return tmp_path


def plan_first(tree, branch, files):
    return run(
        ["bash", str(REPO / ".sdlc/scripts/check-plan-first.sh"), branch],
        cwd=tree,
        input="".join(f"{f}\n" for f in files),
    )


@pytest.mark.parametrize("branch", ["build/0003-x", "plan/0003-x", "fix/0003-x"])
def test_plan_first_fails_a_change_branch_with_code_and_no_plan(plan_tree, branch):
    result = plan_first(plan_tree, branch, ["changes/0003-x/build.md", "src/a.py"])
    assert result.returncode == 1
    assert "::error::This PR changes code (src/a.py, …) for 0003-x, which has no plan.md" in (
        result.stdout
    )
    assert "/sdlc-plan" in result.stdout


def test_plan_first_passes_once_the_plan_is_in_the_tree(plan_tree):
    (plan_tree / "changes/0003-x/plan.md").write_text("# plan\n")  # on the branch, or merged
    result = plan_first(plan_tree, "build/0003-x", ["src/a.py"])
    assert result.returncode == 0 and "has its plan.md" in result.stdout


@pytest.mark.parametrize(
    "files",
    [
        ["changes/0003-x/plan.md"],
        ["changes/0003-x/spec.md", "docs/roadmap.md", "readme.md"],
        [],
    ],
    ids=["plan PR", "docs", "nothing"],
)
def test_plan_first_passes_artifacts_and_docs(plan_tree, files):
    assert plan_first(plan_tree, "plan/0003-x", files).returncode == 0


def test_plan_first_counts_nested_markdown_as_code(plan_tree):
    assert plan_first(plan_tree, "build/0003-x", ["src/README.md"]).returncode == 1


def test_plan_first_allows_the_bug_fast_path_only_on_build(plan_tree):
    ok = plan_first(plan_tree, "build/0005-z", ["tests/test_z.py", "src/z.py"])
    assert ok.returncode == 0 and "fast path" in ok.stdout
    assert plan_first(plan_tree, "fix/0005-z", ["src/z.py"]).returncode == 1
    (plan_tree / "changes/0005-z/spec.md").unlink()
    assert plan_first(plan_tree, "build/0005-z", ["src/z.py"]).returncode == 1, "no spec yet"


@pytest.mark.parametrize("branch", ["chore/bump", "fix/flaky", "build/0009-gone", ""])
def test_plan_first_skips_branches_that_arent_a_change(plan_tree, branch):
    result = plan_first(plan_tree, branch, ["src/a.py"])
    assert result.returncode == 0 and "isn't a change's branch" in result.stdout


def test_the_pr_title_job_runs_the_plan_check():
    workflow = (REPO / ".github/workflows/sdlc-pr-title.yml").read_text()
    assert "HEAD_REF: ${{ github.event.pull_request.head.ref }}" in workflow
    assert '.sdlc/scripts/check-plan-first.sh "$HEAD_REF" < "$RUNNER_TEMP/files.txt"' in workflow


# --- a fast-path bug PR is titled fix(<slug>) (#154) -----------------------------------------

FAST = ["changes/0010-z/bug.md", "changes/0010-z/spec.md", "tests/test_z.py", "src/z.py"]


@pytest.mark.parametrize(
    ("title", "files", "ok"),
    [
        ("fix(0010-z): export no longer hangs", FAST, True),
        ("fix(0010-z): with its build plan", [*FAST, "changes/0010-z/build.md"], True),
        ("fix(0010-z): with a plan too", [*FAST, "changes/0010-z/plan.md"], True),
        ("bug(0010-z): export hangs", FAST, True),  # still allowed, just not the clear choice
        ("fix(0010-z): spec only", ["changes/0010-z/bug.md", "changes/0010-z/spec.md"], False),
        ("fix(0010-z): docs only", ["changes/0010-z/bug.md", "docs/a.md", "readme.md"], False),
        ("fix(0010-z): no report", ["changes/0010-z/spec.md", "src/z.py"], False),
        ("fix(0010-z): two changes", [*FAST, "changes/0011-w/spec.md"], False),
        ("fix(0010-z): an intent", [*FAST, "changes/0010-z/intent.md"], False),
        ("fix(0011-w): wrong scope", FAST, False),
        ("fix: no scope", FAST, False),
        ("feat(0007): intent and code", ["changes/0007-x/intent.md", "src/a.py"], False),
    ],
)
def test_pr_title_lets_a_fast_path_bug_be_a_fix(title, files, ok):
    result = run(
        ["bash", ".sdlc/scripts/check-pr-title.sh", title], input="".join(f"{f}\n" for f in files)
    )
    assert (result.returncode == 0) == ok, result.stdout


@pytest.mark.parametrize("title", ["feat(0010-z): fix it", "fix: no scope", "test(0010-z): x"])
def test_pr_title_suggests_fix_for_a_fast_path_pr(title):
    result = run(
        ["bash", ".sdlc/scripts/check-pr-title.sh", title], input="".join(f"{f}\n" for f in FAST)
    )
    assert result.returncode == 1
    assert "the bug fast path), so title it 'fix(0010-z): <summary>'" in result.stdout


def test_sdlc_pr_runs_both_walkthroughs_on_a_fast_path_pr():
    """#154: the product owner signs off the bug and spec, the engineer the code, in that order."""
    skill = (REPO / ".sdlc/skills/pr/SKILL.md").read_text()
    row = next(line for line in skill.splitlines() if line.startswith("| `fix(<slug>)`"))
    assert "`sdlc-po-review`, then `sdlc-review-findings`" in row
    assert skill.index(row) < skill.index("| anything else"), "matched before plain fix"
    assert "run the product owner's walkthrough first" in skill
    assert "still needs the product owner's approval on the bug and spec" in skill  # until #151


def test_review_rules_know_the_fast_path_and_never_exempt_a_scoped_fix():
    review = (REPO / ".sdlc/REVIEW.md").read_text()
    assert "**The bug fast path** (#148)" in review and "needs no `plan.md`" in review
    assert "a `test(<slug>): …` commit before the fix" in review
    assert "too big for one PR" in review
    assert "Until #151, GitHub doesn't require the product owner's approval" in review
    assert "a `fix(<slug>)` names a change and is never exempt" in review


# --- a descope waits for a person's decision (#132) ------------------------------------------

FAKE_GH_DESCOPES = r"""#!/usr/bin/env bash
[[ "$1" == api ]] || exit 1
echo "$*" >> "$FAKE_CALLS"
case "$2" in
  graphql) file="$FAKE_THREADS" ;;
  repos/o/r/issues/7/comments) file="$FAKE_COMMENTS" ;;
  repos/o/r/commits/abc1234/statuses) file="$FAKE_STATUSES" ;;
  repos/o/r/statuses/abc1234) echo "$*" >> "$FAKE_POSTED"; exit 0 ;;
  *) echo "unexpected: $2" >&2; exit 1 ;;
esac
[[ -e "$file" ]] || { echo "gh: HTTP 502" >&2; exit 1; }
jqx=.
while (($#)); do [[ "$1" == --jq ]] && jqx="$2"; shift; done
jq -r "$jqx" "$file"
"""

DESCOPE = "**Important (product owner decides):** Descope: needs approval. The export isn't built."


def note(who, body, at, kind="User"):
    return {"author": {"login": who, "__typename": kind}, "body": body, "createdAt": at}


def descope_thread(*replies, first=DESCOPE, by="claude"):
    return {"comments": {"nodes": [note(by, first, "2026-11-13T10:00:00Z", "Bot"), *replies]}}


@pytest.fixture
def descopes(tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_DESCOPES)
    (fake / "gh").chmod(0o755)
    files = {n: tmp_path / f"{n}.json" for n in ("comments", "threads", "statuses")}

    def go(threads, reviewed="2026-11-13T10:00:00Z", status=None, script="decided", readable=True):
        summary_comment = {
            "user": {"login": "claude[bot]"},
            "body": "## Review\n<!-- review-findings: important=1 nit=0 -->",
            "updated_at": reviewed,
        }
        files["comments"].write_text(json.dumps([summary_comment] if reviewed else []))
        page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": list(threads)}
        if readable:
            data = {"data": {"repository": {"pullRequest": {"reviewThreads": page}}}}
            files["threads"].write_text(json.dumps(data))
        else:
            files["threads"].unlink(missing_ok=True)
        state, description = status or ("success", "The Claude review is posted")
        files["statuses"].write_text(
            json.dumps([{"context": "claude-review", "state": state, "description": description}])
        )
        env = {
            "PATH": f"{fake}:{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "o/r",
            "FAKE_COMMENTS": str(files["comments"]),
            "FAKE_THREADS": str(files["threads"]),
            "FAKE_STATUSES": str(files["statuses"]),
            "FAKE_POSTED": str(tmp_path / "posted"),
            "FAKE_CALLS": str(tmp_path / "calls"),
        }
        args = ["7"] if script == "decided" else ["7", "abc1234"]
        result = run(["bash", str(REPO / f".sdlc/scripts/descopes-{script}.sh"), *args], env=env)
        posted = tmp_path / "posted"
        result.posted = posted.read_text() if posted.exists() else ""
        posted.unlink(missing_ok=True)
        return result

    return go


def test_descopes_with_none_pass(descopes):
    other = descope_thread(first="**Important:** a plain bug.")
    result = descopes([other])
    assert result.returncode == 0 and result.stdout.strip() == "no descopes to approve"


def test_a_descope_waits_for_a_persons_reply(descopes):
    bot_reply = note(
        "stickle-claude", "Approved: Kieron, 2026-11-13", "2026-11-13T11:00:00Z", "Bot"
    )
    for thread in (descope_thread(), descope_thread(bot_reply)):
        result = descopes([thread])
        assert result.returncode == 1
        assert result.stdout.startswith("A descope waits for a person's decision: The export")
        assert "Reply Approved: <name>, <date>, or send it back" in result.stdout


def test_an_approved_reply_from_a_person_decides_it_and_names_them(descopes):
    approved = note(
        "kieron", "Fine for now.\n\nApproved: Kieron, 2026-11-13", "2026-11-13T11:00:00Z"
    )
    result = descopes([descope_thread(approved)])
    assert result.returncode == 0
    assert result.stdout.strip() == "descopes decided: approved by @kieron (2026-11-13)"


def test_a_descope_sent_back_waits_for_a_review_after_the_reply(descopes):
    back = note("po", "No, build the export.", "2026-11-13T11:00:00Z")
    waiting = descopes([descope_thread(back)], reviewed="2026-11-13T10:30:00Z")
    assert waiting.returncode == 1
    assert "@po sent a descope back (The export" in waiting.stdout
    assert "add the review label" in waiting.stdout
    reviewed = descopes([descope_thread(back)], reviewed="2026-11-13T12:00:00Z")
    assert reviewed.returncode == 0 and "sent back by @po, re-reviewed" in reviewed.stdout
    assert descopes([descope_thread(back)], reviewed=None).returncode == 1  # no review at all


def test_every_descope_must_be_decided(descopes):
    approved = note("kieron", "Approved: Kieron, 2026-11-13", "2026-11-13T11:00:00Z")
    result = descopes([descope_thread(approved), descope_thread()])
    assert result.returncode == 1
    others = descope_thread(first=DESCOPE, by="someone")  # not the reviewer's thread
    assert descopes([descope_thread(approved), others]).returncode == 0


def test_descopes_fail_closed_when_unreadable(descopes):
    assert descopes([], readable=False).returncode == 3


def test_descope_reasons_fit_a_status(descopes):
    long = descope_thread(first=DESCOPE + " " + "x" * 300)
    assert len(descopes([long]).stdout.strip()) <= 140


@pytest.mark.parametrize(
    ("status", "threads", "posted"),
    [
        (("success", "The Claude review is posted"), [descope_thread()], "state=failure"),
        (("failure", "A descope waits for a person's decision: x"), [], "state=success"),
        (
            ("failure", "A descope waits for a person's decision: x"),
            [descope_thread()],
            "state=failure",
        ),
        (("success", "The Claude review is posted"), [], ""),  # nothing to change
        (("pending", "The Claude review is running"), [descope_thread()], ""),  # the review's
        (("failure", "Not reviewed: add the review label"), [], ""),  # not ours to clear
        (("failure", "The review ran but posted no summary"), [], ""),
    ],
)
def test_descopes_status_moves_only_between_posted_and_a_descope(descopes, status, threads, posted):
    result = descopes(threads, status=status, script="status")
    assert result.returncode == 0, result.stderr
    if posted:
        assert posted in result.posted and "context=claude-review" in result.posted
    else:
        assert result.posted == ""


def test_descopes_status_says_who_approved_when_it_clears(descopes):
    approved = note("kieron", "Approved: Kieron, 2026-11-13", "2026-11-13T11:00:00Z")
    status = ("failure", "A descope waits for a person's decision: x")
    result = descopes([descope_thread(approved)], status=status, script="status")
    assert "description=The Claude review is posted; descopes decided: approved by @kieron" in (
        result.posted
    )


def test_descopes_status_fails_when_it_cannot_check(descopes):
    result = descopes([], readable=False, script="status")
    assert result.returncode == 1 and result.posted == ""


def test_the_review_and_each_reply_check_the_descopes():
    review = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    done = review.split("name: Mark the review as done", 1)[1].split(
        "name: Mark the review as failed"
    )[0]
    assert done.index("review-findings.sh") < done.index('.sdlc/scripts/descopes-decided.sh "$PR"')
    workflow = (REPO / ".github/workflows/sdlc-descopes.yml").read_text()
    assert "pull_request_review:\n    types: [submitted, dismissed]" in workflow
    assert "pull_request_review_comment:\n    types: [created]" in workflow
    assert "github.event.comment.user.type == 'User'" in workflow
    assert '.sdlc/scripts/descopes-status.sh "$PR" "$HEAD_SHA"' in workflow
    assert "statuses: write" in workflow
    assert synced(".sdlc/scripts/descopes-decided.sh") and synced(
        ".sdlc/scripts/descopes-status.sh"
    )


def test_the_review_rules_and_skill_say_a_person_decides_a_descope():
    rules = (REPO / ".sdlc/REVIEW.md").read_text()
    assert "has `Descope: needs approval` right after its lead-in" in rules
    assert "a person (not a bot or an App) replies in the thread" in rules
    skill = (REPO / ".sdlc/skills/review-findings/SKILL.md").read_text()
    assert "**A `Descope: needs approval` thread** is decided only by a person's reply" in skill
    assert "never approve one for them" in skill
