"""change.toml: which change a folder holds, and whether it's done (#272).

    number = "0058"
    slug = "0058-working-lift"
    title = "The working lift and stacked floors"
    status = "done"
    pr = "#282"

`number` and `slug` repeat the folder name and `title` repeats the intent's (or bug's) heading,
so a mislaid file says where it belongs. `status` is open, done (merged, not deployed) or
withdrawn; `pr`, optional, is the PR that shipped the change. `make validate` holds the file to
its folder, and check-plan-first.sh holds a build PR to `done`. It is a file of its own because
editing intent.md, bug.md or spec.md trips the gate title check and the out-of-date check.
A folder with no change.toml is allowed for now.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from sdlc.artifacts import COMMENT_RE, Problem

META = "change.toml"
OPEN, DONE, WITHDRAWN = "open", "done", "withdrawn"
STATUSES = (OPEN, DONE, WITHDRAWN)
REQUIRED = ("number", "slug", "title", "status")

TITLE_RE = re.compile(r"^#[ \t]+(?:(?:Intent|Bug):[ \t]*)?(\S.*?)[ \t]*$", re.MULTILINE)
PR_RE = re.compile(r"^#[1-9][0-9]*$")
WITHDRAWN_RE = re.compile(r"^Withdrawn:[ \t]*(\S.*)$", re.MULTILINE)


class MetaError(ValueError):
    """A change.toml that can't be read. The message says why."""


@dataclass(frozen=True)
class Meta:
    number: str
    slug: str
    title: str
    status: str
    pr: str | None = None

    def render(self) -> str:
        pairs = [(key, getattr(self, key)) for key in (*REQUIRED, "pr")]
        # A JSON string is also a TOML basic string.
        return "".join(
            f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in pairs if value
        )


def parse(text: str) -> Meta:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise MetaError(f"isn't valid TOML: {e}") from e
    if extra := sorted(set(data) - {*REQUIRED, "pr"}):
        raise MetaError(f"has unknown keys: {', '.join(extra)}")
    bad = [k for k in REQUIRED if not isinstance(data.get(k), str) or not data[k].strip()]
    if bad:
        raise MetaError(f"needs a non-empty string for: {', '.join(bad)}")
    if data["status"] not in STATUSES:
        raise MetaError(f"status {data['status']!r} is not one of {', '.join(STATUSES)}")
    pr = data.get("pr")
    if pr is not None and not (isinstance(pr, str) and PR_RE.match(pr)):
        raise MetaError(f'pr {pr!r} is not a PR number like "#12"')
    return Meta(**data)


def read(change_dir: Path) -> Meta | None:
    """The folder's change.toml, or None when there isn't one. MetaError when it can't be read."""
    path = change_dir / META
    if not path.exists():
        return None
    try:
        return parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        raise MetaError(f"can't be read: {e}") from e


def first_artifact(change_dir: Path) -> str:
    """The text of intent.md or bug.md, or nothing."""
    for name in ("intent.md", "bug.md"):
        if (change_dir / name).exists():
            return (change_dir / name).read_text(encoding="utf-8")
    return ""


def heading_title(change_dir: Path) -> str | None:
    m = TITLE_RE.search(COMMENT_RE.sub("", first_artifact(change_dir)))
    return m.group(1) if m else None


def withdrawn(change_dir: Path) -> str | None:
    """Who withdrew the change, when and why, or None."""
    m = WITHDRAWN_RE.search(first_artifact(change_dir))
    return m.group(1).strip() if m else None


def expected(change_dir: Path, status: str, pr: str | None = None) -> Meta:
    """What the folder's change.toml should say, given its status."""
    number, _, name = change_dir.name.partition("-")
    title = heading_title(change_dir) or name.replace("-", " ") or change_dir.name
    return Meta(number, change_dir.name, title, status, pr)


FIX = "run `make sync-changes CHANGE={} FIX=1`"


def check_meta(dirs: Collection[Path]) -> list[Problem]:
    """Each change.toml there is agrees with its folder."""
    problems: list[Problem] = []
    for change_dir in dirs:
        path = change_dir / META
        try:
            meta = read(change_dir)
        except MetaError as e:
            problems.append(Problem(path, str(e)))
            continue
        if meta is None:
            continue
        fix = FIX.format(change_dir.name)
        want = expected(change_dir, meta.status)
        for key in ("number", "slug"):
            if getattr(meta, key) != getattr(want, key):
                problems.append(
                    Problem(
                        path,
                        f"{key} is {getattr(meta, key)!r}, but the folder is {change_dir.name}: "
                        f"put the file back where it belongs, or {fix}",
                    )
                )
        title = heading_title(change_dir)
        if title and meta.title != title:
            problems.append(
                Problem(path, f"title is {meta.title!r}, but the heading says {title!r}: {fix}")
            )
        gone = withdrawn(change_dir) is not None
        if gone and meta.status != WITHDRAWN:
            problems.append(
                Problem(path, f"status is {meta.status}, but there's a Withdrawn: line: {fix}")
            )
        if meta.status == WITHDRAWN and not gone:
            problems.append(Problem(path, "status is withdrawn, but there's no Withdrawn: line"))
    return problems
