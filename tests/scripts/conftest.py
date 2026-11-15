import json
import os
import shutil

import pytest

from conftest import REPO, commit, git, init_repo, run

from .helpers import (
    FAKE_GH,
    FAKE_GH_AUTO_MERGE,
    FAKE_GH_DESCOPES,
    FAKE_GH_REQUEST_REVIEW,
    FAKE_GH_REVIEW_CURRENT,
    FAKE_NPM,
    MUTATION,
    PUSHED,
    _pr,
)


@pytest.fixture
def released(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(repo, "chore: initial")
    git(repo, "tag", "v0.4.2")
    return repo


@pytest.fixture
def spec_repo(tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    repo = init_repo(tmp_path / "work")
    commit(
        repo,
        "chore: changes",
        {
            "changes/0001-a/intent.md": "# a\n",
            "changes/0002-b/bug.md": "# b\n",
            "changes/0003-c/intent.md": "# c\n",
            "changes/0003-c/spec.md": "# c spec\n",
        },
    )
    git(repo, "remote", "add", "origin", str(remote))
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH)
    (fake / "gh").chmod(0o755)
    state = tmp_path / "gh"
    state.mkdir()
    env = {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "FAKE_GH_DIR": str(state),
        "OWNER": "o",
        "GITHUB_REPOSITORY": "o/r",
    }
    return repo, remote, state, env


@pytest.fixture
def auto_merge(tmp_path):
    """A repo that qualifies: team-mode protection with the review check required."""
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_AUTO_MERGE)
    (fake / "gh").chmod(0o755)
    state = tmp_path / "gh"
    state.mkdir()
    files = {
        "repo.json": {"allow_auto_merge": True, "allow_merge_commit": True},
        "branch.json": {
            "protection": {"required_status_checks": {"contexts": ["check", "claude-review"]}}
        },
        "protection.json": {
            "required_pull_request_reviews": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews": True,
            }
        },
    }
    for name, data in files.items():
        (state / name).write_text(json.dumps(data))
    (state / "pr.json").write_text(_pr("REVIEW_REQUIRED"))
    (state / "org-vars.json").write_text(json.dumps({"variables": []}))
    env = {"PATH": f"{fake}:{os.environ['PATH']}", "D": str(state), "GITHUB_REPOSITORY": "o/r"}

    def go(**extra):
        result = run(["bash", str(REPO / ".sdlc/scripts/auto-merge.sh"), "7"], env={**env, **extra})
        calls = (state / "calls").read_text() if (state / "calls").exists() else ""
        return result, MUTATION in calls, calls

    return state, go


@pytest.fixture
def agent_env(tmp_path):
    key = tmp_path / "app.pem"
    run(["openssl", "genrsa", "-out", str(key), "2048"], check=True)
    run(
        ["openssl", "rsa", "-in", str(key), "-pubout", "-out", str(tmp_path / "pub.pem")],
        check=True,
    )
    cfg = tmp_path / "config"
    (cfg / "sdlc" / "o_r").mkdir(parents=True)
    (cfg / "sdlc" / "o_r" / "agent.env").write_text(
        "SDLC_AGENT_APP_ID=123\nSDLC_AGENT_APP_SLUG=stickle-claude\nSDLC_AGENT_BOT_ID=999\n"
    )
    fake = tmp_path / "bin"
    fake.mkdir()
    # curl stub that answers like GitHub; see the fixture for how tests steer it.
    shutil.copy(REPO / "tests/fixtures/fake-github-curl.sh", fake / "curl")
    (fake / "curl").chmod(0o755)
    env = {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "XDG_CONFIG_HOME": str(cfg),
        "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        "SDLC_AGENT_KEY_FILE": str(key),
        "SDLC_AGENT_REPO": "o/r",
        "LOG": str(tmp_path),
        "SDLC_RETRY_DELAY": "0",
    }
    return tmp_path, env


@pytest.fixture
def fake_claude(tmp_path):
    """A `claude` on PATH that answers each call with $FAKE_ANSWER and logs its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "claude"
    script.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\036" "$*" >> "$FAKE_LOG"\n'
        '[[ -z "${FAKE_FAIL:-}" ]] || exit 1\nprintf "%b\\n" "$FAKE_ANSWER"\n'
    )
    script.chmod(0o755)
    log = tmp_path / "calls.log"

    def check(answer, *args, fail=False):
        env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_LOG": str(log),
            "FAKE_ANSWER": answer,
            **({"FAKE_FAIL": "1"} if fail else {}),
        }
        result = run([".sdlc/scripts/clause-check.sh", *args], env=env)
        calls = log.read_text().split("\036")[:-1] if log.exists() else []
        log.unlink(missing_ok=True)
        return result, calls

    return check


@pytest.fixture
def request_review(tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_REQUEST_REVIEW)
    (fake / "gh").chmod(0o755)
    state = tmp_path / "gh"
    state.mkdir()

    def go(
        variable="",
        status=200,
        heads=(PUSHED,),
        runs=(),
        labels=(),
        label_fails=False,
        sha=PUSHED,
        ref="feat/x",
        cwd=REPO,
    ):
        (state / "heads").write_text("\n".join(heads) + "\n")
        (state / "ref").write_text(ref)
        (state / "var-status").write_text(str(status))
        (state / "var.json").write_text(json.dumps({"value": variable}))
        (state / "runs.json").write_text(json.dumps({"workflow_runs": list(runs)}))
        (state / "labels.json").write_text(json.dumps([{"name": n} for n in labels]))
        (state / "label-fails").unlink(missing_ok=True)
        if label_fails:
            (state / "label-fails").write_text("")
        (state / "calls").unlink(missing_ok=True)
        env = {
            "PATH": f"{fake}:{os.environ['PATH']}",
            "D": str(state),
            "GITHUB_REPOSITORY": "o/r",
            "REQUEST_REVIEW_WAIT": "2",
            "REQUEST_REVIEW_POLL": "1",
        }
        args = [] if sha is None else [sha]
        result = run(
            ["bash", str(REPO / ".sdlc/scripts/request-review.sh"), "7", *args], cwd=cwd, env=env
        )
        calls = (state / "calls").read_text()
        labelled = any(c.startswith("api repos/o/r/issues/7/labels -f") for c in calls.splitlines())
        return result, labelled, calls

    return go


@pytest.fixture
def runner(tmp_path):
    """A persistent self-hosted runner: its home already has the `claude` the action left."""
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "npm").write_text(FAKE_NPM)
    (fake / "npm").chmod(0o755)
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    (home / ".local/bin/claude").write_text("#!/bin/sh\necho stale\n")
    (home / ".local/bin/claude").chmod(0o755)
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    env = {
        "PATH": f"{fake}:{home / '.local/bin'}:{os.environ['PATH']}",
        "HOME": str(home),
        "RUNNER_TEMP": str(temp),
        "GITHUB_PATH": str(tmp_path / "github_path"),
        "NPM_LOG": str(tmp_path / "npm.log"),
    }
    return tmp_path, env


@pytest.fixture
def descopes(tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_DESCOPES)
    (fake / "gh").chmod(0o755)
    files = {n: tmp_path / f"{n}.json" for n in ("comments", "threads", "statuses")}

    def go(threads, reviewed="2026-11-13T10:00:00Z", status=None, script="decided", readable=True):
        summary_comment = {
            "user": {"login": "claude[bot]"},
            "body": "## Review\n<!-- review-findings: important=1 nit=0 -->",
            "updated_at": reviewed,
        }
        files["comments"].write_text(json.dumps([summary_comment] if reviewed else []))
        page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": list(threads)}
        if readable:
            data = {"data": {"repository": {"pullRequest": {"reviewThreads": page}}}}
            files["threads"].write_text(json.dumps(data))
        else:
            files["threads"].unlink(missing_ok=True)
        state, description = status or ("success", "The Claude review is posted")
        files["statuses"].write_text(
            json.dumps([{"context": "claude-review", "state": state, "description": description}])
        )
        env = {
            "PATH": f"{fake}:{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "o/r",
            "FAKE_COMMENTS": str(files["comments"]),
            "FAKE_THREADS": str(files["threads"]),
            "FAKE_STATUSES": str(files["statuses"]),
            "FAKE_POSTED": str(tmp_path / "posted"),
            "FAKE_CALLS": str(tmp_path / "calls"),
        }
        args = ["7"] if script == "decided" else ["7", "abc1234"]
        result = run(["bash", str(REPO / f".sdlc/scripts/descopes-{script}.sh"), *args], env=env)
        posted = tmp_path / "posted"
        result.posted = posted.read_text() if posted.exists() else ""
        posted.unlink(missing_ok=True)
        return result

    return go


# --- a merge of the base that leaves the PR's diff unchanged keeps its review (#182) ----------
# PR #176: GitHub's Update branch merged main in, the diff was byte-for-byte the same, and the
# push still needed the review label and a second review.


@pytest.fixture
def base_merge(tmp_path):
    """A PR whose commit P was reviewed, after which main moved on (M)."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def git_(*args):
        return run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True
        ).stdout.strip()

    git_("init", "-q", "-b", "main")
    (repo / "app.py").write_text("a = 1\n")
    (repo / "other.py").write_text("b = 1\n")
    (repo / "notes.md").write_text("one\ntwo\nthree\n")
    git_("add", "-A")
    git_("commit", "-qm", "base")
    git_("checkout", "-qb", "pr")
    (repo / "app.py").write_text("a = 2\n")
    (repo / "notes.md").write_text("one\ntwo\nthe PR's line\nthree\n")
    git_("commit", "-qam", "P: the PR's change")
    reviewed = git_("rev-parse", "HEAD")
    git_("checkout", "-q", "main")
    (repo / "other.py").write_text("b = 2\n")
    git_("commit", "-qam", "M: main moves on")
    git_("update-ref", "refs/remotes/origin/main", "main")
    git_("checkout", "-q", "pr")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_REVIEW_CURRENT)
    (fake / "gh").chmod(0o755)
    state = tmp_path / "gh"
    state.mkdir()

    def go(head, base_ref="main", carry=None):
        # As GitHub lists a PR's commits: those on its head that aren't on the base.
        commits = git_("rev-list", "--reverse", f"origin/main..{head}").split()
        (state / "commits").write_text("".join(f"{c}\n" for c in commits))
        for f in state.glob("status-*"):
            f.unlink()
        (state / f"status-{reviewed}").write_text(
            json.dumps([{"context": "claude-review", "state": "success"}])
        )
        (state / "posted").unlink(missing_ok=True)
        env = {"PATH": f"{fake}:{os.environ['PATH']}", "D": str(state), "GITHUB_REPOSITORY": "o/r"}
        if base_ref is not None:
            env["BASE_REF"] = base_ref
        if carry is not None:
            env["SDLC_REVIEW_CARRY_FORWARD"] = carry
        result = run(
            ["bash", str(REPO / ".sdlc/scripts/review-current.sh"), "7", head], cwd=repo, env=env
        )
        posted = state / "posted"
        return result, posted.read_text() if posted.exists() else ""

    return git_, reviewed, go
