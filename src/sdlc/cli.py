"""`sdlc` command: scaffold changes and validate the artifact chain."""

from __future__ import annotations

import argparse
import json
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
    definition_of_done,
    next_slug,
    placeholders,
    stage,
)
from sdlc.clauses import ClauseError, change_blocks
from sdlc.roadmap import check_roadmap
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
# output (one `git add -A` once committed ~82,000 files). Override with SDLC_MAX_CHANGED_FILES,
# or, where an environment variable can't be set (a PR's CI run), with a commit on the branch
# carrying a `Large-change: <reason>` trailer.
MAX_CHANGED_FILES = 300
LARGE_CHANGE_TRAILER = "Large-change"


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return None
    return result.stdout if result.returncode == 0 else None


def merge_base(root: Path) -> str | None:
    """Where this branch left main, or None (not a git checkout, or no main to compare with)."""
    for base in ("origin/main", "main"):
        found = _git(root, "merge-base", base, "HEAD")
        if found:
            return found.strip()
    return None


def branch_changes(root: Path) -> set[Path] | None:
    """Files the branch adds or edits against main, committed or not (plan.md is validated before
    it's committed), as resolved paths. None when there's no main to compare with."""
    base = merge_base(root)
    if base is None:
        return None
    edited = _git(root, "diff", "--name-only", "--relative", base) or ""
    untracked = _git(root, "ls-files", "--others", "--exclude-standard") or ""
    names = [n for n in (edited + "\n" + untracked).splitlines() if n]
    return {(root / n).resolve() for n in names}


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
    base = merge_base(root)
    if base is None:
        return problems  # no main to compare with, e.g. a shallow CI checkout
    changed = _git(root, "diff", "--name-only", base, "HEAD") or ""
    count = len([line for line in changed.splitlines() if line])
    limit = int(os.environ.get("SDLC_MAX_CHANGED_FILES", MAX_CHANGED_FILES))
    if count > limit:
        trailers = _git(
            root,
            "log",
            f"--format=%(trailers:key={LARGE_CHANGE_TRAILER},valueonly,separator=%x0a)",
            f"{base}..HEAD",
        )
        reasons = [r.strip() for r in (trailers or "").splitlines() if r.strip()]
        if reasons:
            # Allowed, but say so in the check output, so the reviewer sees why.
            print(
                f"note: this branch changes {count} files against main (limit {limit}), "
                f"allowed by {LARGE_CHANGE_TRAILER}: {'; '.join(reasons)}",
                file=sys.stderr,
            )
        else:
            problems.append(
                f"this branch changes {count} files against main (limit {limit}); that usually "
                "means dependencies or build output were committed. Check `git diff --stat "
                "main...HEAD`. If it's really intended, add a commit with the trailer "
                f'`{LARGE_CHANGE_TRAILER}: <reason>` (`git commit --allow-empty -m "chore: '
                f'large change" -m "{LARGE_CHANGE_TRAILER}: <reason>"`), or set '
                "SDLC_MAX_CHANGED_FILES locally"
            )
    return problems


def cmd_check(root: Path) -> int:
    words = placeholders(root)
    changed = branch_changes(root)
    dod = definition_of_done(root)
    problems: list[object] = [
        p for d in change_dirs(root) for p in check_change(d, words, changed, dod)
    ]
    problems += dod.problems
    problems += check_adrs(root, words)
    problems += check_config(root)
    problems += check_commits(root)
    problems += check_roadmap(root)
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


def find_change(root: Path, name: str) -> Path | None:
    """A change folder from a path, a full slug or its number (`0002`)."""
    if (path := Path(name)).is_dir():
        return path
    if (path := root / name).is_dir():
        return path
    found = [d for d in change_dirs(root) if d.name == name or d.name.split("-")[0] == name]
    return found[0] if len(found) == 1 else None


def cmd_clauses(root: Path, name: str, ref: str | None) -> int:
    change_dir = find_change(root, name)
    if change_dir is None:
        print(f"no change matching {name!r}", file=sys.stderr)
        return 1
    try:
        found, lost = change_blocks(root, change_dir, ref)
    except ClauseError as e:
        print(f"{change_dir}: {e}", file=sys.stderr)
        return 1
    for line in lost:
        print(
            f"{change_dir}: warning: can't read this as a requirement "
            f"(expected '- R<n>. <requirement>'): {line}",
            file=sys.stderr,
        )
    output = {"change": change_dir.name, "requirements": found, "unreadable": lost}
    print(json.dumps(output, indent=2))
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

    cl = sub.add_parser(
        "clauses",
        help="split a spec into one block per requirement, with the criteria and plan lines "
        "that cite it (JSON)",
    )
    cl.add_argument("change", help="a change: 0002, 0002-name, or a folder path")
    cl.add_argument("--ref", help="only the requirements that are new or differ from this git ref")

    args = parser.parse_args(argv)
    if args.command == "new":
        return cmd_new(args.root, args.name, args.kind)
    if args.command == "check":
        return cmd_check(args.root)
    if args.command == "clauses":
        return cmd_clauses(args.root, args.change, args.ref)
    if args.command == "next":
        return cmd_next(args.root, args.ref, args.slug)
    return cmd_status(args.root)


if __name__ == "__main__":
    sys.exit(main())
