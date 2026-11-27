import json
import os
import re

import pytest

from conftest import REPO, run

from .helpers import synced, thread

# --- the PR title says which gate artifact it changes (#46) ----------------------------------


@pytest.mark.parametrize(
    ("title", "files", "ok"),
    [
        ("spec(0007): add R33", ["changes/0007-x/spec.md"], True),
        ("docs(0007): add sketches", ["changes/0007-x/spec.md", "changes/0007-x/s.png"], False),
        ("feat(0007): build it", ["changes/0007-x/plan.md", "src/a.py"], False),
        ("plan(0007): amend", ["changes/0007-x/spec.md", "changes/0007-x/plan.md"], True),
        ("spec(0007): amend", ["changes/0007-x/spec.md", "changes/0007-x/plan.md"], True),
        ("intent: new idea", ["changes/0009-y/intent.md"], True),
        ("bug(0010): export hangs", ["changes/0010-z/bug.md"], True),
        ("feat(0007): build it", ["changes/0007-x/build.md", "src/a.py"], True),  # not a gate
        ("docs: readme", ["readme.md", "docs/changes/spec.md"], True),  # not a change folder
        ("chore: sync", [], True),
        ("Update spec", ["changes/0007-x/spec.md"], False),  # not conventional at all
    ],
)
def test_pr_title_type_matches_the_gate_artifacts_it_changes(title, files, ok):
    result = run(
        ["bash", ".sdlc/scripts/check-pr-title.sh", title], input="".join(f"{f}\n" for f in files)
    )
    assert (result.returncode == 0) == ok, result.stdout
    assert ("::error::" in result.stdout) == (not ok)


def test_pr_title_error_names_the_types_to_use():
    result = run(
        ["bash", ".sdlc/scripts/check-pr-title.sh", "docs: tidy"],
        input="changes/0007-x/spec.md\nchanges/0007-x/plan.md\n",
    )
    assert (
        "gate artifact (plan.md, spec.md)" in result.stdout and "use plan or spec" in result.stdout
    )


def test_project_review_rules_live_outside_review_md():
    # spellbound3d added a pass to .sdlc/REVIEW.md, which then clashed with every framework update.
    review = (REPO / ".sdlc/REVIEW.md").read_text()
    passes = re.findall(r"^(\d)\. \*\*([^*]+):\*\*", review, re.M)
    assert [n for n, _ in passes] == ["1", "2", "3", "4", "5", "6"]
    assert passes[-1][1] == "Project rules", "last, so the earlier passes keep their numbers"
    assert "`docs/review-rules.md`" in review
    sync = (REPO / ".sdlc/scripts/sync-sdlc.sh").read_text()
    assert "review-rules" not in sync, "the project's file is never synced"
    assert synced(".sdlc/templates/review-rules.md"), (
        "the starting point arrives with the templates"
    )
    template = (REPO / ".sdlc/templates/review-rules.md").read_text()
    assert "Copy this file to docs/review-rules.md" in template


def test_the_roadmap_is_the_projects_and_its_format_is_synced():
    # #81: the framework ships the format and the templates; docs/roadmap.md is the project's.
    sync = (REPO / ".sdlc/scripts/sync-sdlc.sh").read_text()
    assert synced(".sdlc/docs/roadmap-format.md")
    assert '"docs/roadmap.md:' not in sync and "docs/roadmap/adjustments" not in sync
    for name in ("roadmap.md", "roadmap-adjustment.md"):
        assert "docs/roadmap" in (REPO / ".sdlc" / "templates" / name).read_text(), name
    intent = (REPO / ".sdlc/templates/intent.md").read_text()
    assert "Milestone: M<n>" in intent and "Adjustment: NNNN-<slug>" in intent
    # Only in a comment: a repo with no roadmap gets no Milestone: line in its intents.
    assert "\nMilestone:" not in re.sub(r"<!--.*?-->", "", intent, flags=re.S)


def test_next_and_the_upgrade_steps_know_the_roadmap():
    # #81: /sdlc-next reads the roadmap from main; v0.10.0's upgrade covers both consumers' shapes.
    nxt = (REPO / ".sdlc/skills/next/SKILL.md").read_text()
    assert "git show origin/main:docs/roadmap.md" in nxt
    steps = (REPO / "docs/release-notes/v0.10.0.md").read_text().split("## Upgrade steps", 1)[1]
    for case in ("own roadmap check already", "in another shape", "No roadmap"):
        assert case in steps, case
    assert re.findall(r"^(\d)\. ", steps, re.M) == ["1", "2", "3", "4", "5", "6", "7"]


# A gh that serves $FAKE_COMMENTS for the comments call, applying --jq with the real jq.
FAKE_GH_COMMENTS = r"""#!/usr/bin/env bash
[[ "$1" == api ]] || exit 1
echo "$2" >> "$FAKE_CALLS"
[[ -e "$FAKE_COMMENTS" ]] || { echo "gh: HTTP 502" >&2; exit 1; }
jqx=.
while (($#)); do [[ "$1" == --jq ]] && jqx="$2"; shift; done
jq -r "$jqx" "$FAKE_COMMENTS"
"""

SINCE = "2026-11-12T09:00:00Z"


@pytest.fixture
def review_posted(tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_COMMENTS)
    (fake / "gh").chmod(0o755)
    comments = tmp_path / "comments.json"

    def go(found, *args, bot=None):
        if found is None:
            comments.unlink(missing_ok=True)
        else:
            comments.write_text(json.dumps(found))
        env = {
            "PATH": f"{fake}:{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "o/r",
            "FAKE_COMMENTS": str(comments),
            "FAKE_CALLS": str(tmp_path / "calls"),
        }
        if bot:
            env["REVIEW_BOT"] = bot
        return run(
            ["bash", str(REPO / ".sdlc/scripts/review-posted.sh"), *(args or ("7", SINCE))], env=env
        )

    return go


def comment(login="claude[bot]", updated="2026-11-12T09:00:30Z", url="https://x/c/1"):
    return {"user": {"login": login}, "updated_at": updated, "html_url": url}


def test_review_posted_finds_a_summary_posted_or_edited_during_the_job(review_posted, tmp_path):
    result = review_posted([comment(updated="2026-11-12T08:00:00Z", url="old"), comment()])
    assert result.returncode == 0 and "https://x/c/1" in result.stdout
    assert f"repos/o/r/issues/7/comments?since={SINCE}" in (tmp_path / "calls").read_text()
    assert review_posted([comment(updated=SINCE)]).returncode == 0, "at the start counts"


@pytest.mark.parametrize(
    "found",
    [
        [],
        [comment(updated="2026-11-12T08:59:59Z")],  # an older summary, not edited this time
        [comment(login="github-actions[bot]")],  # the "AI review skipped" note
        [comment(login="someone")],
    ],
)
def test_review_posted_fails_with_no_new_summary_from_the_reviewer(review_posted, found):
    # PR #129: the action ended green after refused tool calls, having posted nothing.
    result = review_posted(found)
    assert result.returncode == 1 and "posted no comment on PR #7" in result.stderr


def test_review_posted_reads_another_reviewer_login(review_posted):
    assert (
        review_posted([comment(login="my-reviewer[bot]")], bot="my-reviewer[bot]").returncode == 0
    )


def test_review_posted_fails_when_it_cannot_read_or_is_misused(review_posted):
    assert review_posted(None).returncode == 3
    assert review_posted([], "7", "yesterday").returncode == 2
    assert review_posted([], "x", SINCE).returncode == 2


def test_the_gate_needs_the_summary_not_just_a_green_action():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    steps = workflow.split("\n      - ")
    step = {s.split("\n", 1)[0].removeprefix("name: "): s for s in steps}
    assert "id: start" in step["Mark the review as running"]
    assert 'echo "since=$since" >> "$GITHUB_OUTPUT"' in step["Mark the review as running"]
    done = step["Mark the review as done"]
    assert "SINCE: ${{ steps.start.outputs.since }}" in done
    assert '.sdlc/scripts/review-posted.sh "$PR" "$SINCE"' in done
    # Skipped (a Dependabot PR) is checked first: the action posts nothing then.
    assert done.index('"$WHY" == dependabot') < done.index("review-posted.sh")
    assert "-f state=failure" in done and "posted no summary" in done
    failed = step["Mark the review as failed"]
    assert "if: failure() && steps.done.outputs.reported != 'true'" in failed
    assert synced(".sdlc/scripts/review-posted.sh")


# A gh serving the PR's comments and its review threads (GraphQL), applying --jq with real jq.
FAKE_GH_FINDINGS = r"""#!/usr/bin/env bash
[[ "$1" == api ]] || exit 1
echo "$*" >> "$FAKE_CALLS"
case "$2" in
  graphql) file="$FAKE_THREADS" ;;
  repos/o/r/issues/7/comments) file="$FAKE_COMMENTS" ;;
  *) echo "unexpected: $2" >&2; exit 1 ;;
esac
[[ -e "$file" ]] || { echo "gh: HTTP 502" >&2; exit 1; }
jqx=.
while (($#)); do [[ "$1" == --jq ]] && jqx="$2"; shift; done
jq -r "$jqx" "$file"
"""

# spellbound3d#124's summary (shortened): three Important findings, and no thread for any (#130).
SB124_SUMMARY = (
    "## Review of PR #124\n\n**Findings: 3 Important, 0 Nit.** There were no earlier findings.\n"
    "1. Important: no change folder.\n2. Important: no acceptance criteria.\n"
    "3. Important: the unapproved descopes above.\n"
)


def summary(important=None, nit=0, text="## Review\n"):
    if important is None:
        return text
    return f"{text}\n<!-- review-findings: important={important} nit={nit} -->\n"


@pytest.fixture
def review_findings(tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "gh").write_text(FAKE_GH_FINDINGS)
    (fake / "gh").chmod(0o755)
    comments, threads = tmp_path / "comments.json", tmp_path / "threads.json"

    def go(bodies, found=(), logins=None, read_threads=True):
        logins = logins or ["claude[bot]"] * len(bodies)
        comments.write_text(
            json.dumps(
                [{"user": {"login": u}, "body": b} for u, b in zip(logins, bodies, strict=True)]
            )
        )
        if read_threads:
            page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": list(found)}
            data = {"data": {"repository": {"pullRequest": {"reviewThreads": page}}}}
            threads.write_text(json.dumps(data))
        else:
            threads.unlink(missing_ok=True)
        env = {
            "PATH": f"{fake}:{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "o/r",
            "FAKE_COMMENTS": str(comments),
            "FAKE_THREADS": str(threads),
            "FAKE_CALLS": str(tmp_path / "calls"),
        }
        return run(["bash", str(REPO / ".sdlc/scripts/review-findings.sh"), "7"], env=env)

    return go


def test_review_findings_fails_spellbound3d_124(review_findings):
    # No count line: it fails closed.
    result = review_findings([SB124_SUMMARY])
    assert result.returncode == 1 and "no findings count line" in result.stdout
    # With the count line, three findings against no threads.
    result = review_findings([summary(3, text=SB124_SUMMARY)])
    assert result.returncode == 1
    assert "lists 3 Important finding(s) but 0 open Important thread(s)" in result.stdout
    assert len(result.stdout.strip()) <= 140, "fits a commit status description"


def test_review_findings_passes_when_each_finding_has_an_open_thread(review_findings, tmp_path):
    found = [
        thread("**Important:** no change folder."),
        thread("**Important (product owner decides):** no criteria.", login="claude[bot]"),
        thread("**Important:** fixed earlier.", resolved=True),  # resolved: not counted
        thread("**Nit:** naming."),  # not an Important finding
        thread("**Important:** a person's own note.", login="kieron"),  # not the reviewer's
    ]
    result = review_findings([summary(2)], found)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 open Important finding(s)" in result.stdout
    calls = (tmp_path / "calls").read_text()
    assert "graphql --paginate" in calls and "owner=o" in calls and "name=r" in calls


def test_review_findings_fails_263_whose_nits_were_lost(review_findings):
    """#266: the summary counted two nits and wrote down neither."""
    result = review_findings([summary(0, 2, "Review: 0 Important, 2 Nit (see above)\n")])
    assert result.returncode == 1
    assert "counts 2 Nit(s) but writes down 0" in result.stdout
    assert len(result.stdout.strip()) <= 140, "fits a commit status description"


@pytest.mark.parametrize(
    "text, found, passes",
    [
        ("- **Nit:** a.\n- **Nit:** b.\n", [], True),
        ("- Nit (engineer decides): in `x`, a.\n2. **Nit (engineer decides):** b.\n", [], True),
        ("- **Nit:** a.\n", [thread("**Nit:** b.")], True),
        ("", [thread("**Nit:** a."), thread("**Nit:** b.")], True),
        ("- **Nit:** a.\n", [], False),  # one of two lost
        ("**Nit: 2.**\n- Nit: 2\n", [], False),  # counts aren't findings
        ("- Nitpicking: none\n- Nits: see above\n", [], False),
        ("- **Nit:** a.\n", [thread("**Nit:** old.", resolved=True)], False),
        ("- **Nit:** a.\n", [thread("**Nit:** theirs.", login="kieron")], False),
    ],
)
def test_review_findings_needs_every_counted_nit_written_down(review_findings, text, found, passes):
    result = review_findings([summary(0, 2, text)], found)
    assert (result.returncode == 0) is passes, result.stdout + result.stderr


def test_review_findings_reads_nits_from_the_newest_summary_only(review_findings):
    old = summary(0, 1, "- **Nit:** a.\n")
    assert review_findings([old, summary(0, 1, "see above\n")]).returncode == 1
    assert review_findings([summary(0, 1, "see above\n"), old]).returncode == 0


def test_review_findings_takes_a_count_line_without_nits(review_findings):
    assert review_findings(["x\n<!-- review-findings: important=0 -->"]).returncode == 0


def test_review_findings_passes_a_clean_review(review_findings):
    assert review_findings([summary(0)]).returncode == 0


@pytest.mark.parametrize(
    "count, found",
    [
        (0, [thread()]),  # a thread the count leaves out
        (2, [thread()]),  # a finding with no thread
        (1, [thread(resolved=True)]),  # its thread was resolved, the finding still listed
    ],
)
def test_review_findings_fails_when_the_count_and_threads_differ(review_findings, count, found):
    assert review_findings([summary(count)], found).returncode == 1


def test_review_findings_reads_the_latest_summary_from_the_reviewer(review_findings):
    bodies = [summary(2), summary(0), summary(5)]
    logins = ["claude[bot]", "claude[bot]", "someone"]  # someone else's count line is ignored
    assert review_findings(bodies, logins=logins).returncode == 0


def test_review_findings_fails_when_it_cannot_read(review_findings):
    assert review_findings([summary(0)], read_threads=False).returncode == 3


def test_the_gate_checks_what_the_review_found():
    workflow = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    steps = workflow.split("\n      - ")
    step = {s.split("\n", 1)[0].removeprefix("name: "): s for s in steps}
    done = step["Mark the review as done"]
    # In order: the Dependabot exception, then a summary, then a thread per finding.
    order = ['"$WHY" == dependabot', "review-posted.sh", '.sdlc/scripts/review-findings.sh "$PR"']
    assert [done.index(x) for x in order] == sorted(done.index(x) for x in order)
    assert done.count('echo "reported=true"') == 3 and done.count("exit 1") == 3
    action = step["Review"]
    assert "classify_inline_comments: false" in action
    assert (
        "pulls/${{ github.event.pull_request.number }}/comments -f subject_type=file:*)" in action
    )
    assert "<!-- review-findings: important=<N> nit=<M> -->" in action
    review = (REPO / ".sdlc/REVIEW.md").read_text()
    assert "## Posting findings" in review
    assert "<!-- review-findings: important=<N> nit=<M> -->" in review
    assert "-f subject_type=file -f path=<file>" in review and "`**Important`" in review
    assert synced(".sdlc/scripts/review-findings.sh")


def test_v0_11_0_upgrade_steps_match_what_the_sync_prints():
    notes = (REPO / "docs/release-notes/v0.11.0.md").read_text()
    steps = notes.split("## Upgrade steps", 1)[1]
    sync = (REPO / ".sdlc/scripts/sync-sdlc.sh").read_text()
    for message in ("still use the old paths", "kept your local changes", "include .sdlc/sdlc.mk"):
        assert message in steps and message in sync, message
    assert "your security policy is the project's own" in sync
    assert ".sdlc-local/skills/security-policy/SKILL.md" in steps
    assert (REPO / ".sdlc/docs/overrides.md").is_file() and ".sdlc/docs/overrides.md" in notes
    assert re.findall(r"^(\d)\. ", steps, re.M) == [str(n) for n in range(1, 9)]
