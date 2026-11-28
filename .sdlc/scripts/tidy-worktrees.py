#!/usr/bin/env python3
"""Remove the copies of the code (git worktrees) whose work is finished (#279).

Lists them by default.

Usage: .sdlc/scripts/tidy-worktrees.py          say what would be removed and why the rest stay
       .sdlc/scripts/tidy-worktrees.py --go     remove them

Run it from anywhere in the repo. work-on.sh makes the copies; this cleans them up.

A worktree is removed only when all of these hold:
  - its branch has a merged PR, and its commit is part of that PR and of origin/main
    (so a new worktree with no commits yet stays)
  - the branch has no open PR
  - nothing in it is uncommitted or untracked
  - it isn't the main checkout, locked, or the folder this is run from
  - no process is running in it (a Claude session, a build)

Hand-made ignored files (mock-ups, notes; not caches or test reports) are copied to
~/.local/state/removed-worktrees/<repo>/<time>/ first. The branches stay.
"""

import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Caches and generated output, never copied (Godot's among them: the first consumers use it).
SKIP_DIRS = {
    ".godot",
    ".import",
    "__pycache__",
    ".venv",
    "node_modules",
    "build",
    "dist",
    "coverage",
    "reports",
    "gdunit",
    "warnings",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}
SKIP_NAMES = {"gdunit.rc", "warnings.txt", ".coverage"}
SKIP_SUFFIXES = {".log", ".pyc"}


def run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - list args, no shell (#135)
        args, cwd=cwd, capture_output=True, text=True, errors="surrogateescape"
    )


def must(*args: str, cwd: str | None = None) -> str:
    done = run(*args, cwd=cwd)
    if done.returncode:
        sys.exit(f"error: {' '.join(args[:4])}: {done.stderr.strip() or done.returncode}")
    return done.stdout


def worktrees() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for field in must("git", "worktree", "list", "--porcelain", "-z").split("\0"):
        key, _, value = field.partition(" ")
        if key == "worktree":
            out.append({"path": value})
        elif key:
            out[-1][key] = value
    return out


def inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder + "/")


def process_folders() -> list[tuple[str, str]]:
    """Each process's working folder and name: Linux's /proc, else lsof (macOS)."""
    proc = os.environ.get(
        "SDLC_PROC", "/proc"
    )  # the tests point it elsewhere to take the lsof path
    if not os.path.isdir(f"{proc}/self"):
        if not shutil.which("lsof"):
            sys.exit("error: can't see which folders processes run in (no /proc, no lsof)")
        listing = run("lsof", "-d", "cwd", "-Fcn").stdout
        found, name = [], ""
        for line in listing.splitlines():
            if line.startswith("c"):
                name = line[1:]
            elif line.startswith("n"):
                found.append((line[1:], name))
        return found
    found = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            found.append(
                (os.readlink(f"/proc/{pid}/cwd"), Path(f"/proc/{pid}/comm").read_text().strip())
            )
        except OSError:
            pass
    return found


def why_keep(tree, trees, prs, processes) -> str | None:
    path, branch = tree["path"], tree.get("branch", "").removeprefix("refs/heads/")
    if tree is trees[0]:
        return "the main checkout"
    if inside(os.getcwd(), path):
        return "you are in it"
    if "locked" in tree:
        return "locked"
    if "prunable" in tree or not os.path.isdir(path):
        return "its folder is missing (git worktree prune)"
    if any(t is not tree and inside(t["path"], path) for t in trees):
        return "another worktree is inside it"
    real = os.path.realpath(path)  # the kernel and lsof report resolved paths
    users = sorted({name for folder, name in processes if inside(os.path.realpath(folder), real)})
    if users:
        return "in use by " + ", ".join(users)
    if not branch:
        return "no branch checked out"
    status = run("git", "status", "--porcelain", cwd=path)
    if status.returncode:
        return "git status failed"
    if status.stdout:
        return "uncommitted: " + ", ".join(line[3:] for line in status.stdout.splitlines()[:3])
    mine = [p for p in prs if p["headRefName"] == branch]
    if any(p["state"] == "OPEN" for p in mine):
        return "open PR"
    merged = [p for p in mine if p["state"] == "MERGED"]
    if not merged:
        return "no merged PR"
    head = tree["HEAD"]

    def ancestor(of: str) -> bool:
        return run("git", "merge-base", "--is-ancestor", head, of, cwd=path).returncode == 0

    if not ancestor("origin/main"):
        return "has commits that aren't on origin/main"
    if not any(ancestor(p["headRefOid"]) for p in merged):
        return "its commit isn't part of the merged PR"
    return None


def handmade(path: str) -> list[str]:
    listing = must("git", "ls-files", "-z", "--others", "--ignored", "--exclude-standard", cwd=path)
    keep = []
    for name in filter(None, listing.split("\0")):
        p = Path(name)
        if SKIP_DIRS.intersection(p.parts[:-1]) or any(x.endswith("_cache") for x in p.parts[:-1]):
            continue
        if p.name in SKIP_NAMES or p.suffix in SKIP_SUFFIXES or (Path(path) / p).is_symlink():
            continue
        if not (Path(path) / p).is_file():  # a nested repository, listed as a folder
            sys.exit(f"error: {path}/{name} is not a plain file; nothing was done to {path}")
        keep.append(name)
    return keep


def main() -> None:
    args = sys.argv[1:]
    if args not in ([], ["--go"]):
        print(__doc__.strip())
        sys.exit(0 if args in (["-h"], ["--help"]) else 2)
    must("git", "fetch", "--quiet", "--prune", "origin")
    prs = json.loads(
        must(
            "gh",
            "pr",
            "list",
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            "state,headRefName,headRefOid",
        )
    )
    trees, processes = worktrees(), process_folders()

    root = Path(trees[0]["path"])
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    saved_to = Path.home() / ".local/state/removed-worktrees" / root.name / stamp
    ready = []
    for tree in trees:
        reason = why_keep(tree, trees, prs, processes)
        if reason:
            print(f"keep    {os.path.basename(tree['path'])}: {reason}")
        else:
            ready.append(tree)
    failed = 0
    for tree in ready:
        path = tree["path"]
        name, branch = os.path.basename(path), tree["branch"].removeprefix("refs/heads/")
        files = handmade(path)
        extra = f", saves {len(files)} ignored file(s)" if files else ""
        if args != ["--go"]:
            print(f"remove  {name} ({branch}){extra}")
            continue
        for file in files:
            target = saved_to / name / file
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(path) / file, target)
        # Without --force, git itself refuses anything that has changed since the check.
        done = run("git", "worktree", "remove", path)
        failed += done.returncode != 0
        print(
            f"FAILED  {name}: {done.stderr.strip()}"
            if done.returncode
            else f"removed {name} ({branch}){extra}"
        )
    if args != ["--go"]:
        print(
            f"\n{len(ready)} to remove."
            + (" Run: .sdlc/scripts/tidy-worktrees.py --go" if ready else "")
        )
    else:
        print(
            f"\n{len(ready) - failed} removed."
            + (f" Saved files: {saved_to}" if saved_to.exists() else "")
        )
        if ready:
            print("The branches stay: git branch -d <branch> deletes a merged one.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
