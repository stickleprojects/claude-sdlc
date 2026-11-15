import json
import os
import re

import pytest

from conftest import REPO, run

from .helpers import _pr, spec_pr, synced


def test_auto_merge_is_off_unless_the_repo_opts_in(auto_merge):
    _, go = auto_merge
    result, mutated, calls = go()
    assert result.returncode == 0 and not mutated
    assert result.stdout == result.stderr == ""
    assert "actions/variables/SDLC_AUTO_MERGE" in calls  # a session reads the repo variable
    result, mutated, _ = go(SDLC_AUTO_MERGE="")  # CI passes an unset variable as empty
    assert result.returncode == 0 and not mutated


def test_auto_merge_enables_with_the_chosen_method(auto_merge):
    _, go = auto_merge
    result, mutated, calls = go(SDLC_AUTO_MERGE="merge")
    assert result.returncode == 0, result.stderr
    assert mutated and "method=MERGE" in calls
    assert "auto-merge enabled for #7 (merge)" in result.stdout


def test_auto_merge_reads_the_repo_variable_in_a_session(auto_merge):
    state, go = auto_merge
    (state / "var-SDLC_AUTO_MERGE").write_text(json.dumps({"value": "squash"}))
    (state / "repo.json").write_text(json.dumps({"allow_auto_merge": True}))
    _, mutated, calls = go()
    assert mutated and "method=SQUASH" in calls


def test_auto_merge_reads_an_organization_variable(auto_merge):
    state, go = auto_merge
    org = {"variables": [{"name": "SDLC_AUTO_MERGE", "value": "merge"}]}
    (state / "org-vars.json").write_text(json.dumps(org))
    _, mutated, _ = go()
    assert mutated


def test_auto_merge_warns_when_it_cant_read_the_variable(auto_merge):
    # spellbound3d: an App without Variables: read gets 403, which isn't "not opted in".
    state, go = auto_merge
    (state / "vars-forbidden").write_text("")
    result, mutated, _ = go()
    assert result.returncode == 0 and not mutated
    assert "can't read the repo variable SDLC_AUTO_MERGE" in result.stderr
    assert "Variables: read" in result.stderr


def test_auto_merge_is_silent_on_a_personal_accounts_repo(auto_merge):
    # spellbound3d: the repo lookup's 404 body and the org lookup's 422 body came back as the
    # variable's value ("SDLC_AUTO_MERGE is '{"message":...}'"), instead of "not opted in".
    state, go = auto_merge
    (state / "personal-account").write_text("")
    result, mutated, calls = go()
    assert result.returncode == 0 and not mutated
    assert result.stdout == result.stderr == ""
    assert "organization-variables" in calls


def test_auto_merge_prints_a_setting_for_bootstrap(auto_merge):
    state, _ = auto_merge
    env = {"PATH": f"{state.parent / 'fakebin'}:{os.environ['PATH']}", "D": str(state)}
    env["GITHUB_REPOSITORY"] = "o/r"

    def setting(name="SDLC_AUTO_MERGE"):
        return run(["bash", str(REPO / ".sdlc/scripts/auto-merge.sh"), "--setting", name], env=env)

    (state / "personal-account").write_text("")
    unset = setting()
    assert (unset.returncode, unset.stdout) == (0, "")
    (state / "var-SDLC_AUTO_MERGE_CONFIRMED").write_text(json.dumps({"value": "true"}))
    assert setting("SDLC_AUTO_MERGE_CONFIRMED").stdout == "true"
    (state / "vars-forbidden").write_text("")
    forbidden = setting()
    assert forbidden.returncode == 1 and forbidden.stdout == ""
    assert (
        run(["bash", str(REPO / ".sdlc/scripts/auto-merge.sh"), "--setting", "a;b"]).returncode == 2
    )


def test_bootstrap_reads_the_variables_like_auto_merge_does():
    # spellbound3d: `gh variable get` doesn't exist before gh 2.48 (Ubuntu ships 2.46), and its
    # error was thrown away, so bootstrap skipped auto-merge without a word.
    script = (REPO / ".sdlc/scripts/bootstrap-github.sh").read_text()
    assert "gh variable get" not in script.replace("Not `gh variable get`", "")
    assert 'bash "$auto_merge_sh" --setting' in script
    assert 'bash "$auto_merge_sh" --method' in script
    assert "can't read the SDLC_AUTO_MERGE variable" in script
    assert synced(".sdlc/scripts/auto-merge.sh")


def _write(name, data):
    return lambda state: (state / name).write_text(json.dumps(data))


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        (lambda s: (s / "pr.json").write_text(_pr(None)), "solo mode"),
        (_write("branch.json", {"protection": {}}), "claude-review status isn't required"),
        (
            _write(
                "protection.json",
                {"required_pull_request_reviews": {"dismiss_stale_reviews": False}},
            ),
            "doesn't dismiss stale approvals",
        ),
        (lambda s: (s / "protection.json").unlink(), "can't read main's protection"),
        (_write("repo.json", {"allow_auto_merge": False}), "doesn't allow auto-merge"),
        (_write("repo.json", {"allow_merge_commit": False}), "doesn't allow 'merge' merges"),
    ],
    ids=["no-approval", "no-review-check", "stale-kept", "protection-403", "repo-off", "method"],
)
def test_auto_merge_skips_and_warns_unless_an_approval_gates_the_merge(auto_merge, setup, reason):
    state, go = auto_merge
    setup(state)
    result, mutated, _ = go(SDLC_AUTO_MERGE="merge")
    assert result.returncode == 0, "a skip never fails the caller"
    assert not mutated
    assert "auto-merge not enabled for #7" in result.stderr and reason in result.stderr


def test_auto_merge_rejects_an_unknown_method(auto_merge):
    _, go = auto_merge
    result, mutated, _ = go(SDLC_AUTO_MERGE="yes")
    assert result.returncode == 0 and not mutated
    assert "use merge, squash or rebase" in result.stderr


def test_auto_merge_with_unreadable_protection_relies_on_bootstraps_confirmation(auto_merge):
    # An App token without Administration: read gets 403 on the protection (spellbound3d).
    state, go = auto_merge
    (state / "protection.json").unlink()
    _, mutated, _ = go(SDLC_AUTO_MERGE="merge", SDLC_AUTO_MERGE_CONFIRMED="true")
    assert mutated


def test_auto_merge_reads_rulesets_too(auto_merge):
    state, go = auto_merge
    (state / "protection.json").unlink()
    (state / "branch.json").write_text("{}")
    checks = {"required_status_checks": [{"context": "claude-review"}]}
    rules = [
        {"type": "required_status_checks", "parameters": checks},
        {"type": "pull_request", "parameters": {"dismiss_stale_reviews_on_push": True}},
    ]
    (state / "rules.json").write_text(json.dumps(rules))
    _, mutated, _ = go(SDLC_AUTO_MERGE="merge")
    assert mutated


def test_auto_merge_only_warns_when_github_refuses(auto_merge):
    state, go = auto_merge
    (state / "mutation-fails").write_text("")
    result, _, calls = go(SDLC_AUTO_MERGE="merge")
    assert result.returncode == 0
    assert "GitHub refused: Pull request is in clean status" in result.stderr
    assert "/merge" not in calls, "never falls back to merging directly"


def test_spec_pr_open_offers_each_new_pr_to_auto_merge(spec_repo):
    repo, _, state, env = spec_repo
    (repo / "changes/0001-a/spec.md").write_text("# a spec\n")
    result = spec_pr(repo, env, "open", "changes/0001-a")
    assert result.returncode == 0, result.stderr
    calls = (state / "calls").read_text()
    assert "repos/o/r/actions/variables/SDLC_AUTO_MERGE" in calls
    workflow = (REPO / ".github/workflows/sdlc-spec-from-intent.yml").read_text()
    assert "SDLC_AUTO_MERGE: ${{ vars.SDLC_AUTO_MERGE }}" in workflow


def test_bootstrap_requires_the_review_status_in_every_mode():
    def contexts(*args):
        result = run([".sdlc/scripts/bootstrap-github.sh", *args, "--print-protection"])
        assert result.returncode == 0, result.stderr
        return sorted(json.loads(result.stdout)["required_status_checks"]["contexts"])

    assert contexts("--mode", "team", "--auto-merge", "merge") == [
        "check",
        "claude-review",
        "pr-title",
    ]
    # #46: every push after a review needs a new one, whatever the mode or auto-merge.
    every = ["check", "claude-review", "pr-title"]
    assert contexts("--mode", "team", "--auto-merge", "off") == every
    assert contexts("--mode", "solo", "--auto-merge", "merge") == every


def test_bootstrap_requires_resolved_conversations_and_compares_every_setting():
    # #92 and #91: a setting bootstrap applies but doesn't compare drifts unnoticed.
    for mode in ("solo", "team"):
        result = run([".sdlc/scripts/bootstrap-github.sh", "--mode", mode, "--print-protection"])
        protection = json.loads(result.stdout)
        assert protection["required_conversation_resolution"] is True
    script = (REPO / ".sdlc/scripts/bootstrap-github.sh").read_text()
    shape = script.split("shape='", 1)[1].split("'", 1)[0]
    for field in (
        "dismiss_stale_reviews",
        "required_conversation_resolution",
        "require_code_owner",
    ):
        assert field in shape, field


def test_bootstrap_keeps_protection_added_by_hand():
    have = {
        "required_status_checks": {"contexts": ["check", "review", "e2e"]},
        "required_linear_history": {"enabled": True},
        "required_pull_request_reviews": {"require_last_push_approval": True},
    }
    result = run(
        [".sdlc/scripts/bootstrap-github.sh", "--print-protection"],
        env={"SDLC_HAVE_PROTECTION": json.dumps(have)},
    )
    protection = json.loads(result.stdout)
    contexts = sorted(protection["required_status_checks"]["contexts"])
    # A hand-added `e2e` is kept; `review` only while auto-merge is on (#101 finding 2).
    assert contexts == ["check", "claude-review", "e2e", "pr-title"]
    assert protection["required_linear_history"] is True
    assert protection["required_pull_request_reviews"]["require_last_push_approval"] is True


def test_bootstrap_and_sync_never_write_the_auto_merge_setting():
    # It's the project's choice; re-running bootstrap or syncing must not reset it.
    for path in (".sdlc/scripts/bootstrap-github.sh", ".sdlc/scripts/sync-sdlc.sh"):
        text = (REPO / path).read_text()
        assert not re.search(r"variable (set|delete) SDLC_AUTO_MERGE\b(?!_)", text), path
