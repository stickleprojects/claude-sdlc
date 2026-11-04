"""scripts/create-agent-apps.py: creating the agent's GitHub Apps with the manifest flow."""

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from html.parser import HTMLParser

import pytest

from conftest import REPO, run

PERSONAS = REPO / ".claude/personas.conf"
LOCAL = ["intent", "spec", "plan", "build", "dev", "po-review"]


@pytest.fixture
def apps(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("apps", REPO / "scripts/create-agent-apps.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "apps", module)  # dataclasses look the module up
    spec.loader.exec_module(module)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SDLC_AGENT_KEY_STORE_DIR", str(tmp_path / "keys"))
    return module


def test_one_app_serves_every_local_persona(apps):
    [agent] = apps.plan(PERSONAS, per_persona=False, prefix="stickleprojects-claude")
    assert agent.name == "agent" and agent.personas == LOCAL
    assert agent.app_name == "stickleprojects-claude"
    assert agent.permissions["workflows"] == "write"


def test_per_persona_apps_get_only_what_they_need(apps):
    identities = apps.plan(PERSONAS, per_persona=True, prefix="stickleprojects-claude")
    assert [i.name for i in identities] == [f"agent-{p}" for p in LOCAL]
    assert all(len(i.app_name) <= 34 for i in identities)
    perms = {i.personas[0]: i.permissions for i in identities}
    assert "workflows" in perms["build"] and "workflows" in perms["dev"]
    assert "workflows" not in perms["plan"] and "workflows" not in perms["po-review"]
    assert all(p["contents"] == "write" for p in perms.values())


def test_manifest_has_no_webhook_and_comes_back_here(apps):
    [agent] = apps.plan(PERSONAS, False, "x-claude")
    m = apps.manifest(agent, "http://127.0.0.1:5000", "stickleprojects")
    assert m["hook_attributes"]["active"] is False
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


def test_browser_flow_creates_installs_and_moves_to_the_next_app(apps, monkeypatch, tmp_path):
    identities = apps.plan(PERSONAS, per_persona=True, prefix="s-claude")[:2]
    made = iter([{"id": 11, "slug": "s-claude-intent", "pem": "KEY-1"},
                 {"id": 12, "slug": "s-claude-spec", "pem": "KEY-2"}])  # fmt: skip
    monkeypatch.setattr(apps, "convert", lambda code: next(made))
    monkeypatch.setattr(apps, "bot_id", lambda slug: 900)
    flow = apps.Flow(identities, "stickleprojects", None)
    server = apps.ThreadingHTTPServer(("127.0.0.1", 0), apps.make_handler(flow))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        for n, slug in enumerate(["s-claude-intent", "s-claude-spec"], 1):
            status, body, _ = _get(f"{base}/start")
            form = _Form()
            form.feed(body)
            assert status == 200 and form.action.startswith("https://github.com/settings/apps/new")
            assert form.manifest["name"] == identities[n - 1].app_name
            assert _get(f"{base}/created?code=c&state=wrong")[0] == 400, "state is checked"
            state = form.action.split("state=")[1]
            status, _, location = _get(f"{base}/created?code=c{n}&state={state}")
            assert status == 302 and location == f"https://github.com/apps/{slug}/installations/new"
            assert _get(f"{base}/installed?installation_id=5&setup_action=install")[0] == 302
        status, body, _ = _get(f"{base}/start")
        assert status == 200 and "All done" in body and flow.done.is_set()
    finally:
        server.shutdown()
    config = (tmp_path / "config/sdlc/agent-intent.env").read_text()
    assert "SDLC_AGENT_APP_ID=11" in config and "SDLC_AGENT_APP_SLUG=s-claude-intent" in config
    assert "SDLC_AGENT_BOT_ID=900" in config
    assert (tmp_path / "keys/agent-spec.pem").read_text() == "KEY-2"
    assert oct((tmp_path / "keys/agent-spec.pem").stat().st_mode)[-3:] == "600"


def test_per_persona_override_maps_each_persona_and_the_script_follows_it(apps, tmp_path):
    identities = apps.plan(PERSONAS, per_persona=True, prefix="s-claude")
    apps.write_personas_override(PERSONAS, identities, per_persona=True)
    override = tmp_path / "config/sdlc/personas.conf"
    env = {"XDG_CONFIG_HOME": str(tmp_path / "config"), "SDLC_PERSONAS": ""}

    def ident(*args):
        return run(["bash", str(REPO / "scripts/agent-identity.sh"), *args], env=env)

    assert ident("identity-of", "build").stdout.strip() == "agent-build"
    assert ident("identity-of", "spec-ci").stdout.strip() == "agent-spec"
    assert ident("identity-of", "reviewer").returncode == 1, "claude[bot] isn't one of ours"
    assert ident("identities").stdout.split() == sorted(f"agent-{p}" for p in LOCAL)
    # Going back to one App moves the override aside, so everything maps to `agent` again.
    apps.write_personas_override(PERSONAS, identities[:1], per_persona=False)
    assert not override.exists()
    assert ident("identity-of", "build").stdout.strip() == "agent"


def _answers(*replies):
    it = iter(replies)
    return lambda _prompt: next(it)


def test_prompt_one_app_for_everything(apps):
    assert apps.choose_groups(LOCAL, "s-claude", _answers("1")) == [LOCAL]
    assert apps.choose_groups(LOCAL, "s-claude", _answers("")) == [LOCAL], "Enter = recommended"


def test_prompt_every_persona_its_own_app(apps):
    groups = apps.choose_groups(LOCAL, "s-claude", _answers("2", ""))
    assert groups == [[p] for p in LOCAL]


def test_prompt_several_personas_share_the_plan_app(apps):
    # plan, build and dev get their own; intent, spec and po-review share plan's.
    replies = _answers("2", "3,4,5", "1", "1", "1")
    groups = apps.choose_groups(LOCAL, "s-claude", replies)
    assert groups == [["plan", "intent", "spec", "po-review"], ["build"], ["dev"]]
    identities = apps.build_identities(groups, LOCAL, "s-claude")
    assert [(i.name, i.app_name) for i in identities] == [
        ("agent-plan", "s-claude-plan"),
        ("agent-build", "s-claude-build"),
        ("agent-dev", "s-claude-dev"),
    ]
    assert "workflows" not in identities[0].permissions


def test_prompt_asks_again_after_a_bad_answer(apps, capsys):
    groups = apps.choose_groups(
        LOCAL, "s-claude", _answers("7", "2", "9,x", "6", "1", "1", "1", "1", "1")
    )
    assert groups == [["po-review", "intent", "spec", "plan", "build", "dev"]]
    assert "please answer" in capsys.readouterr().out


def test_nothing_is_created_unless_confirmed(apps, capsys):
    identities = apps.build_identities([LOCAL], LOCAL, "s-claude")
    assert apps.confirm(identities, _answers("")) is True
    assert apps.confirm(identities, _answers("n")) is False
    out = capsys.readouterr().out
    assert "About to create 1 GitHub App(s)" in out and "s-claude" in out


def test_groups_flag_must_cover_each_persona_once(apps):
    groups = apps.parse_groups("intent+spec+plan+po-review, build+dev")
    assert groups == [["intent", "spec", "plan", "po-review"], ["build", "dev"]]
    assert [i.name for i in apps.build_identities(groups, LOCAL, "s")] == [
        "agent-intent",
        "agent-build",
    ]
    with pytest.raises(SystemExit):
        apps.build_identities([["intent", "spec"]], LOCAL, "s")
    with pytest.raises(SystemExit):
        apps.build_identities([LOCAL, ["dev"]], LOCAL, "s")


def test_shared_app_mapping_in_the_override(apps, tmp_path):
    groups = [["plan", "intent", "spec", "po-review"], ["build"], ["dev"]]
    identities = apps.build_identities(groups, LOCAL, "s-claude")
    apps.write_personas_override(PERSONAS, identities, per_persona=True)
    env = {"XDG_CONFIG_HOME": str(tmp_path / "config"), "SDLC_PERSONAS": ""}
    of = lambda p: run(  # noqa: E731
        ["bash", str(REPO / "scripts/agent-identity.sh"), "identity-of", p], env=env
    ).stdout.strip()
    assert of("intent") == "agent-plan" and of("spec-ci") == "agent-plan"
    assert of("dev") == "agent-dev"
