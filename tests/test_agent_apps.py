"""scripts/create-agent-apps.py: creating the agent's GitHub App with the manifest flow."""

import importlib.util
import json
import re
import sys
import threading
import urllib.error
import urllib.request
from html.parser import HTMLParser

import pytest

from conftest import REPO, run


@pytest.fixture
def apps(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("apps", REPO / "scripts/create-agent-apps.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "apps", module)  # dataclasses look the module up
    spec.loader.exec_module(module)
    module.REPO_KEY = "o_r"
    module.KEYS_DIR = tmp_path / "keys"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SDLC_AGENT_KEY_STORE_DIR", str(tmp_path / "keys"))
    return module


def test_one_app_is_named_after_the_repo_and_may_change_workflows(apps):
    agent = apps.new_identity("jobhunt-app")
    assert agent.name == "agent" and agent.app_name == "jobhunt-app-claude"
    assert agent.permissions["workflows"] == "write"
    assert agent.permissions["contents"] == "write"


def test_manifest_has_no_webhook_and_comes_back_here(apps):
    agent = apps.new_identity("x")
    m = apps.manifest(agent, "http://127.0.0.1:5000", "stickleprojects")
    # #102: GitHub refuses the manifest when a hook URL is the local server, even inactive.
    assert "hook_attributes" not in m and m["default_events"] == []
    local = {k for k, v in m.items() if "127.0.0.1" in json.dumps(v)}
    assert local == {"redirect_url", "setup_url"}, "only the URLs GitHub accepts on localhost"
    assert m["redirect_url"] == "http://127.0.0.1:5000/created"
    assert m["setup_url"] == "http://127.0.0.1:5000/installed"
    assert m["public"] is False


class _Form(HTMLParser):
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.action = a["action"]
        if tag == "input" and a.get("name") == "manifest":
            self.manifest = json.loads(a["value"])


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get(url):
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(url) as r:
            return r.status, r.read().decode(), None
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode(), err.headers.get("Location")


def test_browser_flow_creates_and_installs_the_app(apps, monkeypatch, tmp_path):
    identities = [apps.new_identity("s")]
    app = {"id": 11, "slug": "s-claude", "pem": "KEY-1"}
    monkeypatch.setattr(apps, "convert", lambda code: app)
    monkeypatch.setattr(apps, "bot_id", lambda slug: 900)
    flow = apps.Flow(identities, "stickleprojects", None)
    server = apps.ThreadingHTTPServer(("127.0.0.1", 0), apps.make_handler(flow))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, body, _ = _get(f"{base}/start")
        form = _Form()
        form.feed(body)
        assert status == 200 and form.action.startswith("https://github.com/settings/apps/new")
        assert form.manifest["name"] == "s-claude"
        assert _get(f"{base}/created?code=c&state=wrong")[0] == 400, "state is checked"
        state = form.action.split("state=")[1]
        status, _, location = _get(f"{base}/created?code=c1&state={state}")
        assert status == 302 and location == "https://github.com/apps/s-claude/installations/new"
        assert _get(f"{base}/installed?installation_id=5&setup_action=install")[0] == 302
        status, body, _ = _get(f"{base}/start")
        assert status == 200 and "All done" in body and flow.done.is_set()
    finally:
        server.shutdown()
    config = (tmp_path / "config/sdlc/o_r/agent.env").read_text()
    assert "SDLC_AGENT_APP_ID=11" in config and "SDLC_AGENT_APP_SLUG=s-claude" in config
    assert "SDLC_AGENT_BOT_ID=900" in config
    # Keys are filed under the App's own name, so they can't replace another App's key.
    assert (tmp_path / "keys/s-claude.pem").read_text() == "KEY-1"
    assert oct((tmp_path / "keys/s-claude.pem").stat().st_mode)[-3:] == "600"
    assert f"SDLC_AGENT_KEY=file:{tmp_path}/keys/s-claude.pem" in config


def _answers(*replies):
    it = iter(replies)
    return lambda _prompt: next(it)


def test_nothing_is_created_unless_confirmed(apps, capsys):
    identities = [apps.new_identity("jobhunt-app")]
    assert apps.confirm(identities, _answers("")) is True
    assert apps.confirm(identities, _answers("n")) is False
    out = capsys.readouterr().out
    assert "About to create 1 GitHub App" in out and "jobhunt-app-claude" in out


def test_there_are_no_per_persona_options(apps):
    with pytest.raises(SystemExit):
        apps.main(["--per-persona"])
    with pytest.raises(SystemExit):
        apps.main(["--groups", "build,dev"])


@pytest.mark.parametrize(
    ("name", "prefix"),
    [
        ("jobhunt-app", "jobhunt-app"),
        ("JobHunt_App", "jobhunt-app"),
        ("my.cool  repo!", "my-cool-repo"),
        ("--x--", "x"),
        ("a" * 40, "a" * 27),
        ("!!!", ""),
    ],
)
def test_prefix_is_made_safe_for_github(apps, name, prefix):
    assert apps.safe_prefix(name) == prefix
    assert len(f"{apps.safe_prefix(name)}-claude") <= 34


def test_prefix_is_asked_first_and_defaults_to_the_repo(apps, capsys):
    assert apps.ask_prefix("jobhunt-app", _answers("")) == "jobhunt-app"
    assert apps.ask_prefix("jobhunt-app", _answers("Job Hunt")) == "job-hunt"
    assert "using job-hunt" in capsys.readouterr().out
    assert apps.ask_prefix("jobhunt-app", _answers("!!", "jh")) == "jh"


def test_repo_key_matches_the_bash_side(apps, tmp_path):
    assert apps.repo_key("Stickleprojects/JobHunt-App") == "stickleprojects_jobhunt-app"
    env = {"XDG_CONFIG_HOME": str(tmp_path), "SDLC_AGENT_REPO": "Stickleprojects/JobHunt-App"}
    (tmp_path / "sdlc/stickleprojects_jobhunt-app").mkdir(parents=True)
    (tmp_path / "sdlc/stickleprojects_jobhunt-app/agent.env").write_text(
        "SDLC_AGENT_APP_ID=1\nSDLC_AGENT_APP_SLUG=jobhunt-app-claude\n"
    )
    out = run(["bash", str(REPO / "scripts/agent-identity.sh"), "show"], env=env)
    assert out.stdout.strip() == "1 jobhunt-app-claude"


# --- reuse, locations and not overwriting ------------------------------------------------------


def _app_config(path, slug="shared-claude", app_id=7):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"SDLC_AGENT_APP_ID={app_id}\nSDLC_AGENT_APP_SLUG={slug}\nSDLC_AGENT_KEY=file:/k/{slug}.pem\n"
    )
    return path


def test_existing_apps_are_found_once_through_pointers(apps, tmp_path):
    shared = _app_config(tmp_path / "anywhere/shared.env")
    apps.write_pointer(tmp_path / "config/sdlc/o_a/agent.env", shared)
    apps.write_pointer(tmp_path / "config/sdlc/o_b/agent.env", shared)
    _app_config(tmp_path / "config/sdlc/o_c/agent.env", "c-claude", 9)
    found = apps.find_existing_apps([shared])
    assert sorted(slug for slug, _ in found) == ["c-claude", "shared-claude"]


def test_reusing_an_app_links_this_repo_without_creating_anything(apps, tmp_path):
    shared = _app_config(tmp_path / "anywhere/shared.env")
    reuse = apps.choose_existing([("shared-claude", shared)], _answers("2"))
    assert reuse.existing == shared and reuse.name == "agent"
    assert apps.clashes([reuse]) == []
    apps.link_existing(reuse)
    pointer = tmp_path / "config/sdlc/o_r/agent.env"
    assert pointer.read_text().endswith(f"SDLC_AGENT_USE={shared.resolve()}\n")
    assert apps.clashes([reuse]) == [], "pointing at it already is not a clash"
    text = apps.describe([reuse])
    assert "Reusing (nothing created, no key changed)" in text and "About to create" not in text


def test_existing_configs_are_never_replaced_silently(apps, tmp_path):
    agent = apps.new_identity("jh")
    assert apps.clashes([agent]) == []
    _app_config(tmp_path / "config/sdlc/o_r/agent.env", "old-app")
    assert apps.clashes([agent]) == [tmp_path / "config/sdlc/o_r/agent.env"]
    other = _app_config(tmp_path / "anywhere/other.env", "other")
    reuse = apps.Identity("agent", "other", slug="other", existing=other)
    assert apps.clashes([reuse]) == [tmp_path / "config/sdlc/o_r/agent.env"]


def test_new_config_can_live_anywhere_with_a_pointer_left_behind(apps, tmp_path):
    agent = apps.new_identity("jh")
    agent.config_path = tmp_path / "my/place/jh-claude.env"
    agent.slug, agent.app_id = "jh-claude", 5
    apps.write_config(agent, 0, "keyring:github-app-private-key:jh-claude")
    assert (
        "SDLC_AGENT_KEY=keyring:github-app-private-key:jh-claude" in agent.config_path.read_text()
    )
    pointer = (tmp_path / "config/sdlc/o_r/agent.env").read_text()
    assert f"SDLC_AGENT_USE={agent.config_path.resolve()}" in pointer


def test_main_refuses_to_replace_without_force(apps, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SDLC_AGENT_REPO", "o/r")
    _app_config(tmp_path / "config/sdlc/o_r/agent.env", "old-app")
    assert apps.main(["--yes", "--no-browser"]) == 1
    assert "Not replacing" in capsys.readouterr().out


def test_main_use_shares_an_app_across_repos(apps, tmp_path, monkeypatch, capsys):
    shared = _app_config(tmp_path / "anywhere/shared.env")
    for repo in ["o/a", "o/b"]:
        monkeypatch.setenv("SDLC_AGENT_REPO", repo)
        assert apps.main(["--use", str(shared), "--yes"]) == 0
    for key in ["o_a", "o_b"]:
        text = (tmp_path / f"config/sdlc/{key}/agent.env").read_text()
        assert f"SDLC_AGENT_USE={shared.resolve()}" in text
    assert "installations/new" in capsys.readouterr().out


# --- what GitHub can answer when the App is created ---------------------------------------------


@pytest.fixture
def fake_api(apps, monkeypatch):
    """A local stand-in for api.github.com's manifest conversion endpoint. Set .status and
    .body for what it answers."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class State:
        status, body = (
            201,
            json.dumps({"id": 1, "slug": "x", "pem": "-----BEGIN RSA PRIVATE KEY-----"}),
        )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):  # noqa: N802
            body = State.body.encode()
            self.send_response(State.status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(apps, "API", f"http://127.0.0.1:{server.server_address[1]}")
    yield State
    server.shutdown()


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (404, '{"message": "Not Found"}', "expired or was already used"),
        (422, '{"message": "Name has already been taken"}', "Name has already been taken"),
        (401, '{"message": "Bad credentials"}', "refused the request: Bad credentials"),
        (403, "{}", "refused the request"),
        (502, "<html>bad gateway</html>", "GitHub had an error (502)"),
        (201, "not json at all", "wasn't JSON"),
        (201, '["a list"]', "wasn't an App"),
        (201, '{"id": 1, "slug": "x"}', "missing the App's pem"),
        (201, '{"id": 1, "slug": "x", "pem": "garbage"}', "missing the App's key"),
    ],
)
def test_conversion_failures_become_readable_errors(apps, fake_api, status, body, reason):
    fake_api.status, fake_api.body = status, body
    with pytest.raises(apps.ConversionError, match=re.escape(reason)):
        apps.convert("code")


def test_conversion_timeout_is_readable(apps, monkeypatch):
    def slow(*_a, **_k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(apps.urllib.request, "urlopen", slow)
    with pytest.raises(apps.ConversionError, match="didn't answer"):
        apps.convert("code")


def test_good_conversion(apps, fake_api):
    assert apps.convert("code")["slug"] == "x"


def _serve(apps, flow):
    server = apps.ThreadingHTTPServer(("127.0.0.1", 0), apps.make_handler(flow))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _state(base):
    form = _Form()
    form.feed(_get(f"{base}/start")[1])
    return form.action.split("state=")[1]


def test_failed_exchange_writes_nothing_and_can_be_retried(apps, monkeypatch, tmp_path, capsys):
    agent = apps.new_identity("jh")
    answers = iter([apps.ConversionError("the code has expired or was already used"), None])

    def convert(code):
        result = next(answers)
        if isinstance(result, Exception):
            raise result
        return {"id": 3, "slug": "jh-claude", "pem": "-----BEGIN KEY-----"}

    monkeypatch.setattr(apps, "convert", convert)
    monkeypatch.setattr(apps, "bot_id", lambda slug: 1)
    flow = apps.Flow([agent], "o", None, "o/r")
    server, base = _serve(apps, flow)
    try:
        state = _state(base)
        status, body, _ = _get(f"{base}/created?code=a&state={state}")
        assert status == 502 and "Try again" in body and "Generate a private key" in body
        assert not (tmp_path / "config/sdlc/o_r/agent.env").exists(), "nothing written"
        assert _get(f"{base}/created?code=a&state={state}")[0] == 400, "the spent state is refused"
        status, _, location = _get(f"{base}/created?code=b&state={_state(base)}")
        assert status == 302 and "jh-claude/installations/new" in location
    finally:
        server.shutdown()
    assert "SDLC_AGENT_APP_SLUG=jh-claude" in (tmp_path / "config/sdlc/o_r/agent.env").read_text()
    assert "may already exist on GitHub" in capsys.readouterr().err


def test_skipping_the_app_records_it_with_the_ways_to_recover(apps):
    flow = apps.Flow([apps.new_identity("jh")], "o", None, "o/r")
    server, base = _serve(apps, flow)
    try:
        _get(f"{base}/start")
        assert _get(f"{base}/next")[0] == 302
    finally:
        server.shutdown()
    assert [i.app_name for i in flow.skipped] == ["jh-claude"]
    hint = apps.recovery_hint("jh-claude", "agent")
    assert "settings/apps/jh-claude" in hint and "Generate a private key" in hint
    assert "setup --identity agent" in hint and "Delete GitHub App" in hint


def test_start_page_explains_sign_in_and_taken_names(apps):
    flow = apps.Flow([apps.new_identity("jh")], "o", None, "o/r")
    server, base = _serve(apps, flow)
    try:
        body = _get(f"{base}/start")[1]
    finally:
        server.shutdown()
    assert "sign in" in body and "name is taken" in body and "/next" in body
