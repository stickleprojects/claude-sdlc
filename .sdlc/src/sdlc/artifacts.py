"""The artifact chain: each change folder holds intent.md -> spec.md -> plan.md.

A bug starts from bug.md instead of intent.md, and its spec may be short:
bug.md -> spec.md (requirements and acceptance criteria) -> plan.md.

Each stage reads the previous artifact, so a later artifact is only valid when
its predecessor exists. Required sections mirror the files in .sdlc/templates/
(.sdlc/templates/bug-spec.md for a bug's spec).

build.md is optional and sits outside the chain: the /build skill writes it from
an approved plan.md to split the build into milestones, one per session.

Architecture decision records (ADRs) sit outside changes altogether, in
docs/adr/NNNN-slug.md (template: .sdlc/templates/adr.md). They belong to the repo, and
/plan reads them and checks each accepted one's "Revisit when" triggers.

The words that read as "nothing here" in a section come from placeholders.toml,
overridable per repo in .sdlc.toml (see Placeholders).

A plan's Descopes section lists what it leaves undone, untested or checked only by hand, each with
a person's approval (.sdlc/skills/scope.md). It is required only in a plan.md the branch adds or
edits, so plans merged before it existed stay valid (NEW_SECTIONS). Such a plan also names, under
Verification, the kinds of work from the definition of done that apply (DefinitionOfDone).
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Collection
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
        "Descopes",
    ],
}

# Sections added after changes were already merged without them. They are required only in a file
# the branch adds or edits against main (#95), so merged artifacts stay valid until they're edited.
NEW_SECTIONS: dict[str, frozenset[str]] = {"plan.md": frozenset({"Descopes"})}

# A Descopes entry: `- Descope: <what> because <reason>. Approved: <name>, <date>.`, or a check a
# person must try by hand: `- Human check: <what, and how> because <reason>. Approved: …`.
# The definition of done: what done means for each kind of work. The framework's rows are in
# .sdlc/templates/definition-of-done.md (synced); a repo's docs/definition-of-done.md (never
# synced) adds kinds and replaces the framework's row of the same kind.
DOD_DEFAULTS = Path(".sdlc") / "templates" / "definition-of-done.md"
DOD_PROJECT = Path("docs") / "definition-of-done.md"
DOD_FIELD = "Definition of done"
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")

DESCOPE_KINDS = ("Descope", "Human check")
DESCOPE_RE = re.compile(rf"^(?:\*\*)?({'|'.join(DESCOPE_KINDS)}):(?:\*\*)?\s*", re.I)
APPROVED_RE = re.compile(r"\bApproved:(?:\*\*)?\s*(.*)$", re.I)

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
LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*")

SLUG_RE = re.compile(r"^[0-9]{4}-[a-z0-9]+(-[a-z0-9]+)*$")
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
MILESTONE_RE = re.compile(r"^###\s+(M\d+)\b.*$", re.MULTILINE)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# An acceptance criterion: `- AC1 (R1): ...` (or `- A1 ...`), the form coverage checks read.
CRITERION_RE = re.compile(r"^\s*[-*]\s+(?:\*\*)?AC?\d+\b", re.MULTILINE)
NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)


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


@dataclass(frozen=True)
class DefinitionOfDone:
    """The kinds of work and what done means for each, the framework's rows merged with the repo's.

    rows: kind, lowercased, to (the kind as written, what done means). problems: what was wrong
    with either table."""

    rows: dict[str, tuple[str, str]]
    problems: tuple[Problem, ...] = ()

    @property
    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.rows.values()]


def table_rows(text: str) -> list[tuple[str, str]]:
    """The (first, second) cells of each row of a Markdown table, without its header row."""
    rows: list[tuple[str, str]] = []
    for line in COMMENT_RE.sub("", text).splitlines():
        m = TABLE_ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 2 or not cells[0].strip("-: "):
            continue  # the |---|---| line
        kind = cells[0].strip("* ")
        if kind.lower() != "kind of work":
            rows.append((kind, cells[1]))
    return rows


def definition_of_done(root: Path) -> DefinitionOfDone:
    """The framework's table, then the repo's on top: same kind replaces, a new kind is added."""
    rows: dict[str, tuple[str, str]] = {}
    problems: list[Problem] = []
    for path in (root / DOD_DEFAULTS, root / DOD_PROJECT):
        if not path.exists():
            continue
        found = table_rows(path.read_text(encoding="utf-8"))
        if not found:
            problems.append(
                Problem(path, "has no rows: expected a '| Kind of work | Done means |' table")
            )
        seen: set[str] = set()
        for kind, done in found:
            key = kind.lower()
            if key in seen:
                problems.append(Problem(path, f"lists the kind '{kind}' twice"))
            if "," in kind:
                problems.append(
                    Problem(path, f"kind '{kind}' has a comma; plans separate kinds with commas")
                )
            if not done:
                problems.append(Problem(path, f"kind '{kind}' doesn't say what done means"))
            seen.add(key)
            rows[key] = (kind, done)
    return DefinitionOfDone(rows=rows, problems=tuple(problems))


def check_dod(path: Path, dod: DefinitionOfDone) -> list[Problem]:
    """A plan names, under Verification, the kinds of work from the definition of done it meets."""
    if not dod.rows:  # fail safe: with no table, no name could be checked
        return [Problem(path, f"no definition of done found: expected {DOD_DEFAULTS}")]
    value = field(section(path.read_text(encoding="utf-8"), "Verification"), DOD_FIELD)
    known = f"known kinds: {', '.join(dod.kinds)}"
    line = f"'- **{DOD_FIELD}:** <kinds>'"
    if value is None:
        return [
            Problem(
                path,
                f"Verification has no {line} line naming the kinds of work that apply ({known})",
            )
        ]
    names = [n.strip().rstrip(".") for n in value.split(",") if n.strip()]
    if not names or value.startswith("<"):
        return [Problem(path, f"{DOD_FIELD} names no kind of work ({known})")]
    unknown = [n for n in names if n.lower() not in dod.rows]
    if unknown:
        return [
            Problem(
                path,
                f"{DOD_FIELD} names {', '.join(unknown)}, not in the definition of done ({known})",
            )
        ]
    return []


@dataclass(frozen=True)
class Placeholders:
    """Words that read as "nothing here": placeholders.toml merged with the repo's .sdlc.toml.

    nothing_written: for sections that must have content; compared per line, ignoring case,
    a list marker and a trailing full stop. explicit_none: for sections that must be cleared;
    compared exactly. problems: what was wrong with .sdlc.toml (its bad keys are ignored).
    """

    nothing_written: frozenset[str]
    explicit_none: frozenset[str]
    problems: tuple[str, ...] = ()

    def names_nothing(self, line: str) -> bool:
        word = LIST_MARKER_RE.sub("", line).strip().rstrip(".").lower()
        return not word or word in self.nothing_written

    def is_none(self, text: str) -> bool:
        return text.strip() in self.explicit_none


DEFAULT_PLACEHOLDERS = Path(__file__).with_name("placeholders.toml")
CONFIG_FILE = ".sdlc.toml"


PLACEHOLDER_KEYS = ("keywords", "additional_keywords")


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def placeholders(root: Path) -> Placeholders:
    """The framework's lists, merged with the repo's .sdlc.toml: per list, the repo's `keywords`
    replace the framework's, then its `additional_keywords` are added."""
    shipped = tomllib.loads(DEFAULT_PLACEHOLDERS.read_text(encoding="utf-8"))["placeholders"]
    words = {name: list(table["keywords"]) for name, table in shipped.items()}
    problems: list[str] = []
    local: object = {}
    config = root / CONFIG_FILE
    if config.exists():
        try:
            local = tomllib.loads(config.read_text(encoding="utf-8")).get("placeholders", {})
        except tomllib.TOMLDecodeError as e:
            problems.append(f"isn't valid TOML ({e}); using the framework's words")
    if not isinstance(local, dict):
        problems.append("[placeholders] must be a table; using the framework's words")
        local = {}
    for name, table in local.items():
        where = f"placeholders.{name}"
        if name not in words:
            problems.append(f"unknown list {where}; expected one of: {', '.join(words)}")
            continue
        if not isinstance(table, dict):
            problems.append(f"{where} must be a table with keywords or additional_keywords")
            continue
        for key, value in table.items():
            if key not in PLACEHOLDER_KEYS:
                problems.append(
                    f"unknown key {where}.{key}; expected one of: {', '.join(PLACEHOLDER_KEYS)}"
                )
            elif not _strings(value):
                problems.append(f"{where}.{key} must be a list of strings")
        if _strings(table.get("keywords")):
            words[name] = list(table["keywords"])
        if _strings(table.get("additional_keywords")):
            words[name] += table["additional_keywords"]
    return Placeholders(
        nothing_written=frozenset(w.strip().rstrip(".").lower() for w in words["nothing_written"]),
        explicit_none=frozenset(w.strip() for w in words["explicit_none"]),
        problems=tuple(problems),
    )


def check_config(root: Path) -> list[Problem]:
    return [Problem(root / CONFIG_FILE, p) for p in placeholders(root).problems]


def check_build(path: Path, words: Placeholders | None = None) -> list[Problem]:
    words = words or placeholders(path.parents[2])
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
        if not words.is_none(build.questions):
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


def check_criteria(path: Path) -> list[Problem]:
    """A spec's acceptance criteria are `- AC<n>` bullets, not a numbered list (#90).

    Checked while the spec is the latest artifact and the branch adds or edits it, so the spec PR
    fails rather than the plan PR after it; merged specs, and specs that already have a plan,
    stay as they were merged.
    """
    text = path.read_text(encoding="utf-8")
    if "Acceptance criteria" not in headings(text):
        return []  # reported as a missing section
    body = section(text, "Acceptance criteria")
    expected = "expected '- AC<n> (R<n>): ...' bullets"
    # A readable criterion passes, even with numbered steps nested under it.
    if CRITERION_RE.search(body):
        return []
    if NUMBERED_RE.search(body):
        return [Problem(path, f"Acceptance criteria are a numbered list; {expected}")]
    return [Problem(path, f"Acceptance criteria has no criterion that can be read; {expected}")]


def check_requirements(path: Path) -> list[Problem]:
    """Every line under a spec's ## Requirements reads as a requirement (`- R<n>. ...`), so the
    clause check can split it (#47). Checked only in specs the branch adds or edits: specs merged
    before this rule stay valid until someone edits them."""
    from sdlc.clauses import ClauseError, blocks, unreadable  # clauses imports this module

    text = path.read_text(encoding="utf-8")
    if "Requirements" not in headings(text):
        return []  # reported as a missing section
    expected = "expected '- R<n>. <requirement>'"
    try:
        blocks(text)
    except ClauseError:
        return [Problem(path, f"no requirement under ## Requirements can be read; {expected}")]
    return [
        Problem(path, f"can't read this as a requirement ({expected}): {line}")
        for line in unreadable(text)
    ]


def descope_items(body: str) -> list[str]:
    """Each entry in a Descopes section, without the list marker. An indented line straight after an
    entry is a wrapped part of it; any other line is an entry of its own, so prose after an approved
    entry is checked as an entry, not read as part of it."""
    items: list[str] = []
    wrapping = False  # the line before was part of an entry
    for line in body.splitlines():
        if not line.strip():
            wrapping = False
            continue
        text = LIST_MARKER_RE.sub("", line).strip()
        if wrapping and line[:1].isspace() and not LIST_MARKER_RE.match(line):
            items[-1] += " " + text
        else:
            items.append(text)
        wrapping = True
    return items


def check_descopes(path: Path, words: Placeholders) -> list[Problem]:
    """A plan's Descopes: `None.`, or entries that each say what kind they are and who approved
    them. A descope still written in Risks, the place before this section, is reported too."""
    text = path.read_text(encoding="utf-8")
    problems: list[Problem] = []
    for line in section(text, "Risks").splitlines():
        if DESCOPE_RE.match(LIST_MARKER_RE.sub("", line).strip()):
            problems.append(
                Problem(path, "a Descope: or Human check: line is in Risks; move it to Descopes")
            )
            break
    if "Descopes" not in headings(text):
        return problems  # reported as a missing section
    body = section(text, "Descopes")
    if words.is_none(body):
        return problems
    form = "'- Descope: <what> because <reason>. Approved: <name>, <date>.' (or '- Human check: …')"
    items = descope_items(body)
    if not items:
        return [
            *problems,
            Problem(path, f"Descopes is empty; write 'None.' or list each as {form}"),
        ]
    for item in items:
        quoted = item if len(item) <= 60 else item[:57] + "..."
        if item.startswith("<"):
            problems.append(
                Problem(path, f"Descopes still has the template's text; write 'None.' or {form}")
            )
            continue
        if not DESCOPE_RE.match(item):
            problems.append(Problem(path, f"Descopes entry isn't in the form {form}: {quoted}"))
            continue
        m = APPROVED_RE.search(item)
        who = (m.group(1) if m else "").strip().rstrip(".")
        if (
            not who
            or who.startswith("<")
            or who.lower().startswith("not yet")
            or words.names_nothing(who)
        ):
            problems.append(
                Problem(path, f"Descopes entry has no 'Approved: <name>, <date>': {quoted}")
            )
    return problems


def check_change(
    change_dir: Path,
    words: Placeholders | None = None,
    changed: Collection[Path] | None = None,
    dod: DefinitionOfDone | None = None,
) -> list[Problem]:
    """Problems with one change folder. `changed` holds the files the branch adds or edits
    (resolved paths); NEW_SECTIONS, the Descopes rules, the definition of done line, the
    readable-requirements rule and the criteria form apply only to those. None means it isn't
    known (no git, or no main to compare with), and those rules are skipped."""
    problems: list[Problem] = []
    words = words or placeholders(change_dir.parents[1])
    edited = {p.resolve() for p in changed or ()}
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
        is_edited = path.resolve() in edited
        if not is_edited:
            required = [h for h in required if h not in NEW_SECTIONS.get(name, ())]
        missing = [h for h in required if h not in headings(path.read_text(encoding="utf-8"))]
        if missing:
            problems.append(Problem(path, f"missing sections: {', '.join(missing)}"))
        if name == "spec.md" and is_edited:
            problems.extend(check_requirements(path))
        if name == "plan.md" and is_edited:
            problems.extend(check_descopes(path, words))
            problems.extend(check_dod(path, dod or definition_of_done(change_dir.parents[1])))
    spec = change_dir / "spec.md"
    # Only a spec the branch adds or edits, like the other new rules: a merged spec in a form
    # this rejects would otherwise fail every unrelated branch, sync PRs included (#101).
    if spec.exists() and not (change_dir / "plan.md").exists() and spec.resolve() in edited:
        problems.extend(check_criteria(spec))
    if not any((change_dir / first).exists() for first in ("intent.md", "bug.md")):
        problems.append(Problem(change_dir, "has no intent.md (or bug.md for a bug)"))
    build = change_dir / BUILD
    if build.exists():
        if not (change_dir / "plan.md").exists():
            problems.append(Problem(build, "exists but plan.md is missing"))
        problems.extend(check_build(build, words))
    return problems


def adr_files(root: Path) -> list[Path]:
    folder = root / ADR_DIR
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.md") if p.name not in ADR_SKIP)


def revisit_triggers(text: str, words: Placeholders) -> list[str]:
    """An ADR's Revisit when lines that name a trigger, without their list markers."""
    lines = section(text, "Revisit when").splitlines()
    return [
        LIST_MARKER_RE.sub("", ln).strip()
        for ln in lines
        if ln.strip() and not words.names_nothing(ln)
    ]


def check_adrs(root: Path, words: Placeholders | None = None) -> list[Problem]:
    """Each ADR has its sections and a known status; an accepted one says when to revisit it."""
    words = words or placeholders(root)
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
            triggers = revisit_triggers(text, words)
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
