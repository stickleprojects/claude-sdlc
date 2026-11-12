"""The project's overrides of framework files (#133).

The framework lives in .sdlc/ and the sync owns it. A project changes a framework file by
putting its own version at the same path under .sdlc-local/, which the sync never writes:

- a whole-file override replaces the framework's file;
- a Markdown override that starts with `<!-- extends -->` changes only named blocks of it.

In an extending override, each operation names a block of the base file and says what to do:

    <!-- replace: Problem -->      ...new text for the block...   <!-- /replace -->
    <!-- append: Problem -->       ...text added at its end...    <!-- /append -->
    <!-- prepend: Problem -->      ...text added at its start...  <!-- /prepend -->

Without a name, `append` and `prepend` apply to the whole file. Every heading is a block
named by its text, running to the next heading of the same or a higher level; a base file can
mark a finer block with `<!-- block: name -->` ... `<!-- /block: name -->`. Text outside the
operations is ignored, so an override can explain itself in comments.

Only the folders below can be overridden. Code and the guardrail hooks can't: an override
there would let a project, or an agent working in it, switch a guardrail off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

FRAMEWORK = Path(".sdlc")
LOCAL = Path(".sdlc-local")
OVERRIDABLE = ("skills/", "agents/", "templates/", "prompts/", "REVIEW.md")
# Hooks can be added (rows in .sdlc-local/hooks/hooks.tsv, scripts beside it), never replaced.
LOCAL_HOOKS = "hooks/"

EXTENDS = re.compile(r"\A\s*<!--\s*extends\s*-->[ \t]*\n?")
OPERATION = re.compile(
    r"<!--\s*(?P<op>replace|append|prepend)(?:\s*:\s*(?P<name>.*?))?\s*-->[ \t]*\n?"
    r"(?P<body>.*?)"
    r"<!--\s*/(?P=op)\s*-->[ \t]*\n?",
    re.S,
)
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^\s*(```|~~~)")
MARK_OPEN = re.compile(r"^\s*<!--\s*block\s*:\s*(.+?)\s*-->\s*$")
MARK_CLOSE = re.compile(r"^\s*<!--\s*/block\s*:\s*(.+?)\s*-->\s*$")


class OverrideError(Exception):
    """An override that can't be applied: the message says which file and why."""


@dataclass(frozen=True)
class Block:
    name: str
    start: int  # offset of the block's first character (its heading or marker line)
    end: int  # offset just past its last character
    marked: bool = False  # between <!-- block --> markers, which stay in place


def overridable(rel: str) -> bool:
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in OVERRIDABLE)


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


def blocks(text: str) -> dict[str, Block]:
    """Every heading and marked block in a Markdown file, by normalised name."""
    lines = text.splitlines(keepends=True)
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line)
    end_of_text = pos

    found: dict[str, Block] = {}
    headings: list[tuple[int, str, int]] = []  # (level, name, line index)
    marks: dict[str, int] = {}
    in_fence = False
    for i, line in enumerate(lines):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if m := HEADING.match(line.rstrip("\n")):
            headings.append((len(m[1]), m[2], i))
        elif m := MARK_OPEN.match(line):
            marks[_norm(m[1])] = i
        elif (m := MARK_CLOSE.match(line)) and _norm(m[1]) in marks:
            start = marks.pop(_norm(m[1]))
            end = offsets[i] + len(lines[i])
            found[_norm(m[1])] = Block(m[1], offsets[start], end, marked=True)
    for n, (level, name, i) in enumerate(headings):
        end = end_of_text
        for later_level, _, j in headings[n + 1 :]:
            if later_level <= level:
                end = offsets[j]
                break
        found.setdefault(_norm(name), Block(name, offsets[i], end))
    return found


def extend(base: str, override: str, where: str = "override") -> str:
    """Apply an extending override's operations to the base text, in order."""
    body = EXTENDS.sub("", override, count=1)
    ops = list(OPERATION.finditer(body))
    if not ops:
        raise OverrideError(f"{where}: starts with <!-- extends --> but has no operations")
    text = base
    for op in ops:
        kind, name, new = op["op"], (op["name"] or "").strip(), op["body"]
        if not name:
            if kind == "replace":
                raise OverrideError(f"{where}: replace needs a block name (or override the file)")
            text = (text + _sep(text) + new) if kind == "append" else (new + _sep(new) + text)
            continue
        found = blocks(text).get(_norm(name))
        if found is None:
            raise OverrideError(f"{where}: the base file has no block named {name!r}")
        chunk = text[found.start : found.end]
        if found.marked:  # work on what's between the markers; the markers stay
            first, _, rest = chunk.partition("\n")
            inner, _, close = rest.rstrip("\n").rpartition("\n")
            inner = inner + "\n" if inner else ""
            if kind == "replace":
                inner = new.rstrip("\n") + "\n" if new.strip() else ""
            elif kind == "append":
                inner = inner + new.rstrip("\n") + "\n"
            else:
                inner = new.rstrip("\n") + "\n" + inner
            chunk = first + "\n" + inner + close + chunk[len(chunk.rstrip("\n")) :]
        elif kind == "replace":  # the new text, then the gap the old block left before the next
            trail = chunk[len(chunk.rstrip("\n")) :]
            chunk = (new.rstrip("\n") + "\n" + trail[1:]) if new.strip() else ""
        elif kind == "append":
            trail = chunk[len(chunk.rstrip("\n")) :]  # keep the blank line before the next block
            chunk = chunk.rstrip("\n") + "\n" + new.rstrip("\n") + "\n" + trail[1:]
        elif kind == "prepend":
            first, _, rest = chunk.partition("\n")  # after the heading line
            chunk = first + "\n" + new.rstrip("\n") + "\n" + rest
        text = text[: found.start] + chunk + text[found.end :]
    return text


def _sep(text: str) -> str:
    return "" if text.endswith("\n\n") or not text else ("\n" if text.endswith("\n") else "\n\n")


def resolve(root: Path, rel: str) -> str:
    """The effective text of .sdlc/<rel>: the project's override applied, if it has one."""
    rel = rel.removeprefix("./").removeprefix(f"{FRAMEWORK}/").removeprefix(f"{LOCAL}/")
    base_path, local_path = root / FRAMEWORK / rel, root / LOCAL / rel
    if not local_path.is_file():
        if not base_path.is_file():
            raise OverrideError(f"{FRAMEWORK / rel}: no such framework file")
        return base_path.read_text(encoding="utf-8")
    if not overridable(rel):
        raise OverrideError(f"{LOCAL / rel}: {rel} can't be overridden ({_why(rel)})")
    local = local_path.read_text(encoding="utf-8")
    if not EXTENDS.match(local):
        return local
    if not base_path.is_file():
        raise OverrideError(f"{LOCAL / rel}: extends {FRAMEWORK / rel}, which doesn't exist")
    if base_path.suffix != ".md":
        raise OverrideError(f"{LOCAL / rel}: only Markdown files can be extended block by block")
    return extend(base_path.read_text(encoding="utf-8"), local, str(LOCAL / rel))


def _why(rel: str) -> str:
    if rel.startswith(LOCAL_HOOKS):
        return "hooks can be added in .sdlc-local/hooks/hooks.tsv, not replaced"
    return "only " + ", ".join(OVERRIDABLE) + " can be"


def local_files(root: Path) -> list[str]:
    """Every file under .sdlc-local/, relative to it."""
    local = root / LOCAL
    if not local.is_dir():
        return []
    return sorted(p.relative_to(local).as_posix() for p in local.rglob("*") if p.is_file())


def check_overrides(root: Path) -> list[tuple[Path, str]]:
    """Each override that doesn't resolve, as (path, problem), for `sdlc check`."""
    problems = []
    for rel in local_files(root):
        if rel == "local.mk":
            continue  # make settings, not an override
        if rel.startswith(LOCAL_HOOKS):
            if (root / FRAMEWORK / rel).exists():  # added hooks are fine; replacing one isn't
                problems.append((root / LOCAL / rel, f"{rel} can't be overridden ({_why(rel)})"))
            continue
        try:
            resolve(root, rel)
        except OverrideError as e:
            problems.append((root / LOCAL / rel, str(e).split(": ", 1)[-1]))
    return problems
