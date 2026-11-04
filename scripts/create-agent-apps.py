#!/usr/bin/env python3
"""Create Claude's GitHub App identities with GitHub's App manifest flow.

Usage: scripts/agent-identity.sh create [--per-persona] [--name PREFIX] [--org ORG] [--no-browser]

  (default)       one App, `agent`, for every local persona
  --per-persona   one App per local persona (`agent-build`, `agent-plan`, ...), each with only
                  the permissions it needs; the mapping is written to ~/.config/sdlc/personas.conf

How it works: a small server on 127.0.0.1 serves a page that posts each App's manifest to
GitHub. You click "Create GitHub App"; GitHub redirects back here with a one-time code, which is
exchanged for the App's id and private key (POST /app-manifests/{code}/conversions). The key
goes into the keyring, the id and slug into ~/.config/sdlc/<identity>.env, and the browser moves
on to the App's install page. After you install it, GitHub sends you back here for the next App.

Standard library only, so consumers need nothing installed. Env: SDLC_GITHUB_WEB and
SDLC_GITHUB_API override github.com (tests); SDLC_AGENT_KEY_STORE_DIR stores keys as files in
that directory instead of the keyring (machines without secret-tool).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import secrets
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

GITHUB = os.environ.get("SDLC_GITHUB_WEB", "https://github.com")
API = os.environ.get("SDLC_GITHUB_API", "https://api.github.com")
NAME_LIMIT = 34  # GitHub App names are at most 34 characters

# What every Claude identity needs: commit and push, open PRs, comment and label, read CI.
BASE_PERMISSIONS = {
    "contents": "write",
    "pull_requests": "write",
    "issues": "write",
    "metadata": "read",
    "actions": "read",
    "checks": "read",
    "statuses": "read",
}
# Only personas that may change .github/workflows/ get the workflows permission.
WORKFLOW_PERSONAS = {"build", "dev"}


@dataclass
class Identity:
    name: str
    personas: list[str]
    app_name: str
    slug: str = ""
    app_id: int = 0

    @property
    def permissions(self) -> dict[str, str]:
        perms = dict(BASE_PERMISSIONS)
        if WORKFLOW_PERSONAS & set(self.personas):
            perms["workflows"] = "write"
        return perms


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "sdlc"


def read_registry(path: Path) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    """Identity kinds by name, and (persona, identity, where) rows, from personas.conf."""
    kinds: dict[str, str] = {}
    personas: list[tuple[str, str, str]] = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "identity":
            kinds[parts[1]] = parts[2]
        elif len(parts) >= 4 and parts[0] == "persona":
            personas.append((parts[1], parts[2], parts[3]))
    return kinds, personas


def plan(registry: Path, per_persona: bool, prefix: str) -> list[Identity]:
    kinds, personas = read_registry(registry)
    local = [
        p for p, ident, where in personas if where == "local" and kinds.get(ident) == "github-app"
    ]
    if not local:
        raise SystemExit(f"no local github-app personas in {registry}")
    if not per_persona:
        return [Identity("agent", local, prefix[:NAME_LIMIT])]
    return [Identity(f"agent-{p}", [p], f"{prefix}-{p}"[:NAME_LIMIT]) for p in local]


def manifest(identity: Identity, base_url: str, owner: str) -> dict:
    return {
        "name": identity.app_name,
        "url": f"{GITHUB}/{owner}",
        "description": f"Claude ({', '.join(identity.personas)}) for the claude-sdlc pipeline.",
        "public": False,
        "hook_attributes": {"url": f"{base_url}/hook", "active": False},
        "redirect_url": f"{base_url}/created",
        "setup_url": f"{base_url}/installed",
        "default_permissions": identity.permissions,
        "default_events": [],
    }


def convert(code: str) -> dict:
    """Exchange the one-time code for the App's id, slug and private key."""
    request = urllib.request.Request(
        f"{API}/app-manifests/{quote(code)}/conversions",
        method="POST",
        headers={"Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def bot_id(slug: str) -> int:
    try:
        with urllib.request.urlopen(f"{API}/users/{quote(slug)}%5Bbot%5D", timeout=30) as r:
            return int(json.load(r)["id"])
    except (urllib.error.URLError, KeyError, ValueError):
        return 0


def store_key(identity: str, pem: str) -> str:
    store = os.environ.get("SDLC_AGENT_KEY_STORE_DIR")
    if store:
        path = Path(store) / f"{identity}.pem"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600)
        path.write_text(pem)
        return str(path)
    label = f"claude-sdlc GitHub App private key ({identity})"
    subprocess.run(
        ["secret-tool", "store", "--label", label, "service", "claude-sdlc",
         "account", f"github-app-private-key:{identity}"],
        input=pem, text=True, check=True,
    )  # fmt: skip
    return f"keyring ({label})"


def write_config(identity: Identity, bot: int) -> Path:
    path = config_dir() / f"{identity.name}.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# claude-sdlc agent identity (scripts/agent-identity.sh). Not secret: the key is in"
        " the keyring.\n"
        f"SDLC_AGENT_APP_ID={identity.app_id}\n"
        f"SDLC_AGENT_APP_SLUG={identity.slug}\n"
        f"SDLC_AGENT_BOT_ID={bot}\n"
    )
    return path


def write_personas_override(registry: Path, identities: list[Identity], per_persona: bool) -> str:
    """Per-persona: point each persona at its own App in ~/.config/sdlc/personas.conf, which
    overrides the repo's copy (that one is framework-owned and replaced by make sync-sdlc).
    One App: remove any earlier override, so everything maps to `agent` again."""
    override = config_dir() / "personas.conf"
    if not per_persona:
        if override.exists():
            override.rename(override.with_suffix(".conf.bak"))
            return f"moved the old per-persona mapping to {override.with_suffix('.conf.bak')}"
        return "the repo's .claude/personas.conf applies (one App: agent)"
    by_persona = {p: i.name for i in identities for p in i.personas}
    lines = []
    for line in registry.read_text().splitlines():
        parts = line.split()
        if parts[:1] == ["persona"] and len(parts) >= 4:
            target = by_persona.get(parts[1]) or (
                by_persona.get("spec") if parts[1] == "spec-ci" else None
            )
            if target:
                line = line.replace(f" {parts[2]} ", f" {target} ", 1)
        lines.append(line)
        if parts[:2] == ["identity", "agent"]:
            for i in identities:
                lines.append(
                    f"identity {i.name}  github-app  ~/.config/sdlc/{i.name}.env + keyring"
                )
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text(
        "# Per-persona Apps, written by scripts/agent-identity.sh create --per-persona.\n"
        + "\n".join(lines)
        + "\n"
    )
    return f"wrote the per-persona mapping to {override}"


@dataclass
class Flow:
    identities: list[Identity]
    owner: str
    org: str | None
    index: int = 0
    state: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    done: threading.Event = field(default_factory=threading.Event)
    log: list[str] = field(default_factory=list)

    @property
    def current(self) -> Identity | None:
        return self.identities[self.index] if self.index < len(self.identities) else None

    def advance(self) -> None:
        self.index += 1
        self.state = secrets.token_urlsafe(16)
        if self.current is None:
            self.done.set()


def page(title: str, body: str) -> bytes:
    return (
        f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>"
        "<body style='font:16px system-ui;max-width:40em;margin:3em auto'>"
        f"<h1>{html.escape(title)}</h1>{body}</body>"
    ).encode()


def make_handler(flow: Flow):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:  # keep the terminal quiet
            pass

        def send(self, status: int, body: bytes = b"", location: str | None = None) -> None:
            self.send_response(status)
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (http.server's name)
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            base = f"http://{self.headers['Host']}"
            if url.path in ("/", "/start"):
                self.start(base)
            elif url.path == "/created":
                self.created(query)
            elif url.path in ("/installed", "/next"):
                flow.advance()
                self.send(302, location=f"{base}/start")
            else:
                self.send(404, page("Not found", ""))

        def start(self, base: str) -> None:
            ident = flow.current
            if ident is None:
                done = "".join(f"<li>{html.escape(line)}</li>" for line in flow.log)
                self.send(200, page("All done", f"<ul>{done}</ul><p>Back to the terminal.</p>"))
                flow.done.set()
                return
            target = (
                f"{GITHUB}/organizations/{flow.org}/settings/apps/new"
                if flow.org
                else f"{GITHUB}/settings/apps/new"
            )
            data = html.escape(json.dumps(manifest(ident, base, flow.org or flow.owner)))
            n, total = flow.index + 1, len(flow.identities)
            self.send(
                200,
                page(
                    f"Create {ident.app_name} ({n} of {total})",
                    f"<p>For: {html.escape(', '.join(ident.personas))}. GitHub will ask you to "
                    "confirm the name and create the App, then to install it.</p>"
                    f"<form id=f method=post action='{target}?state={flow.state}'>"
                    f"<input type=hidden name=manifest value='{data}'>"
                    "<button>Continue to GitHub</button></form>"
                    "<script>document.getElementById('f').submit()</script>",
                ),
            )

        def created(self, query: dict[str, str]) -> None:
            ident = flow.current
            if ident is None or query.get("state") != flow.state or "code" not in query:
                self.send(
                    400, page("Unexpected request", "<p>State didn't match. Start again.</p>")
                )
                return
            try:
                app = convert(query["code"])
            except urllib.error.URLError as err:
                self.send(502, page("GitHub refused the code", f"<p>{html.escape(str(err))}</p>"))
                return
            ident.slug, ident.app_id = app["slug"], int(app["id"])
            where = store_key(ident.name, app["pem"])
            config = write_config(ident, bot_id(ident.slug))
            flow.log.append(f"{ident.name}: {ident.slug}[bot] (app {ident.app_id}), key in {where}")
            print(f"  created {ident.slug} (app {ident.app_id}); config {config}", flush=True)
            self.send(302, location=f"{GITHUB}/apps/{ident.slug}/installations/new")

    return Handler


def owner_from_git() -> str:
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    path = url.removesuffix(".git").split("github.com")[-1].lstrip(":/")
    return path.split("/")[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-identity.sh create", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--per-persona", action="store_true", help="one App per local persona")
    parser.add_argument(
        "--name", help="App name (prefix with --per-persona); default <owner>-claude"
    )
    parser.add_argument("--org", help="create the Apps under this organization, not your account")
    parser.add_argument("--registry", type=Path, help="personas.conf (default: the repo's)")
    parser.add_argument("--port", type=int, default=0, help="local port (default: any free one)")
    parser.add_argument("--no-browser", action="store_true", help="print the URL instead")
    args = parser.parse_args(argv)

    registry = args.registry or Path(__file__).resolve().parents[1] / ".claude" / "personas.conf"
    owner = args.org or owner_from_git()
    if not owner and not args.name:
        raise SystemExit("can't tell the GitHub owner from origin; pass --name or --org")
    identities = plan(registry, args.per_persona, args.name or f"{owner}-claude")

    flow = Flow(identities, owner, args.org)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(flow))
    url = f"http://127.0.0.1:{server.server_address[1]}/start"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    names = ", ".join(i.app_name for i in identities)
    print(f"Creating {len(identities)} GitHub App(s): {names}")
    print(f"Open {url} if your browser doesn't. If you skip an install page, open .../next.")
    if not args.no_browser:
        webbrowser.open(url)
    finished = flow.done.wait(timeout=30 * 60)
    server.shutdown()
    if not finished:
        print("timed out after 30 minutes; Apps created so far are kept", file=sys.stderr)
    print(write_personas_override(registry, identities, args.per_persona))
    for line in flow.log:
        print(f"  {line}")
    if flow.log:
        print("Next, in each repo: scripts/bootstrap-github.sh --mode team --skip-token")
    return 0 if finished else 1


if __name__ == "__main__":
    sys.exit(main())
