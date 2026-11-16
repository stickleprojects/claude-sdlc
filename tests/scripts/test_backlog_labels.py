import json
import os
import stat
import subprocess

import pytest

from conftest import REPO, run

# --- the backlog's priority, impact and effort labels (#204) ---------------------------------

SCRIPT = REPO / "scripts/backlog-labels.sh"
SKILL = REPO / ".claude/skills/backlog/SKILL.md"

# A gh that keeps the repo's labels, each issue's labels and the comments in files under
# $FAKE_GH_DIR, so a test checks what ends up on an issue, not which calls were made.
FAKE_GH = r"""#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
from urllib.parse import unquote

d = Path(os.environ["FAKE_GH_DIR"])
args = sys.argv[1:]
with (d / "calls").open("a") as f:
    f.write(" ".join(args) + "\n")
assert args[0] == "api", args
args = args[1:]
method, fields, jq, path = "GET", [], None, None
i = 0
while i < len(args):
    a = args[i]
    if a == "-X":
        method = args[i + 1]; i += 2; continue
    if a == "-f":
        fields.append(args[i + 1]); i += 2; continue
    if a == "--jq":
        jq = args[i + 1]; i += 2; continue
    if a == "--paginate":
        i += 1; continue
    path = a; i += 1
if (d / "fail").exists() and (d / "fail").read_text().strip() in path:
    sys.exit(1)
parts = path.split("?")[0].split("/")[3:]  # after repos/<owner>/<repo>
labels = d / "labels"
known = labels.read_text().splitlines() if labels.exists() else []

def issue_file(n):
    return d / f"issue-{n}"

if parts == ["labels"] and fields:  # create
    name = next(f.split("=", 1)[1] for f in fields if f.startswith("name="))
    if name in known:
        print("already_exists", file=sys.stderr); sys.exit(1)
    labels.write_text("\n".join(known + [name]) + "\n")
elif parts[0] == "labels" and method == "PATCH":
    sys.exit(0 if unquote(parts[1]) in known else 1)
elif parts == ["issues"]:
    out = subprocess.run(["jq", "-r", jq], input=(d / "issues.json").read_text(),
                         text=True, capture_output=True)
    print(out.stdout, end="")
elif len(parts) == 2 and parts[0] == "issues":
    f = issue_file(parts[1])
    if not f.exists():
        print("gh: Not Found (HTTP 404)", file=sys.stderr); sys.exit(1)
    print(f.read_text(), end="")
elif len(parts) == 3 and parts[2] == "labels":
    f = issue_file(parts[1])
    have = f.read_text().splitlines()
    add = [x.split("=", 1)[1] for x in fields if x.startswith("labels[]=")]
    f.write_text("".join(l + "\n" for l in have + [a for a in add if a not in have]))
elif len(parts) == 4 and parts[2] == "labels" and method == "DELETE":
    f = issue_file(parts[1])
    name = unquote(parts[3])
    f.write_text("".join(l + "\n" for l in f.read_text().splitlines() if l != name))
elif len(parts) == 3 and parts[2] == "comments":
    body = next(x.split("=", 1)[1] for x in fields if x.startswith("body="))
    with (d / "comments").open("a") as c:
        c.write(f"#{parts[1]}: {body}\n")
else:
    print(f"fake gh: unhandled {method} {path}", file=sys.stderr); sys.exit(3)
"""


@pytest.fixture
def gh(tmp_path):
    """A fake gh on PATH, with issues #1 (no labels) and #2 (P2, impact low, effort S, bug)."""
    bin_dir, state = tmp_path / "bin", tmp_path / "gh"
    bin_dir.mkdir()
    state.mkdir()
    fake = bin_dir / "gh"
    fake.write_text(FAKE_GH)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    (state / "issue-1").write_text("")
    (state / "issue-2").write_text("priority: P2\nimpact: low\neffort: S\nbug\n")
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_GH_DIR": str(state),
        "BACKLOG_REPO": "o/r",
        "SDLC_AGENT_IDENTITY": "",
    }

    def call(*args, **extra):
        return run(["bash", str(SCRIPT), *args], env={**env, **extra})

    call.state = state
    call.labels = lambda n: (state / f"issue-{n}").read_text().splitlines()
    call.comments = lambda: (
        (state / "comments").read_text() if (state / "comments").exists() else ""
    )
    return call


def test_labels_creates_the_nine_and_updates_them_on_a_second_run(gh):
    first = gh("labels")
    assert first.returncode == 0, first.stderr
    assert first.stdout.count("created: ") == 9
    assert sorted((gh.state / "labels").read_text().splitlines()) == sorted(
        [f"priority: P{n}" for n in (1, 2, 3)]
        + [f"impact: {i}" for i in ("high", "medium", "low")]
        + [f"effort: {e}" for e in "SML"]
    )
    again = gh("labels")
    assert again.returncode == 0 and again.stdout.count("updated: ") == 9


def test_labels_fails_when_a_label_cant_be_made(gh):
    (gh.state / "fail").write_text("repos/o/r/labels")
    result = gh("labels")
    assert result.returncode == 1
    assert "couldn't create or update the label 'priority: P1'" in result.stderr


def test_list_shows_each_open_issue_and_leaves_out_pull_requests(gh):
    issues = [
        {"number": 1, "title": "No labels", "labels": []},
        {
            "number": 2,
            "title": "Labelled",
            "labels": [
                {"name": "priority: P2"},
                {"name": "impact: low"},
                {"name": "effort: S"},
                {"name": "bug"},
            ],
        },
        {
            "number": 3,
            "title": "Two priorities",
            "labels": [{"name": "priority: P1"}, {"name": "priority: P3"}],
        },
        {"number": 4, "title": "A PR", "labels": [], "pull_request": {}},
    ]
    (gh.state / "issues.json").write_text(json.dumps(issues))
    result = gh("list")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "#1\t-\t-\t-\tNo labels",
        "#2\tP2\tlow\tS\tLabelled",
        "#3\tP1+P3\t-\t-\tTwo priorities",
    ]


def test_set_gives_a_first_priority_without_a_comment(gh):
    result = gh("set", "1", "P1", "high", "M")
    assert result.returncode == 0, result.stderr
    assert sorted(gh.labels(1)) == ["effort: M", "impact: high", "priority: P1"]
    assert result.stdout == "#1: priority P1 (new), impact high, effort M\n"
    assert gh.comments() == ""


def test_set_replaces_each_category_and_keeps_other_labels(gh):
    result = gh("set", "2", "P2", "high", "L")
    assert result.returncode == 0, result.stderr
    assert sorted(gh.labels(2)) == ["bug", "effort: L", "impact: high", "priority: P2"]
    assert result.stdout == "#2: priority P2 (unchanged), impact high, effort L\n"
    assert gh.comments() == "", "an unchanged priority posts nothing"


def test_a_changed_priority_needs_a_reason(gh):
    result = gh("set", "2", "P1", "low", "S")
    assert result.returncode == 2
    assert "#2's priority changes from P2 to P1: give the reason" in result.stderr
    assert "priority: P2" in gh.labels(2), "nothing changed"


def test_a_changed_priority_is_commented_with_its_reason(gh):
    result = gh("set", "2", "P1", "high", "S", "It blocks the release.")
    assert result.returncode == 0, result.stderr
    assert "priority: P1" in gh.labels(2) and "priority: P2" not in gh.labels(2)
    assert "#2: priority P2 -> P1 (commented)" in result.stdout
    assert gh.comments() == (
        "#2: Priority: P2 → P1. It blocks the release. (posted from Claude Code)\n"
    )


def test_the_comment_is_signed_as_the_agent_under_its_identity(gh):
    gh("set", "2", "P3", "low", "S", "Nobody's hit it.", SDLC_AGENT_IDENTITY="agent")
    assert gh.comments().endswith("Nobody's hit it. — Claude\n")


def test_two_priorities_are_cleaned_up_to_one(gh):
    (gh.state / "issue-3").write_text("priority: P1\npriority: P3\n")
    result = gh("set", "3", "P1", "low", "S", "Settled on P1.")
    assert result.returncode == 0, result.stderr
    assert sorted(gh.labels(3)) == ["effort: S", "impact: low", "priority: P1"]
    assert "P1+P3 -> P1" in result.stdout


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["x", "P1", "high", "S"], "'x' isn't an issue number"),
        (["1", "P4", "high", "S"], "priority 'P4' isn't P1, P2 or P3"),
        (["1", "P1", "huge", "S"], "impact 'huge' isn't high, medium or low"),
        (["1", "P1", "high", "XL"], "effort 'XL' isn't S, M or L"),
    ],
)
def test_set_refuses_a_value_it_doesnt_know(gh, args, message):
    result = gh("set", *args)
    assert result.returncode == 2
    assert message in result.stderr
    assert not (gh.state / "calls").exists(), "nothing is sent"


def test_set_fails_on_an_issue_it_cant_read(gh):
    result = gh("set", "9", "P1", "high", "S")
    assert result.returncode == 1
    assert "couldn't read issue #9" in result.stderr


def test_a_failed_label_change_fails_and_says_so(gh):
    (gh.state / "fail").write_text("issues/2/labels")
    result = gh("set", "2", "P1", "high", "S", "Because.")
    assert result.returncode == 1
    assert "couldn't remove 'priority: P2' from #2" in result.stderr
    assert gh.comments() == ""


@pytest.mark.parametrize("args", [[], ["nope"], ["set", "1"]])
def test_usage_on_a_wrong_call(gh, args):
    result = gh(*args)
    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_the_backlog_skill_lives_in_this_repos_own_skills_and_runs_the_script():
    """Framework-only (#204): the sync installs skills only from .sdlc/claude/skills, so a skill
    in this repo's .claude/skills never reaches a consumer (test_scenario checks the result)."""
    assert SKILL.is_file()
    assert not (REPO / ".sdlc/claude/skills/backlog").exists()
    assert (
        '".sdlc/claude/skills:.claude/skills"' in (REPO / ".sdlc/scripts/sync-sdlc.sh").read_text()
    )
    assert "scripts/backlog-labels.sh" in SKILL.read_text()
    ls = subprocess.run(
        ["git", "ls-files", "-s", "scripts/backlog-labels.sh"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert ls.stdout.startswith("100755"), "executable, or the skill's call fails on Linux"
