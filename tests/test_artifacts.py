from pathlib import Path

import pytest

from conftest import commit, git, init_repo
from sdlc.artifacts import (
    ADR_SECTIONS,
    BUG_CHAIN,
    BUILD_SECTIONS,
    CHAIN,
    TEMPLATES,
    build_progress,
    check_adrs,
    check_change,
    check_config,
    definition_of_done,
    next_slug,
    placeholders,
    stage,
)
from sdlc.cli import check_commits, main

REPO = Path(__file__).resolve().parents[1]


def write(path: Path, sections: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def body(s: str) -> str:
        return "- AC1 (R1): text" if s == "Acceptance criteria" else "text"

    path.write_text("# Title\n\n" + "".join(f"## {s}\n\n{body(s)}\n\n" for s in sections))


@pytest.fixture
def change(tmp_path: Path) -> Path:
    return tmp_path / "changes" / "0001-example"


def test_complete_intent_is_valid(change: Path) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    assert check_change(change) == []
    assert stage(change) == "intent"


def test_missing_sections_are_reported(change: Path) -> None:
    write(change / "intent.md", ["Problem"])
    [problem] = check_change(change)
    assert "Proposed outcome" in problem.message


def test_spec_without_intent_breaks_chain(change: Path) -> None:
    write(change / "spec.md", CHAIN["spec.md"])
    messages = [p.message for p in check_change(change)]
    assert any("earlier artifact" in m for m in messages)
    assert any("no intent.md" in m for m in messages)


def test_bad_folder_name(tmp_path: Path) -> None:
    bad = tmp_path / "changes" / "Example"
    write(bad / "intent.md", CHAIN["intent.md"])
    assert any("folder name" in p.message for p in check_change(bad))


def test_next_slug_increments(tmp_path: Path) -> None:
    (tmp_path / "changes" / "0007-old").mkdir(parents=True)
    assert next_slug(tmp_path, "new-thing") == "0008-new-thing"


@pytest.mark.parametrize(
    ("kind", "name"), [(k, n) for k, c in [("feature", CHAIN), ("bug", BUG_CHAIN)] for n in c]
)
def test_templates_satisfy_their_own_rules(kind: str, name: str) -> None:
    rules = CHAIN if kind == "feature" else BUG_CHAIN
    text = (REPO / "templates" / TEMPLATES[kind][name]).read_text()
    for section in rules[name]:
        assert f"## {section}" in text


def test_new_then_check_round_trip(tmp_path: Path) -> None:
    (tmp_path / "templates").mkdir()
    template = (REPO / "templates" / "intent.md").read_text()
    (tmp_path / "templates" / "intent.md").write_text(template)
    assert main(["--root", str(tmp_path), "new", "add-login"]) == 0
    assert (tmp_path / "changes" / "0001-add-login" / "intent.md").exists()
    assert main(["--root", str(tmp_path), "check"]) == 0


def test_new_rejects_bad_name(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), "new", "Bad Name"]) == 2


# --- commit guards -------------------------------------------------------------------------


@pytest.fixture
def branch_repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "r")
    commit(repo, "chore: start", {"README.md": "x\n"})
    git(repo, "switch", "-q", "-c", "feature")
    return repo


def test_tracked_node_modules_fail_validate(branch_repo: Path) -> None:
    commit(branch_repo, "oops", {"app/node_modules/left-pad/index.js": "x\n"})
    [problem] = check_commits(branch_repo)
    assert "node_modules" in problem
    assert main(["--root", str(branch_repo), "check"]) == 1


def test_branch_with_too_many_files_fails_validate(branch_repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDLC_MAX_CHANGED_FILES", "3")
    commit(branch_repo, "big", {f"out/{i}.txt": "x\n" for i in range(4)})
    [problem] = check_commits(branch_repo)
    assert "changes 4 files against main (limit 3)" in problem


def test_large_change_trailer_allows_a_big_branch(branch_repo: Path, monkeypatch, capsys) -> None:
    # #63: a PR can't set an env var in CI, but it can carry a commit trailer.
    monkeypatch.setenv("SDLC_MAX_CHANGED_FILES", "3")
    commit(branch_repo, "big", {f"out/{i}.txt": "x\n" for i in range(4)})
    [problem] = check_commits(branch_repo)
    assert "Large-change: <reason>" in problem
    git(
        branch_repo,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "chore: scaffold",
        "-m",
        "Large-change: generated API client",
    )
    assert check_commits(branch_repo) == []
    assert "allowed by Large-change: generated API client" in capsys.readouterr().err


def test_large_change_trailer_still_rejects_node_modules(branch_repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDLC_MAX_CHANGED_FILES", "1")
    commit(branch_repo, "oops", {"node_modules/x/index.js": "x\n", "a.txt": "x\n"})
    git(branch_repo, "commit", "-q", "--allow-empty", "-m", "c", "-m", "Large-change: why")
    [problem] = check_commits(branch_repo)
    assert "node_modules" in problem


def test_normal_branch_passes_commit_guards(branch_repo: Path) -> None:
    commit(branch_repo, "small", {"src/a.py": "x\n", "src/node_modules_helper.py": "x\n"})
    assert check_commits(branch_repo) == []


def test_commit_guards_skip_outside_git(tmp_path: Path) -> None:
    assert check_commits(tmp_path) == []


# --- bugs --------------------------------------------------------------------------------


def test_bug_with_short_spec_and_plan_is_valid(change: Path) -> None:
    write(change / "bug.md", BUG_CHAIN["bug.md"])
    assert check_change(change) == []
    assert stage(change) == "bug"
    write(change / "spec.md", ["Requirements", "Acceptance criteria"])
    write(change / "plan.md", CHAIN["plan.md"])
    assert check_change(change) == []
    assert stage(change) == "plan"


def test_bug_spec_still_needs_requirements_and_criteria(change: Path) -> None:
    write(change / "bug.md", BUG_CHAIN["bug.md"])
    write(change / "spec.md", ["Requirements"])
    [problem] = check_change(change)
    assert "Acceptance criteria" in problem.message


def test_feature_spec_still_needs_every_section(change: Path) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    write(change / "spec.md", ["Requirements", "Acceptance criteria"])
    [problem] = check_change(change)
    assert "Policy concerns" in problem.message


def test_intent_and_bug_together_are_reported(change: Path) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    write(change / "bug.md", BUG_CHAIN["bug.md"])
    assert any("both intent.md and bug.md" in p.message for p in check_change(change))


def _templates(root: Path) -> None:
    (root / "templates").mkdir()
    for name in ("intent.md", "bug.md"):
        (root / "templates" / name).write_text((REPO / "templates" / name).read_text())


def test_new_bug_round_trip(tmp_path: Path) -> None:
    _templates(tmp_path)
    assert main(["--root", str(tmp_path), "new", "export-hangs", "--type", "bug"]) == 0
    folder = tmp_path / "changes" / "0001-export-hangs"
    assert (folder / "bug.md").exists()
    assert not (folder / "intent.md").exists()
    assert main(["--root", str(tmp_path), "check"]) == 0


def test_new_reads_type_from_the_environment(tmp_path: Path, monkeypatch) -> None:
    # `make new-change NAME=x TYPE=bug` reaches the CLI as $TYPE.
    _templates(tmp_path)
    monkeypatch.setenv("TYPE", "bug")
    assert main(["--root", str(tmp_path), "new", "export-hangs"]) == 0
    assert (tmp_path / "changes" / "0001-export-hangs" / "bug.md").exists()


def test_new_rejects_unknown_type(tmp_path: Path) -> None:
    _templates(tmp_path)
    assert main(["--root", str(tmp_path), "new", "x", "--type", "chore"]) == 2


# --- build.md: the optional build plan -------------------------------------------------

BUILD_TEMPLATE = (REPO / "templates" / "build.md").read_text()


def planned(change: Path) -> Path:
    for name, sections in CHAIN.items():
        write(change / name, sections)
    return change / "build.md"


def approved(text: str) -> str:
    return text.replace(
        "- **Status:** draft, awaiting approval", "- **Status:** in progress"
    ).replace("- **Approved:** not yet", "- **Approved:** Sam, 2026-11-05")


def messages(change: Path) -> list[str]:
    return [p.message for p in check_change(change)]


def test_build_template_is_a_valid_draft(change: Path) -> None:
    planned(change).write_text(BUILD_TEMPLATE)
    assert check_change(change) == []
    assert stage(change) == "build"
    assert build_progress(change) == "draft, awaiting approval, 0/2 milestones done"


def test_build_template_has_its_sections() -> None:
    for heading in BUILD_SECTIONS:
        assert f"## {heading}" in BUILD_TEMPLATE


def test_build_without_plan_is_reported(change: Path) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    (change / "build.md").write_text(BUILD_TEMPLATE)
    assert any("plan.md is missing" in m for m in messages(change))


def test_approved_build_is_valid(change: Path) -> None:
    planned(change).write_text(approved(BUILD_TEMPLATE))
    assert check_change(change) == []


def test_approval_with_open_questions_is_reported(change: Path) -> None:
    text = approved(BUILD_TEMPLATE).replace(
        "None.\n\n## Milestones", "1. Keep the backend-first order?\n\n## Milestones"
    )
    planned(change).write_text(text)
    assert any("Questions before approval" in m for m in messages(change))


def test_approval_without_approver_is_reported(change: Path) -> None:
    text = BUILD_TEMPLATE.replace(
        "- **Status:** draft, awaiting approval", "- **Status:** in progress"
    )
    planned(change).write_text(text)
    assert any("Approved" in m for m in messages(change))


def test_not_yet_approved_in_any_case_is_reported(change: Path) -> None:
    text = approved(BUILD_TEMPLATE).replace("Sam, 2026-11-05", "Not yet")
    planned(change).write_text(text)
    assert any("Approved" in m for m in messages(change))


def test_building_from_a_draft_is_reported(change: Path) -> None:
    text = BUILD_TEMPLATE.replace("- **Status:** todo", "- **Status:** in progress", 1)
    planned(change).write_text(text)
    assert any("still a draft" in m for m in messages(change))


def test_redraft_keeps_done_milestones(change: Path) -> None:
    text = BUILD_TEMPLATE.replace("- **Status:** todo", "- **Status:** done (abc1234)", 1)
    planned(change).write_text(text)
    assert check_change(change) == []
    assert build_progress(change).endswith("1/2 milestones done")


def test_one_milestone_build_is_reported(change: Path) -> None:
    text = BUILD_TEMPLATE.split("### M2.")[0] + "## Deviations from the plan\n\n"
    text += "## Flaky tests\n\n## Session log\n"
    planned(change).write_text(text)
    assert any("one milestone" in m for m in messages(change))


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("- **Status:** draft, awaiting approval", "- **Status:** nearly done", "Status must"),
        ("- **Status:** draft, awaiting approval <!--", "<!--", "Status must"),
        ("- **Status:** todo", "- **Status:** finished", "M1 status"),
        ("- **Status:** todo", "- **Owner:** me", "M1 status"),
        ("## Flaky tests", "## Flakes", "missing sections: Flaky tests"),
    ],
)
def test_unrecognised_build_text_fails_safe(
    change: Path, old: str, new: str, expected: str
) -> None:
    planned(change).write_text(BUILD_TEMPLATE.replace(old, new, 1))
    assert any(expected in m for m in messages(change))


def test_finished_build_from_before_the_template_stays_valid(change: Path) -> None:
    planned(change).write_text(
        "# Build\n\n- **Status:** PR open (#12)\n\n## Milestones\n\n"
        "### M1. Server\n\n- **Status:** done (abc1234)\n"
    )
    assert check_change(change) == []


def test_status_shows_build_progress(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    planned(tmp_path / "changes" / "0001-example").write_text(approved(BUILD_TEMPLATE))
    write(tmp_path / "changes" / "0002-other" / "intent.md", CHAIN["intent.md"])
    assert main(["--root", str(tmp_path), "status"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "0001-example\tbuild\tin progress, 0/2 milestones done",
        "0002-other\tintent",
    ]


ADR_TEMPLATE = (REPO / "templates" / "adr.md").read_text()


def accepted_adr(trigger: str = "- a plan hand-builds navigation state") -> str:
    text = ADR_TEMPLATE.replace("proposed <!--", "accepted (Sam, 2026-11-06) <!--", 1)
    return text.replace("- <trigger>", trigger)


def adr(root: Path, name: str, text: str) -> Path:
    path = root / "docs" / "adr" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def adr_messages(root: Path) -> list[str]:
    return [p.message for p in check_adrs(root)]


def test_no_adr_folder_is_fine(tmp_path: Path) -> None:
    assert check_adrs(tmp_path) == []


def test_adr_template_has_its_sections() -> None:
    for heading in ADR_SECTIONS:
        assert f"## {heading}" in ADR_TEMPLATE


def test_adr_template_is_a_valid_proposal(tmp_path: Path) -> None:
    adr(tmp_path, "0001-client-stack.md", ADR_TEMPLATE)
    adr(tmp_path, "README.md", "# Decisions\n")
    assert check_adrs(tmp_path) == []


def test_leftover_placeholder_beside_a_real_trigger_is_reported(tmp_path: Path) -> None:
    adr(tmp_path, "0001-client-stack.md", accepted_adr("- a plan hand-builds routing\n- <trigger>"))
    assert adr_messages(tmp_path) == ["Revisit when still has the template's <trigger>"]


def test_accepted_adr_with_a_trigger_is_valid(tmp_path: Path) -> None:
    adr(tmp_path, "0001-client-stack.md", accepted_adr())
    assert check_adrs(tmp_path) == []


@pytest.mark.parametrize(
    "trigger",
    [
        "",
        "None.",
        "never",
        "<!-- later -->",
        "- <trigger>",
        "- None",
        "- N/A",
        "* TBD.",
        "1. todo",
        "-",
    ],
)
def test_accepted_adr_without_a_trigger_is_reported(tmp_path: Path, trigger: str) -> None:
    adr(tmp_path, "0001-client-stack.md", accepted_adr(trigger))
    assert any("Revisit when names no trigger" in m for m in adr_messages(tmp_path))


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("proposed <!--", "agreed <!--", "Status must"),
        ("proposed <!--", "<!--", "Status must"),
        ("## Revisit when", "## Later", "missing sections: Revisit when"),
        ("## Alternatives considered", "## Options", "missing sections: Alternatives"),
    ],
)
def test_unrecognised_adr_text_fails_safe(
    tmp_path: Path, old: str, new: str, expected: str
) -> None:
    adr(tmp_path, "0001-client-stack.md", ADR_TEMPLATE.replace(old, new, 1))
    assert any(expected in m for m in adr_messages(tmp_path))


def test_superseded_adr_names_an_existing_one(tmp_path: Path) -> None:
    adr(
        tmp_path,
        "0001-client-stack.md",
        ADR_TEMPLATE.replace("proposed <!--", "superseded by 0002 <!--"),
    )
    assert any("no such ADR" in m for m in adr_messages(tmp_path))
    adr(tmp_path, "0002-adopt-router.md", accepted_adr())
    assert check_adrs(tmp_path) == []


def test_bad_adr_names_and_duplicate_numbers_are_reported(tmp_path: Path) -> None:
    adr(tmp_path, "client-stack.md", ADR_TEMPLATE)
    adr(tmp_path, "0001-a.md", ADR_TEMPLATE)
    adr(tmp_path, "0001-b.md", ADR_TEMPLATE)
    found = adr_messages(tmp_path)
    assert any("0001-short-slug.md" in m for m in found)
    assert any("0001 is used twice" in m for m in found)


def test_check_reports_adr_problems(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    adr(tmp_path, "0001-client-stack.md", accepted_adr(""))
    assert main(["--root", str(tmp_path), "check"]) == 1
    assert "Revisit when" in capsys.readouterr().err


def test_placeholder_words_come_from_the_framework_file(tmp_path: Path) -> None:
    words = placeholders(tmp_path)
    assert {"none", "tbd"} <= words.nothing_written
    assert words.explicit_none == {"None", "None."}
    assert check_config(tmp_path) == []


def repo_config(root: Path, text: str) -> None:
    (root / ".sdlc.toml").write_text(text)


def test_repo_config_adds_to_the_framework_list(tmp_path: Path) -> None:
    repo_config(tmp_path, '[placeholders.nothing_written]\nadditional_keywords = ["Pending."]\n')
    for trigger in ("- pending", "- tbd"):
        adr(tmp_path, "0001-client-stack.md", accepted_adr(trigger))
        assert any("names no trigger" in m for m in adr_messages(tmp_path)), trigger
    assert check_config(tmp_path) == []


def test_repo_config_replaces_the_framework_list(tmp_path: Path) -> None:
    repo_config(tmp_path, '[placeholders.nothing_written]\nkeywords = ["none", "pending"]\n')
    adr(tmp_path, "0001-client-stack.md", accepted_adr("- pending"))
    assert any("names no trigger" in m for m in adr_messages(tmp_path))
    adr(tmp_path, "0001-client-stack.md", accepted_adr("- tbd"))
    assert adr_messages(tmp_path) == [], "the repo's keywords replaced the framework's"


def test_repo_config_replaces_then_adds(tmp_path: Path) -> None:
    repo_config(
        tmp_path,
        "[placeholders.explicit_none]\n"
        'keywords = ["None."]\nadditional_keywords = ["Nothing open."]\n',
    )
    assert placeholders(tmp_path).explicit_none == {"None.", "Nothing open."}


def test_repo_config_sets_what_clears_a_build(change: Path) -> None:
    repo_config(
        change.parents[1], '[placeholders.explicit_none]\nadditional_keywords = ["Nothing open."]\n'
    )
    cleared = approved(BUILD_TEMPLATE).replace(
        "None.\n\n## Milestones", "Nothing open.\n\n## Milestones"
    )
    planned(change).write_text(cleared)
    assert check_change(change) == []
    planned(change).write_text(approved(BUILD_TEMPLATE))
    assert check_change(change) == [], "the framework's None. still clears it"
    planned(change).write_text(cleared.replace("Nothing open.", "TBD"))
    assert any("Questions before approval" in m for m in messages(change))


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ("[placeholders\n", "isn't valid TOML"),
        ("placeholders = 1\n", "must be a table"),
        ('[placeholders.nothing]\nkeywords = ["x"]\n', "unknown list placeholders.nothing"),
        ('[placeholders]\nexplicit_none = ["None."]\n', "explicit_none must be a table"),
        ('[placeholders.explicit_none]\nwords = ["x"]\n', "unknown key placeholders.explicit_none"),
        ('[placeholders.explicit_none]\nkeywords = "None."\n', "keywords must be a list"),
        ("[placeholders.explicit_none]\nadditional_keywords = [1]\n", "must be a list of strings"),
    ],
)
def test_bad_repo_config_is_reported_and_ignored(
    tmp_path: Path, config: str, expected: str
) -> None:
    (tmp_path / ".sdlc.toml").write_text(config)
    [problem] = check_config(tmp_path)
    assert expected in problem.message
    assert placeholders(tmp_path).explicit_none == {"None", "None."}
    assert main(["--root", str(tmp_path), "check"]) == 1


# --- acceptance criteria format (#90) -----------------------------------------------------


def spec_with_criteria(change: Path, criteria: str) -> Path:
    write(change / "intent.md", CHAIN["intent.md"])
    spec = change / "spec.md"
    write(spec, [s for s in CHAIN["spec.md"] if s != "Acceptance criteria"])
    spec.write_text(spec.read_text() + f"## Acceptance criteria\n\n{criteria}\n")
    return spec


@pytest.mark.parametrize(
    "criteria",
    [
        "- AC1 (R1): `make check` exits 0.\n- AC2 (R2): prints X.",
        "- A1 (R1). Starting the app exits non-zero.\n  It names the setting.",
        "Each is a test that fails before the change.\n\n- AC1: a test shows it.",
        "- AC1 (R1): the save flow works:\n  1. open the app\n  2. click save",
    ],
)
def test_readable_criteria_are_valid(change: Path, criteria: str) -> None:
    spec_with_criteria(change, criteria)
    assert check_change(change) == []


@pytest.mark.parametrize(
    ("criteria", "says"),
    [
        ("1. `make check` exits 0.\n2. prints X.", "numbered list"),
        ("- `make check` exits 0.", "no criterion"),
        ("Quantifiable checks.", "no criterion"),
    ],
)
def test_unreadable_criteria_fail_on_the_spec_pr(change: Path, criteria: str, says: str) -> None:
    spec_with_criteria(change, criteria)
    [problem] = check_change(change)
    assert says in problem.message and "AC<n>" in problem.message


def test_criteria_of_a_planned_spec_are_left_as_merged(change: Path) -> None:
    spec_with_criteria(change, "1. `make check` exits 0.")
    write(change / "plan.md", CHAIN["plan.md"])
    assert check_change(change) == []


def test_spec_templates_show_a_readable_criterion() -> None:
    for name in ("spec.md", "bug-spec.md"):
        text = (REPO / "templates" / name).read_text()
        assert "\n- AC1 (R1): " in text


# --- descopes and test level (#95) ----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ".claude/agents/verifier.md",
        ".claude/skills/plan/SKILL.md",
        ".claude/skills/build/SKILL.md",
        ".claude/skills/spec/SKILL.md",
        ".claude/skills/review-findings/SKILL.md",
        "REVIEW.md",
    ],
)
def test_guardrails_read_the_scope_rules(path: str) -> None:
    assert "scope.md" in (REPO / path).read_text()


def test_worker_blocks_on_an_unapproved_descope() -> None:
    build = (REPO / ".claude/skills/build/SKILL.md").read_text()
    worker = build[build.index("## Worker mode") :]
    assert "**A descope nobody approved:**" in worker and "return `BLOCKED`" in worker
    assert "Descopes:" in worker  # the report carries them back to the orchestrator


def test_plan_template_says_how_a_descope_is_approved() -> None:
    text = (REPO / "templates/plan.md").read_text()
    assert "Descope: <what> because <reason>. Approved: <name>, <date>." in text


# --- plan descopes (#95, #32) --------------------------------------------------------------


def with_dod(root: Path) -> None:
    """The framework's definition of done, where the repo's sync would put it."""
    target = root / "templates" / "definition-of-done.md"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((REPO / "templates/definition-of-done.md").read_text())


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


def test_merged_plan_without_descopes_stays_valid(change: Path) -> None:
    write(change / "intent.md", CHAIN["intent.md"])
    write(change / "spec.md", CHAIN["spec.md"])
    (change / "plan.md").write_text(plan_with(None))
    assert check_change(change) == []  # not known to be edited
    assert check_change(change, changed=set()) == []  # not edited on this branch


def test_edited_plan_needs_descopes(change: Path) -> None:
    [problem] = edited_plan(change, plan_with(None))
    assert problem == "missing sections: Descopes"


@pytest.mark.parametrize(
    "descopes",
    [
        "None.",
        "- Descope: dock UI widget tests because the editor can't run headless. "
        "Approved: Sam, 2026-11-10.",
        "- **Descope:** lint of game/addons/x because it's vendored. **Approved:** Sam, 2026-11-10",
        "- Descope: the export step because it needs a signing key we\n"
        "  don't have in CI. Approved: Sam, 2026-11-10.",  # wrapped
        "- Human check: walk the new room and check the lighting feels right because no test "
        "measures feel. Approved: Sam, 2026-11-10.\n"
        "- Descope: x because y. Approved: Ana (tech lead), 2026-11-10.",
    ],
)
def test_descopes_that_pass(change: Path, descopes: str) -> None:
    assert edited_plan(change, plan_with(descopes)) == []


@pytest.mark.parametrize(
    ("descopes", "expected"),
    [
        ("", "Descopes is empty"),
        ("<None., or each descope and human check, as below>", "still has the template's text"),
        ("The dock UI isn't unit-tested.", "isn't in the form"),
        ("- Descope: dock UI tests because they're slow.", "no 'Approved: <name>, <date>'"),
        ("- Descope: x because y. Approved: <name>, <date>.", "no 'Approved"),
        ("- Descope: x because y. Approved: not yet", "no 'Approved"),
        ("- Descope: x because y. Approved: TBD", "no 'Approved"),
        ("- Human check: play level 1 because feel. Approved:", "no 'Approved"),
        ("- Not tested: the dock, like the rest of it", "isn't in the form"),
        # Prose after an approved entry is an entry of its own, not part of the approved one.
        (
            "- Descope: a because b. Approved: Sam, 2026-11-10.\n\nThe dock isn't unit-tested.",
            "isn't in the form",
        ),
        (
            "- Descope: a because b. Approved: Sam, 2026-11-10.\nThe dock isn't unit-tested.",
            "isn't in the form",
        ),
        (
            "- Descope: a because b. Approved: Sam, 2026-11-10.\n\n  The dock isn't unit-tested.",
            "isn't in the form",
        ),
    ],
)
def test_descopes_that_fail(change: Path, descopes: str, expected: str) -> None:
    [problem] = edited_plan(change, plan_with(descopes))
    assert expected in problem


def test_a_descope_left_in_risks_is_reported(change: Path) -> None:
    risks = "- Descope: dock UI tests because thin. Approved: Sam, 2026-11-10."
    [problem] = edited_plan(change, plan_with("None.", risks=risks))
    assert "move it to Descopes" in problem


def test_bug_plan_needs_descopes_too(change: Path) -> None:
    with_dod(change.parents[1])
    write(change / "bug.md", BUG_CHAIN["bug.md"])
    write(change / "spec.md", BUG_CHAIN["spec.md"])
    (change / "plan.md").write_text(plan_with(None))
    [problem] = check_change(change, changed={change / "plan.md"})
    assert "Descopes" in problem.message


def test_plan_template_fails_until_descopes_are_filled(change: Path) -> None:
    template = (REPO / "templates/plan.md").read_text()
    problems = " | ".join(edited_plan(change, template))
    assert "Definition of done names no kind" in problems
    assert "still has the template's text" in problems
    filled = template.replace("<None., or each", "None.\n\n<!--", 1)
    filled = filled.replace("<the kinds of work that apply, e.g. Any code, UI>", "Any code")
    assert edited_plan(change, filled) == []


def test_validate_requires_descopes_only_in_plans_the_branch_edits(branch_repo: Path) -> None:
    change = "changes/0001-x/"
    sections = {n: "# T\n\n" + "".join(f"## {s}\n\ntext\n\n" for s in CHAIN[n]) for n in CHAIN}
    old_plan = plan_with(None)
    git(branch_repo, "switch", "-q", "main")
    with_dod(branch_repo)
    commit(
        branch_repo,
        "plan: merged before descopes",
        {change + "intent.md": sections["intent.md"], change + "spec.md": sections["spec.md"]}
        | {change + "plan.md": old_plan},
    )
    git(branch_repo, "switch", "-q", "-c", "next")
    root = ["--root", str(branch_repo), "check"]
    assert main(root) == 0  # merged plan, untouched

    plan = branch_repo / change / "plan.md"
    plan.write_text(old_plan + "\nAn edit.\n")  # uncommitted, as /plan validates before committing
    assert main(root) == 1
    plan.write_text(plan_with("None."))
    assert main(root) == 0
    commit(branch_repo, "plan: descopes")
    assert main(root) == 0

    new = "changes/0002-y/"
    for name in ("intent.md", "spec.md"):
        (branch_repo / new / name).parent.mkdir(parents=True, exist_ok=True)
        (branch_repo / new / name).write_text(sections[name])
    (branch_repo / new / "plan.md").write_text(plan_with(None))  # untracked
    assert main(root) == 1


def test_guardrails_point_at_the_descopes_section() -> None:
    scope = (REPO / ".claude/skills/scope.md").read_text()
    assert "under **Descopes**" in scope and "- Human check:" in scope
    plan = (REPO / ".claude/skills/plan/SKILL.md").read_text()
    assert "Fill **Descopes**" in plan and "Human check:" in plan
    for path in (".claude/skills/build/SKILL.md", ".claude/agents/verifier.md", "REVIEW.md"):
        text = (REPO / path).read_text()
        assert "Descopes" in text, path
        assert "plan.md's Risks" not in text and "in its Risks" not in text, path


def test_human_checks_are_pending_and_listed_for_the_owner() -> None:
    verifier = (REPO / ".claude/agents/verifier.md").read_text()
    assert "PENDING, never PASS" in verifier
    assert "`VERDICT: PENDING (<k> human checks)`" in verifier
    build = (REPO / ".claude/skills/build/SKILL.md").read_text()
    assert "**To check by hand**" in build and "`VERDICT: PENDING`" in build
    assert "**To check by hand**" in (REPO / "REVIEW.md").read_text()


# --- definition of done (#95) ---------------------------------------------------------------

DOD_TEMPLATE = (REPO / "templates/definition-of-done.md").read_text()


def dod_root(tmp_path: Path, project: str | None = None) -> Path:
    (tmp_path / "templates").mkdir(exist_ok=True)
    (tmp_path / "templates/definition-of-done.md").write_text(DOD_TEMPLATE)
    if project is not None:
        (tmp_path / "docs").mkdir(exist_ok=True)
        (tmp_path / "docs/definition-of-done.md").write_text(project)
    return tmp_path


def test_definition_of_done_defaults_cover_the_kinds_from_95() -> None:
    dod = definition_of_done(REPO)
    assert dod.problems == ()
    for kind in ("Any code", "UI", "Plugin or extension", "Data or schema"):
        assert kind in dod.kinds
    assert "through the UI" in dod.rows["ui"][1]


def test_project_rows_replace_and_add(tmp_path: Path) -> None:
    project = (
        "| Kind of work | Done means |\n|---|---|\n"
        "| **ui** | Widget tests in the real editor, and a contrast check. |\n"
        "| Godot scene | The scene loads headless and its signals are connected. |\n"
    )
    dod = definition_of_done(dod_root(tmp_path, project))
    assert dod.problems == ()
    assert dod.rows["ui"] == ("ui", "Widget tests in the real editor, and a contrast check.")
    assert "Godot scene" in dod.kinds and "Any code" in dod.kinds


@pytest.mark.parametrize(
    ("project", "expected"),
    [
        ("# Our definition of done\n\nWe test everything.\n", "has no rows"),
        ("| Kind of work | Done means |\n|---|---|\n| UI | a |\n| ui | b |\n", "twice"),
        ("| Kind of work | Done means |\n|---|---|\n| UI, web | a |\n", "has a comma"),
        ("| Kind of work | Done means |\n|---|---|\n| UI |  |\n", "doesn't say what done means"),
    ],
)
def test_bad_project_table_is_reported(tmp_path: Path, project: str, expected: str) -> None:
    [problem] = definition_of_done(dod_root(tmp_path, project)).problems
    assert expected in problem.message and "docs/definition-of-done.md" in str(problem.path)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("- **Definition of done:** Any code, UI", None),
        ("- **Definition of done:** any code, ui.", None),  # case and a full stop don't matter
        ("", "no '- **Definition of done:** <kinds>' line"),
        (
            "- **Definition of done:** <the kinds of work that apply, e.g. Any code, UI>",
            "names no kind",
        ),
        ("- **Definition of done:**", "names no kind"),
        ("- **Definition of done:** Any code, UX", "names UX, not in the definition of done"),
    ],
)
def test_plan_names_its_definition_of_done(tmp_path: Path, line: str, expected: str | None) -> None:
    root = dod_root(tmp_path)
    change = root / "changes" / "0001-x"
    plan = plan_with("None.").replace("- **Definition of done:** Any code\n", line + "\n")
    problems = edited_plan(change, plan)
    if expected is None:
        assert problems == []
    else:
        [problem] = problems
        assert expected in problem
        assert "known kinds: Any code, UI" in problem


def test_merged_plan_needs_no_definition_of_done_line(tmp_path: Path) -> None:
    change = dod_root(tmp_path) / "changes" / "0001-x"
    write(change / "intent.md", CHAIN["intent.md"])
    write(change / "spec.md", CHAIN["spec.md"])
    (change / "plan.md").write_text(
        plan_with(None).replace("- **Definition of done:** Any code\n", "")
    )
    assert check_change(change, changed=set()) == []


def test_a_project_kind_can_be_named(tmp_path: Path) -> None:
    project = "| Kind of work | Done means |\n|---|---|\n| Godot scene | Loads headless. |\n"
    change = dod_root(tmp_path, project) / "changes" / "0001-x"
    plan = plan_with("None.").replace("Any code\n", "Any code, Godot scene\n", 1)
    assert edited_plan(change, plan) == []


def test_validate_reports_a_bad_project_table(tmp_path: Path) -> None:
    dod_root(tmp_path, "nothing here\n")
    assert main(["--root", str(tmp_path), "check"]) == 1


def test_stages_hold_work_to_the_definition_of_done() -> None:
    for path in (
        ".claude/skills/scope.md",
        ".claude/skills/plan/SKILL.md",
        ".claude/skills/build/SKILL.md",
        ".claude/agents/verifier.md",
        "REVIEW.md",
    ):
        text = (REPO / path).read_text()
        assert "definition-of-done.md" in text, path
        assert "Definition of done:" in text, path
    assert "- **Definition of done:**" in (REPO / "templates/plan.md").read_text()


def test_an_edited_plan_fails_without_a_definition_of_done(change: Path) -> None:
    # Fail safe (PR #100 review): with no table, a plan could name any kind and pass.
    write(change / "intent.md", CHAIN["intent.md"])
    write(change / "spec.md", CHAIN["spec.md"])
    plan = change / "plan.md"
    plan.write_text(plan_with("None.").replace("Any code", "Banana"))
    [problem] = check_change(change, changed={plan})
    assert (
        problem.message == "no definition of done found: expected templates/definition-of-done.md"
    )
    assert check_change(change, changed=set()) == []  # a merged plan isn't held to it


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


def clause_blocks(spec: str = CLAUSE_SPEC, plan: str | None = CLAUSE_PLAN) -> dict:
    from sdlc.clauses import blocks

    return {b.id: b for b in blocks(spec, plan)}


def test_clauses_reads_each_requirement_with_its_continuation_lines() -> None:
    found = clause_blocks()
    assert list(found) == ["R1", "R2", "R3", "R4"]
    assert found["R2"].text == (
        'When nothing matches, the list shows "No roles match", offers a button that clears the '
        "search, and keeps the text."
    )
    assert found["R3"].text == "Results are ordered by title."
    # Prose after a blank line, and group labels, aren't part of the requirement above.
    assert found["R1"].text == "The list has a search box. It filters by title."
    assert found["R4"].text == "Export writes a CSV."


def test_clauses_attach_the_criteria_that_cite_each_requirement() -> None:
    found = clause_blocks()
    assert [c.id for c in found["R1"].criteria] == ["AC1", "AC3"]
    assert [c.id for c in found["R2"].criteria] == ["AC2", "AC3", "Untestable"]
    assert [c.id for c in found["R3"].criteria] == ["AC3"], "R1–R3 is a range"
    assert [c.id for c in found["R4"].criteria] == ["A4"]
    assert "2. type zzz" in found["R2"].criteria[0].text, "nested steps stay with the criterion"


def test_clauses_attach_plan_lines_citing_a_requirement_or_its_criteria() -> None:
    found = clause_blocks()
    assert [(p.section, p.text) for p in found["R1"].plan] == [
        ("Approach", "The box filters on each keystroke (R1).")
    ]
    assert [p.text for p in found["R2"].plan] == ["| AC2 | `make test` | message shows |"]
    assert [p.text for p in found["R4"].plan] == ["| A4 | `make test` | a CSV |"], (
        "an HTML comment isn't a plan line"
    )
    assert clause_blocks(plan=None)["R1"].plan == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("R1, R2", {"R1", "R2"}),
        ("R2–R4", {"R2", "R3", "R4"}),
        ("AC1-AC3", {"AC1", "AC2", "AC3"}),
        ("R5 to 6", {"R5", "R6"}),
        ("R2D2 and FOR1", set()),
        ("R14a, R14b", {"R14a", "R14b"}),
    ],
)
def test_cited_expands_ranges(text: str, expected: set[str]) -> None:
    from sdlc.clauses import cited

    assert cited(text) == expected


@pytest.mark.parametrize(
    "requirements",
    ["", "Numbered, testable requirements (R1, R2, ...).", "1. The list has a search box."],
)
def test_clauses_fail_safe_when_no_requirement_can_be_read(requirements: str) -> None:
    from sdlc.clauses import ClauseError, blocks

    with pytest.raises(ClauseError, match="no requirements could be read"):
        blocks(f"# Spec\n\n## Requirements\n\n{requirements}\n\n## Acceptance criteria\n")


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


def test_clauses_command_prints_json_for_a_change(tmp_path: Path, capsys) -> None:
    import json

    root = clause_repo(tmp_path)
    for name in ("0001", "0001-search", str(root / "changes/0001-search")):
        assert main(["--root", str(root), "clauses", name]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["change"] == "0001-search"
        assert [b["id"] for b in out["requirements"]] == ["R1", "R2", "R3", "R4"]
        assert out["requirements"][3]["criteria"] == [
            {"id": "A4", "text": "(R4). Export writes a CSV."}
        ]


def test_clauses_command_fails_for_an_unknown_change_or_unreadable_spec(
    tmp_path: Path, capsys
) -> None:
    root = clause_repo(tmp_path)
    assert main(["--root", str(root), "clauses", "0009"]) == 1
    assert "no change matching '0009'" in capsys.readouterr().err
    (root / "changes/0001-search/spec.md").write_text("# Spec\n\n## Requirements\n\nTBD\n")
    assert main(["--root", str(root), "clauses", "0001"]) == 1
    assert "no requirements could be read" in capsys.readouterr().err
    (root / "changes/0001-search/spec.md").unlink()
    assert main(["--root", str(root), "clauses", "0001"]) == 1


def test_clauses_with_a_ref_keeps_only_what_changed(tmp_path: Path, capsys) -> None:
    import json

    root = clause_repo(tmp_path)
    spec = root / "changes/0001-search/spec.md"
    plan = root / "changes/0001-search/plan.md"
    spec.write_text(
        CLAUSE_SPEC.replace("Results are ordered by title.", "Results are ordered by date.")
        + "- R9. not in Requirements, so not read.\n"
    )
    plan.write_text(CLAUSE_PLAN + "| AC1 | `make test` | filtered |\n")

    def ids(*ref: str) -> list[str]:
        assert main(["--root", str(root), "clauses", "0001", *ref]) == 0
        return [b["id"] for b in json.loads(capsys.readouterr().out)["requirements"]]

    # R3's text changed, and R1 has a new plan row for its criterion AC1.
    assert ids("--ref", "HEAD") == ["R1", "R3"]
    assert ids() == ["R1", "R2", "R3", "R4"]
    # A ref without the spec (a new change): check everything.
    git(root, "rm", "-q", "--cached", "changes/0001-search/spec.md")
    git(root, "commit", "-q", "-m", "drop spec")
    assert ids("--ref", "HEAD") == ["R1", "R2", "R3", "R4"]


def test_clause_coverage_reaches_every_stage() -> None:
    for path in (
        ".claude/skills/spec/SKILL.md",
        ".claude/skills/plan/SKILL.md",
        ".claude/agents/verifier.md",
        "REVIEW.md",
    ):
        text = (REPO / path).read_text()
        assert "clause" in text.lower(), path
    review = (REPO / "REVIEW.md").read_text()
    assert "scripts/clause-check.sh" in review
    assert "IDs only" in review, "the spec-match line states its basis"
    assert "Untestable (R<n>)" in (REPO / "templates/spec.md").read_text()
    assert "make clauses CHANGE=" in (REPO / ".claude/agents/verifier.md").read_text()


def test_clauses_with_a_ref_whose_spec_cant_be_read_checks_everything(
    tmp_path: Path, capsys
) -> None:
    import json

    root = init_repo(tmp_path / "repo")
    commit(root, "old", {"changes/0001-search/spec.md": "# Spec\n\n## Requirements\n\nTBD\n"})
    (root / "changes/0001-search/spec.md").write_text(CLAUSE_SPEC)
    assert main(["--root", str(root), "clauses", "0001", "--ref", "HEAD"]) == 0
    assert len(json.loads(capsys.readouterr().out)["requirements"]) == 4


def test_clauses_list_requirement_lines_they_cant_read() -> None:
    # PR #107 review: a line in another form, or an R<n> with no text, was dropped silently.
    from sdlc.clauses import blocks, unreadable

    spec = CLAUSE_SPEC.replace(
        "- R4: Export writes a CSV.",
        "- R4: Export writes a CSV.\n- Requirement 5: Import reads a CSV.\n- R6.\n"
        "3. The export is quick.\n<!-- - an HTML comment isn't a line -->",
    )
    assert unreadable(spec) == [
        "- Requirement 5: Import reads a CSV.",
        "- R6.",
        "3. The export is quick.",
    ]
    assert [b.id for b in blocks(spec)] == ["R1", "R2", "R3", "R4"], "the rest are still checked"
    # Wrapped lines, group labels and prose aren't requirements that went missing.
    assert unreadable(CLAUSE_SPEC) == []
    # Lettered requirements (spellbound3d 0006's `- **R14a.** …`) are read, not reported.
    lettered = CLAUSE_SPEC.replace("- R4: Export", "- **R4a.** Export")
    assert unreadable(lettered) == [] and "R4a" in [b.id for b in blocks(lettered)]


def test_clauses_command_warns_and_lists_unreadable_lines(tmp_path: Path, capsys) -> None:
    import json

    root = clause_repo(tmp_path)
    spec = root / "changes/0001-search/spec.md"
    spec.write_text(CLAUSE_SPEC.replace("- R4: Export", "- Requirement 4: Export"))
    for ref in ([], ["--ref", "HEAD"]):  # listed whatever the ref: nothing has checked them
        assert main(["--root", str(root), "clauses", "0001", *ref]) == 0
        out, err = capsys.readouterr()
        assert json.loads(out)["unreadable"] == ["- Requirement 4: Export writes a CSV."]
        assert "warning: can't read this as a requirement" in err
