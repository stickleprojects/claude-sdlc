"""`sdlc` command: scaffold changes and validate the artifact chain."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from sdlc.artifacts import (
    build_progress,
    change_dirs,
    check_adrs,
    check_change,
    check_config,
    next_slug,
    placeholders,
    stage,
)
from sdlc.routing import steps

# `make new-change NAME=x TYPE=bug`: make exports command-line variables to recipes, so the
# type arrives as $TYPE even when a consumer's Makefile doesn't pass it on.
KINDS = {"feature": "intent.md", "bug": "bug.md"}

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def cmd_new(root: Path, name: str, kind: str = "feature") -> int:
    if not NAME_RE.match(name):
        print(f"name must be kebab-case, got {name!r}", file=sys.stderr)
        return 2
    if kind not in KINDS:
        print(f"type must be one of {', '.join(KINDS)}, got {kind!r}", file=sys.stderr)
        return 2
    first = KINDS[kind]
    slug = next_slug(root, name)
    target = root / "changes" / slug
    target.mkdir(parents=True)
    shutil.copy(root / "templates" / first, target / first)
    print(target / first)
    return 0


# A branch that changes more files than this almost certainly swept in dependencies or build
# output (one `git add -A` once committed ~82,000 files). Override with SDLC_MAX_CHANGED_FILES.
MAX_CHANGED_FILES = 300


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return None
    return result.stdout if result.returncode == 0 else None


def check_commits(root: Path) -> list[str]:
    """Problems with what is committed: dependency folders, or far too many changed files."""
    problems: list[str] = []
    tracked = _git(root, "ls-files", "-z")
    if tracked is None:
        return problems  # not a git checkout
    vendored = [p for p in tracked.split("\0") if "node_modules" in p.split("/")]
    if vendored:
        problems.append(
            f"{len(vendored)} tracked file(s) under node_modules (e.g. {vendored[0]}); "
            "remove them with `git rm -r --cached` and add node_modules/ to .gitignore"
        )
    for base in ("origin/main", "main"):
        merge_base = _git(root, "merge-base", base, "HEAD")
        if merge_base:
            break
    else:
        return problems  # no main to compare with, e.g. a shallow CI checkout
    changed = _git(root, "diff", "--name-only", merge_base.strip(), "HEAD") or ""
    count = len([line for line in changed.splitlines() if line])
    limit = int(os.environ.get("SDLC_MAX_CHANGED_FILES", MAX_CHANGED_FILES))
    if count > limit:
        problems.append(
            f"this branch changes {count} files against main (limit {limit}); that usually "
            "means dependencies or build output were committed. Check `git diff --stat "
            "main...HEAD`; if it's really intended, set SDLC_MAX_CHANGED_FILES"
        )
    return problems


def cmd_check(root: Path) -> int:
    words = placeholders(root)
    problems: list[object] = [p for d in change_dirs(root) for p in check_change(d, words)]
    problems += check_adrs(root, words)
    problems += check_config(root)
    problems += check_commits(root)
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"ok: {len(change_dirs(root))} change(s) valid")
    return 1 if problems else 0


def cmd_status(root: Path) -> int:
    for d in change_dirs(root):
        progress = build_progress(d)
        print(f"{d.name}\t{stage(d)}" + (f"\t{progress}" if progress else ""))
    return 0


def cmd_next(root: Path, ref: str | None, slug: str | None) -> int:
    found = steps(root, ref, slug)
    for step in found:
        print(step)
    if slug and not found:
        print(f"no change matching {slug!r}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sdlc")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="start a change from templates/intent.md (or bug.md)")
    new.add_argument("name", help="kebab-case name, e.g. add-login")
    new.add_argument(
        "--type",
        dest="kind",
        default=os.environ.get("TYPE") or "feature",
        help="feature (intent.md, the default) or bug (bug.md); defaults to $TYPE",
    )
    sub.add_parser("check", help="validate every change folder and docs/adr")
    sub.add_parser("status", help="show the stage each change has reached")
    nxt = sub.add_parser("next", help="show each change's next step and the skill that owns it")
    nxt.add_argument("slug", nargs="?", help="one change: 0002 or 0002-name")
    nxt.add_argument("--ref", help="read the changes from this git ref, e.g. origin/main")

    args = parser.parse_args(argv)
    if args.command == "new":
        return cmd_new(args.root, args.name, args.kind)
    if args.command == "check":
        return cmd_check(args.root)
    if args.command == "next":
        return cmd_next(args.root, args.ref, args.slug)
    return cmd_status(args.root)


if __name__ == "__main__":
    sys.exit(main())
