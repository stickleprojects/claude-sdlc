import json

import pytest

from conftest import REPO, run

from .helpers import synced

# --- a review that posts nothing says why, and runs once more (#157) -------------------------


def execution_output(result, denials=()):
    """claude-code-action's execution output: the session's messages, the result last."""
    return [
        {"type": "system", "subtype": "init"},
        {
            "type": "result",
            "subtype": result,
            "num_turns": 10,
            "permission_denials": list(denials),
        },
    ]


def denials_of(tmp_path, content, label=None):
    out = tmp_path / "claude-execution-output.json"
    if content is not None:
        out.write_text(content if isinstance(content, str) else json.dumps(content))
    args = ["bash", str(REPO / ".sdlc/scripts/review-denials.sh"), str(out)]
    return run(args + ([label] if label else []))


def test_review_denials_lists_each_refused_call(tmp_path):
    refused = [
        {"tool_name": "Bash", "tool_input": {"command": "gh api repos/o/r/issues/7/comments"}},
        {"tool_name": "Write", "tool_input": {"file_path": "/tmp/x", "content": "y" * 900}},
    ]
    result = denials_of(tmp_path, execution_output("success", refused), "the first review")
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert lines[0] == "the first review: success after 10 turn(s), 2 refused tool call(s)"
    assert lines[1] == "  refused: Bash: gh api repos/o/r/issues/7/comments"
    assert lines[2].startswith("  refused: Write: {") and len(lines[2]) < 340  # input cut short


def call(name, tool_input):
    return {"type": "tool_use", "name": name, "input": tool_input}


def test_review_denials_lists_each_tool_call_with_calls(tmp_path):
    session = execution_output("success")
    session[1:1] = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "No findings."}]}},
        {
            "type": "assistant",
            "message": {
                "content": [
                    call("Read", {"file_path": ".review-rules.md"}),
                    call("Bash", {"command": "gh pr diff 7"}),
                    call("Bash", {"command": 'gh pr comment 7 --body "one\n\ntwo"'}),
                ]
            },
        },
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "SECRET"}]}},
        {"type": "assistant", "message": {"content": [call("Write", {"content": "y" * 900})]}},
    ]
    out = tmp_path / "claude-execution-output.json"
    out.write_text(json.dumps(session))
    script = str(REPO / ".sdlc/scripts/review-denials.sh")
    result = run(["bash", script, "--calls", str(out), "the review"])
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert lines[0] == "the review: success after 10 turn(s), 0 refused tool call(s)"
    assert lines[1] == '  called: Read: {"file_path":".review-rules.md"}'
    assert lines[2] == "  called: Bash: gh pr diff 7"
    assert lines[3] == '  called: Bash: gh pr comment 7 --body "one two"'  # one line each
    assert lines[4].startswith("  called: Write: {") and len(lines[4]) < 240  # input cut short
    assert len(lines) == 5
    # Only the calls: never the model's text or what the tools returned.
    assert "No findings" not in result.stdout and "SECRET" not in result.stdout
    # Without --calls, the calls aren't listed.
    assert "called:" not in run(["bash", script, str(out)]).stdout


def test_review_denials_reads_a_single_result_object(tmp_path):
    result = denials_of(tmp_path, execution_output("error_max_turns")[1])
    assert "the review: error_max_turns after 10 turn(s), 0 refused" in result.stdout


@pytest.mark.parametrize(
    ("content", "says"),
    [
        (None, "no execution output for the review"),
        ("", "no execution output"),
        ("not json", "isn't the JSON it should be"),
        ([{"type": "system"}], "no result message"),
    ],
    ids=["missing", "empty", "not json", "no result"],
)
def test_review_denials_never_fails(tmp_path, content, says):
    result = denials_of(tmp_path, content)
    assert result.returncode == 0 and says in result.stdout


def test_the_review_runs_once_more_when_it_posts_nothing():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    steps = workflow.split("\n      - ")
    step = {s.split("\n", 1)[0].removeprefix("name: "): s for s in steps}
    first, retry, posted = (
        step["Review"],
        step["Review once more"],
        step["Check the review posted its summary"],
    )

    # The retry is the same review: everything from `with:` on is identical.
    def inputs(text):  # from `with:` on, without the comments that lead into the next step
        lines = text.split("        with:\n", 1)[1].rstrip("\n").splitlines()
        while lines and lines[-1].lstrip().startswith("#"):
            lines.pop()
        return lines

    assert inputs(retry) == inputs(first) and len(inputs(first)) > 20
    assert (
        "uses: anthropics/claude-code-action@v1" in first
        and "uses: anthropics/claude-code-action@v1" in retry
    )
    assert "if: steps.posted.outputs.posted == 'false'" in retry
    assert "if: steps.workflow_change.outputs.skipped != 'true'" in posted
    assert '.sdlc/scripts/review-posted.sh "$PR" "$SINCE"' in posted
    assert "review-denials.sh" in posted and "review-attempt-1.json" in posted
    order = [
        "Review",
        "Check the review posted its summary",
        "Review once more",
        "Mark the review as done",
    ]
    names = list(step)
    assert [names.index(n) for n in order] == sorted(names.index(n) for n in order)
    keep = step["Keep the review's output"]
    assert "if: always() && (failure() || steps.posted.outputs.posted == 'false')" in keep
    assert "uses: actions/upload-artifact@v4" in keep and "retention-days: 7" in keep
    assert "${{ runner.temp }}/review-attempt-1.json" in keep
    assert "if: failure()" in step["Show why the review stopped"]
    calls = step["List the review's tool calls"]
    assert "if: always() && steps.workflow_change.outputs.skipped != 'true'" in calls
    assert '--calls "$RUNNER_TEMP/review-attempt-1.json" "the first review"' in calls
    assert '--calls "$RUNNER_TEMP/claude-execution-output.json" "the second review"' in calls
    assert '--calls "$RUNNER_TEMP/claude-execution-output.json" "the review"' in calls
    assert names.index("Review once more") < names.index("List the review's tool calls")
    assert synced(".sdlc/scripts/review-denials.sh")
