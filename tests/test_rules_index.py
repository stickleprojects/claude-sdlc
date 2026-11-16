"""The rules index (.sdlc/docs/rules.md) and the rule markers in the prompts agree (#201).

Each rule in REVIEW.md, the skills and the verifier carries a `<!-- rule: <id> -->` marker on
its line, and has one row in the index under the heading of the file it lives in, saying what
holds it. These tests replace checking a rule's wording: a reworded rule keeps its marker, and
a deleted or moved one fails here until the index says so.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INDEX = REPO / ".sdlc/docs/rules.md"
MARKER = re.compile(r"<!-- rule: ([^ ]+) -->")
ID = re.compile(r"^[a-z]+\.[a-z0-9-]+$")
# Where rules live: every prompt the skills, the review and the verifier read.
PROMPTS = ["REVIEW.md", "skills/**/*.md", "agents/*.md"]
HOLDER_KINDS = ("hook", "check", "eval", "test")


def prompt_files() -> list[Path]:
    return sorted({p for g in PROMPTS for p in (REPO / ".sdlc").glob(g)})


def markers() -> list[tuple[str, str]]:
    """(id, file) for every marker in every Markdown file under .sdlc/."""
    found = []
    for path in sorted((REPO / ".sdlc").rglob("*.md")):
        if path == INDEX:  # its intro shows the marker's form
            continue
        for rid in MARKER.findall(path.read_text(encoding="utf-8")):
            found.append((rid, path.relative_to(REPO).as_posix()))
    return found


def parse_index(text: str) -> list[tuple[str, str, list[str]]]:
    """(id, home file, holders) per row; a row outside a file's section is an error."""
    rows, home = [], None
    for line in text.splitlines():
        if m := re.fullmatch(r"## `([^`]+)`", line):
            home = m.group(1)
            continue
        m = re.fullmatch(r"\| `([^`]+)` \| (.+) \| (.+) \|", line)
        if not m:
            continue
        assert home, f"row outside a file's section: {line}"
        held = m.group(3).strip()
        holders = [] if held == "nothing" else re.findall(r"`([^`]+)`", held)
        assert held == "nothing" or holders, (
            f"{m.group(1)}: Held by is neither holders nor 'nothing'"
        )
        rows.append((m.group(1), home, holders))
    return rows


ROWS = parse_index(INDEX.read_text(encoding="utf-8"))


def test_the_index_has_rows() -> None:
    assert len(ROWS) > 100, "the index parser found too few rows: did the table format change?"


def test_ids_are_unique_and_well_formed() -> None:
    ids = [rid for rid, _, _ in ROWS]
    assert sorted(i for i in set(ids) if ids.count(i) > 1) == []
    assert [i for i in ids if not ID.match(i)] == []


def test_each_marker_appears_once() -> None:
    found = [rid for rid, _ in markers()]
    assert sorted(i for i in set(found) if found.count(i) > 1) == [], "a rule has one home"


def test_every_marker_is_indexed_and_every_row_has_its_marker_in_its_home() -> None:
    indexed = {rid: home for rid, home, _ in ROWS}
    found = dict(markers())
    assert sorted(set(found) - set(indexed)) == [], "markers with no row in .sdlc/docs/rules.md"
    assert sorted(set(indexed) - set(found)) == [], "rows whose marker is in no file"
    moved = {rid: (indexed[rid], found[rid]) for rid in indexed if found[rid] != indexed[rid]}
    assert moved == {}, "rows filed under another file than the one holding the marker"


def test_markers_live_only_in_prompts() -> None:
    allowed = {p.relative_to(REPO).as_posix() for p in prompt_files()}
    assert sorted({f for _, f in markers()} - allowed) == []


def test_every_prompt_with_rules_is_a_section_of_the_index() -> None:
    homes = {home for _, home, _ in ROWS}
    assert sorted(homes - {p.relative_to(REPO).as_posix() for p in prompt_files()}) == []


def test_a_marker_is_never_inside_a_code_block() -> None:
    bad = []
    for path in prompt_files():
        inside = False
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("```"):
                inside = not inside
            elif inside and MARKER.search(line):
                bad.append(f"{path.relative_to(REPO)}:{n}")
    assert bad == []


def hook_commands() -> set[str]:
    """The command column of each row in .sdlc/hooks/hooks.tsv (not its comments)."""
    rows = (REPO / ".sdlc/hooks/hooks.tsv").read_text(encoding="utf-8").splitlines()
    return {r.split("\t")[2].split()[0] for r in rows if r and not r.startswith("#")}


def holder_problem(holder: str) -> str | None:
    """Why a holder doesn't exist, or None when it does."""
    kind, sep, target = holder.partition(": ")
    if not sep or kind not in HOLDER_KINDS:
        return f"unknown holder kind (expected {', '.join(HOLDER_KINDS)} or nothing)"
    if kind == "eval":
        return None if (REPO / "evals/tasks" / f"{target}.json").is_file() else "no such eval task"
    path, _, name = target.partition("::")
    if not (REPO / path).is_file():
        return "no such file"
    if kind == "hook" and path not in hook_commands():
        return "not a hook row in .sdlc/hooks/hooks.tsv"
    if kind == "test" and not name:
        return "a test holder names its test: <path>::<name>"
    if name and not re.search(rf"^\s*def {re.escape(name)}\(", (REPO / path).read_text(), re.M):
        return f"no def {name} in {path}"
    return None


@pytest.mark.parametrize(
    ("holder", "problem"),
    [
        ("hook: .sdlc/hooks/plan-gate.sh", None),
        ("hook: .sdlc/hooks/dispatch.sh", "not a hook row in .sdlc/hooks/hooks.tsv"),
        ("check: .sdlc/scripts/nope.sh", "no such file"),
        ("check: .sdlc/src/sdlc/artifacts.py::check_build", None),
        ("check: .sdlc/src/sdlc/artifacts.py::check_nope", "no def check_nope"),
        ("eval: bug-fast-path", None),
        ("eval: no-such-task", "no such eval task"),
        ("test: tests/test_routing.py", "a test holder names its test"),
        ("ci: x", "unknown holder kind"),
    ],
)
def test_holder_check_tells_real_holders_from_missing_ones(
    holder: str, problem: str | None
) -> None:
    got = holder_problem(holder)
    assert got == problem if problem is None else (got or "").startswith(problem)


def test_every_holder_exists() -> None:
    bad = {
        f"{rid}: {h}": why
        for rid, _, holders in ROWS
        for h in holders
        if (why := holder_problem(h))
    }
    assert bad == {}


def test_parse_index_reads_nothing_and_lists_and_rejects_a_bare_cell() -> None:
    text = "## `a.md`\n\n| Id | Rule | Held by |\n|---|---|---|\n| `x.a` | r | nothing |\n"
    text += "| `x.b` | r | `eval: e`, `check: c.sh` |\n"
    assert parse_index(text) == [("x.a", "a.md", []), ("x.b", "a.md", ["eval: e", "check: c.sh"])]
    with pytest.raises(AssertionError, match="neither"):
        parse_index("## `a.md`\n| `x.c` | r | a hook |\n")
    with pytest.raises(AssertionError, match="outside"):
        parse_index("| `x.d` | r | nothing |\n")
