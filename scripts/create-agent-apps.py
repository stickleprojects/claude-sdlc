#!/usr/bin/env python3
"""Create Claude's GitHub App identities with GitHub's App manifest flow.

Usage: scripts/agent-identity.sh create [--per-persona | --groups G] [--name PREFIX] [--org ORG]
                                        [--yes] [--no-browser]

  (no flags, in a terminal)  asks: one App for everything, or one per persona, and for each
                             persona whether to reuse an App already chosen; then shows what it
                             will create and asks to continue before opening the browser
  (no flags, no terminal)    one App, `agent`, for every local persona
  --per-persona              one App per local persona (`agent-build`, `agent-plan`, ...)
  --groups G                 your own grouping, e.g. "intent+spec+plan+po-review,build+dev"
  --yes                      don't ask to confirm

Each App gets only the permissions its personas need. Anything other than one App writes the
persona-to-App mapping to ~/.config/sdlc/personas.conf.

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


def local_personas(registry: Path) -> list[str]:
    kinds, personas = read_registry(registry)
    local = [
        p for p, ident, where in personas if where == "local" and kinds.get(ident) == "github-app"
    ]
    if not local:
        raise SystemExit(f"no local github-app personas in {registry}")
    return local


def build_identities(groups: list[list[str]], local: list[str], prefix: str) -> list[Identity]:
    """One Identity per group of personas. A single group holding every persona is `agent`;
    any other group is named after its first persona (agent-build serves build and dev)."""
    seen = [p for g in groups for p in g]
    if sorted(seen) != sorted(local) or len(seen) != len(set(seen)):
        raise SystemExit(f"each of these personas must be in exactly one group: {', '.join(local)}")
    if len(groups) == 1:
        return [Identity("agent", list(groups[0]), prefix[:NAME_LIMIT])]
    return [Identity(f"agent-{g[0]}", list(g), f"{prefix}-{g[0]}"[:NAME_LIMIT]) for g in groups]


def plan(registry: Path, per_persona: bool, prefix: str) -> list[Identity]:
    local = local_personas(registry)
    groups = [[p] for p in local] if per_persona else [local]
    return build_identities(groups, local, prefix)


def parse_groups(text: str) -> list[list[str]]:
    return [[p.strip() for p in g.split("+") if p.strip()] for g in text.split(",") if g.strip()]


def _pick(ask, question: str, options: list[str], default: int = 1) -> int:
    """Ask until the answer is one of the numbered options; Enter takes the default."""
    while True:
        print(question)
        for n, option in enumerate(options, 1):
            print(f"  {n}) {option}")
        answer = ask(f"Choice [{default}]: ").strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer)
        print(f"  please answer 1-{len(options)}")


def _pick_many(ask, question: str, options: list[str]) -> list[int]:
    """Ask for a comma-separated list of option numbers; Enter takes all of them."""
    while True:
        print(question)
        for n, option in enumerate(options, 1):
            print(f"  {n}) {option}")
        answer = ask("Numbers, comma-separated [all]: ").strip()
        if not answer:
            return list(range(1, len(options) + 1))
        parts = [a.strip() for a in answer.split(",") if a.strip()]
        if parts and all(a.isdigit() and 1 <= int(a) <= len(options) for a in parts):
            return sorted({int(a) for a in parts})
        print(f"  please answer with numbers 1-{len(options)}, e.g. 1,3")


def choose_groups(local: list[str], prefix: str, ask=input) -> list[list[str]]:
    """Ask: one App for everything, or Apps per persona. With Apps per persona, first pick
    which personas get an App of their own, then which of those each other persona shares."""
    one = f"One App for everything ({prefix}): every persona signs as itself (recommended)"
    each = "Apps per persona: choose which personas get their own App; the rest share one of them"
    if _pick(ask, "How many GitHub Apps should Claude use?", [one, each]) == 1:
        return [local]
    owners = [
        local[n - 1] for n in _pick_many(ask, "\nWhich personas get an App of their own?", local)
    ]
    groups = {owner: [owner] for owner in owners}
    for persona in local:
        if persona in groups:
            continue
        apps = [f"{prefix}-{owner}" for owner in owners]
        choice = _pick(ask, f"\n{persona}: which App does it share?", apps)
        groups[owners[choice - 1]].append(persona)
    return [groups[owner] for owner in owners]


def describe(identities: list[Identity]) -> str:
    lines = [f"About to create {len(identities)} GitHub App(s):"]
    for i in identities:
        extra = "  (can change .github/workflows)" if "workflows" in i.permissions else ""
        lines.append(f"  {i.app_name:<34}  for {', '.join(i.personas)}{extra}")
    lines.append(
        "For each one, your browser opens GitHub: click Create GitHub App, then install it"
        " on your repos."
    )
    return "\n".join(lines)


def confirm(identities: list[Identity], ask=input) -> bool:
    print(describe(identities))
    return ask("Continue? [Y/n] ").strip().lower() in ("", "y", "yes")


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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--per-persona", action="store_true", help="one App per local persona")
    mode.add_argument("--groups", help='personas sharing an App, e.g. "intent+spec,build+dev"')
    parser.add_argument("--yes", action="store_true", help="don't ask to confirm")
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
    prefix = args.name or f"{owner}-claude"
    local = local_personas(registry)
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if args.groups:
        groups = parse_groups(args.groups)
    elif args.per_persona:
        groups = [[p] for p in local]
    elif interactive:
        groups = choose_groups(local, prefix)
    else:
        groups = [local]
    identities = build_identities(groups, local, prefix)
    if interactive and not args.yes and not confirm(identities):
        print("Nothing created.")
        return 1

    flow = Flow(identities, owner, args.org)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(flow))
    url = f"http://127.0.0.1:{server.server_address[1]}/start"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if not interactive:
        print(describe(identities))
    print(f"Open {url} if your browser doesn't. If you skip an install page, open .../next.")
    if not args.no_browser:
        webbrowser.open(url)
    finished = flow.done.wait(timeout=30 * 60)
    server.shutdown()
    if not finished:
        print("timed out after 30 minutes; Apps created so far are kept", file=sys.stderr)
    print(write_personas_override(registry, identities, per_persona=len(identities) > 1))
    for line in flow.log:
        print(f"  {line}")
    if flow.log:
        print("Next, in each repo: scripts/bootstrap-github.sh --mode team --skip-token")
    return 0 if finished else 1


if __name__ == "__main__":
    sys.exit(main())
