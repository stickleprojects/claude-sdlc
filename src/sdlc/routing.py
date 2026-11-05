"""Where each change is, and the next step: the routing table the entry skills share.

People remember a few skills (/intent, /plan, /build, /pr, /next). Each one asks this
module where a change is, and hands over to the skill that owns the next step. The
table lives here, once, so the skills can't drift apart; `.claude/skills/routing.md`
explains it for the skills.

Only files are read, from the working tree or from a git ref (normally origin/main, which
holds what has been merged). Open PRs are GitHub state: the skills check those themselves.
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


def next_step(change_dir: Path, merged: bool) -> Next:
    """The next step for one change. `merged` means the files come from main, so a build
    plan saying "PR open" there has been merged (it only reaches main with its PR)."""
    slug, where = change_dir.name, stage(change_dir)
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
            next_step(d, merged=ref is not None)
            for d in change_dirs(base)
            if slug is None or d.name == slug or d.name.startswith(f"{slug}-")
        ]
    return found
