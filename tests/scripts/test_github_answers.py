import shutil

import pytest

from conftest import run

from .helpers import identity

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
