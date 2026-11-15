from conftest import REPO, git

from .helpers import spec_pr


def test_spec_pr_pending_skips_changes_with_an_open_spec_pr(spec_repo):
    repo, _, state, env = spec_repo
    (state / "open-spec_0001-a").write_text("18\n")
    result = spec_pr(repo, env, "pending")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["changes/0002-b"]
    assert "spec PR #18 is already open" in result.stderr


def test_spec_pr_pending_fails_when_github_errors(spec_repo):
    # Treating an API error as "no open PR" would open a duplicate.
    repo, _, state, env = spec_repo
    (state / "fail").write_text("")
    assert spec_pr(repo, env, "pending").returncode != 0


def test_spec_pr_open_pushes_one_branch_per_change_named_after_it(spec_repo):
    repo, remote, state, env = spec_repo
    (repo / "changes/0001-a/spec.md").write_text("# a spec\n")
    (repo / "changes/0002-b/spec.md").write_text("# b spec\n")
    (repo / "stray.txt").write_text("agent leftovers\n")
    result = spec_pr(repo, env, "open", "changes/0001-a", "changes/0002-b")
    assert result.returncode == 0, result.stderr
    for slug, kind in [("0001-a", "intent"), ("0002-b", "bug")]:
        files = git(remote, "show", "--name-only", "--format=%s", f"spec/{slug}").splitlines()
        assert files[0] == f"spec({slug}): generate from accepted {kind}"
        assert [f for f in files[1:] if f] == [f"changes/{slug}/spec.md"]
    calls = (state / "calls").read_text()
    assert "title=spec(0001-a): generate from accepted intent" in calls
    assert "title=spec(0002-b): generate from accepted bug" in calls


def test_spec_pr_open_closes_an_older_run_numbered_pr_it_supersedes(spec_repo):
    repo, _, state, env = spec_repo
    (repo / "changes/0001-a/spec.md").write_text("# a spec\n")
    (state / "legacy").write_text("19\n")
    (state / "legacy-files").write_text("changes/0001-a/spec.md\n")
    result = spec_pr(repo, env, "open", "changes/0001-a")
    assert result.returncode == 0, result.stderr
    calls = (state / "calls").read_text()
    assert "repos/o/r/issues/19/comments" in calls
    assert "-X PATCH repos/o/r/pulls/19 --silent -f state=closed" in calls
    assert "closed #19 (superseded by #42)" in result.stdout


def test_spec_from_intent_queues_runs_and_uses_spec_pr():
    workflow = (REPO / ".github/workflows/sdlc-spec-from-intent.yml").read_text()
    assert "group: spec-from-intent" in workflow
    assert "cancel-in-progress: false" in workflow
    assert ".sdlc/scripts/spec-pr.sh pending" in workflow
    assert "GITHUB_RUN_ID" not in workflow
