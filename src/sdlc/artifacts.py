"""The artifact chain: each change folder holds intent.md -> spec.md -> plan.md.

A bug starts from bug.md instead of intent.md, and its spec may be short:
bug.md -> spec.md (requirements and acceptance criteria) -> plan.md.

Each stage reads the previous artifact, so a later artifact is only valid when
its predecessor exists. Required sections mirror the files in templates/
(templates/bug-spec.md for a bug's spec).

build.md is optional and sits outside the chain: the /build skill writes it from
an approved plan.md to split the build into milestones, one per session.

Architecture decision records (ADRs) sit outside changes altogether, in
docs/adr/NNNN-slug.md (template: templates/adr.md). They belong to the repo, and
/plan reads them and checks each accepted one's "Revisit when" triggers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Ordered: each artifact depends on the one before it.
CHAIN: dict[str, list[str]] = {
    "intent.md": [
        "Problem",
        "Proposed outcome",
        "Affected users and systems",
        "Constraints",
        "Open questions",
    ],
    "spec.md": [
        "Summary",
        "Requirements",
        "Acceptance criteria",
        "Policy concerns",
        "Out of scope",
    ],
    "plan.md": [
        "Approach",
        "Steps",
        "Verification",
        "Risks",
    ],
}

# A bug found in testing: a lighter first artifact, and a spec that needs only the
# requirements and one acceptance test per symptom.
BUG_CHAIN: dict[str, list[str]] = {
    "bug.md": [
        "What happens",
        "What should happen",
        "Steps to reproduce",
        "Where seen",
    ],
    "spec.md": [
        "Requirements",
        "Acceptance criteria",
    ],
    "plan.md": CHAIN["plan.md"],
}

# Where each chain's artifacts come from, by artifact name.
TEMPLATES: dict[str, dict[str, str]] = {
    "feature": {name: name for name in CHAIN},
    "bug": {"bug.md": "bug.md", "spec.md": "bug-spec.md", "plan.md": "plan.md"},
}

# Optional: the build plan, written by /build once plan.md is merged.
BUILD = "build.md"
BUILD_SECTIONS = [
    "Questions before approval",
    "Milestones",
    "Deviations from the plan",
    "Flaky tests",
    "Session log",
]
BUILD_STATUSES = ("draft", "in progress", "PR open")
MILESTONE_STATUSES = ("todo", "in progress", "done", "reopened")

# Optional: architecture decision records, one file per decision.
ADR_DIR = Path("docs") / "adr"
ADR_SECTIONS = [
    "Status",
    "Context",
    "Decision",
    "Alternatives considered",
    "Consequences",
    "Revisit when",
]
ADR_STATUS_RE = re.compile(r"^(proposed|accepted|superseded by (?:ADR )?(\d{4}))\b", re.I)
ADR_SKIP = ("README.md", "index.md")
# "Revisit when" lines that name no trigger, once the list marker is stripped.
NO_TRIGGER = {"none", "never", "n/a", "na", "tbd", "todo", "-"}
LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*")

SLUG_RE = re.compile(r"^[0-9]{4}-[a-z0-9]+(-[a-z0-9]+)*$")
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
MILESTONE_RE = re.compile(r"^###\s+(M\d+)\b.*$", re.MULTILINE)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def field(text: str, name: str) -> str | None:
    """Value of a `- **Name:** value` line, without HTML comments, or None."""
    m = re.search(rf"^\s*-\s+\*\*{re.escape(name)}:\*\*(.*)$", text, re.MULTILINE)
    return COMMENT_RE.sub("", m.group(1)).strip() if m else None


def section(text: str, heading: str) -> str:
    """Body of a `## heading` section, without HTML comments."""
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    return COMMENT_RE.sub("", m.group(1)).strip() if m else ""


@dataclass(frozen=True)
class Build:
    """What build.md says: the build's status and each milestone's status."""

    status: str | None
    approved: str | None
    milestones: dict[str, str | None]
    questions: str

    @classmethod
    def parse(cls, text: str) -> Build:
        text_no_comments = COMMENT_RE.sub("", text)
        parts = MILESTONE_RE.split(text_no_comments)
        header = parts[0]
        milestones = {parts[i]: field(parts[i + 1], "Status") for i in range(1, len(parts), 2)}
        return cls(
            status=field(header, "Status"),
            approved=field(header, "Approved"),
            milestones=milestones,
            questions=section(text, "Questions before approval"),
        )

    @property
    def is_draft(self) -> bool:
        return (self.status or "").startswith("draft")

    def progress(self) -> str:
        done = sum(1 for s in self.milestones.values() if (s or "").startswith("done"))
        return f"{self.status or 'no status'}, {done}/{len(self.milestones)} milestones done"


def check_build(path: Path) -> list[Problem]:
    text = path.read_text(encoding="utf-8")
    problems: list[Problem] = []
    build = Build.parse(text)
    if not build.status or not build.status.startswith(BUILD_STATUSES):
        problems.append(
            Problem(path, f"Status must start with one of: {', '.join(BUILD_STATUSES)}")
        )
    # A build whose PR is open is history; builds written before these rules stay valid.
    finished = (build.status or "").startswith("PR open")
    required = ["Milestones"] if finished else BUILD_SECTIONS
    missing = [h for h in required if h not in headings(text)]
    if missing:
        problems.append(Problem(path, f"missing sections: {', '.join(missing)}"))
    if not build.milestones:
        problems.append(Problem(path, "has no milestones (### M1. <name>)"))
    elif len(build.milestones) == 1 and not finished:
        problems.append(
            Problem(path, "has one milestone: build it in one session from plan.md, no build.md")
        )
    for name, status in build.milestones.items():
        if not status or not status.startswith(MILESTONE_STATUSES):
            problems.append(
                Problem(path, f"{name} status must be one of: {', '.join(MILESTONE_STATUSES)}")
            )
    if build.status and not build.is_draft and not finished:
        if build.questions not in ("None", "None."):
            problems.append(Problem(path, "approved, but Questions before approval isn't 'None.'"))
        if not build.approved or build.approved.lower().startswith("not yet"):
            problems.append(Problem(path, "approved, but Approved doesn't say who and when"))
    if build.is_draft:
        # A re-draft (the plan changed mid-build) keeps its done milestones, but no
        # milestone is built while the build plan waits for approval.
        started = [n for n, s in build.milestones.items() if (s or "").startswith("in progress")]
        if started:
            names = ", ".join(started)
            problems.append(Problem(path, f"still a draft, but {names} is in progress"))
    return problems


@dataclass(frozen=True)
class Problem:
    path: Path
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def headings(text: str) -> set[str]:
    return {h.strip() for h in HEADING_RE.findall(text)}


def kind(change_dir: Path) -> str:
    """'bug' when the change starts from bug.md, otherwise 'feature'."""
    return "bug" if (change_dir / "bug.md").exists() else "feature"


def chain(change_dir: Path) -> dict[str, list[str]]:
    return BUG_CHAIN if kind(change_dir) == "bug" else CHAIN


def stage(change_dir: Path) -> str:
    """Name of the latest artifact present, or 'empty'."""
    if (change_dir / BUILD).exists() and (change_dir / "plan.md").exists():
        return "build"
    present = [name for name in chain(change_dir) if (change_dir / name).exists()]
    return present[-1].removesuffix(".md") if present else "empty"


def check_change(change_dir: Path) -> list[Problem]:
    problems: list[Problem] = []
    if not SLUG_RE.match(change_dir.name):
        problems.append(Problem(change_dir, "folder name must look like 0001-short-slug"))

    if (change_dir / "intent.md").exists() and (change_dir / "bug.md").exists():
        problems.append(Problem(change_dir, "has both intent.md and bug.md; keep one"))

    previous_present = True
    for name, required in chain(change_dir).items():
        path = change_dir / name
        if not path.exists():
            previous_present = False
            continue
        if not previous_present:
            problems.append(Problem(path, "exists but an earlier artifact in the chain is missing"))
        missing = [h for h in required if h not in headings(path.read_text(encoding="utf-8"))]
        if missing:
            problems.append(Problem(path, f"missing sections: {', '.join(missing)}"))
    if not any((change_dir / first).exists() for first in ("intent.md", "bug.md")):
        problems.append(Problem(change_dir, "has no intent.md (or bug.md for a bug)"))
    build = change_dir / BUILD
    if build.exists():
        if not (change_dir / "plan.md").exists():
            problems.append(Problem(build, "exists but plan.md is missing"))
        problems.extend(check_build(build))
    return problems


def adr_files(root: Path) -> list[Path]:
    folder = root / ADR_DIR
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.md") if p.name not in ADR_SKIP)


def revisit_triggers(text: str) -> list[str]:
    """An ADR's Revisit when lines, without list markers or placeholders that name no trigger."""
    lines = (
        LIST_MARKER_RE.sub("", line).strip() for line in section(text, "Revisit when").splitlines()
    )
    return [line for line in lines if line and line.rstrip(".").lower() not in NO_TRIGGER]


def check_adrs(root: Path) -> list[Problem]:
    """Each ADR has its sections and a known status; an accepted one says when to revisit it."""
    problems: list[Problem] = []
    files = adr_files(root)
    numbers: dict[str, list[Path]] = {}
    for path in files:
        if SLUG_RE.match(path.stem):
            numbers.setdefault(path.stem[:4], []).append(path)
        else:
            problems.append(Problem(path, "ADR file name must look like 0001-short-slug.md"))
    for number, paths in numbers.items():
        if len(paths) > 1:
            names = ", ".join(p.name for p in paths)
            problems.append(Problem(paths[0].parent, f"ADR number {number} is used twice: {names}"))
    for path in files:
        text = path.read_text(encoding="utf-8")
        missing = [h for h in ADR_SECTIONS if h not in headings(text)]
        if missing:
            problems.append(Problem(path, f"missing sections: {', '.join(missing)}"))
        status = section(text, "Status")
        m = ADR_STATUS_RE.match(status)
        if not m:
            problems.append(
                Problem(path, "Status must start with: proposed, accepted or superseded by NNNN")
            )
        elif m.group(2) and m.group(2) not in numbers:
            problems.append(Problem(path, f"superseded by {m.group(2)}, but there's no such ADR"))
        elif m.group(1).lower() == "accepted":
            triggers = revisit_triggers(text)
            if "<trigger>" in triggers:
                problems.append(Problem(path, "Revisit when still has the template's <trigger>"))
            if not [t for t in triggers if t != "<trigger>"]:
                problems.append(
                    Problem(path, "accepted, but Revisit when names no trigger to check at /plan")
                )
    return problems


def build_progress(change_dir: Path) -> str | None:
    """One line of build progress from build.md, or None when there is none."""
    path = change_dir / BUILD
    if not path.exists():
        return None
    return Build.parse(path.read_text(encoding="utf-8")).progress()


def change_dirs(root: Path) -> list[Path]:
    changes = root / "changes"
    if not changes.is_dir():
        return []
    return sorted(p for p in changes.iterdir() if p.is_dir() and not p.name.startswith("."))


def next_slug(root: Path, name: str) -> str:
    numbers = [int(p.name[:4]) for p in change_dirs(root) if p.name[:4].isdigit()]
    return f"{max(numbers, default=0) + 1:04d}-{name}"
