"""scripts/create-agent-apps.py: creating the agent's GitHub Apps with the manifest flow."""

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

PERSONAS = REPO / ".claude/personas.conf"
LOCAL = ["intent", "spec", "plan", "build", "dev", "po-review"]


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


def test_one_app_serves_every_local_persona(apps):
    [agent] = apps.plan(PERSONAS, per_persona=False, prefix="jobhunt-app")
    assert agent.name == "agent" and agent.personas == LOCAL
    assert agent.app_name == "jobhunt-app-claude"
    assert agent.permissions["workflows"] == "write"


def test_per_persona_apps_get_only_what_they_need(apps):
    identities = apps.plan(PERSONAS, per_persona=True, prefix="jobhunt-app")
    assert [i.name for i in identities] == [f"agent-{p}" for p in LOCAL]
    assert identities[2].app_name == "jobhunt-app-plan"
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
    config = (tmp_path / "config/sdlc/o_r/agent-intent.env").read_text()
    assert "SDLC_AGENT_APP_ID=11" in config and "SDLC_AGENT_APP_SLUG=s-claude-intent" in config
    assert "SDLC_AGENT_BOT_ID=900" in config
    # Keys are filed under the App's own name, so they can't replace another App's key.
    assert (tmp_path / "keys/s-claude-spec.pem").read_text() == "KEY-2"
    assert oct((tmp_path / "keys/s-claude-spec.pem").stat().st_mode)[-3:] == "600"
    assert f"SDLC_AGENT_KEY=file:{tmp_path}/keys/s-claude-intent.pem" in config


def test_per_persona_override_maps_each_persona_and_the_script_follows_it(apps, tmp_path):
    identities = apps.plan(PERSONAS, per_persona=True, prefix="s-claude")
    apps.write_personas_override(PERSONAS, identities, per_persona=True)
    override = tmp_path / "config/sdlc/o_r/personas.conf"
    env = {
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "SDLC_PERSONAS": "",
        "SDLC_AGENT_REPO": "o/r",
    }

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
    assert apps.choose_groups(LOCAL, "s", _answers("1")) == [LOCAL]
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
    identities = apps.build_identities([LOCAL], LOCAL, "jobhunt-app")
    assert apps.confirm(identities, _answers("")) is True
    assert apps.confirm(identities, _answers("n")) is False
    out = capsys.readouterr().out
    assert "About to create 1 GitHub App:" in out and "jobhunt-app-claude" in out


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
    env = {
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "SDLC_PERSONAS": "",
        "SDLC_AGENT_REPO": "o/r",
    }
    of = lambda p: run(  # noqa: E731
        ["bash", str(REPO / "scripts/agent-identity.sh"), "identity-of", p], env=env
    ).stdout.strip()
    assert of("intent") == "agent-plan" and of("spec-ci") == "agent-plan"
    assert of("dev") == "agent-dev"


@pytest.mark.parametrize(
    ("name", "prefix"),
    [
        ("jobhunt-app", "jobhunt-app"),
        ("JobHunt_App", "jobhunt-app"),
        ("my.cool  repo!", "my-cool-repo"),
        ("--x--", "x"),
        ("a" * 40, "a" * 24),
        ("!!!", ""),
    ],
)
def test_prefix_is_made_safe_for_github(apps, name, prefix):
    assert apps.safe_prefix(name) == prefix
    assert len(f"{apps.safe_prefix(name)}-po-review") <= 34


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
    _app_config(tmp_path / "config/sdlc/o_c/agent-plan.env", "c-plan", 9)
    found = apps.find_existing_apps([shared])
    assert sorted(slug for slug, _ in found) == ["c-plan", "shared-claude"]


def test_reusing_an_app_links_this_repo_without_creating_anything(apps, tmp_path):
    shared = _app_config(tmp_path / "anywhere/shared.env")
    reuse = apps.choose_existing(LOCAL, [("shared-claude", shared)], _answers("2"))
    assert reuse.existing == shared and reuse.personas == LOCAL
    assert apps.clashes([reuse]) == []
    apps.link_existing(reuse)
    pointer = tmp_path / "config/sdlc/o_r/agent.env"
    assert pointer.read_text().endswith(f"SDLC_AGENT_USE={shared.resolve()}\n")
    assert apps.clashes([reuse]) == [], "pointing at it already is not a clash"
    text = apps.describe([reuse])
    assert "Reusing (nothing created, no key changed)" in text and "About to create" not in text


def test_each_new_app_can_instead_be_an_existing_one(apps, tmp_path):
    shared = _app_config(tmp_path / "anywhere/shared.env")
    identities = apps.build_identities(
        [["plan", "intent", "spec", "po-review"], ["build"], ["dev"]], LOCAL, "jh"
    )
    apps.choose_sources(identities, [("shared-claude", shared)], _answers("2", "1", "1"))
    assert [i.existing for i in identities] == [shared, None, None]
    assert "About to create 2 GitHub Apps" in apps.describe(identities)


def test_existing_configs_are_never_replaced_silently(apps, tmp_path):
    [agent] = apps.plan(PERSONAS, False, "jh")
    assert apps.clashes([agent]) == []
    _app_config(tmp_path / "config/sdlc/o_r/agent.env", "old-app")
    assert apps.clashes([agent]) == [tmp_path / "config/sdlc/o_r/agent.env"]
    other = _app_config(tmp_path / "anywhere/other.env", "other")
    reuse = apps.Identity("agent", LOCAL, "other", slug="other", existing=other)
    assert apps.clashes([reuse]) == [tmp_path / "config/sdlc/o_r/agent.env"]


def test_new_config_can_live_anywhere_with_a_pointer_left_behind(apps, tmp_path):
    [agent] = apps.plan(PERSONAS, False, "jh")
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
    assert apps.main(["--registry", str(PERSONAS), "--yes", "--no-browser"]) == 1
    assert "Not replacing" in capsys.readouterr().out


def test_main_use_shares_an_app_across_repos(apps, tmp_path, monkeypatch, capsys):
    shared = _app_config(tmp_path / "anywhere/shared.env")
    for repo in ["o/a", "o/b"]:
        monkeypatch.setenv("SDLC_AGENT_REPO", repo)
        assert apps.main(["--registry", str(PERSONAS), "--use", str(shared), "--yes"]) == 0
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
    [agent] = apps.plan(PERSONAS, False, "jh")
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


def test_skipping_an_app_records_it_with_the_ways_to_recover(apps):
    identities = apps.plan(PERSONAS, True, "jh")[:2]
    flow = apps.Flow(identities, "o", None, "o/r")
    server, base = _serve(apps, flow)
    try:
        _get(f"{base}/start")
        assert _get(f"{base}/next")[0] == 302
    finally:
        server.shutdown()
    assert [i.app_name for i in flow.skipped] == ["jh-intent"]
    hint = apps.recovery_hint("jh-intent", "agent-intent")
    assert "settings/apps/jh-intent" in hint and "Generate a private key" in hint
    assert "setup --identity agent-intent" in hint and "Delete GitHub App" in hint


def test_start_page_explains_sign_in_and_taken_names(apps):
    flow = apps.Flow(apps.plan(PERSONAS, False, "jh"), "o", None, "o/r")
    server, base = _serve(apps, flow)
    try:
        body = _get(f"{base}/start")[1]
    finally:
        server.shutdown()
    assert "sign in" in body and "name is taken" in body and "/next" in body
