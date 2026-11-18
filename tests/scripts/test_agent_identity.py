import json
import re

import pytest

from conftest import REPO, run

from .helpers import (
    DEFERRABLE_JOBS,
    HEAVY_JOBS,
    RUNS_ON,
    RUNS_ON_DEFERRABLE,
    RUNS_ON_HEAVY,
    gh_expr,
    identity,
)

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
    # A light job never takes the heavy label (#222).
    both = {"SDLC_RUNNER": "self-hosted", "SDLC_RUNNER_HEAVY": "big"}
    assert gh_expr(expr, {**ctx, "vars": both}) == runner
    assert gh_expr(expr, {**ctx, "vars": {"SDLC_RUNNER_HEAVY": "big"}}) == "ubuntu-latest"


@pytest.mark.parametrize(
    "variables, own_code",
    [
        ({"SDLC_RUNNER": "light", "SDLC_RUNNER_HEAVY": "heavy"}, "heavy"),
        ({"SDLC_RUNNER": "light"}, "light"),  # no heavy label: falls back to SDLC_RUNNER
        ({"SDLC_RUNNER_HEAVY": "heavy"}, "heavy"),  # heavy only: light jobs stay on GitHub's
        ({}, "ubuntu-latest"),
    ],
    ids=["both", "light only", "heavy only", "neither"],
)
@pytest.mark.parametrize(
    "event", [{"pull_request": SAME}, {"ref": "refs/heads/main"}], ids=["same-repo PR", "push"]
)
def test_heavy_jobs_use_sdlc_runner_heavy_then_sdlc_runner(variables, own_code, event):
    expr = RUNS_ON_HEAVY.removeprefix("runs-on: ${{").removesuffix("}}")
    ctx = {"github": {"repository": REPO_NAME, "event": event}, "vars": variables}
    assert gh_expr(expr, ctx) == own_code


@pytest.mark.parametrize(
    "event",
    [
        {"pull_request": FORK},
        {"pull_request": DELETED_FORK},
        {"issue": {"pull_request": {"url": "x"}}, "comment": {}},
    ],
    ids=["fork PR", "deleted fork", "PR comment"],
)
def test_heavy_jobs_keep_the_fork_guard(event):
    expr = RUNS_ON_HEAVY.removeprefix("runs-on: ${{").removesuffix("}}")
    ctx = {"github": {"repository": REPO_NAME, "event": event}}
    both = {"SDLC_RUNNER": "light", "SDLC_RUNNER_HEAVY": "heavy"}
    assert gh_expr(expr, {**ctx, "vars": both}) == "ubuntu-latest"


ON = {"SDLC_CHECK_AFTER_REVIEW": "on"}


@pytest.mark.parametrize(
    "event_name, event, setting, runner",
    [
        ("pull_request", {"pull_request": SAME}, ON, "light"),  # deferred: only a note
        ("pull_request", {"pull_request": SAME}, {"SDLC_CHECK_AFTER_REVIEW": "Off"}, "heavy"),
        ("pull_request", {"pull_request": SAME}, {}, "heavy"),
        ("push", {"ref": "refs/heads/main"}, ON, "heavy"),  # main runs make check here
        ("pull_request", {"pull_request": FORK}, ON, "ubuntu-latest"),  # forks: never ours
    ],
    ids=["deferred PR", "setting off", "setting unset", "push to main", "fork PR"],
)
def test_a_deferred_ci_check_takes_the_light_runner(event_name, event, setting, runner):
    # #236: a deferred `check` starting a heavy runner for an echo.
    expr = RUNS_ON_DEFERRABLE.removeprefix("runs-on: ${{").removesuffix("}}")
    both = {"SDLC_RUNNER": "light", "SDLC_RUNNER_HEAVY": "heavy", **setting}
    gh = {"event_name": event_name, "repository": REPO_NAME, "event": event}
    assert gh_expr(expr, {"github": gh, "vars": both}) == runner
    # Without SDLC_RUNNER a deferred one goes to GitHub's, never the heavy label.
    heavy_only = {"SDLC_RUNNER_HEAVY": "heavy", **setting}
    want = "ubuntu-latest" if runner in ("light", "ubuntu-latest") else "heavy"
    assert gh_expr(expr, {"github": gh, "vars": heavy_only}) == want


@pytest.mark.parametrize(
    "workflow", sorted(p.name for p in REPO.glob(".github/workflows/*.yml")), ids=str
)
def test_every_job_runs_on_sdlc_runner_with_the_fork_guard(workflow):
    text = (REPO / ".github/workflows" / workflow).read_text()
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("runs-on:")]
    assert lines, f"{workflow} has no jobs"
    # A job pinned to a literal runner stays queued in an outage and blocks the merge. Jobs that
    # run `make check` or the evals take the heavy label (#222); the rest never do.
    runs_on, job = {}, None
    for line in text.splitlines():
        if m := re.match(r"^  ([a-z][a-z0-9_-]*):$", line):
            job = m.group(1)
        elif line.strip().startswith("runs-on:"):
            runs_on[job] = line.strip()
    heavy = HEAVY_JOBS.get(workflow, set())
    deferrable = DEFERRABLE_JOBS.get(workflow, set())  # #236
    named = heavy | deferrable
    assert named <= runs_on.keys(), f"{workflow}: no job named {named - runs_on.keys()}"
    want = {
        j: RUNS_ON_DEFERRABLE if j in deferrable else RUNS_ON_HEAVY if j in heavy else RUNS_ON
        for j in runs_on
    }
    assert runs_on == want, runs_on
    jobs = re.findall(r"^  [a-z][a-z0-9_-]*:\n(?:    .*\n|\n)*?    steps:", text, re.M)
    assert len(lines) == len(jobs), f"{workflow}: a job without runs-on"


def test_every_variable_the_synced_workflows_read_is_listed_by_the_sync():
    used = set()
    for path in REPO.glob(".github/workflows/sdlc-*.yml"):
        used |= set(re.findall(r"vars\.([A-Z][A-Z0-9_]*)", path.read_text()))
    sync = (REPO / ".sdlc/scripts/sync-sdlc.sh").read_text()
    assert "SDLC_RUNNER_HEAVY" in used
    assert {v for v in used if f'"variable {v}"' not in sync} == set()


def test_sdlc_runner_heavy_is_documented():
    settings = (REPO / ".sdlc/docs/settings.md").read_text()
    assert any(line.startswith("| `SDLC_RUNNER_HEAVY`") for line in settings.splitlines())
    assert "SDLC_RUNNER_HEAVY" in (REPO / ".sdlc/docs/self-hosted-runner.md").read_text()
