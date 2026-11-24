from pathlib import Path

import pytest

from conftest import REPO, run

from .helpers import FAST, descope_thread, note

# --- a build PR that amends its plan (#174) ---------------------------------------------------
# spellbound3d 0029: two decisions made mid-build needed a separate spec PR (#183) and five extra
# approvals. With SDLC_BUILD_AMENDS_PLAN=on the build PR carries them, and one reply from a
# person approves them all.

AMENDS = ["changes/0029-w/plan.md", "changes/0029-w/spec.md", "changes/0029-w/build.md", "src/w.py"]
LISTED = (
    "Builds the castle.\n\n## Plan changes\n\n- Interior brick runs dropped (Kieron, 14 Nov).\n"
)


def title_check(title, files, tmp_path, amends="on", body=LISTED):
    env = {"SDLC_BUILD_AMENDS_PLAN": amends}
    if body is not None:
        (tmp_path / "body.md").write_text(body)
        env["SDLC_PR_BODY_FILE"] = str(tmp_path / "body.md")
    return run(
        ["bash", ".sdlc/scripts/check-pr-title.sh", title],
        input="".join(f"{f}\n" for f in files),
        env=env,
    )


@pytest.mark.parametrize(
    ("title", "files", "kwargs", "ok"),
    [
        ("feat(0029-w): the whole castle", AMENDS, {}, True),
        ("fix(0029-w): the warp", AMENDS, {}, True),
        ("feat: no scope is fine", AMENDS, {}, True),
        ("feat(0029-w): plan only", ["changes/0029-w/plan.md", "src/w.py"], {}, True),
        ("feat(0029-w): setting off", AMENDS, {"amends": ""}, False),
        ("feat(0029-w): setting off", AMENDS, {"amends": "off"}, False),
        ("feat(0029-w): no section", AMENDS, {"body": "Builds the castle."}, False),
        ("feat(0029-w): no body", AMENDS, {"body": None}, False),
        ("feat(0029-w): no code", ["changes/0029-w/plan.md", "changes/0029-w/spec.md"], {}, False),
        ("feat(0029-w): an intent too", [*AMENDS, "changes/0029-w/intent.md"], {}, False),
        ("feat(0029-w): two changes", [*AMENDS, "changes/0030-v/plan.md"], {}, False),
        ("docs(0029-w): wrong type", AMENDS, {}, False),
        ("plan(0029-w): still a plan PR", AMENDS, {}, True),
    ],
)
def test_pr_title_lets_a_build_pr_amend_its_plan_when_the_repo_opts_in(
    title, files, kwargs, ok, tmp_path
):
    result = title_check(title, files, tmp_path, **kwargs)
    assert (result.returncode == 0) == ok, result.stdout


def test_pr_title_asks_for_the_plan_changes_section(tmp_path):
    result = title_check("feat(0029-w): build", AMENDS, tmp_path, body="Builds the castle.")
    assert result.returncode == 1
    assert "under a '## Plan changes' heading in the PR body" in result.stdout


def test_pr_title_keeps_the_fast_path_with_amendments_on(tmp_path):
    result = title_check("fix(0010-z): export no longer hangs", FAST, tmp_path)
    assert result.returncode == 0 and "the bug fast path" in result.stdout


PLAN_CHANGES = (
    "**Important (engineer decides; product owner for spec clauses):** Plan changes: needs"
    " approval. Two amendments, both recorded in build.md."
)


def test_plan_changes_wait_for_a_persons_reply(descopes):
    bot_line = note("stickle-claude", "Approved: Kieron, 2026-11-14", "2026-11-14T11:00:00Z", "Bot")
    for thread in (
        descope_thread(first=PLAN_CHANGES),
        descope_thread(bot_line, first=PLAN_CHANGES),
    ):
        result = descopes([thread])
        assert result.returncode == 1
        assert result.stdout.startswith("A plan change waits for a person's decision: Two amend")


def test_one_reply_approves_every_plan_change(descopes):
    approved = note("kieron", "Approved: Kieron, 2026-11-15", "2026-11-15T11:00:00Z")
    result = descopes([descope_thread(approved, first=PLAN_CHANGES)])
    assert result.returncode == 0
    assert (
        result.stdout.strip() == "descopes decided: plan changes approved by @kieron (2026-11-15)"
    )


def test_plan_changes_sent_back_wait_for_a_re_review(descopes):
    back = note("kieron", "No: keep the brick runs.", "2026-11-15T11:00:00Z")
    result = descopes([descope_thread(back, first=PLAN_CHANGES)], reviewed="2026-11-15T10:30:00Z")
    assert result.returncode == 1 and "@kieron sent a plan change back" in result.stdout


def test_descopes_status_clears_a_plan_change_once_approved(descopes):
    approved = note("kieron", "Approved: Kieron, 2026-11-15", "2026-11-15T11:00:00Z")
    status = ("failure", "A plan change waits for a person's decision: x")
    result = descopes(
        [descope_thread(approved, first=PLAN_CHANGES)], status=status, script="status"
    )
    assert "state=success" in result.posted
    assert "plan changes approved by @kieron" in result.posted
    waiting = descopes([descope_thread(first=PLAN_CHANGES)], status=status, script="status")
    assert "state=failure" in waiting.posted


def test_build_amends_plan_is_wired_through_ci_the_rules_and_the_skill():
    title = (REPO / ".github/workflows/sdlc-pr-title.yml").read_text()
    assert "SDLC_BUILD_AMENDS_PLAN: ${{ vars.SDLC_BUILD_AMENDS_PLAN }}" in title
    assert 'SDLC_PR_BODY_FILE="$RUNNER_TEMP/body.md"' in title
    review = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    assert (
        review.count("SDLC_BUILD_AMENDS_PLAN variable is '${{ vars.SDLC_BUILD_AMENDS_PLAN }}'") == 2
    )
    rules = (REPO / ".sdlc/REVIEW.md").read_text()
    assert "Session decisions: needs approval." in rules  # descopes-decided.sh reads this lead-in
    build = (REPO / ".sdlc/skills/build/SKILL.md").read_text()
    assert "gh variable get SDLC_BUILD_AMENDS_PLAN" in build
    settings = (REPO / ".sdlc/docs/settings.md").read_text()
    assert "| `SDLC_BUILD_AMENDS_PLAN` | `on`, `off` | off |" in settings


def test_descopes_skip_a_bots_review_as_well_as_its_comments():
    # #189: the reviewer's own pull_request_review events started the job for nothing.
    workflow = (REPO / ".github/workflows/sdlc-descopes.yml").read_text()
    assert "github.event.comment.user.type == 'User'" in workflow
    assert (
        "(github.event_name != 'pull_request_review' || github.event.review.user.type == 'User')"
        in workflow
    )


def test_runner_docs_warn_about_old_pull_refs_and_secret_scans():
    doc = (REPO / ".sdlc/docs/self-hosted-runner.md").read_text()
    assert "refs/remotes/pull/*" in doc and "persists between jobs" in doc


def test_the_check_job_keeps_a_projects_reports():
    # #188: spellbound3d's last edit to a synced workflow was its own report upload.
    workflow = (REPO / ".github/workflows/sdlc-ci.yml").read_text()
    check = workflow[workflow.index("make check") :]
    step = check[check.index("- uses: actions/upload-artifact@v4") :][:300]
    assert "if: always()" in step and "path: reports/" in step
    assert "if-no-files-found: ignore" in step


def test_check_after_review_runs_no_action_after_pr_code():
    # #188: that job has main's privileges, so no upload (or any action) after `make check`.
    after = (REPO / ".github/workflows/sdlc-check-after-review.yml").read_text()
    assert "upload-artifact" not in after[after.index('          make "$target"') :]


def main_moves_on(git_, path, text):
    """Commit to main, as another PR's merge would, and update origin/main."""
    git_("checkout", "-q", "main")
    (Path(git_("rev-parse", "--show-toplevel")) / path).write_text(text)
    git_("commit", "-qam", f"main changes {path}")
    git_("update-ref", "refs/remotes/origin/main", "main")
    git_("checkout", "-q", "pr")


def test_update_branch_needs_a_review_when_main_changed_a_file_the_pr_changes(base_merge):
    # PR #193: main (#186) edited the readme next to the PR's own line. The merge is clean, but
    # two edits to one file can reword the same rule, which only a review sees.
    git_, _, go = base_merge
    main_moves_on(git_, "notes.md", "one\nmain's line\ntwo\nthree\n")
    git_("merge", "-q", "--no-edit", "main")
    _, posted = go(git_("rev-parse", "HEAD"))
    assert "state=pending" in posted, posted
    assert "Not reviewed: main changed notes.md too, which this PR changes" in posted


def test_update_branch_keeps_the_review_when_main_changed_other_files(base_merge):
    git_, reviewed, go = base_merge
    main_moves_on(git_, "other.py", "b = 5\n")
    git_("merge", "-q", "--no-edit", "main")
    _, posted = go(git_("rev-parse", "HEAD"))
    assert "state=success" in posted, posted
    assert f"The Claude review of {reviewed[:7]} still holds" in posted


def test_two_update_branch_merges_in_a_row_keep_the_review(base_merge):
    git_, _, go = base_merge
    git_("merge", "-q", "--no-edit", "main")
    main_moves_on(git_, "other.py", "b = 3\n")
    git_("merge", "-q", "--no-edit", "main")
    _, posted = go(git_("rev-parse", "HEAD"))
    assert "state=success" in posted, posted


def test_a_conflict_resolved_by_hand_needs_a_review(base_merge):
    git_, _, go = base_merge
    main_moves_on(git_, "app.py", "a = 9\n")  # the line the PR changed: a conflict
    root = Path(git_("rev-parse", "--show-toplevel"))
    merge = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "merge", "main"]
    assert run(merge, cwd=root).returncode != 0, "main's change to app.py should conflict"
    assert (root / ".git" / "MERGE_HEAD").exists(), "the merge started and stopped on the conflict"
    (root / "app.py").write_text("a = 2\n")
    git_("add", "app.py")
    git_("commit", "-qm", "merge main, keeping the PR's line")
    _, posted = go(git_("rev-parse", "HEAD"))
    assert "state=pending" in posted and "Not reviewed" in posted


def test_a_merge_of_a_branch_that_isnt_the_base_needs_a_review(base_merge):
    git_, _, go = base_merge
    git_("checkout", "-qb", "side", "main~1")
    (Path(git_("rev-parse", "--show-toplevel")) / "side.py").write_text("s = 1\n")
    git_("add", "side.py")
    git_("commit", "-qm", "a side branch")
    git_("checkout", "-q", "pr")
    git_("merge", "-q", "--no-edit", "side")
    _, posted = go(git_("rev-parse", "HEAD"))
    assert "state=pending" in posted


@pytest.mark.parametrize(
    ("carry", "kept"), [(None, True), ("on", True), ("", True), ("off", False)]
)
def test_review_carry_forward_can_be_turned_off(base_merge, carry, kept):
    git_, _, go = base_merge
    git_("merge", "-q", "--no-edit", "main")
    _, posted = go(git_("rev-parse", "HEAD"), carry=carry)
    assert ("state=success" in posted) == kept, posted


def test_review_carry_forward_is_a_documented_repo_variable():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    job = workflow[workflow.index("  unreviewed-push:") :]
    assert "SDLC_REVIEW_CARRY_FORWARD: ${{ vars.SDLC_REVIEW_CARRY_FORWARD }}" in job
    settings = (REPO / ".sdlc/docs/settings.md").read_text()
    assert "| `SDLC_REVIEW_CARRY_FORWARD` | `on`, `off` | on |" in settings
