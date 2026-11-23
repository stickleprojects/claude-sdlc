"""Where each change is, and the next step: the routing table the entry skills share.

People remember a few skills (/sdlc-intent, /sdlc-plan, /sdlc-build, /sdlc-pr, /sdlc-next).
Each one asks this module where a change is, and hands over to the skill that owns the next
step. The
table lives here, once, so the skills can't drift apart; `.sdlc/skills/routing.md`
explains it for the skills.

Only files and git history are read, from the working tree or from a git ref (normally
origin/main, which holds what has been merged). Open PRs are GitHub state: the skills check
those themselves.
"""

from __future__ import annotations

import io
import re
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sdlc.artifacts import BUILD, Build, change_dirs, kind, stage
from sdlc.meta import DONE, META, OPEN, WITHDRAWN, MetaError, parse, read
from sdlc.meta import WITHDRAWN_RE as WITHDRAWN_RE


@dataclass(frozen=True)
class Next:
    slug: str
    stage: str
    skill: str  # the skill that owns the next step (sdlc-…), or "done" or "withdrawn"
    detail: str

    def __str__(self) -> str:
        return f"{self.slug}\t{self.stage}\t{self.skill}\t{self.detail}"


# Each artifact and what it's based on: when the base changes after it, it's out of date.
BASES = [
    ("spec.md", ("intent.md", "bug.md")),
    ("plan.md", ("spec.md",)),
    (BUILD, ("plan.md", "spec.md")),
]
# Who updates an out-of-date artifact.
OWNER = {"spec.md": "sdlc-spec", "plan.md": "sdlc-plan", BUILD: "sdlc-build"}


def git(root: Path, *args: str) -> str | None:
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
    return result.stdout.strip() if result.returncode == 0 else None


def out_of_date(
    root: Path, rev: str, slug: str, present: set[str], tooling: bool = False
) -> tuple[str, str] | None:
    """(artifact, why) for the earliest artifact whose base changed after it was last
    committed at `rev`, or None. Outside git, or before anything is committed, nothing is.
    A tooling change's plan (#221) has no spec, so its base is the intent."""
    folder = f"changes/{slug}"
    bases_of = dict(BASES)
    if tooling:
        bases_of["plan.md"] = ("intent.md",)

    def last(name: str) -> str | None:
        return git(root, "log", "-1", "--format=%H", rev, "--", f"{folder}/{name}") or None

    for artifact, _ in BASES:
        bases = bases_of[artifact]
        if artifact not in present:
            continue
        mine = last(artifact)
        if not mine:
            continue
        for base in bases:
            theirs = last(base) if base in present else None
            if theirs and git(root, "merge-base", "--is-ancestor", theirs, mine) is None:
                return artifact, (
                    f"out of date: {base} changed in {theirs[:7]} after {artifact}; "
                    f"update {artifact}, or confirm it still holds"
                )
    return None


def merged_build(root: Path, rev: str, slug: str, bringing: str | None = None) -> str | None:
    """How a small build (one with no build.md) shows it merged at `rev`: "#N", or None.

    A large build records "PR open" in build.md, which reaches main with its PR. A small build
    leaves no file, so its merge is read from history (#122): the merge commit GitHub writes,
    `Merge pull request #N from <owner>/build/<slug>` (the branch's own merges of main don't
    match), or, in a repo that squash-merges, the build PR's title `feat(<slug>): ... (#N)`
    (`fix(<slug>)` for a bug, `chore(<slug>)` or `ci(<slug>)` for a tooling change, #221).
    A repo that rebase-merges leaves neither.

    With `bringing` (a file in the change folder), the merge counts only if it brought that
    file to main: a fast-path bug's PR carries its spec.md with the fix (#148), and a bug
    report merged from a `build/<slug>` branch mustn't read as the fix.
    """
    patterns = (
        ("--merges", rf"^Merge pull request #[0-9]+ from [^ ]+/build/{slug}$"),
        ("--no-merges", rf"^(feat|fix|chore|ci)\({slug}\)!?: .* \(#[0-9]+\)$"),
    )
    for merges, pattern in patterns:
        found = git(root, "log", rev, merges, "-E", f"--grep={pattern}", "--format=%H %s")
        for line in found.splitlines() if found else []:
            sha, subject = line.split(" ", 1)
            if bringing and not git(
                root, "diff", "--name-only", f"{sha}^1", sha, "--", f"changes/{slug}/{bringing}"
            ):
                continue
            if m := re.search(r"#\d+", subject):
                return m.group()
    return None


def finished(change_dir: Path, root: Path | None, rev: str) -> tuple[bool, str | None]:
    """Whether the files and git history say this merged change is built, and the PR: "#N" if known.
    `change_dir` holds the files at `rev`."""
    slug, where = change_dir.name, stage(change_dir)
    if (change_dir / BUILD).exists():
        status = Build.parse((change_dir / BUILD).read_text(encoding="utf-8")).status or ""
        pr = re.search(r"#\d+", status)
        return status.startswith("PR open"), pr.group() if pr else None
    small: str | None = None
    if where == "plan" and root is not None:
        small = merged_build(root, rev, slug)
    elif where == "spec" and root is not None and (change_dir / "bug.md").exists():
        small = merged_build(root, rev, slug, bringing="spec.md")  # the fast path, #148
    return small is not None, small


def main_ref(root: Path) -> str | None:
    """What's merged: origin/main, else main, else (no main at all) HEAD. None outside git."""
    for ref in ("origin/main", "main", "HEAD"):
        if git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"):
            return ref
    return None


def done_on_main(root: Path, slug: str) -> bool | None:
    """Whether main's change.toml says done; None when there's no main to read."""
    ref = main_ref(root)
    if ref is None or ref == "HEAD":
        return None
    text = git(root, "show", f"{ref}:changes/{slug}/{META}")
    if text is None:
        return False
    try:
        return parse(text).status == DONE
    except MetaError:
        return False


def was_done(root: Path, rev: str, slug: str) -> bool:
    """Whether change.toml ever said done at `rev`: if it's open now, someone reopened it
    (reverting a build's PR takes its status back too)."""
    path = f"changes/{slug}/{META}"
    said_done = ("-G", '^status *= *"done"')
    log = ("log", "-1", "--full-history", "--format=%H", *said_done, rev, "--", path)
    return bool(git(root, *log))


def next_step(change_dir: Path, merged: bool, root: Path | None = None, rev: str = "HEAD") -> Next:
    """The next step for one change. `merged` means the files come from main, so a build
    plan saying "PR open" there has been merged (it only reaches main with its PR). With
    `root`, git history at `rev` also says whether an artifact is out of date."""
    slug, where = change_dir.name, stage(change_dir)
    for first in ("intent.md", "bug.md"):
        path = change_dir / first
        if path.exists() and (m := WITHDRAWN_RE.search(path.read_text(encoding="utf-8"))):
            return Next(slug, where, "withdrawn", m.group(1).strip())
    try:
        meta = read(change_dir)
    except MetaError as e:
        return Next(slug, where, "sdlc-next", f"{META} {e}: correct it")
    if meta and meta.status == WITHDRAWN:
        return Next(slug, where, "withdrawn", f"{META} says withdrawn")
    # In a checkout, a build branch says done before its PR merges, so main has the last word.
    unmerged = False
    if meta and meta.status == DONE:
        if merged or root is None or done_on_main(root, slug) is not False:
            detail = "built and merged" + (f" ({meta.pr})" if meta.pr else "")
            return Next(slug, where, "done", detail)
        unmerged = True
    by_git, pr = finished(change_dir, root, rev)
    if (change_dir / BUILD).exists():
        by_git = merged and by_git
    if by_git and meta and meta.status == OPEN:
        if root is not None and was_done(root, rev, slug):
            by_git, pr = False, None  # reopened: the file says so, and the old merge doesn't count
        else:
            return Next(
                slug,
                where,
                "sdlc-next",
                f"{META} says open, but git shows its build merged ({pr or 'no PR number'}): "
                f"run `make sync-changes CHANGE={slug}`",
            )
    small_build = pr if by_git and not (change_dir / BUILD).exists() else None
    if root is not None and not by_git:
        present = {p.name for p in change_dir.iterdir()}
        if stale := out_of_date(root, rev, slug, present, tooling=kind(change_dir) == "tooling"):
            artifact, why = stale
            return Next(slug, where, OWNER[artifact], why)
    if unmerged and not by_git and where in ("spec", "plan"):
        return Next(slug, where, "sdlc-pr", f"{META} says done, but it isn't merged: see its PR")
    if where == "empty":
        return Next(slug, where, "sdlc-intent", "no intent.md or bug.md yet: describe the change")
    if where == "intent" and kind(change_dir) == "tooling":
        return Next(
            slug,
            where,
            "sdlc-plan",
            "a tooling change (no spec): plan it, then build it in the same PR",
        )
    if where in ("intent", "bug"):
        return Next(
            slug,
            where,
            "sdlc-spec",
            f"the spec is generated when the {where} merges; review its spec PR (/sdlc-pr)",
        )
    if where == "spec":
        if small_build is not None:
            return Next(slug, where, "done", f"fixed on the fast path and merged ({small_build})")
        return Next(slug, where, "sdlc-plan", "plan it")
    if where == "plan":
        if small_build is not None:
            return Next(slug, where, "done", f"built and merged ({small_build})")
        return Next(slug, where, "sdlc-build", "build it")
    build = Build.parse((change_dir / BUILD).read_text(encoding="utf-8"))
    status = build.status or ""
    if build.is_draft:
        return Next(slug, where, "sdlc-build", "approve the build plan (build.md)")
    if status.startswith("PR open"):
        if by_git:
            return Next(slug, where, "done", "built and merged" + (f" ({pr})" if pr else ""))
        if merged:
            return Next(slug, where, "sdlc-build", f"reopened after its build merged ({status})")
        return Next(slug, where, "sdlc-pr", f"{status}: work through its review")
    todo = [n for n, s in build.milestones.items() if not (s or "").startswith("done")]
    return Next(
        slug, where, "sdlc-build", f"{build.progress()}; next {todo[0] if todo else 'the PR'}"
    )


def extract(root: Path, ref: str, into: Path) -> Path | None:
    """Unpack ref's changes/ folder into `into`; None when the ref has no changes/."""
    result = subprocess.run(  # noqa: S603 - list args, no shell (#135)
        ["git", "archive", "--format=tar", ref, "changes"],  # noqa: S607 - git from PATH, as every script here runs it
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as tar:
        try:
            tar.extractall(into, filter="data")
        except TypeError:  # Python before 3.12: no filter, and this is our own repo's tree
            tar.extractall(into)  # noqa: S202
    return into


def steps(root: Path, ref: str | None = None, slug: str | None = None) -> list[Next]:
    """The next step for every change (or the one named), from the working tree or a ref."""
    with tempfile.TemporaryDirectory() as tmp:
        base = root
        if ref:
            base = extract(root, ref, Path(tmp)) or Path(tmp)
        found = [
            next_step(d, merged=ref is not None, root=root, rev=ref or "HEAD")
            for d in change_dirs(base)
            if slug is None or d.name == slug or d.name.startswith(f"{slug}-")
        ]
    return found
