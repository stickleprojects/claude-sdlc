"""`sdlc` command: scaffold changes and validate the artifact chain."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from sdlc.artifacts import change_dirs, check_change, next_slug, stage

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def cmd_new(root: Path, name: str) -> int:
    if not NAME_RE.match(name):
        print(f"name must be kebab-case, got {name!r}", file=sys.stderr)
        return 2
    slug = next_slug(root, name)
    target = root / "changes" / slug
    target.mkdir(parents=True)
    shutil.copy(root / "templates" / "intent.md", target / "intent.md")
    print(target / "intent.md")
    return 0


def cmd_check(root: Path) -> int:
    problems = [p for d in change_dirs(root) for p in check_change(d)]
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"ok: {len(change_dirs(root))} change(s) valid")
    return 1 if problems else 0


def cmd_status(root: Path) -> int:
    for d in change_dirs(root):
        print(f"{d.name}\t{stage(d)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sdlc")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="start a change from templates/intent.md")
    new.add_argument("name", help="kebab-case name, e.g. add-login")
    sub.add_parser("check", help="validate every change folder")
    sub.add_parser("status", help="show the stage each change has reached")

    args = parser.parse_args(argv)
    if args.command == "new":
        return cmd_new(args.root, args.name)
    if args.command == "check":
        return cmd_check(args.root)
    return cmd_status(args.root)


if __name__ == "__main__":
    sys.exit(main())
