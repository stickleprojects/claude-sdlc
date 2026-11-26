"""`sdlc` command: scaffold changes and validate the artifact chain."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from sdlc.artifacts import (
    Problem,
    build_progress,
    change_dirs,
    check_adrs,
    check_change,
    check_config,
    definition_of_done,
    kind,
    next_slug,
    placeholders,
    stage,
)
from sdlc.clauses import STAGE_FIELDS, ClauseError, change_blocks
from sdlc.meta import (
    DONE,
    OPEN,
    STATUSES,
    WITHDRAWN,
    MetaError,
    check_meta,
    expected,
    read,
    withdrawal,
)
from sdlc.resolve import OverrideError, check_overrides, resolve
from sdlc.roadmap import check_roadmap
from sdlc.routing import steps
from sdlc.sweep import matching, set_status, sweep, write

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
    try:  # the project's override of the template, if it has one (#133)
        text = resolve(root, f"templates/{first}")
    except OverrideError as e:
        print(e, file=sys.stderr)
        target.rmdir()
        return 1
    # Block markers are for overrides to aim at; the change's own file doesn't need them.
    text = re.sub(r"^[ \t]*<!--\s*/?block\s*:[^>]*-->[ \t]*\n", "", text, flags=re.M)
    if first == "intent.md" and (root / "docs" / "roadmap.md").is_file():
        text = add_milestone_line(text)
    (target / first).write_text(text, encoding="utf-8")
    write(target, expected(target, OPEN))
    print(target / first)
    # Branches take the slug with its number; shown only the path, agents dropped it (#185).
    print(f"slug: {slug} (its branches: build/{slug}, plan/{slug}, …)")
    return 0


def add_milestone_line(text: str) -> str:
    """With a roadmap, a new intent gets a live `Milestone: M<n>` under `Product owner:` (#187).

    `make validate` fails it until the intent skill fills in the milestone, so no change goes
    on the roadmap unplaced. Without a roadmap the template's commented hint is all there is.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("Product owner:"):
            return "\n".join([*lines[: i + 1], "Milestone: M<n>", *lines[i + 1 :]])
    return text


# A branch that changes more files than this almost certainly swept in dependencies or build
# output (one `git add -A` once committed ~82,000 files). Override with SDLC_MAX_CHANGED_FILES,
# or, where an environment variable can't be set (a PR's CI run), with a commit on the branch
# carrying a `Large-change: <reason>` trailer.
MAX_CHANGED_FILES = 300
LARGE_CHANGE_TRAILER = "Large-change"


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603 - list args, no shell (#135)
            ["git", *args],  # noqa: S607 - git from PATH, as every script here runs it
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
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


LOCAL_CHECK_LINE = re.compile(r"^(- )?Local check:", re.MULTILINE)
# The script parses the line and asks make (#253): the repo's synced copy, or the one beside this
# package when it runs from the framework's source tree.
LOCAL_CHECK_SCRIPT = Path(".sdlc/scripts/local-check.sh")


def check_local_check(root: Path) -> list[Problem]:
    """The CLAUDE.md `Local check:` line names make targets the Makefile has (#253). The script
    is the one parser; it only runs when the line is there, so other repos never call make."""
    claude_md = root / "CLAUDE.md"
    if not claude_md.is_file() or not LOCAL_CHECK_LINE.search(
        claude_md.read_text(encoding="utf-8")
    ):
        return []
    script = root / LOCAL_CHECK_SCRIPT
    if not script.is_file():
        script = Path(__file__).resolve().parents[2] / "scripts" / "local-check.sh"
    result = subprocess.run(  # noqa: S603 - list args, no shell (#135)
        ["bash", str(script), "--validate"],  # noqa: S607 - bash from PATH
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SDLC_CLAUDE_MD": str(claude_md)},
    )
    if result.returncode == 0:
        return []
    message = result.stderr.strip().removeprefix("CLAUDE.md: ")
    message = message or "the Local check line can't be read"
    return [Problem(claude_md, message)]


UPGRADE_PENDING = Path(".sdlc/upgrade-pending.md")


def check_upgrade(root: Path) -> list[Problem]:
    """A framework sync left upgrade steps to do (#20): its PR can't merge until they're done."""
    path = root / UPGRADE_PENDING
    if not path.is_file():
        return []
    releases = re.findall(r"^# (v\S+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    which = f" from {', '.join(releases)}" if releases else ""
    return [
        Problem(
            path,
            f"the framework sync left upgrade steps{which} to do: run /sdlc to work through "
            "them, then delete this file",
        )
    ]


def cmd_check(root: Path) -> int:
    words = placeholders(root)
    changed = branch_changes(root)
    dod = definition_of_done(root)
    problems: list[object] = [
        p for d in change_dirs(root) for p in check_change(d, words, changed, dod)
    ]
    problems += check_meta(change_dirs(root))
    problems += dod.problems
    problems += check_adrs(root, words)
    problems += check_config(root)
    problems += check_commits(root)
    problems += check_roadmap(root)
    problems += check_upgrade(root)
    problems += check_local_check(root)
    problems += [Problem(path, message) for path, message in check_overrides(root)]
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"ok: {len(change_dirs(root))} change(s) valid")
    return 1 if problems else 0


def cmd_status(root: Path) -> int:
    for d in change_dirs(root):
        try:
            meta = read(d)
        except MetaError:
            meta = None  # make validate reports it
        if meta and meta.status != OPEN:
            progress = meta.status + (f" ({meta.pr})" if meta.pr else "")
        else:
            progress = build_progress(d)
        print(f"{d.name}\t{stage(d)}" + (f"\t{progress}" if progress else ""))
    return 0


def cmd_next(root: Path, ref: str | None, slug: str | None, only_open: bool = False) -> int:
    found = steps(root, ref, slug)
    closed = [s.skill for s in found if s.skill in (DONE, WITHDRAWN)]
    for step in found:
        if not (only_open and step.skill in (DONE, WITHDRAWN)):
            print(step)
    if only_open:  # on stderr, so the output stays one change a line
        left_out = f"{closed.count(DONE)} done, {closed.count(WITHDRAWN)} withdrawn"
        print(f"left out: {left_out}", file=sys.stderr)
    if slug and not found:
        print(f"no change matching {slug!r}", file=sys.stderr)
        return 1
    return 0


def cmd_sync_changes(
    root: Path, slug: str | None, fix: bool, status: str | None, pr: str | None
) -> int:
    """Report, or fix, each change.toml. 0 when nothing is left wrong."""
    folders = matching(root, slug)
    if slug and len(folders) != 1:
        what = "matches several changes" if folders else "matches no change"
        print(f"{slug!r} {what}", file=sys.stderr)
        return 2
    if (status or pr) and not (slug and status):
        print("STATUS needs CHANGE, and PR needs both", file=sys.stderr)
        return 2
    if status:
        if pr and not re.fullmatch(r"#?[1-9][0-9]*", pr):
            print(f"PR must be a number, got {pr!r}", file=sys.stderr)
            return 2
        meta = set_status(folders[0], status, f"#{pr.removeprefix('#')}" if pr else None)
        print(f"{folders[0].name}\tstatus {meta.status}" + (f" ({meta.pr})" if meta.pr else ""))
        if fix:
            write(folders[0], meta)
        else:
            print("nothing written: add FIX=1", file=sys.stderr)
        return 0
    left = 0
    fixable = 0
    for finding in sweep(root, slug):
        if finding.meta and fix:
            write(root / "changes" / finding.slug, finding.meta)
            print(f"fixed\t{finding}")
        else:
            left += 1
            fixable += finding.meta is not None
            print(f"{'fixable' if finding.meta else 'decide'}\t{finding}")
    if not left:
        print(f"ok: {len(folders)} change.toml file(s) in sync")
    elif fixable:
        print(f"{fixable} can be fixed: add FIX=1", file=sys.stderr)
    return 1 if left else 0


def find_change(root: Path, name: str) -> Path | None:
    """A change folder from a path, a full slug or its number (`0002`)."""
    if (path := Path(name)).is_dir():
        return path
    if (path := root / name).is_dir():
        return path
    found = [d for d in change_dirs(root) if d.name == name or d.name.split("-")[0] == name]
    return found[0] if len(found) == 1 else None


def cmd_clauses(root: Path, name: str, ref: str | None, stage: str | None = None) -> int:
    change_dir = find_change(root, name)
    if change_dir is None:
        print(f"no change matching {name!r}", file=sys.stderr)
        return 1
    try:
        found, lost = change_blocks(root, change_dir, ref, stage)
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
    new = sub.add_parser("new", help="start a change from .sdlc/templates/intent.md (or bug.md)")
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

    nxt.add_argument(
        "--open", dest="only_open", action="store_true", help="leave out done and withdrawn changes"
    )

    sc = sub.add_parser(
        "sync-changes", help="compare each change.toml with its folder and git; --fix corrects it"
    )
    sc.add_argument("slug", nargs="?", help="one change: 0002 or 0002-name")
    sc.add_argument("--fix", action="store_true", help="write the corrections (never commits)")
    sc.add_argument("--status", choices=STATUSES, help="set this change's status by hand")
    sc.add_argument("--pr", help="with --status, the PR that shipped it")

    cs = sub.add_parser("change-status", help="print change.toml's status, or 'none' (for scripts)")
    cs.add_argument("change_dir", type=Path, help="a change folder, e.g. changes/0002-name")

    cl = sub.add_parser(
        "clauses",
        help="split a spec into one block per requirement, with the criteria and plan lines "
        "that cite it (JSON)",
    )
    cl.add_argument("change", help="a change: 0002, 0002-name, or a folder path")
    cl.add_argument("--ref", help="only the requirements that are new or differ from this git ref")
    cl.add_argument(
        "--stage",
        choices=sorted(STAGE_FIELDS),
        help="with --ref, count only what this stage's check reads as a difference "
        "(default: everything)",
    )

    kd = sub.add_parser(
        "kind",
        help="print a change's kind: feature, bug or tooling (the scripts read it, #221)",
    )
    kd.add_argument("change_dir", type=Path, help="a change folder, e.g. changes/0002-name")

    wd = sub.add_parser(
        "withdrawn",
        help="print why a change is withdrawn, or nothing if it isn't (the scripts read it, #286)",
    )
    wd.add_argument("change_dir", type=Path, help="a change folder, e.g. changes/0002-name")

    res = sub.add_parser(
        "resolve",
        help="print a framework file with the project's override applied (.sdlc-local/)",
    )
    res.add_argument("path", help="a path under .sdlc/, e.g. skills/build/SKILL.md")

    args = parser.parse_args(argv)
    if args.command == "resolve":
        try:
            sys.stdout.write(resolve(args.root, args.path))
        except OverrideError as e:
            print(e, file=sys.stderr)
            return 1
        return 0
    if args.command == "kind":
        if not args.change_dir.is_dir():
            print(f"no change folder {args.change_dir}", file=sys.stderr)
            return 1
        print(kind(args.change_dir))
        return 0
    if args.command == "withdrawn":
        if not args.change_dir.is_dir():
            print(f"no change folder {args.change_dir}", file=sys.stderr)
            return 1
        print(withdrawal(args.change_dir) or "")
        return 0
    if args.command == "change-status":
        try:
            meta = read(args.change_dir)
        except MetaError as e:
            print(f"{args.change_dir}: change.toml {e}", file=sys.stderr)
            return 1
        print(meta.status if meta else "none")
        return 0
    if args.command == "sync-changes":
        return cmd_sync_changes(args.root, args.slug, args.fix, args.status, args.pr)
    if args.command == "new":
        return cmd_new(args.root, args.name, args.kind)
    if args.command == "check":
        return cmd_check(args.root)
    if args.command == "clauses":
        return cmd_clauses(args.root, args.change, args.ref, args.stage)
    if args.command == "next":
        return cmd_next(args.root, args.ref, args.slug, args.only_open)
    return cmd_status(args.root)


if __name__ == "__main__":
    sys.exit(main())
