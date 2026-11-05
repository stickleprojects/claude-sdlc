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


def test_review_does_not_run_on_every_push():
    workflow = (REPO / ".github/workflows/claude-review.yml").read_text()
    assert "types: [opened, ready_for_review, labeled]" in workflow
    assert "synchronize" not in workflow


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


def test_bootstrap_can_refresh_the_app_key_secret():
    script = (REPO / "scripts/bootstrap-github.sh").read_text()
    assert "--update-agent-key) update_agent_key=1" in script
    assert "((update_agent_key == 0)) && gh secret list" in script


def test_bootstrap_help_lists_every_step():
    help_text = run(["scripts/bootstrap-github.sh", "--help"]).stdout
    for n in range(1, 12):
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


# --- agent identity -------------------------------------------------------------------------

PERSONAS = REPO / ".claude/personas.conf"


def _registry():
    rows = [line.split() for line in PERSONAS.read_text().splitlines() if line[:1].isalpha()]
    identities = {r[1]: r[2] for r in rows if r[0] == "identity"}
    personas = {r[1]: (r[2], r[3]) for r in rows if r[0] == "persona"}
    return identities, personas


def test_persona_registry_matches_the_skills_and_workflows():
    identities, personas = _registry()
    for name, (identity, where) in personas.items():
        assert identity in identities, name
        assert where in {"local", "ci"}, name
    skill = (REPO / ".claude/skills/agent-identity/SKILL.md").read_text()
    for name in re.findall(r"^\| `([a-z-]+)` \|", skill, re.MULTILINE):
        assert personas.get(name, ("", ""))[1] == "local", f"skill persona {name} not in registry"
    text = PERSONAS.read_text()
    for wf in ["spec-from-intent.yml", "claude-review.yml", "claude-mention.yml"]:
        assert (REPO / ".github/workflows" / wf).exists() and wf in text


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
        "SDLC_PERSONAS": str(PERSONAS),
        "LOG": str(tmp_path),
        "SDLC_RETRY_DELAY": "0",
    }
    return tmp_path, env


def identity(env, *args, stdin=None):
    return run(["bash", str(REPO / "scripts/agent-identity.sh"), *args], env=env, input=stdin)


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


def test_env_makes_git_act_as_the_bot_for_a_local_persona(agent_env):
    _, env = agent_env
    out = identity(env, "env", "--persona", "build")
    assert out.returncode == 0, out.stderr
    assert "GIT_AUTHOR_NAME='stickle-claude[bot]'" in out.stdout
    assert "999+stickle-claude[bot]@users.noreply.github.com" in out.stdout
    assert "SDLC_AGENT_PERSONA='build'" in out.stdout
    assert "insteadOf" in out.stdout


def test_env_rejects_unknown_and_ci_personas(agent_env):
    _, env = agent_env
    assert identity(env, "env", "--persona", "wizard").returncode == 1
    reviewer = identity(env, "env", "--persona", "reviewer")
    assert reviewer.returncode == 1 and "runs in ci" in reviewer.stderr


def test_env_without_setup_falls_back_to_the_person(agent_env, tmp_path):
    _, env = agent_env
    out = identity({**env, "XDG_CONFIG_HOME": str(tmp_path / "empty")}, "env")
    assert out.returncode == 0 and out.stdout == ""
    assert "acts as you" in out.stderr


def test_agent_session_starts_claude_with_the_identity(agent_env):
    _, env = agent_env
    out = run(
        ["bash", str(REPO / "scripts/agent-session.sh"), "--persona", "dev"],
        env={**env, "SDLC_CLAUDE": "env"},
    )
    assert out.returncode == 0, out.stderr
    assert "GIT_COMMITTER_NAME=stickle-claude[bot]" in out.stdout
    assert "SDLC_AGENT_PERSONA=dev" in out.stdout


def test_each_repo_has_its_own_apps(agent_env):
    # An App made for o/r doesn't leak into another repo on the same machine.
    _, env = agent_env
    assert identity(env, "show").stdout.strip() == "123 stickle-claude"
    other = identity({**env, "SDLC_AGENT_REPO": "o/jobhunt-app"}, "show")
    assert other.returncode == 1
    assert identity({**env, "SDLC_AGENT_REPO": "o/jobhunt-app"}, "env").stdout == ""


def test_workflows_guard_against_agent_loops():
    mention = (REPO / ".github/workflows/claude-mention.yml").read_text()
    assert "github.event.comment.user.type == 'User'" in mention
    review = (REPO / ".github/workflows/claude-review.yml").read_text()
    assert "allowed_bots: ${{ vars.SDLC_AGENT_APP_SLUG }}" in review
    spec = (REPO / ".github/workflows/spec-from-intent.yml").read_text()
    assert "actions/create-github-app-token" in spec


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
    args = ["bash", str(REPO / "scripts/tests-locked.sh")] + ([path] if path else [])
    clean = {"SDLC_LOCK_TESTS": "", "SDLC_CHANGE": "", **(env or {})}
    return run(args, cwd=repo, env=clean).returncode == 0


def test_bug_tests_stay_editable_until_the_failing_test_is_committed(bug_branch):
    assert not locked(bug_branch, "tests/test_overlap.py")
    commit(bug_branch, "test(0003-overlap): failing test for overlap", {"tests/t.py": "x\n"})
    assert locked(bug_branch, "tests/test_overlap.py")
    assert locked(bug_branch, "app/src/__tests__/overlap.test.tsx")
    assert locked(bug_branch, "app/e2e/screens.spec.ts")
    assert not locked(bug_branch, "src/overlap.py"), "code stays editable"


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


def test_agent_session_locks_tests_for_a_bug_fix(bug_branch):
    commit(bug_branch, "test(0003-overlap): failing test", {"tests/t.py": "x\n"})
    out = run(
        ["bash", str(REPO / "scripts/agent-session.sh")],
        cwd=bug_branch,
        env={"SDLC_CLAUDE": "env", "SDLC_LOCK_TESTS": "", "XDG_CONFIG_HOME": str(bug_branch)},
    )
    assert out.returncode == 0, out.stderr
    assert "SDLC_LOCK_TESTS=1" in out.stdout
    assert "tests locked" in out.stderr


def test_every_session_loads_the_agent_identity():
    settings = json.loads((REPO / ".claude/settings.json").read_text())
    commands = [h["command"] for e in settings["hooks"]["SessionStart"] for h in e["hooks"]]
    assert '"$CLAUDE_PROJECT_DIR"/scripts/agent-session.sh --hook' in commands


def test_session_hook_is_a_no_op_without_setup(tmp_path):
    env_file = tmp_path / "env"
    out = run(
        ["bash", str(REPO / "scripts/agent-session.sh"), "--hook"],
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
