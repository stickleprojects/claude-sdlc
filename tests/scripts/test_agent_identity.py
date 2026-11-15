import json
import re

import pytest

from conftest import REPO, run

from .helpers import RUNS_ON, gh_expr, identity

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
