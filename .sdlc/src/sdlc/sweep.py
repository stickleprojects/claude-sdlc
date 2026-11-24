"""`make sync-changes`: compare every change.toml with its folder and with git, and fix it (#272).

Housekeeping, for when something got past the skills and CI, and the one-off fill of a repo that
had no change.toml files. It reports; with `fix` it writes the working tree, for review in a PR.
It never commits, and never turns `done` back to `open`: git can miss a real merge (a branch with
another name, a rebase merge), and a status someone reopened (a reverted build) stays reopened.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from sdlc.artifacts import change_dirs
from sdlc.meta import DONE, META, OPEN, WITHDRAWN, Meta, MetaError, expected, read, withdrawn
from sdlc.routing import extract, finished, git, main_ref, was_done


@dataclass(frozen=True)
class Finding:
    slug: str
    message: str
    meta: Meta | None = None  # what to write, or None when only a person can decide

    def __str__(self) -> str:
        return f"{self.slug}\t{self.message}"


def _describe(old: Meta | None, new: Meta) -> str:
    if old is None:
        return f"no {META}: status {new.status}" + (f" ({new.pr})" if new.pr else "")
    fields = ("number", "slug", "title", "status", "pr")
    keys = [k for k in fields if getattr(old, k) != getattr(new, k)]
    return "; ".join(f"{k}: {getattr(old, k)!r} -> {getattr(new, k)!r}" for k in keys)


def _sweep_one(root: Path, d: Path, base: Path | None, ref: str | None) -> list[Finding]:
    slug = d.name
    try:
        old = read(d)
    except MetaError as e:
        return [Finding(slug, f"{META} {e}: correct it, or set STATUS=open|done|withdrawn")]
    # Copied or moved from another folder: its status and PR are that change's, not this one's.
    mine = old if old and old.slug == slug else None
    merged, pr = False, None
    if ref and base and (base / "changes" / slug).is_dir():
        merged, pr = finished(base / "changes" / slug, root, ref)
    notes: list[Finding] = []
    if withdrawn(d) is not None:
        status = WITHDRAWN
    elif mine is None:
        if ref is None:
            why = f"no usable {META}, and no full git history to read its status from"
            return [Finding(slug, why)]
        status = DONE if merged else OPEN
    else:
        status = mine.status
        if status == WITHDRAWN:
            notes.append(Finding(slug, "status is withdrawn, but there's no Withdrawn: line"))
        elif status == OPEN and merged:
            if was_done(root, ref, slug):
                notes.append(
                    Finding(slug, f"reopened after its build merged ({pr or 'no PR'}): left open")
                )
            else:
                status = DONE
        elif status == DONE and ref and not merged and not mine.pr:
            try:
                on_main = read(base / "changes" / slug) if base else None
            except MetaError:
                on_main = None
            # Done here but not on main is a build on its way; done on main with no merge isn't.
            if on_main and on_main.status == DONE:
                notes.append(
                    Finding(
                        slug,
                        "done, but git shows no merge: if that's right, record the PR "
                        "(STATUS=done PR=<n>), otherwise set STATUS=open",
                    )
                )
    keep = mine.pr if mine else None
    new = expected(d, status, (keep or pr) if status == DONE else keep)
    if new != old:
        return [Finding(slug, _describe(old, new), new), *notes]
    return notes


def sweep(root: Path, slug: str | None = None) -> list[Finding]:
    """What's wrong, in folder order."""
    shallow = git(root, "rev-parse", "--is-shallow-repository")
    ref = main_ref(root) if shallow == "false" else None
    with tempfile.TemporaryDirectory() as tmp:
        base = extract(root, ref, Path(tmp)) if ref else None
        return [f for d in matching(root, slug) for f in _sweep_one(root, d, base, ref)]


def matching(root: Path, slug: str | None) -> list[Path]:
    return [
        d
        for d in change_dirs(root)
        if slug is None or d.name == slug or d.name.startswith(f"{slug}-")
    ]


def set_status(d: Path, status: str, pr: str | None) -> Meta:
    """What change.toml says once a person sets its status by hand."""
    try:
        old = read(d)
    except MetaError:
        old = None
    new = expected(d, status, pr or (old.pr if old and old.slug == d.name else None))
    return replace(new, pr=None) if status == OPEN else new


def write(d: Path, meta: Meta) -> None:
    (d / META).write_text(meta.render(), encoding="utf-8")
