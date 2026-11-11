"""`sdlc clauses`: a spec split into one block per requirement (#47).

Each block holds a requirement's text, the acceptance criteria that cite it, and the plan.md
lines that cite it or its criteria. The clause check (`scripts/clause-check.sh`) sends one
block at a time to a small model, which finds the clauses nothing tests or plans. This module
does no judgement: it only reads text and IDs, so it is cheap and unit-tested.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sdlc.artifacts import COMMENT_RE, HEADING_RE, LIST_MARKER_RE, section

# `- R1. text`, `R1: text`, `1. **R1** text`, `- **R14a.** text` and the like, at line start.
REQUIREMENT_RE = re.compile(
    r"^(?:[-*+]|\d+[.)])?\s*(?:\*\*)?(R\d+[a-z]?)\b(?:\*\*)?[.:)]?(?:\*\*)?\s*(.*)$"
)
# `- AC1 (R1): text`, `- A1 (R1). text`, or an untestable clause: `- Untestable (R3): ...`.
CRITERION_LINE_RE = re.compile(
    r"^\s*[-*]\s+(?:\*\*)?(AC?\d+|Untestable)\b(?:\*\*)?\s*(.*)$", re.IGNORECASE
)
# A group label between requirements, such as `**Tests**`, ends the requirement above it.
GROUP_LABEL_RE = re.compile(r"^\*\*[^*]+\*\*:?$")
# A top-level list entry: a marker then a space, so a group label like `**Search**` isn't one.
LIST_ENTRY_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+\S")
RANGE_RE = re.compile(r"\b(R|AC|A)(\d+)\s*(?:–|—|-|to)\s*(?:\1)?(\d+)\b")
ID_RE = re.compile(r"\b(R|AC|A)(\d+[a-z]?)\b")


class ClauseError(Exception):
    """The spec can't be split: no requirements could be read from it."""


@dataclass
class Criterion:
    id: str
    text: str


@dataclass
class PlanLine:
    section: str
    text: str


@dataclass
class Block:
    id: str
    text: str
    criteria: list[Criterion] = field(default_factory=list)
    plan: list[PlanLine] = field(default_factory=list)


def cited(text: str) -> set[str]:
    """Every R, AC and A ID a line cites, with ranges (`R1–R3`) expanded."""
    ids = {f"{p}{n}" for p, n in ID_RE.findall(text)}
    for prefix, start, end in RANGE_RE.findall(text):
        lo, hi = int(start), int(end)
        if lo <= hi and hi - lo < 200:
            ids.update(f"{prefix}{n}" for n in range(lo, hi + 1))
    return ids


def _entries(body: str, start: re.Pattern[str]) -> list[tuple[str, str]]:
    """(id, text) for each line `start` matches, joined with the lines that continue it: indented
    lines, and lines straight after it that don't start a new list entry or a group label."""
    entries: list[tuple[str, str]] = []
    open_entry = gap = False
    for line in body.splitlines():
        if m := start.match(line):
            entries.append((m.group(1), m.group(2).strip()))
            open_entry, gap = True, False
        elif not open_entry:
            continue
        elif not line.strip():
            gap = True
        elif line[:1].isspace() or not (
            gap or LIST_MARKER_RE.match(line) or GROUP_LABEL_RE.match(line.strip())
        ):
            eid, text = entries[-1]
            entries[-1] = (eid, f"{text} {line.strip()}".strip())
        else:
            open_entry = False  # a new list entry or label ends the one above
    return entries


def _plan_lines(plan: str) -> list[tuple[str, str, set[str]]]:
    """(section, line, IDs it cites) for each plan.md line that cites an ID."""
    out = []
    heading = ""
    for line in COMMENT_RE.sub("", plan).splitlines():
        if m := HEADING_RE.match(line):
            heading = m.group(1).strip()
            continue
        if ids := cited(line):
            out.append((heading, line.strip(), ids))
    return out


def unreadable(spec: str) -> list[str]:
    """Lines under ## Requirements that look like a requirement but can't be read as one: a
    top-level list entry that isn't `R<n>`, or an `R<n>` with no text. Reported so they read as
    unchecked, never as having nothing to check (PR #107 review). Indented lines continue the
    entry above them, and prose that isn't a list entry is left alone."""
    out = []
    for line in COMMENT_RE.sub("", section(spec, "Requirements")).splitlines():
        if line[:1].isspace() or not line.strip():
            continue
        m = REQUIREMENT_RE.match(line)
        if (m and not m.group(2).strip()) or (not m and LIST_ENTRY_RE.match(line)):
            out.append(line.strip())
    return out


def blocks(spec: str, plan: str | None = None) -> list[Block]:
    """One block per requirement in the spec's Requirements section.

    Raises ClauseError when no requirement can be read, so a spec in a form this doesn't
    recognise fails the check instead of reading as "nothing to check". Lines that can't be
    read when others can are listed by `unreadable`.
    """
    found = [
        Block(rid, text)
        for rid, text in _entries(section(spec, "Requirements"), REQUIREMENT_RE)
        if text
    ]
    if not found:
        raise ClauseError(
            "no requirements could be read from ## Requirements; expected lines such as "
            "'- R1. <requirement>'"
        )
    by_id = {b.id: b for b in found}
    criteria_of: dict[str, set[str]] = {b.id: set() for b in found}
    for cid, text in _entries(section(spec, "Acceptance criteria"), CRITERION_LINE_RE):
        cid = "Untestable" if cid.lower() == "untestable" else cid.upper()
        for rid in sorted(i for i in cited(text) if i.startswith("R") and i in by_id):
            by_id[rid].criteria.append(Criterion(cid, text))
            if cid != "Untestable":
                criteria_of[rid].add(cid)
    for heading, line, ids in _plan_lines(plan or ""):
        for b in found:
            if b.id in ids or ids & criteria_of[b.id]:
                b.plan.append(PlanLine(heading, line))
    return found


def _git_show(root: Path, ref: str, path: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    result = subprocess.run(
        ["git", "show", f"{ref}:{rel.as_posix()}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def change_blocks(
    root: Path, change_dir: Path, ref: str | None = None
) -> tuple[list[dict], list[str]]:
    """The change's blocks as plain dicts, and its unreadable requirement lines. With `ref`, only
    the blocks that are new or differ from the ones at that ref (the requirement's text, its
    criteria or its plan lines), so an amendment PR checks only what it touched. Unreadable lines
    are always listed: nothing has checked them, whatever the ref."""
    spec_path, plan_path = change_dir / "spec.md", change_dir / "plan.md"
    if not spec_path.exists():
        raise ClauseError(f"{spec_path} doesn't exist")
    plan = plan_path.read_text(encoding="utf-8") if plan_path.exists() else None
    spec = spec_path.read_text(encoding="utf-8")
    current = [asdict(b) for b in blocks(spec, plan)]
    lost = unreadable(spec)
    if ref is None:
        return current, lost
    old_spec = _git_show(root, ref, spec_path)
    if old_spec is None:
        return current, lost
    try:
        old = {b.id: asdict(b) for b in blocks(old_spec, _git_show(root, ref, plan_path))}
    except ClauseError:
        return current, lost
    return [b for b in current if old.get(b["id"]) != b], lost
