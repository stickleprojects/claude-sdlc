"""Helpers shared by more than one test file in this package."""

from pathlib import Path

from conftest import commit, init_repo
from sdlc.artifacts import CHAIN, check_change

REPO = Path(__file__).resolve().parents[2]


def write(path: Path, sections: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def body(s: str) -> str:
        return "- AC1 (R1): text" if s == "Acceptance criteria" else "text"

    path.write_text("# Title\n\n" + "".join(f"## {s}\n\n{body(s)}\n\n" for s in sections))


def messages(change: Path) -> list[str]:
    return [p.message for p in check_change(change)]


# --- plan descopes (#95, #32) --------------------------------------------------------------


def with_dod(root: Path) -> None:
    """The framework's definition of done, where the repo's sync would put it."""
    target = root / ".sdlc" / "templates" / "definition-of-done.md"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((REPO / ".sdlc/templates/definition-of-done.md").read_text())


def plan_with(descopes: str | None, risks: str = "text") -> str:
    """A complete plan.md; `descopes` is the Descopes body, or None to leave the section out."""
    head = "".join(f"## {s}\n\ntext\n\n" for s in ("Approach", "Steps"))
    head += "## Verification\n\n- **Definition of done:** Any code\n\ntext\n\n"
    tail = "" if descopes is None else f"## Descopes\n\n{descopes}\n"
    return f"# Plan\n\n{head}## Risks\n\n{risks}\n\n{tail}"


def edited_plan(change: Path, text: str) -> list[str]:
    """Problems with a plan the branch edits, from a change that is otherwise complete."""
    with_dod(change.parents[1])
    write(change / "intent.md", CHAIN["intent.md"])
    write(change / "spec.md", CHAIN["spec.md"])
    (change / "plan.md").write_text(text)
    return [p.message for p in check_change(change, changed={change / "plan.md"})]


# --- clause coverage: `sdlc clauses` (#47) ---------------------------------------------------

CLAUSE_SPEC = """# Spec: search

## Requirements

**Search**
- R1. The list has a search box. It filters by title.
- R2. When nothing matches, the list shows "No roles match",
  offers a button that clears the search, and keeps the text.
1. **R3** Results are ordered by title.

**Export**
- R4: Export writes a CSV.

Some note about the group that isn't part of R4's text.

## Acceptance criteria

- AC1 (R1): typing filters by title.
- AC2 (R2): "zzz" shows "No roles match".
  1. open the list
  2. type zzz
- AC3 (R1–R3): `make check` exits 0.
- A4 (R4). Export writes a CSV.
- Untestable (R2): "keeps the text" because the box is native.
- AC5: no requirement cited.

## Policy concerns

None.
"""

CLAUSE_PLAN = """# Plan

## Approach

The box filters on each keystroke (R1).
<!-- R4 is mentioned only in a comment -->

## Verification

| AC2 | `make test` | message shows |
| A4 | `make test` | a CSV |
"""


def clause_blocks(
    spec: str = CLAUSE_SPEC, plan: str | None = CLAUSE_PLAN, build: str | None = None
) -> dict:
    from sdlc.clauses import blocks

    return {b.id: b for b in blocks(spec, plan, build)}


def clause_repo(tmp_path: Path) -> Path:
    root = init_repo(tmp_path / "repo")
    commit(
        root,
        "spec",
        {
            "changes/0001-search/spec.md": CLAUSE_SPEC,
            "changes/0001-search/plan.md": CLAUSE_PLAN,
        },
    )
    return root
