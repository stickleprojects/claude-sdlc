#!/usr/bin/env python3
"""Create Claude's GitHub App identity with GitHub's App manifest flow.

Usage: scripts/agent-identity.sh create [--name PREFIX] [--org ORG] [--yes] [--no-browser]

Run it in each repo that uses the pipeline: the App belongs to that repo, and is named after it
(<prefix>-claude). It's the identity `agent`, used by every Claude session in the repo and by
the spec workflow, so Claude never acts as the person.

  (in a terminal)  asks whether to reuse an App already on this machine, then for the name
                   prefix (default: the repo's name, made safe); shows what it will create and
                   asks to continue before any browser opens
  --yes            don't ask to confirm

How it works: a small server on 127.0.0.1 serves a page that posts the App's manifest to
GitHub. You click "Create GitHub App"; GitHub redirects back here with a one-time code, which is
exchanged for the App's id and private key (POST /app-manifests/{code}/conversions). The key
goes into the keyring, the id and slug into ~/.config/sdlc/<identity>.env, and the browser moves
on to the App's install page. After you install it, GitHub sends you back here.

Standard library only, so consumers need nothing installed. Env: SDLC_GITHUB_WEB and
SDLC_GITHUB_API override github.com (tests); SDLC_AGENT_KEY_STORE_DIR stores keys as files in
that directory instead of the keyring (machines without secret-tool).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
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
SUFFIX = "-claude"
PREFIX_LIMIT = NAME_LIMIT - len(SUFFIX)
# owner_repo of the repo the App is for. Its config and key are kept apart
# from other repos': ~/.config/sdlc/<owner>_<repo>/. Set by main(); tests set it directly.
REPO_KEY = ""
# Where new Apps' private keys go: None means the keyring. --keys-dir or SDLC_AGENT_KEY_STORE_DIR.
KEYS_DIR: Path | None = None

# What Claude needs: commit and push (workflows too, since builds may change CI), open PRs,
# comment and label, read CI, and read repo variables (scripts/auto-merge.sh reads
# SDLC_AUTO_MERGE from a session).
PERMISSIONS = {
    "contents": "write",
    "pull_requests": "write",
    "issues": "write",
    "metadata": "read",
    "actions": "read",
    "checks": "read",
    "statuses": "read",
    "workflows": "write",
    "actions_variables": "read",
}


@dataclass
class Identity:
    name: str
    app_name: str
    slug: str = ""
    app_id: int = 0
    existing: Path | None = None  # reuse the App in this config file: nothing is created
    config_path: Path | None = None  # write the new App's config here, not the default place

    @property
    def permissions(self) -> dict[str, str]:
        return dict(PERMISSIONS)


def config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "sdlc"
    return base / REPO_KEY if REPO_KEY else base


def safe_prefix(name: str) -> str:
    """A GitHub-App-safe name prefix: lowercase letters, digits and single dashes, short enough
    for the "-claude" suffix. "JobHunt_App" -> "jobhunt-app"."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return cleaned[:PREFIX_LIMIT].rstrip("-")


def repo_key(repo: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", repo.lower().replace("/", "_"))


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


def new_identity(prefix: str) -> Identity:
    return Identity("agent", f"{prefix}{SUFFIX}"[:NAME_LIMIT])


def choose_existing(existing: list[tuple[str, Path]], ask=input):
    """First question when Apps already exist on this machine: reuse one here?
    Returns an Identity reusing it, or None to create a new App."""
    if not existing:
        return None
    options = ["No: create a new App for this repo"]
    options += [f"Yes: use {slug} ({path})" for slug, path in existing]
    choice = _pick(ask, "Claude already has GitHub Apps on this machine. Reuse one here?", options)
    if choice == 1:
        return None
    slug, path = existing[choice - 2]
    return Identity("agent", slug, slug=slug, existing=path)


def describe(identities: list[Identity]) -> str:
    new = [i for i in identities if i.existing is None]
    reused = [i for i in identities if i.existing is not None]
    lines = []
    if new:
        lines.append("\nAbout to create 1 GitHub App, for every Claude session in this repo:")
        for i in new:
            lines.append(f"  {i.app_name:<34}  (can change .github/workflows)")
            lines.append(f"  {'':<34}  config: {target_of(i)}")
    if reused:
        lines.append("\nReusing (nothing created, no key changed):")
        for i in reused:
            lines.append(f"  {i.app_name:<34}  ({i.existing})")
    if new:
        lines.append(
            "Your browser opens GitHub: click Create GitHub App, then install it on this repo."
        )
    if reused:
        lines.append("A reused App must also be installed on this repo; you'll get the link.")
    return "\n".join(lines)


def confirm(identities: list[Identity], ask=input) -> bool:
    print(describe(identities))
    return ask("Continue? [Y/n] ").strip().lower() in ("", "y", "yes")


def manifest(identity: Identity, base_url: str, owner: str, repo: str = "") -> dict:
    return {
        "name": identity.app_name,
        "url": f"{GITHUB}/{repo or owner}",
        "description": f"Claude for {repo or owner}, via the claude-sdlc pipeline.",
        "public": False,
        # No hook_attributes: the App uses no webhook, and GitHub rejects a hook URL it can't
        # reach from the internet, even an inactive one (#102). The localhost redirect and
        # setup URLs are accepted.
        "redirect_url": f"{base_url}/created",
        "setup_url": f"{base_url}/installed",
        "default_permissions": identity.permissions,
        "default_events": [],
    }


class ConversionError(Exception):
    """GitHub didn't hand over the new App's credentials; the message says why, for a person."""


def convert(code: str) -> dict:
    """Exchange the one-time code for the App's id, slug and private key.

    Not retried: the code works once, so a second POST after a timeout would fail even if the
    first one succeeded. Every failure becomes a ConversionError with a readable reason."""
    request = urllib.request.Request(
        f"{API}/app-manifests/{quote(code)}/conversions",
        method="POST",
        headers={"Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            app = json.load(response)
    except urllib.error.HTTPError as err:
        detail = ""
        try:
            detail = json.load(err).get("message", "")
        except (ValueError, AttributeError, OSError):
            pass
        reasons = {
            404: "the code has expired or was already used (each code works once, for an hour)",
            422: "GitHub couldn't make the App from the manifest",
            401: "GitHub refused the request",
            403: "GitHub refused the request",
        }
        reason = reasons.get(err.code) or (
            f"GitHub had an error ({err.code})" if err.code >= 500 else f"HTTP {err.code}"
        )
        raise ConversionError(f"{reason}{': ' + detail if detail else ''}") from err
    except (TimeoutError, urllib.error.URLError) as err:
        raise ConversionError(f"GitHub didn't answer ({getattr(err, 'reason', err)})") from err
    except ValueError as err:
        raise ConversionError("GitHub's reply wasn't JSON") from err
    if not isinstance(app, dict):
        raise ConversionError("GitHub's reply wasn't an App")
    missing = [k for k in ("id", "slug", "pem") if not app.get(k)]
    if missing or not str(app["pem"]).startswith("-----BEGIN"):
        raise ConversionError(f"GitHub's reply is missing the App's {', '.join(missing) or 'key'}")
    return app


def recovery_hint(app_name: str, identity: str) -> str:
    """What to do when an App may exist on GitHub without its key here: it was created but
    the code exchange failed, or GitHub said the name is taken because it was made before."""
    return (
        f"{app_name} may already exist on GitHub without its key on this machine. Either:\n"
        f"  - keep it: open {GITHUB}/settings/apps/{app_name}, click 'Generate a private key',"
        f" then run\n    scripts/agent-identity.sh setup --identity {identity}"
        " --app-id <its App ID> --key <downloaded .pem>\n"
        f"  - or delete it on that page (Advanced, Delete GitHub App) and run create again\n"
        "  - or run create again with another --name"
    )


def bot_id(slug: str) -> int:
    try:
        with urllib.request.urlopen(f"{API}/users/{quote(slug)}%5Bbot%5D", timeout=30) as r:
            return int(json.load(r)["id"])
    except (urllib.error.URLError, KeyError, ValueError):
        return 0


def store_key(slug: str, pem: str) -> str:
    """Store a new App's private key under the App's own name, which is unique on GitHub, so
    no other App's key (in any repo) can be overwritten. Returns the reference the config
    records: keyring:<account> or file:<path>."""
    if KEYS_DIR:
        path = KEYS_DIR / f"{slug}.pem"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600)
        path.chmod(0o600)
        path.write_text(pem)
        return f"file:{path.resolve()}"
    account = f"github-app-private-key:{slug}"
    subprocess.run(
        ["secret-tool", "store", "--label", f"claude-sdlc GitHub App private key ({slug})",
         "service", "claude-sdlc", "account", account],
        input=pem, text=True, check=True,
    )  # fmt: skip
    return f"keyring:{account}"


def default_config(identity: str) -> Path:
    """Where agent-identity.sh looks for this repo's identity: a config, or a pointer to one."""
    return config_dir() / f"{identity}.env"


def parse_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
    return values


def write_pointer(at: Path, target: Path) -> None:
    at.parent.mkdir(parents=True, exist_ok=True)
    at.write_text(
        "# Points this repo's identity at a config kept elsewhere (agent-identity.sh).\n"
        f"SDLC_AGENT_USE={target.resolve()}\n"
    )


def write_config(identity: Identity, bot: int, key_ref: str) -> Path:
    """Write the new App's config where asked (default: this repo's config folder). Anywhere
    else, the default place gets a pointer to it."""
    default = default_config(identity.name)
    path = identity.config_path or default
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# claude-sdlc agent identity (scripts/agent-identity.sh). Not secret: the key is at\n"
        "# SDLC_AGENT_KEY. Several repos may point at this file to share the App.\n"
        f"SDLC_AGENT_APP_ID={identity.app_id}\n"
        f"SDLC_AGENT_APP_SLUG={identity.slug}\n"
        f"SDLC_AGENT_BOT_ID={bot}\n"
        f"SDLC_AGENT_KEY={key_ref}\n"
    )
    if path.resolve() != default.resolve():
        write_pointer(default, path)
    return path


def link_existing(identity: Identity) -> Path:
    """Point this repo's identity at an existing App's config. Creates nothing on GitHub and
    copies no key, so the App and its key stay shared."""
    default = default_config(identity.name)
    assert identity.existing is not None
    if identity.existing.resolve() != default.resolve():
        write_pointer(default, identity.existing)
    return identity.existing


def find_existing_apps(extra: list[Path] = ()) -> list[tuple[str, Path]]:
    """(slug, config file) for every App config on this machine, under ~/.config/sdlc and any
    extra paths; pointers are followed to the file they name. One entry per file."""
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "sdlc"
    found: dict[Path, str] = {}
    candidates = sorted(base.rglob("*.env")) if base.is_dir() else []
    for path in [*candidates, *extra]:
        try:
            values = parse_env(path)
            if "SDLC_AGENT_USE" in values:
                path = Path(values["SDLC_AGENT_USE"])
                values = parse_env(path)
        except OSError:
            continue
        if values.get("SDLC_AGENT_APP_SLUG") and values.get("SDLC_AGENT_APP_ID"):
            found.setdefault(path.resolve(), values["SDLC_AGENT_APP_SLUG"])
    return [(slug, path) for path, slug in found.items()]


def target_of(identity: Identity) -> Path:
    return identity.config_path or default_config(identity.name)


def clashes(identities: list[Identity]) -> list[Path]:
    """Config files that this run would replace with something else: the new App's config,
    or this repo's default config, which may become a pointer. A file that already is, or
    already points at, what it would be written as isn't a clash."""
    out: list[Path] = []
    for i in identities:
        targets = {default_config(i.name)}
        if i.existing is None:
            targets.add(target_of(i))
        for t in targets:
            if not t.exists():
                continue
            if i.existing is not None:
                same = t.resolve() == i.existing.resolve()
                points = parse_env(t).get("SDLC_AGENT_USE") == str(i.existing.resolve())
                if same or points:
                    continue
            out.append(t)
    return sorted(set(out))


@dataclass
class Flow:
    identities: list[Identity]
    owner: str
    org: str | None
    repo: str = ""
    index: int = 0
    state: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    done: threading.Event = field(default_factory=threading.Event)
    log: list[str] = field(default_factory=list)
    skipped: list[Identity] = field(default_factory=list)

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
                ident = flow.current
                if ident is not None and not ident.slug:  # skipped before it was created
                    flow.skipped.append(ident)
                    print(f"  skipped {ident.app_name}", flush=True)
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
            data = html.escape(json.dumps(manifest(ident, base, flow.org or flow.owner, flow.repo)))
            n, total = flow.index + 1, len(flow.identities)
            self.send(
                200,
                page(
                    f"Create {ident.app_name} ({n} of {total})",
                    "<p>For every Claude session in this repo. GitHub will ask you to "
                    "confirm the name and create the App, then to install it.</p>"
                    "<p>If GitHub asks you to sign in, do, then come back to this page: the"
                    " form may not survive the sign-in. If GitHub says the name is taken, you"
                    " probably made this App before: <a href='/next'>skip it</a>, and the"
                    " terminal will say how to reuse it.</p>"
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
            except ConversionError as err:
                flow.state = secrets.token_urlsafe(16)  # the old code is spent either way
                hint = recovery_hint(ident.app_name, ident.name)
                print(f"  {ident.app_name}: {err}\n{hint}", file=sys.stderr, flush=True)
                self.send(
                    502,
                    page(
                        f"{ident.app_name}: GitHub didn't hand over the App",
                        f"<p>{html.escape(str(err))}.</p><pre>{html.escape(hint)}</pre>"
                        "<p><a href='/start'>Try again</a> (if GitHub then says the name is"
                        " taken, use one of the options above) or <a href='/next'>skip this"
                        " App</a>.</p>",
                    ),
                )
                return
            ident.slug, ident.app_id = app["slug"], int(app["id"])
            where = store_key(ident.slug, app["pem"])
            config = write_config(ident, bot_id(ident.slug), where)
            flow.log.append(f"{ident.name}: {ident.slug}[bot] (app {ident.app_id}), key at {where}")
            print(f"  created {ident.slug} (app {ident.app_id}); config {config}", flush=True)
            self.send(302, location=f"{GITHUB}/apps/{ident.slug}/installations/new")

    return Handler


def repo_from_git() -> str:
    """owner/name of origin, or "" outside a GitHub checkout. SDLC_AGENT_REPO overrides it."""
    if os.environ.get("SDLC_AGENT_REPO"):
        return os.environ["SDLC_AGENT_REPO"]
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    path = url.removesuffix(".git").split("github.com")[-1].lstrip(":/")
    return path if path.count("/") == 1 else ""


def ask_prefix(default: str, ask=input) -> str:
    """The first question: what Claude's Apps for this repo are called."""
    while True:
        answer = ask(f"Name prefix for this repo's Claude Apps [{default}]: ").strip() or default
        prefix = safe_prefix(answer)
        if prefix:
            if prefix != answer:
                print(f"  using {prefix} (lowercase letters, digits and dashes only)")
            return prefix
        print("  please use some letters or digits")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-identity.sh create", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--use", type=Path, metavar="CONFIG", help="reuse this existing App config")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--config", type=Path, help="write the new App's config to this file")
    where.add_argument("--config-dir", type=Path, help="write the new App's config in here")
    parser.add_argument("--keys-dir", type=Path, help="keep private keys here, not the keyring")
    parser.add_argument("--force", action="store_true", help="replace existing configs")
    parser.add_argument("--yes", action="store_true", help="don't ask to confirm")
    parser.add_argument("--name", help="App name prefix; default: the repo's name, made safe")
    parser.add_argument("--org", help="create the App under this organization, not your account")
    parser.add_argument("--port", type=int, default=0, help="local port (default: any free one)")
    parser.add_argument("--no-browser", action="store_true", help="print the URL instead")
    args = parser.parse_args(argv)

    global REPO_KEY, KEYS_DIR
    repo = repo_from_git()
    if not repo:
        raise SystemExit("run this in a repo whose origin is on GitHub (or set SDLC_AGENT_REPO)")
    REPO_KEY = repo_key(repo)
    keys = args.keys_dir or os.environ.get("SDLC_AGENT_KEY_STORE_DIR")
    KEYS_DIR = Path(keys).expanduser() if keys else None
    owner = args.org or repo.split("/")[0]
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    existing = find_existing_apps()

    identities = None
    if args.use:
        found = find_existing_apps([args.use.expanduser()])
        match = [e for e in found if e[1] == args.use.expanduser().resolve()]
        if not match:
            raise SystemExit(f"{args.use} isn't an App config (needs SDLC_AGENT_APP_ID and _SLUG)")
        slug, path = match[0]
        identities = [Identity("agent", slug, slug=slug, existing=path)]
    elif interactive:
        reuse = choose_existing(existing)
        identities = [reuse] if reuse else None
    if identities is None:
        default_prefix = safe_prefix(repo.split("/")[1])
        if args.name:
            prefix = safe_prefix(args.name)
        elif interactive:
            prefix = ask_prefix(default_prefix)
        else:
            prefix = default_prefix
        if not prefix:
            raise SystemExit("the name prefix needs letters or digits")
        identities = [new_identity(prefix)]

    new = [i for i in identities if i.existing is None]
    for i in new:
        if args.config:
            i.config_path = args.config.expanduser()
        elif args.config_dir:
            i.config_path = args.config_dir.expanduser() / f"{i.app_name}.env"

    if interactive and not args.yes and not confirm(identities):
        print("Nothing created.")
        return 1
    replaced = clashes(identities)
    if replaced and not args.force:
        listing = "\n".join(f"  {p}" for p in replaced)
        question = (
            f"These configs already exist and would point at the new App instead:\n{listing}\n"
            "The App they name stays on GitHub, and its key isn't touched. Replace? [y/N] "
        )
        if not (interactive and input(question).strip().lower() in ("y", "yes")):
            print(f"Not replacing:\n{listing}\nUse --force to replace, or --use / --config.")
            return 1

    for i in identities:
        if i.existing is not None:
            link_existing(i)
            print(f"  {i.name}: using {i.slug} ({i.existing})")
            print(f"  install it on {repo}: {GITHUB}/apps/{i.slug}/installations/new")

    finished = True
    flow = Flow(new, owner, args.org, repo)
    if new:
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
    for line in flow.log:
        print(f"  {line}")
    for ident in flow.skipped:
        print(f"Skipped {ident.app_name}. If GitHub said the name is taken:")
        print(recovery_hint(ident.app_name, ident.name))
    print("Next, in this repo: scripts/bootstrap-github.sh --mode team --skip-token")
    return 0 if finished else 1


if __name__ == "__main__":
    sys.exit(main())
