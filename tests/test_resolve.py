"""Overrides of framework files in .sdlc-local/ (#133)."""

import pytest

from conftest import REPO, run
from sdlc.cli import main
from sdlc.resolve import OverrideError, blocks, check_overrides, extend, resolve

BASE = """# Title

Intro line.

## Problem

Base problem.

### Detail

Base detail.

## Outcome

Base outcome.
"""


def project(tmp_path, base=BASE, local=None, rel="templates/x.md"):
    (tmp_path / ".sdlc" / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".sdlc" / rel).write_text(base)
    if local is not None:
        (tmp_path / ".sdlc-local" / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / ".sdlc-local" / rel).write_text(local)
    return tmp_path


def test_without_an_override_the_framework_file_is_used(tmp_path):
    assert resolve(project(tmp_path), "templates/x.md") == BASE
    assert resolve(tmp_path, ".sdlc/templates/x.md") == BASE, "a .sdlc/ prefix is fine"


def test_a_whole_file_override_replaces_it(tmp_path):
    assert resolve(project(tmp_path, local="ours\n"), "templates/x.md") == "ours\n"


def test_a_project_can_add_a_file_the_framework_lacks(tmp_path):
    (tmp_path / ".sdlc-local/skills/ours").mkdir(parents=True)
    (tmp_path / ".sdlc-local/skills/ours/SKILL.md").write_text("ours\n")
    assert resolve(tmp_path, "skills/ours/SKILL.md") == "ours\n"


def test_replace_swaps_a_heading_block_and_its_subsections():
    out = extend(
        BASE,
        "<!-- extends -->\n<!-- replace: Problem -->\n## Problem\n\nOurs.\n\n<!-- /replace -->\n",
    )
    assert "Ours." in out and "Base problem." not in out and "Base detail." not in out
    assert out.index("Ours.") < out.index("## Outcome")


def test_a_subsection_is_its_own_block():
    out = extend(
        BASE,
        "<!-- extends -->\n<!-- replace: Detail -->\n"
        "### Detail\n\nOur detail.\n\n<!-- /replace -->\n",
    )
    assert "Base problem." in out and "Our detail." in out and "Base detail." not in out


def test_append_and_prepend_keep_the_block():
    override = (
        "<!-- extends -->\n"
        "<!-- append: Outcome -->\nAppended.\n<!-- /append -->\n"
        "<!-- prepend: Problem -->\nPrepended.\n<!-- /prepend -->\n"
    )
    out = extend(BASE, override)
    assert out.index("## Problem\n") < out.index("Prepended.") < out.index("Base problem.")
    assert out.index("Base outcome.") < out.index("Appended.")
    assert out.endswith("Appended.\n")


def test_append_to_a_middle_block_keeps_the_gap_before_the_next():
    out = extend(BASE, "<!-- extends -->\n<!-- append: Detail -->\nMore.\n<!-- /append -->\n")
    assert "Base detail.\nMore.\n\n## Outcome" in out


def test_a_bare_append_or_prepend_is_for_the_whole_file():
    override = (
        "<!-- extends -->\n<!-- append -->\nAfter the steps above, also lint.\n<!-- /append -->\n"
        "<!-- prepend -->\nRead this first.\n<!-- /prepend -->\n"
    )
    out = extend(BASE, override)
    assert out.startswith("Read this first.\n\n# Title")
    assert out.endswith("Base outcome.\n\nAfter the steps above, also lint.\n")


def test_names_ignore_case_and_spacing_and_operations_apply_in_order():
    override = (
        "<!-- extends -->\n"
        "<!-- replace:   problem -->\n## Problem\n\nFirst.\n\n<!-- /replace -->\n"
        "<!-- append: PROBLEM -->\nSecond.\n<!-- /append -->\n"
    )
    out = extend(BASE, override)
    assert out.index("First.") < out.index("Second.") < out.index("## Outcome")


def test_a_marked_block_is_a_finer_target():
    base = "# T\n\n<!-- block: header -->\nOwner: <name>\n<!-- /block: header -->\n\n## A\n\nx\n"
    assert set(blocks(base)) == {"header", "t", "a"}
    out = extend(
        base, "<!-- extends -->\n<!-- append: header -->\nMilestone: M<n>\n<!-- /append -->\n"
    )
    assert "Owner: <name>\nMilestone: M<n>\n<!-- /block: header -->" in out


def test_headings_inside_code_fences_are_not_blocks():
    base = "# T\n\n```md\n## Not a block\n```\n\n## Real\n\nx\n"
    assert "not a block" not in blocks(base) and "real" in blocks(base)


def test_text_outside_operations_is_ignored():
    override = (
        "<!-- extends -->\nWhy we override this: our CI.\n<!-- append -->\nx\n<!-- /append -->\n"
    )
    assert "our CI" not in extend(BASE, override)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        (
            "<!-- extends -->\n<!-- replace: Nope -->\nx\n<!-- /replace -->\n",
            "no block named 'Nope'",
        ),
        ("<!-- extends -->\nnothing\n", "has no operations"),
        (
            "<!-- extends -->\n<!-- replace -->\nx\n<!-- /replace -->\n",
            "replace needs a block name",
        ),
    ],
)
def test_a_bad_extension_says_why(override, message):
    with pytest.raises(OverrideError, match=message):
        extend(BASE, override)


@pytest.mark.parametrize("rel", ["scripts/agent.sh", "hooks/protect-paths.sh", "src/sdlc/cli.py"])
def test_code_and_guardrails_cant_be_overridden(tmp_path, rel):
    project(tmp_path, base="real\n", local="weakened\n", rel=rel)
    with pytest.raises(OverrideError, match="can't be overridden"):
        resolve(tmp_path, rel)
    assert check_overrides(tmp_path), "make validate reports it"


def test_only_markdown_extends_block_by_block(tmp_path):
    project(tmp_path, base="a: 1\n", local="<!-- extends -->\n", rel="templates/x.yml")
    with pytest.raises(OverrideError, match="only Markdown"):
        resolve(tmp_path, "templates/x.yml")


def test_validate_reports_an_override_whose_block_is_gone(tmp_path, capsys):
    local = "<!-- extends -->\n<!-- replace: Gone -->\nx\n<!-- /replace -->\n"
    project(tmp_path, local=local)
    (tmp_path / ".sdlc-local/hooks").mkdir()
    (tmp_path / ".sdlc-local/hooks/hooks.tsv").write_text("added, not an override\n")
    (tmp_path / ".sdlc-local/local.mk").write_text("X = 1\n")
    problems = check_overrides(tmp_path)
    assert [(p.relative_to(tmp_path).as_posix(), m) for p, m in problems] == [
        (".sdlc-local/templates/x.md", "the base file has no block named 'Gone'")
    ]


def test_sdlc_new_uses_the_projects_template_without_block_markers(tmp_path):
    (tmp_path / ".sdlc/templates").mkdir(parents=True)
    (tmp_path / ".sdlc/templates/intent.md").write_text(
        (REPO / ".sdlc/templates/intent.md").read_text()
    )
    (tmp_path / ".sdlc-local/templates").mkdir(parents=True)
    (tmp_path / ".sdlc-local/templates/intent.md").write_text(
        "<!-- extends -->\n<!-- append: header -->\nMilestone: M<n>\n<!-- /append -->\n"
    )
    assert main(["--root", str(tmp_path), "new", "phone-access"]) == 0
    text = (tmp_path / "changes/0001-phone-access/intent.md").read_text()
    assert "Product owner: <name>\n" in text and "\nMilestone: M<n>\n" in text
    assert "block:" not in text


def test_resolve_script_prints_the_effective_file(tmp_path):
    out = run(["bash", str(REPO / ".sdlc/scripts/resolve.sh"), "templates/plan.md"])
    assert out.returncode == 0 and out.stdout == (REPO / ".sdlc/templates/plan.md").read_text()
    missing = run(["bash", str(REPO / ".sdlc/scripts/resolve.sh"), "templates/nope.md"])
    assert missing.returncode == 1 and "no such framework file" in missing.stderr


def test_the_framework_templates_header_block_is_there_to_extend():
    for name in ("intent.md", "bug.md"):
        assert "header" in blocks((REPO / ".sdlc/templates" / name).read_text()), name


def test_a_replacement_keeps_the_gap_before_the_next_block_and_empty_removes_it():
    out = extend(
        BASE, "<!-- extends -->\n<!-- replace: Detail -->\n### Detail\nTight.<!-- /replace -->\n"
    )
    assert "### Detail\nTight.\n\n## Outcome" in out
    gone = extend(BASE, "<!-- extends -->\n<!-- replace: Detail -->\n<!-- /replace -->\n")
    assert "Detail" not in gone and "Base problem.\n\n## Outcome" in gone
