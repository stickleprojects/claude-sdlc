import os
import shutil

import pytest

from conftest import REPO, init_repo, run

from .helpers import PUSHED, review_run, synced


def test_request_review_adds_the_label_when_auto_merge_is_off(request_review):
    result, labelled, _ = request_review(variable="")
    assert result.returncode == 0 and labelled
    assert result.stdout == (
        "Added the review label: auto-merge is off, so pushes don't start a review.\n"
    )


def test_request_review_leaves_the_push_review_alone_when_auto_merge_is_on(request_review):
    # spellbound3d PR #95: the label cancelled the review the push had started.
    result, labelled, calls = request_review(variable="merge", runs=[review_run()])
    assert result.returncode == 0 and not labelled
    assert "SDLC_AUTO_MERGE=merge" in result.stdout and "abc1234" in result.stdout
    assert f"actions/runs?head_sha={PUSHED}&event=pull_request" in calls
    # No label to add, so no waiting for GitHub to show the push: even an old head is fine.
    assert "api repos/o/r/pulls/7 " not in calls
    result, labelled, _ = request_review(variable="merge", runs=[review_run()], heads=("0ld0000",))
    assert not labelled and "already started a review" in result.stdout


@pytest.mark.parametrize(
    "runs",
    [
        [],  # no run yet
        [review_run("skipped")],  # the job's condition skipped it
        [review_run("cancelled")],  # a newer run replaced it
        [review_run(path=".github/workflows/sdlc-ci.yml")],  # another workflow
    ],
)
def test_request_review_adds_the_label_when_no_review_started_on_the_push(request_review, runs):
    result, labelled, _ = request_review(variable="squash", runs=runs)
    assert result.returncode == 0 and labelled
    assert "no review run started on abc1234" in result.stdout


def test_request_review_counts_a_finished_review_of_the_push(request_review):
    result, labelled, _ = request_review(variable="merge", runs=[review_run("success")])
    assert not labelled and "already started a review" in result.stdout


@pytest.mark.parametrize("status", [403, 500])
def test_request_review_falls_back_to_the_runs_when_the_variable_cant_be_read(
    request_review, status
):
    result, labelled, _ = request_review(status=status, runs=[review_run()])
    assert not labelled
    assert "couldn't read SDLC_AUTO_MERGE, but a review run already started" in result.stdout
    result, labelled, _ = request_review(status=status)
    assert labelled
    assert result.stdout == (
        "Added the review label: couldn't read SDLC_AUTO_MERGE, and no review run had started "
        "on abc1234.\n"
    )


def test_request_review_reads_an_unset_variable_as_off(request_review):
    # A 404 means the variable isn't set (auto-merge.sh --setting); not an unreadable one.
    result, labelled, _ = request_review(status=404)
    assert labelled and "auto-merge is off" in result.stdout


def test_request_review_waits_for_github_to_show_the_push(request_review):
    result, labelled, calls = request_review(heads=("0ld0000", "0ld0000", PUSHED))
    assert labelled, result.stdout
    assert calls.count("api repos/o/r/pulls/7 ") == 3


def test_request_review_never_labels_the_old_head(request_review):
    result, labelled, _ = request_review(heads=("0ld0000",))
    assert result.returncode == 0 and not labelled
    assert result.stdout.startswith("Not adding the review label (auto-merge is off, ")
    assert "still 0ld0000, not the pushed abc1234" in result.stdout


def test_request_review_leaves_a_label_that_is_already_on(request_review):
    result, labelled, _ = request_review(labels=["bug", "review"])
    assert not labelled and "already on" in result.stdout


@pytest.fixture
def other_checkout(tmp_path):
    """A checkout on a branch with one commit of its own, which isn't the PR's head."""
    repo = tmp_path / "checkout"
    repo.mkdir()
    for cmd in (
        ["git", "init", "-q", "-b", "build/0029-x"],
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "local",
        ],
    ):
        run(cmd, cwd=repo, check=True)
    local = run(["git", "rev-parse", "HEAD"], cwd=repo, check=True).stdout.strip()
    return repo, local


def test_request_review_from_another_checkout_names_the_prs_head(request_review, other_checkout):
    # spellbound3d#183: run from #182's checkout, it named a981ed0 instead of #183's 751a1c7.
    repo, local = other_checkout
    result, labelled, calls = request_review(sha=None, ref="spec/0029-amend", cwd=repo)
    # Labelled at all means it waited for abc1234: with the local commit it would never match.
    assert result.returncode == 0 and labelled, result.stdout + result.stderr
    result, labelled, calls = request_review(
        variable="merge", runs=[review_run()], sha=None, ref="spec/0029-amend", cwd=repo
    )
    assert f"actions/runs?head_sha={PUSHED}&" in calls and local not in calls


def test_request_review_on_the_prs_branch_names_the_local_push(request_review, other_checkout):
    # The skills' case: this checkout just pushed, and GitHub may still show the old head (#105).
    repo, local = other_checkout
    result, labelled, calls = request_review(
        variable="merge", runs=[review_run()], sha=None, ref="build/0029-x", cwd=repo
    )
    assert result.returncode == 0 and not labelled, result.stdout + result.stderr
    assert f"actions/runs?head_sha={local}&" in calls and local[:7] in result.stdout


def test_request_review_says_when_it_couldnt_add_the_label(request_review):
    result, labelled, _ = request_review(label_fails=True)
    assert result.returncode == 0
    assert result.stdout.startswith("Couldn't add the review label")


def test_request_review_usage():
    assert run(["bash", ".sdlc/scripts/request-review.sh"]).returncode == 2
    assert run(["bash", ".sdlc/scripts/request-review.sh", "7", "not-a-sha"]).returncode == 2


def test_request_review_rejects_a_bad_sha_even_when_it_cant_tell_the_repo(tmp_path):
    # With no GITHUB_REPOSITORY and no gh login (CI aside), the repo lookup used to come first
    # and exit 0, so a bad sha went unreported.
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gh").write_text("#!/usr/bin/env bash\nexit 1\n")
    (fake / "gh").chmod(0o755)
    env = {"PATH": f"{fake}:{os.environ['PATH']}", "GITHUB_REPOSITORY": ""}
    result = run(["bash", ".sdlc/scripts/request-review.sh", "7", "not-a-sha"], env=env)
    assert result.returncode == 2 and "no commit to review" in result.stderr


def test_skills_ask_for_a_review_through_request_review():
    for path in (
        ".sdlc/skills/review-findings/SKILL.md",
        ".sdlc/skills/po-review/SKILL.md",
        ".sdlc/skills/build/SKILL.md",
    ):
        text = (REPO / path).read_text()
        assert ".sdlc/scripts/request-review.sh <N>" in text, path
        assert 'labels[]=review"' not in text, f"{path} adds the label directly"
    assert synced(".sdlc/scripts/request-review.sh")


def test_request_review_expands_the_checkouts_head_for_the_runs_api(request_review, other_checkout):
    repo, full = other_checkout
    for sha in (None, full[:7]):  # no sha on the PR's branch means HEAD; a short one is expanded
        _, _, calls = request_review(
            variable="merge", runs=[review_run()], sha=sha, ref="build/0029-x", cwd=repo
        )
        assert f"actions/runs?head_sha={full}&" in calls


def test_baseline_gitignore_keeps_the_build_skill_while_ignoring_build_output(tmp_path):
    # #103: a bare `build/` also matched .claude/skills/build/, so a file a sync added there
    # was ignored and the sync PR silently left it out. Since #133 the framework's own
    # .gitignore files carry the exception, so the project's root file never changes for it.
    # Since #23 the stub's folder is sdlc-build, so only .sdlc/ needs one.
    repo = init_repo(tmp_path / "r")
    shutil.copy(REPO / ".sdlc" / "templates" / "gitignore", repo / ".gitignore")
    nested = ".sdlc/.gitignore"
    (repo / nested).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / nested, repo / nested)
    paths = [
        ".claude/skills/sdlc-build/new.md",
        ".sdlc/skills/build/SKILL.md",
        "build/out.js",
        "app/build/out.js",
        ".sdlc/src/sdlc/__pycache__/x.pyc",
    ]
    for path in paths:
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text("x\n")
    ignored = run(["git", "check-ignore", *paths], cwd=repo).stdout.split()
    assert ignored == ["build/out.js", "app/build/out.js", ".sdlc/src/sdlc/__pycache__/x.pyc"]


def test_the_build_skill_stays_tracked_under_a_projects_own_build_rule(tmp_path):
    repo = init_repo(tmp_path / "r")
    (repo / ".gitignore").write_text("build/\n")  # the project's file, nothing of ours in it
    nested = ".sdlc/.gitignore"
    (repo / nested).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / nested, repo / nested)
    # The stub's folder is sdlc-build since #23, which a `build/` rule doesn't match.
    for skill in (".claude/skills/sdlc-build/SKILL.md", ".sdlc/skills/build/SKILL.md"):
        (repo / skill).parent.mkdir(parents=True, exist_ok=True)
        (repo / skill).write_text("x\n")
        assert run(["git", "check-ignore", skill], cwd=repo).returncode == 1, skill
    assert "skills/build" not in (REPO / ".sdlc/templates/gitignore").read_text()


def test_v0_9_1_upgrade_steps_name_commands_that_exist():
    notes = (REPO / "docs/release-notes/v0.9.1.md").read_text()
    assert notes.startswith("## Upgrade steps")  # the section /sdlc carries out
    bootstrap = (REPO / ".sdlc/scripts/bootstrap-github.sh").read_text()
    assert (
        "scripts/bootstrap-github.sh --gitignore-only" in notes and "--gitignore-only)" in bootstrap
    )
    identity = (REPO / ".sdlc/scripts/agent-identity.sh").read_text()
    for sub in ("create", "check"):
        assert f"scripts/agent-identity.sh {sub}" in notes and f"  {sub})" in identity
    assert "!.claude/skills/build/" in notes  # since #23 not needed: the stub is sdlc-build/
