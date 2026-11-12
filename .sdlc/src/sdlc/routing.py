"""Where each change is, and the next step: the routing table the entry skills share.

People remember a few skills (/intent, /plan, /build, /pr, /next). Each one asks this
module where a change is, and hands over to the skill that owns the next step. The
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

from sdlc.artifacts import BUILD, Build, change_dirs, stage


@dataclass(frozen=True)
class Next:
    slug: str
    stage: str
    skill: str  # the entry skill that owns the next step, or "done"
    detail: str

    def __str__(self) -> str:
        return f"{self.slug}\t{self.stage}\t{self.skill}\t{self.detail}"


WITHDRAWN_RE = re.compile(r"^Withdrawn:[ \t]*(\S.*)$", re.MULTILINE)

# Each artifact and what it's based on: when the base changes after it, it's out of date.
BASES = [
    ("spec.md", ("intent.md", "bug.md")),
    ("plan.md", ("spec.md",)),
    (BUILD, ("plan.md", "spec.md")),
]
# Who updates an out-of-date artifact.
OWNER = {"spec.md": "spec", "plan.md": "plan", BUILD: "build"}


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def out_of_date(root: Path, rev: str, slug: str, present: set[str]) -> tuple[str, str] | None:
    """(artifact, why) for the earliest artifact whose base changed after it was last
    committed at `rev`, or None. Outside git, or before anything is committed, nothing is."""
    folder = f"changes/{slug}"

    def last(name: str) -> str | None:
        return _git(root, "log", "-1", "--format=%H", rev, "--", f"{folder}/{name}") or None

    for artifact, bases in BASES:
        if artifact not in present:
            continue
        mine = last(artifact)
        if not mine:
            continue
        for base in bases:
            theirs = last(base) if base in present else None
            if theirs and _git(root, "merge-base", "--is-ancestor", theirs, mine) is None:
                return artifact, (
                    f"out of date: {base} changed in {theirs[:7]} after {artifact}; "
                    f"update {artifact}, or confirm it still holds"
                )
    return None


def merged_build(root: Path, rev: str, slug: str) -> str | None:
    """How a small build (one with no build.md) shows it merged at `rev`: "#N", or None.

    A large build records "PR open" in build.md, which reaches main with its PR. A small build
    leaves no file, so its merge is read from history (#122): the merge commit GitHub writes,
    `Merge pull request #N from <owner>/build/<slug>` (the branch's own merges of main don't
    match), or, in a repo that squash-merges, the build PR's title `feat(<slug>): ... (#N)`
    (`fix(<slug>)` for a bug). A repo that rebase-merges leaves neither.
    """
    patterns = (
        ("--merges", rf"^Merge pull request #[0-9]+ from [^ ]+/build/{slug}$"),
        ("--no-merges", rf"^(feat|fix)\({slug}\)!?: .* \(#[0-9]+\)$"),
    )
    for kind, pattern in patterns:
        found = _git(root, "log", rev, kind, "-E", f"--grep={pattern}", "--format=%s", "-1")
        if found and (m := re.search(r"#\d+", found)):
            return m.group()
    return None


def next_step(change_dir: Path, merged: bool, root: Path | None = None, rev: str = "HEAD") -> Next:
    """The next step for one change. `merged` means the files come from main, so a build
    plan saying "PR open" there has been merged (it only reaches main with its PR). With
    `root`, git history at `rev` also says whether an artifact is out of date."""
    slug, where = change_dir.name, stage(change_dir)
    for first in ("intent.md", "bug.md"):
        path = change_dir / first
        if path.exists() and (m := WITHDRAWN_RE.search(path.read_text(encoding="utf-8"))):
            return Next(slug, where, "withdrawn", m.group(1).strip())
    finished = False
    small_build: str | None = None
    if (change_dir / BUILD).exists():
        status = Build.parse((change_dir / BUILD).read_text(encoding="utf-8")).status or ""
        finished = merged and status.startswith("PR open")
    elif where == "plan" and root is not None:
        small_build = merged_build(root, rev, slug)
        finished = small_build is not None
    if root is not None and not finished:
        present = {p.name for p in change_dir.iterdir()}
        if stale := out_of_date(root, rev, slug, present):
            artifact, why = stale
            return Next(slug, where, OWNER[artifact], why)
    if where == "empty":
        return Next(slug, where, "intent", "no intent.md or bug.md yet: describe the change")
    if where in ("intent", "bug"):
        return Next(
            slug,
            where,
            "spec",
            f"the spec is generated when the {where} merges; review its spec PR (/pr)",
        )
    if where == "spec":
        return Next(slug, where, "plan", "plan it")
    if where == "plan":
        if small_build is not None:
            return Next(slug, where, "done", f"built and merged ({small_build})")
        return Next(slug, where, "build", "build it")
    build = Build.parse((change_dir / BUILD).read_text(encoding="utf-8"))
    status = build.status or ""
    if build.is_draft:
        return Next(slug, where, "build", "approve the build plan (build.md)")
    if status.startswith("PR open"):
        if merged:
            pr = re.search(r"#\d+", status)
            return Next(
                slug, where, "done", "built and merged" + (f" ({pr.group()})" if pr else "")
            )
        return Next(slug, where, "pr", f"{status}: work through its review")
    todo = [n for n, s in build.milestones.items() if not (s or "").startswith("done")]
    return Next(slug, where, "build", f"{build.progress()}; next {todo[0] if todo else 'the PR'}")


def _extract(root: Path, ref: str, into: Path) -> Path | None:
    """Unpack ref's changes/ folder into `into`; None when the ref has no changes/."""
    result = subprocess.run(
        ["git", "archive", "--format=tar", ref, "changes"],
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
            base = _extract(root, ref, Path(tmp)) or Path(tmp)
        found = [
            next_step(d, merged=ref is not None, root=root, rev=ref or "HEAD")
            for d in change_dirs(base)
            if slug is None or d.name == slug or d.name.startswith(f"{slug}-")
        ]
    return found
