"""The roadmap check: docs/roadmap.md, the change intents and the adjustment records agree.

Optional: it runs only in a repo that has `docs/roadmap.md` (#81). The format came from
spellbound3d's change 0011 and its ADR 0009; `.sdlc/docs/roadmap-format.md` describes it for people.

Reads files only (plus the branch name and the git log), and reports every failure in one run:

- every feature change (a folder with `intent.md`) has exactly one row in a milestone's
  `### Changes` table, and every row names such a change;
- every intent has one `Milestone: M<n>` line, and its row sits under that milestone;
- each row's status matches the change's state, as `make next` reads it;
- each `Adjustment:` line names an `accepted` record in docs/roadmap/adjustments/;
- a `done` milestone has only `done` and `withdrawn` rows, and every exit criterion ticked;
- a milestone past `draft` has at least one exit criterion;
- every `done` milestone and row, and nothing else, shows a green tick (✅) before its status.

Anything it can't read (an unknown status, a malformed row or record) is a failure that names
the file, never "nothing there". Folders with only `bug.md` are ignored: bugs aren't planned.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from sdlc.artifacts import BUILD, Build, Problem, change_dirs
from sdlc.routing import WITHDRAWN_RE, merged_build

ROADMAP = "docs/roadmap.md"
ADJUSTMENTS = "docs/roadmap/adjustments"

MILESTONE_STATUSES = ("agreed", "done", "draft", "in progress")
ROW_STATUSES = ("done", "planned", "withdrawn")
RECORD_STATUSES = ("accepted", "proposed", "superseded")
RECORD_CHANGES = ("exit criteria", "goal", "new milestone", "order", "scope")
RECORD_SECTIONS = ("What changes", "Why")
TICK = "✅"  # shown before the status of every done milestone and row, and only those

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_MILESTONE_ANY = re.compile(r"^##\s+M\d+\b")
_MILESTONE = re.compile(r"^##\s+M(\d+):\s+\S.*?\s+·\s+(✅\s+)?`([^`]+)`\s*$")
_CHANGES_HEADING = re.compile(r"^###\s+Changes\s*$")
_EXIT_LABEL = re.compile(r"^\*\*Exit criteria\*\*\s*$")
_CHECKBOX = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+\S")
_TABLE_HEADER = re.compile(r"^\|\s*Change\s*\|\s*Summary\s*\|\s*Status\s*\|\s*$")
_SEPARATOR = re.compile(r"^\|(\s*:?-+:?\s*\|)+\s*$")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_CHANGE_CELL = re.compile(r"^\[(\d{4}-[a-z0-9-]+)\]\(\.\./changes/(\d{4}-[a-z0-9-]+)/\)$")
_MILESTONE_ID = re.compile(r"^M(\d+)$")
_RECORD_NAME = re.compile(r"^\d{4}-[a-z0-9]+(-[a-z0-9]+)*$")
_LINK_TARGET = re.compile(r"\]\(([^)]*)\)")
_CHANGE_PATH = re.compile(r"(?:^|/)(changes/\d{4}-[a-z0-9-]+)/?$")


def strip_comments(text: str) -> str:
    return _COMMENT.sub("", text)


def lines_named(text: str, name: str) -> list[str]:
    """Values of every `Name: value` line, outside HTML comments."""
    pattern = re.compile(rf"^{re.escape(name)}:[ \t]*(.*?)[ \t]*$", re.MULTILINE)
    return pattern.findall(strip_comments(text))


class Report:
    def __init__(self) -> None:
        self.problems: list[Problem] = []

    def fail(self, where: str, message: str) -> None:
        self.problems.append(Problem(Path(where), message))


@dataclass
class Row:
    slug: str
    status: str
    milestone: str
    line: int


@dataclass
class Milestone:
    name: str  # "M1"
    title: str
    status: str
    line: int
    criteria: list[tuple[bool, str]] = field(default_factory=list)  # (ticked, text)


@dataclass
class Roadmap:
    milestones: dict[str, Milestone] = field(default_factory=dict)
    rows: dict[str, Row] = field(default_factory=dict)  # slug -> row


def parse_roadmap(root: Path, report: Report) -> Roadmap:
    roadmap = Roadmap()
    path = root / ROADMAP
    lines = path.read_text(encoding="utf-8").splitlines()
    current: Milestone | None = None
    with_table: set[str] = set()
    in_criteria = False
    for index, line in enumerate(lines):
        number = index + 1
        where = f"{ROADMAP}:{number}"
        if line.startswith("## "):
            current = _milestone_heading(line, number, roadmap, report)
            in_criteria = False
        elif _CHANGES_HEADING.match(line):
            in_criteria = False
            if current is None:
                report.fail(where, "### Changes is not under a ## M<n> milestone")
            elif current.name in with_table:
                report.fail(where, f"{current.name} already has a ### Changes table")
            else:
                with_table.add(current.name)
                _read_table(lines, index + 1, current.name, roadmap, report, where)
        elif current is not None and _EXIT_LABEL.match(line):
            in_criteria = True
        elif in_criteria and (m := _CHECKBOX.match(line)):
            current.criteria.append((m.group(1) != " ", line.strip()))
        elif in_criteria and line.strip() and not line.startswith((" ", "\t")):
            in_criteria = False  # the list ended: the next label, table or paragraph
    return roadmap


def _milestone_heading(line: str, number: int, roadmap: Roadmap, report: Report):
    if not _MILESTONE_ANY.match(line):
        return None  # another section, e.g. "Later": not a milestone, so not checked
    where = f"{ROADMAP}:{number}"
    m = _MILESTONE.match(line)
    if not m or m.group(3) not in MILESTONE_STATUSES:
        report.fail(
            where,
            "milestone heading is not '## M<n>: <title> · `<status>`' with a status of "
            + ", ".join(MILESTONE_STATUSES),
        )
        return None
    if bool(m.group(2)) != (m.group(3) == "done"):
        report.fail(where, f"a done milestone, and only a done one, has {TICK} before its status")
        return None
    name = f"M{int(m.group(1))}"
    if name in roadmap.milestones:
        report.fail(where, f"{name} appears twice")
        return None
    title = line.split(":", 1)[1].rsplit("·", 1)[0].strip()
    roadmap.milestones[name] = Milestone(name, title, m.group(3), number)
    return roadmap.milestones[name]


def _read_table(
    lines: list[str], start: int, milestone: str, roadmap: Roadmap, report: Report, where: str
) -> None:
    i = start
    while i < len(lines) and not lines[i].strip():
        i += 1
    if not (
        i + 1 < len(lines) and _TABLE_HEADER.match(lines[i]) and _SEPARATOR.match(lines[i + 1])
    ):
        report.fail(where, "### Changes has no | Change | Summary | Status | table")
        return
    i += 2
    while i < len(lines) and lines[i].startswith("|"):
        _read_row(lines[i], i + 1, milestone, roadmap, report)
        i += 1


def _read_row(line: str, number: int, milestone: str, roadmap: Roadmap, report: Report) -> None:
    where = f"{ROADMAP}:{number}"
    cells = [c.strip() for c in _CELL_SPLIT.split(line.strip())[1:-1]]
    if len(cells) != 3:
        report.fail(where, f"row has {len(cells)} cells, expected 3")
        return
    m = _CHANGE_CELL.match(cells[0])
    if not m or m.group(1) != m.group(2):
        report.fail(where, f"change cell '{cells[0]}' is not [NNNN-slug](../changes/NNNN-slug/)")
        return
    status = cells[2]
    ticked = status.startswith(TICK)
    status = status.removeprefix(TICK).strip()
    if ticked != (status == "done"):
        report.fail(where, f"write a done row's status as '{TICK} done', and no other with {TICK}")
        return
    if status not in ROW_STATUSES:
        report.fail(where, f"status '{status}' is not one of {', '.join(ROW_STATUSES)}")
        return
    slug = m.group(1)
    if slug in roadmap.rows:
        report.fail(where, f"{slug} already has a row at line {roadmap.rows[slug].line}")
        return
    roadmap.rows[slug] = Row(slug, status, milestone, number)


@dataclass
class Record:
    status: str | None
    number: str


def parse_records(root: Path, roadmap: Roadmap, report: Report) -> dict[str, Record]:
    """Every adjustment record by slug (NNNN-name), each checked for its fields."""
    records: dict[str, Record] = {}
    folder = root / ADJUSTMENTS
    if not folder.is_dir():
        return records
    paths = [p for p in sorted(folder.glob("*.md")) if p.name != "README.md"]
    for path in paths:
        where = f"{ADJUSTMENTS}/{path.name}"
        if not _RECORD_NAME.match(path.stem):
            report.fail(where, "name is not NNNN-<slug>.md")
            continue
        text = path.read_text(encoding="utf-8")
        records[path.stem] = _check_record(text, root, roadmap, report, where, path.stem[:4])
    by_number = {r.number: r for r in records.values()}
    for path in paths:
        if path.stem in records:
            _check_supersedes(path, by_number, report)
    return records


def _one(text: str, name: str, report: Report, where: str) -> str | None:
    values = lines_named(text, name)
    if len(values) != 1:
        report.fail(where, f"no {name}: line" if not values else f"{len(values)} {name}: lines")
        return None
    return values[0]


def _check_record(
    text: str, root: Path, roadmap: Roadmap, report: Report, where: str, number: str
) -> Record:
    status = _one(text, "Status", report, where)
    if status is not None and status not in RECORD_STATUSES:
        report.fail(where, f"Status: '{status}' is not one of {', '.join(RECORD_STATUSES)}")
        status = None
    milestones = _one(text, "Milestones", report, where)
    for name in (m.strip() for m in (milestones or "").split(",") if milestones is not None):
        if not _MILESTONE_ID.match(name):
            report.fail(where, f"Milestones: '{name}' is not M<number>")
        elif f"M{int(name[1:])}" not in roadmap.milestones:
            report.fail(where, f"Milestones: {name} is not a milestone in the roadmap")
    changes = _one(text, "Changes", report, where)
    if changes is not None and changes not in RECORD_CHANGES:
        report.fail(where, f"Changes: '{changes}' is not one of {', '.join(RECORD_CHANGES)}")
    intent = _one(text, "Intent", report, where)
    if intent is not None:
        link = _LINK_TARGET.search(intent)
        target = _CHANGE_PATH.search(link.group(1)) if link else None
        if not target:
            report.fail(where, f"Intent: '{intent}' links to no change folder")
        elif not (root / target.group(1) / "intent.md").is_file():
            report.fail(where, f"Intent: '{target.group(1)}' links to no change folder")
    body = strip_comments(text)
    for heading in RECORD_SECTIONS:
        m = re.search(rf"^##\s+{heading}\s*$(.*?)(?=^##\s|\Z)", body, re.M | re.S)
        if not m:
            report.fail(where, f"no ## {heading} section")
        elif not m.group(1).strip():
            report.fail(where, f"## {heading} is empty")
    return Record(status, number)


def _check_supersedes(path: Path, by_number: dict[str, Record], report: Report) -> None:
    where = f"{ADJUSTMENTS}/{path.name}"
    for value in lines_named(path.read_text(encoding="utf-8"), "Supersedes"):
        if not re.fullmatch(r"\d{4}", value):
            report.fail(where, f"Supersedes: '{value}' is not NNNN")
        elif value not in by_number:
            report.fail(where, f"Supersedes: {value} names no record")
        elif by_number[value].status != "superseded":
            report.fail(where, f"Supersedes: {value} is {by_number[value].status}, not superseded")


def allowed_statuses(
    root: Path, change_dir: Path, text: str, branch: str | None
) -> tuple[set[str], str]:
    """The row statuses this change's state allows, and the reason."""
    if WITHDRAWN_RE.search(text):
        return {"withdrawn"}, "the intent is withdrawn"
    build = change_dir / BUILD
    if build.is_file():
        if (Build.parse(build.read_text(encoding="utf-8")).status or "").startswith("PR open"):
            return {"done"}, "build.md says PR open, so it must be done"
    elif (change_dir / "plan.md").is_file():
        # A small build leaves no file, so its merge is read from history, as `make next` does.
        if pr := merged_build(root, "HEAD", change_dir.name):
            return {"done"}, f"its build merged ({pr}), so it must be done"
        # Not found: unmerged, or a history this can't read (a shallow clone, rebase merges).
        return {"planned", "done"}, "a small build may have merged"
    if branch == f"build/{change_dir.name}":
        return {"planned", "done"}, "this is its build branch"
    return {"planned"}, "its build has not merged (must be planned)"


def _intent_milestone(text: str, report: Report, where: str) -> str | None:
    values = lines_named(text, "Milestone")
    if len(values) != 1:
        report.fail(
            where,
            "intent.md has no Milestone: line (the roadmap milestone it delivers)"
            if not values
            else f"intent.md has {len(values)} Milestone: lines",
        )
        return None
    m = _MILESTONE_ID.match(values[0])
    if not m:
        report.fail(where, f"Milestone: '{values[0]}' is not M<number>")
        return None
    return f"M{int(m.group(1))}"


def check_change(
    root: Path,
    change_dir: Path,
    roadmap: Roadmap,
    records: dict[str, Record],
    branch: str | None,
    report: Report,
) -> None:
    slug = change_dir.name
    where = f"changes/{slug}"
    text = (change_dir / "intent.md").read_text(encoding="utf-8")
    milestone = _intent_milestone(text, report, where)
    if milestone is not None and milestone not in roadmap.milestones:
        report.fail(where, f"Milestone: {milestone} is not a milestone in {ROADMAP}")
    row = roadmap.rows.get(slug)
    if row is None:
        report.fail(where, f"no row in {ROADMAP} (add it to its milestone's ### Changes table)")
    else:
        if milestone is not None and milestone != row.milestone:
            report.fail(where, f"intent.md says {milestone}, but its row is under {row.milestone}")
        allowed, reason = allowed_statuses(root, change_dir, text, branch)
        if row.status not in allowed:
            if row.status == "withdrawn":
                reason = "the intent has no Withdrawn: line"
            report.fail(where, f"row is {row.status}, but {reason}")
    for name in lines_named(text, "Adjustment"):
        if not _RECORD_NAME.match(name):
            report.fail(where, f"Adjustment: '{name}' is not NNNN-<slug>")
        elif name not in records:
            report.fail(where, f"Adjustment: {name} has no record at {ADJUSTMENTS}/{name}.md")
        elif records[name].status != "accepted":
            report.fail(where, f"Adjustment: {name} is {records[name].status}, not accepted")


def check_milestones(roadmap: Roadmap, report: Report) -> None:
    for milestone in roadmap.milestones.values():
        where = f"{ROADMAP}:{milestone.line}"
        if milestone.status != "draft" and not milestone.criteria:
            report.fail(
                where,
                f"{milestone.name} is {milestone.status}, but has no **Exit criteria** "
                "checkboxes (only a draft milestone may have none yet)",
            )
        if milestone.status != "done":
            continue
        for row in roadmap.rows.values():
            if row.milestone == milestone.name and row.status not in ("done", "withdrawn"):
                report.fail(where, f"{milestone.name} is done, but {row.slug} is {row.status}")
        for ticked, text in milestone.criteria:
            if not ticked:
                report.fail(where, f"{milestone.name} is done, but an exit criterion isn't: {text}")


def feature_changes(root: Path) -> list[Path]:
    return [d for d in change_dirs(root) if (d / "intent.md").is_file()]


def current_branch(root: Path) -> str | None:
    for name in ("BRANCH", "GITHUB_HEAD_REF"):
        if os.environ.get(name):
            return os.environ[name]
    try:
        out = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def has_roadmap(root: Path) -> bool:
    return (root / ROADMAP).is_file()


def check_roadmap(root: Path, branch: str | None = None) -> list[Problem]:
    """Every roadmap problem, or none when the repo has no roadmap (it's optional)."""
    if not has_roadmap(root):
        return []
    branch = branch if branch is not None else current_branch(root)
    report = Report()
    roadmap = parse_roadmap(root, report)
    records = parse_records(root, roadmap, report)
    changes = feature_changes(root)
    for change_dir in changes:
        check_change(root, change_dir, roadmap, records, branch, report)
    names = {d.name for d in changes}
    for row in sorted(roadmap.rows.values(), key=lambda r: r.line):
        if row.slug not in names:
            report.fail(
                f"{ROADMAP}:{row.line}", f"row {row.slug} names no change with an intent.md"
            )
    check_milestones(roadmap, report)
    return report.problems
