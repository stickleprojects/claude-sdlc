"""ci-change-thread.sh: the review job asks a person to approve a CI change (ADR 0001, #293)."""

import json
import os

import pytest

from conftest import REPO, commit, git, init_repo, run

from .helpers import synced

SCRIPT = REPO / ".sdlc/scripts/ci-change-thread.sh"

FAKE_GH = r"""#!/usr/bin/env bash
# PR #7's review comments from $D/comments.json; a POST is logged, and fails for paths in $D/refuse.
echo "$*" >> "$D/calls"
args=("$@") jqf="" path="" body=""
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[i]}" in
    --jq) jqf="${args[i+1]}" ;;
    -f) case "${args[i+1]}" in
          path=*) path="${args[i+1]#path=}" ;;
          body=*) body="${args[i+1]#body=}" ;;
        esac ;;
  esac
done
[[ "$2" == repos/o/r/pulls/7/comments ]] || { echo "unexpected: $2" >&2; exit 1; }
if [[ -z "$path" ]]; then
  [[ -e "$D/unreadable" ]] && exit 1
  jq -r "$jqf" "$D/comments.json"
  exit
fi
grep -qxF "$path" "$D/refuse" 2>/dev/null && exit 1
printf '%s' "$body" > "$D/posted-body"
echo "$path" >> "$D/posted-on"
"""


@pytest.fixture
def thread(tmp_path):
    repo = init_repo(tmp_path / "repo")
    commit(repo, "base", {"src/app.py": "v1\n", ".github/workflows/ci.yml": "v1\n"})
    git(repo, "checkout", "-q", "-b", "pr")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH)
    (fake / "gh").chmod(0o755)
    state = tmp_path / "gh"
    state.mkdir()

    def go(comments=(), refuse=(), unreadable=False):
        (state / "comments.json").write_text(json.dumps(list(comments)))
        (state / "refuse").write_text("".join(f"{p}\n" for p in refuse))
        for name in ("calls", "posted-body", "posted-on", "unreadable"):
            (state / name).unlink(missing_ok=True)
        if unreadable:
            (state / "unreadable").touch()
        head = git(repo, "rev-parse", "HEAD")
        env = {"PATH": f"{fake}:{os.environ['PATH']}", "D": str(state), "GITHUB_REPOSITORY": "o/r"}
        result = run(["bash", str(SCRIPT), "7", "main", head], cwd=repo, env=env)
        read = lambda n: (state / n).read_text() if (state / n).exists() else ""  # noqa: E731
        return result, read("posted-body"), read("posted-on").split()

    return repo, go


def test_no_ci_change_posts_nothing(thread):
    repo, go = thread
    commit(repo, "code", {"src/app.py": "v2\n", "Makefile": "x\n"})
    result, body, _ = go()
    assert result.returncode == 0 and body == "" and "no file on the approval list" in result.stdout


def test_a_ci_change_gets_one_thread_listing_its_files(thread):
    repo, go = thread
    commit(repo, "ci", {".github/workflows/ci.yml": "v2\n", "uv.lock": "x\n", "src/app.py": "v2\n"})
    result, body, on = go()
    assert result.returncode == 0, result.stderr
    first = body.splitlines()[0]
    assert first == "**CI change: needs approval.** This PR changes 2 files that set CI's rules:"
    assert "- `.github/workflows/ci.yml`\n- `uv.lock`" in body and "src/app.py" not in body
    assert "Approved: <name>, <date>" in body and "<!-- ci-change: " in body
    assert on == [".github/workflows/ci.yml"]


def test_the_same_change_isnt_asked_twice_but_a_new_one_is(thread):
    repo, go = thread
    commit(repo, "ci", {".github/workflows/ci.yml": "v2\n"})
    _, body, _ = go()
    earlier = {"user": {"login": "github-actions[bot]"}, "body": body}
    result, again, _ = go([earlier])
    assert result.returncode == 0 and again == "" and "already has its thread" in result.stdout
    # Not the job's own: a person (or the reviewer) quoting the marker doesn't count.
    result, quoted, _ = go([{**earlier, "user": {"login": "claude[bot]"}}])
    assert quoted != ""
    commit(repo, "ci again", {".github/workflows/ci.yml": "v3\n"})
    result, new, _ = go([earlier])
    assert result.returncode == 0 and new != "" and new != body


def test_it_tries_the_next_file_and_fails_when_none_takes_it(thread):
    repo, go = thread
    commit(repo, "ci", {".github/a.yml": "x\n", ".github/b.yml": "y\n"})
    result, _, on = go(refuse=[".github/a.yml"])
    assert result.returncode == 0 and on == [".github/b.yml"]
    result, _, _ = go(refuse=[".github/a.yml", ".github/b.yml"])
    assert result.returncode == 1 and "couldn't post" in result.stderr


def test_it_fails_closed_when_the_comments_cant_be_read(thread):
    repo, go = thread
    commit(repo, "ci", {".github/workflows/ci.yml": "v2\n"})
    result, body, _ = go(unreadable=True)
    assert result.returncode == 1 and body == ""


def test_usage():
    assert run(["bash", str(SCRIPT), "7", "main"]).returncode == 2
    assert run(["bash", str(SCRIPT), "x", "main", "a" * 40]).returncode == 2


def test_its_thread_is_the_one_descopes_decided_reads():
    """The lead-in and the author are what descopes-decided.sh matches (PR #307)."""
    script = SCRIPT.read_text()
    decided = (REPO / ".sdlc/scripts/descopes-decided.sh").read_text()
    assert "CI change: needs approval" in script and "CI change: needs approval" in decided
    assert "CI_BOT:-github-actions[bot]" in script and "CI_BOT:-github-actions[bot]" in decided
    assert synced(".sdlc/scripts/ci-change-thread.sh")
    mode = run(["git", "ls-files", "-s", ".sdlc/scripts/ci-change-thread.sh"]).stdout
    assert mode.startswith("100755"), mode
