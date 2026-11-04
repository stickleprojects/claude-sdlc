"""The artifact chain: each change folder holds intent.md -> spec.md -> plan.md.

A bug starts from bug.md instead of intent.md, and its spec may be short:
bug.md -> spec.md (requirements and acceptance criteria) -> plan.md.

Each stage reads the previous artifact, so a later artifact is only valid when
its predecessor exists. Required sections mirror the files in templates/
(templates/bug-spec.md for a bug's spec).
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

SLUG_RE = re.compile(r"^[0-9]{4}-[a-z0-9]+(-[a-z0-9]+)*$")
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


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
    return problems


def change_dirs(root: Path) -> list[Path]:
    changes = root / "changes"
    if not changes.is_dir():
        return []
    return sorted(p for p in changes.iterdir() if p.is_dir() and not p.name.startswith("."))


def next_slug(root: Path, name: str) -> str:
    numbers = [int(p.name[:4]) for p in change_dirs(root) if p.name[:4].isdigit()]
    return f"{max(numbers, default=0) + 1:04d}-{name}"
