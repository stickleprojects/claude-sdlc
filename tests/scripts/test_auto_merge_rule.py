import json
import os
import re

import pytest

from conftest import REPO, init_repo, run

from .helpers import review_run

# --- THE RULE for SDLC_AUTO_MERGE, in every place that reads it (#101) ----------------------

AUTO_MERGE_VALUES = [
    ("", False),
    ("off", False),
    ("OFF", False),
    ("Off", False),
    ("merge", True),
    ("Squash", True),
]


def workflow_reviews_pushes(value: str) -> bool:
    """sdlc-claude-review.yml's push gate, evaluated as GitHub does: `!=` on strings ignores
    case."""
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    assert "(vars.SDLC_AUTO_MERGE != '' && vars.SDLC_AUTO_MERGE != 'off')" in workflow
    return value.lower() != "" and value.lower() != "off"


@pytest.mark.parametrize(("value", "on"), AUTO_MERGE_VALUES)
def test_every_reader_of_sdlc_auto_merge_follows_the_same_rule(request_review, value, on):
    method = run(
        ["bash", ".sdlc/scripts/auto-merge.sh", "--method"], env={"SDLC_AUTO_MERGE": value}
    )
    assert method.returncode == 0
    assert method.stdout == (value.lower() if on else "")

    # (bootstrap's reading of the rule is tested end to end below: it deletes a leftover
    # SDLC_AUTO_MERGE_CONFIRMED only when auto-merge is off)

    # request-review: with the push's review running, it labels only when auto-merge is off.
    _, labelled, _ = request_review(variable=value, runs=[review_run()])
    assert labelled == (not on)

    assert workflow_reviews_pushes(value) == on


def test_auto_merge_method_fails_when_the_variable_cant_be_read(auto_merge):
    state, _ = auto_merge
    (state / "vars-forbidden").write_text("")
    result = run(
        ["bash", str(REPO / ".sdlc/scripts/auto-merge.sh"), "--method"],
        env={
            "PATH": f"{state.parent / 'fakebin'}:{os.environ['PATH']}",
            "D": str(state),
            "GITHUB_REPOSITORY": "o/r",
        },
    )
    assert result.returncode == 1 and result.stdout == ""


def test_auto_merge_reads_every_page_of_organization_variables(auto_merge):
    # #101 finding 5: past the first 30 an org variable read as unset.
    _, go = auto_merge
    _, _, calls = go()
    org = [c for c in calls.splitlines() if "organization-variables" in c]
    assert org and all("--paginate" in c for c in org)


def _rulesets_only(state, dismiss):
    (state / "protection.json").unlink(missing_ok=True)
    (state / "no-classic-protection").write_text("")
    (state / "branch.json").write_text(json.dumps({"protection": {}}))
    rule = {"type": "pull_request", "parameters": {"dismiss_stale_reviews_on_push": dismiss}}
    checks = {
        "type": "required_status_checks",
        "parameters": {"required_status_checks": [{"context": "claude-review"}]},
    }
    (state / "rules.json").write_text(json.dumps([rule, checks]))


def test_auto_merge_ignores_a_stale_confirmation_on_a_rulesets_only_branch(auto_merge):
    # #101 finding 6: "Branch not protected" (404) means rulesets only, so a CONFIRMED=true left
    # from a classic setup mustn't stand in for a ruleset that doesn't dismiss stale approvals.
    state, go = auto_merge
    _rulesets_only(state, dismiss=False)
    result, mutated, _ = go(SDLC_AUTO_MERGE="merge", SDLC_AUTO_MERGE_CONFIRMED="true")
    assert not mutated
    assert "doesn't dismiss stale approvals on push" in result.stderr
    _rulesets_only(state, dismiss=True)
    _, mutated, _ = go(SDLC_AUTO_MERGE="merge", SDLC_AUTO_MERGE_CONFIRMED="")
    assert mutated, "the rulesets alone decide"


def test_auto_merge_still_trusts_the_confirmation_when_protection_cant_be_read(auto_merge):
    state, go = auto_merge
    (state / "protection.json").unlink()  # 403: a token without Administration: read
    _, mutated, _ = go(SDLC_AUTO_MERGE="merge", SDLC_AUTO_MERGE_CONFIRMED="true")
    assert mutated


FAKE_GH_BOOTSTRAP = r"""#!/usr/bin/env bash
# Enough of GitHub for a whole bootstrap run: logs each call, keeps the protection it's sent.
echo "$*" >> "$D/calls"
case "$*" in
  *actions/variables/SDLC_AUTO_MERGE_CONFIRMED*) echo "${FAKE_CONFIRMED-true}" ;;
  *actions/variables/SDLC_AUTO_MERGE*) echo "gh: Not Found (HTTP 404)" >&2; exit 1 ;;
  *organization-variables*) echo "gh: Validation Failed (HTTP 422)" >&2; exit 1 ;;
  "variable delete"*|"variable set"*) exit 0 ;;
  "api -X PUT repos/o/r/branches/main/protection"*) cat > "$D/put.json" ;;
  *branches/main/protection*) cat "$D/protection.json" ;;
  *) echo '{}' ;;
esac
"""


@pytest.fixture
def bootstrap_run(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_BOOTSTRAP)
    (fake / "gh").chmod(0o755)
    repo = init_repo(tmp_path / "repo")
    protection = {"required_status_checks": {"contexts": ["check", "pr-title", "review"]}}
    (tmp_path / "protection.json").write_text(json.dumps(protection))

    def go(*args, **env):
        (tmp_path / "calls").unlink(missing_ok=True)
        result = run(
            [
                "bash",
                str(REPO / ".sdlc/scripts/bootstrap-github.sh"),
                "--repo",
                "o/r",
                "--mode",
                "team",
                "--skip-token",
                *args,
            ],
            cwd=repo,
            env={"PATH": f"{fake}:{os.environ['PATH']}", "D": str(tmp_path), **env},
            input="",
        )
        out = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout + result.stderr)
        put = tmp_path / "put.json"
        sent = json.loads(put.read_text()) if put.exists() else None
        put.unlink(missing_ok=True)
        return result, out, (tmp_path / "calls").read_text(), sent

    return go


def test_bootstrap_with_auto_merge_off_drops_review_and_the_stale_confirmation(bootstrap_run):
    # #101 findings 2 and 6: `review` can't pass without push reviews, and a CONFIRMED=true left
    # from when auto-merge was on would be trusted if it's turned on again.
    result, out, calls, sent = bootstrap_run()
    assert result.returncode == 0, out
    assert sent["required_status_checks"]["contexts"] == ["check", "claude-review", "pr-title"]
    assert "the old review check is no longer required" in out
    assert "variable delete SDLC_AUTO_MERGE_CONFIRMED -R o/r" in calls
    assert "deleted SDLC_AUTO_MERGE_CONFIRMED (auto-merge is off)" in out


def test_bootstrap_with_auto_merge_off_leaves_no_confirmation_alone(bootstrap_run):
    _, out, calls, _ = bootstrap_run(FAKE_CONFIRMED="")
    assert "variable delete" not in calls and "SDLC_AUTO_MERGE_CONFIRMED" not in out


def test_bootstrap_dry_run_says_it_would_delete_the_confirmation(bootstrap_run):
    _, out, calls, sent = bootstrap_run("--dry-run")
    assert "would delete SDLC_AUTO_MERGE_CONFIRMED (auto-merge is off)" in out
    assert "variable delete" not in calls and sent is None


@pytest.mark.parametrize("value", ["merge", "off"])
def test_bootstrap_requires_claude_review_and_drops_the_old_gate(bootstrap_run, value):
    _, out, calls, sent = bootstrap_run("--auto-merge", value)
    on = value != "off"
    assert "claude-review" in sent["required_status_checks"]["contexts"], "whatever auto-merge"
    assert "review" not in sent["required_status_checks"]["contexts"], "the old gate is dropped"
    if not on:  # (when on, it's deleted only if main doesn't qualify, as before)
        assert "deleted SDLC_AUTO_MERGE_CONFIRMED (auto-merge is off)" in out


def test_bootstrap_keeps_the_claude_review_status_when_auto_merge_is_off(bootstrap_run, tmp_path):
    # #46 reversed #101's "drop it when off": unreviewed pushes are now marked, not left Expected.
    (tmp_path / "protection.json").write_text(
        json.dumps({"required_status_checks": {"contexts": ["check", "pr-title", "claude-review"]}})
    )
    _, out, _, sent = bootstrap_run()
    assert sent["required_status_checks"]["contexts"] == ["check", "claude-review", "pr-title"]
    assert "no longer required (auto-merge is off" not in out


def test_auto_merge_refuses_the_old_review_check_as_the_gate(auto_merge):
    # #101 finding 4: a job skipped by another label satisfies the job's own `review` check.
    state, go = auto_merge
    (state / "branch.json").write_text(
        json.dumps({"protection": {"required_status_checks": {"contexts": ["check", "review"]}}})
    )
    result, mutated, _ = go(SDLC_AUTO_MERGE="merge")
    assert not mutated
    assert "requires the old 'review' check, which a skipped review job satisfies" in result.stderr


def test_auto_merge_never_merges_a_pr_that_changes_a_file_on_the_ci_approval_list(auto_merge):
    # A person approves those files in the PR (ADR 0001, #293), so a person merges it. The
    # review workflows (#14), with their names since #23 and before it, are on the list too.
    state, go = auto_merge
    for path in (
        ".github/workflows/sdlc-claude-review.yml",
        ".github/workflows/sdlc-claude-mention.yml",
        ".github/workflows/claude-review.yml",
        ".github/workflows/sdlc-ci.yml",
        ".github/dependabot.yml",
        ".sdlc/hooks/plan-gate.sh",
        ".claude/settings.json",
        "uv.lock",
    ):
        files = [{"filename": "README.md"}, {"filename": path}]
        (state / "pr-files.json").write_text(json.dumps(files))
        result, mutated, calls = go(SDLC_AUTO_MERGE="merge")
        assert not mutated and f"it changes {path}, which is on the CI approval list" in (
            result.stderr
        ), path
        assert "pulls/7/files --paginate" in calls
    for path in ("README.md", "Makefile", ".sdlc/scripts/clause-check.sh"):
        (state / "pr-files.json").write_text(json.dumps([{"filename": path}]))
        _, mutated, _ = go(SDLC_AUTO_MERGE="merge")
        assert mutated, path


def test_review_posts_its_own_claude_review_status():
    # #101 finding 4: a skipped job posts no status, so it can't satisfy the required gate.
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    assert "\n  statuses: write\n" in workflow
    steps = workflow.split("\n      - ")
    names = [s.split("\n", 1)[0] for s in steps]
    action = names.index("name: Review")
    running = next(i for i, n in enumerate(names) if "Mark the review as running" in n)
    done = next(i for i, n in enumerate(names) if "Mark the review as done" in n)
    failed = next(i for i, n in enumerate(names) if "Mark the review as failed" in n)
    assert running < action < done < failed
    for i, state, when in (
        (running, "pending", None),
        (done, "success", "success()"),
        (failed, "failure", "failure()"),
    ):
        assert f"-f state={state}" in steps[i] and "-f context=claude-review" in steps[i]
        assert "statuses/$HEAD_SHA" in steps[i]
        if when:
            assert f"if: {when}" in steps[i]
    assert "HEAD_SHA: ${{ github.event.pull_request.head.sha }}" in workflow
    assert "No AI review: the PR changes an sdlc-claude-*.yml workflow" in steps[done]


def test_review_notes_a_workflow_change_on_the_push_that_makes_it():
    # #101 finding 3: the note was posted only when the PR opened.
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    note = workflow[workflow.index("- name: Note when the AI review can't run") :]
    note = note[: note.index("\n      - ", 1)]
    assert "if: github.event.action == 'opened'" not in note, "runs on every event"
    assert 'git diff --name-only "$BEFORE" HEAD' in note and "synchronize)" in note
    assert 'echo "skipped=true" >> "$GITHUB_OUTPUT"' in note


def test_v0_10_0_upgrade_steps_match_the_scripts():
    notes = (REPO / "docs/release-notes/v0.10.0.md").read_text()
    assert "## Upgrade steps" in notes
    bootstrap = (REPO / ".sdlc/scripts/bootstrap-github.sh").read_text()
    for quoted in (
        "'check', 'pr-title' and 'claude-review'",
        "the old review check is no longer required",
    ):
        assert quoted in notes and quoted in bootstrap, quoted
    assert "scripts/request-review.sh <N>" in notes and "unreviewed-push" in notes
    assert '"${1:-}" == --method' in (REPO / ".sdlc/scripts/auto-merge.sh").read_text()
    assert "your own scripts that aren't executable in git" in notes
