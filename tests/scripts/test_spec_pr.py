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


def test_spec_pr_pending_skips_a_withdrawn_change(spec_repo):
    # #286: spellbound3d's 0078 was withdrawn at the intent stage, and every later merge to main
    # that touched an intent listed it again, so a spec was generated for a binned change.
    repo, _, _, env = spec_repo
    withdrawn = "Withdrawn: Kieron, 2026-11-25. Not needed.\n"
    (repo / "changes/0001-a/intent.md").write_text(f"# a\n\n{withdrawn}")
    (repo / "changes/0002-b/bug.md").write_text(f"# b\n\n{withdrawn}")
    (repo / "changes/0004-d").mkdir()
    (repo / "changes/0004-d/intent.md").write_text("# d\n")
    (repo / "changes/0004-d/change.toml").write_text(
        'number = "0004"\nslug = "0004-d"\ntitle = "d"\nstatus = "withdrawn"\n'
    )
    (repo / "changes/0005-e").mkdir()
    (repo / "changes/0005-e/intent.md").write_text("# e\n\nWithdrawn:\n")  # no reason: not one
    result = spec_pr(repo, env, "pending")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["changes/0005-e"]
    assert "skip changes/0001-a: withdrawn (Kieron, 2026-11-25. Not needed.)" in result.stderr
    assert "skip changes/0002-b: withdrawn (Kieron" in result.stderr
    assert "skip changes/0004-d: withdrawn (change.toml says withdrawn)" in result.stderr
