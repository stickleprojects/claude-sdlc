import json
import os

import pytest

from conftest import REPO, run

from .helpers import DESCOPE, FAKE_GH_DESCOPES, descope_thread, note

SCRIPT = REPO / ".sdlc/scripts/review-threads.sh"
WORKFLOW = REPO / ".github/workflows/sdlc-claude-review.yml"


@pytest.fixture
def threads(tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_DESCOPES)
    (fake / "gh").chmod(0o755)
    file = tmp_path / "threads.json"

    def go(nodes, readable=True):
        if readable:
            page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}
            file.write_text(
                json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": page}}}})
            )
        env = {
            "PATH": f"{fake}:{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "o/r",
            "FAKE_THREADS": str(file),
            "FAKE_CALLS": str(tmp_path / "calls"),
        }
        return run(["bash", str(SCRIPT), "7"], env=env)

    return go


def thread(*replies, resolved=False, outdated=False, first=DESCOPE):
    t = descope_thread(*replies, first=first)
    return {**t, "isResolved": resolved, "isOutdated": outdated, "path": "a.sh", "line": 3}


def test_each_thread_says_whether_it_is_resolved_and_who_wrote_what(threads):
    approved = note("kieron", "Approved: Kieron, 18 Nov", "2026-11-18T07:00:00Z")
    fixed = thread(resolved=True, first="**Important:** a bug, since fixed.")
    result = threads([thread(approved), fixed])
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert [t["resolved"] for t in out] == [False, True]
    assert out[0]["first"] == {"author": "claude", "bot": True, "body": DESCOPE}
    assert out[0]["replies"] == [
        {"author": "kieron", "bot": False, "body": "Approved: Kieron, 18 Nov"}
    ]
    assert out[1]["replies"] == [] and out[1]["path"] == "a.sh" and out[1]["line"] == 3


def test_no_threads_is_an_empty_list(threads):
    result = threads([])
    assert result.returncode == 0 and json.loads(result.stdout) == []


def test_long_bodies_are_cut(threads):
    out = json.loads(threads([thread(first="x" * 2000)]).stdout)
    assert len(out[0]["first"]["body"]) == 600


def test_unreadable_threads_fail_closed_with_nothing_on_stdout(threads):
    result = threads([], readable=False)
    assert result.returncode == 3 and result.stdout == ""
    assert "can't read PR #7's review threads" in result.stderr


def test_bad_arguments_print_usage():
    result = run(["bash", str(SCRIPT), "seven"])
    assert result.returncode == 2 and "Usage:" in result.stderr


def test_the_review_reads_thread_state_from_the_file_not_the_api():
    text = WORKFLOW.read_text()
    # Both review steps get the file, and neither is told to fetch threads itself.
    assert text.count(".review-threads.json") >= 4
    assert ".sdlc/scripts/review-threads.sh" in text
    assert "gh api graphql" not in text.split("--allowedTools")[1]
