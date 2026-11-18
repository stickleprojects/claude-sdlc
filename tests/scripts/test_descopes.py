import pytest

from conftest import REPO

from .helpers import DESCOPE, descope_thread, note, synced


def test_descopes_with_none_pass(descopes):
    other = descope_thread(first="**Important:** a plain bug.")
    result = descopes([other])
    assert result.returncode == 0 and result.stdout.strip() == "no descopes to approve"


def test_a_descope_waits_for_a_persons_reply(descopes):
    bot_reply = note(
        "stickle-claude", "Approved: Kieron, 2026-11-13", "2026-11-13T11:00:00Z", "Bot"
    )
    for thread in (descope_thread(), descope_thread(bot_reply)):
        result = descopes([thread])
        assert result.returncode == 1
        assert result.stdout.startswith("A descope waits for a person's decision: The export")
        assert "Reply Approved: <name>, <date>, or send it back" in result.stdout


def test_an_approved_reply_from_a_person_decides_it_and_names_them(descopes):
    approved = note(
        "kieron", "Fine for now.\n\nApproved: Kieron, 2026-11-13", "2026-11-13T11:00:00Z"
    )
    result = descopes([descope_thread(approved)])
    assert result.returncode == 0
    assert result.stdout.strip() == "descopes decided: approved by @kieron (2026-11-13)"


def test_a_descope_sent_back_waits_for_a_review_after_the_reply(descopes):
    back = note("po", "No, build the export.", "2026-11-13T11:00:00Z")
    waiting = descopes([descope_thread(back)], reviewed="2026-11-13T10:30:00Z")
    assert waiting.returncode == 1
    assert "@po sent a descope back (The export" in waiting.stdout
    assert "add the review label" in waiting.stdout
    reviewed = descopes([descope_thread(back)], reviewed="2026-11-13T12:00:00Z")
    assert reviewed.returncode == 0 and "sent back by @po, re-reviewed" in reviewed.stdout
    assert descopes([descope_thread(back)], reviewed=None).returncode == 1  # no review at all


def test_every_descope_must_be_decided(descopes):
    approved = note("kieron", "Approved: Kieron, 2026-11-13", "2026-11-13T11:00:00Z")
    result = descopes([descope_thread(approved), descope_thread()])
    assert result.returncode == 1
    others = descope_thread(first=DESCOPE, by="someone")  # not the reviewer's thread
    assert descopes([descope_thread(approved), others]).returncode == 0


def test_descopes_fail_closed_when_unreadable(descopes):
    assert descopes([], readable=False).returncode == 3


def test_descope_reasons_fit_a_status(descopes):
    long = descope_thread(first=DESCOPE + " " + "x" * 300)
    assert len(descopes([long]).stdout.strip()) <= 140


@pytest.mark.parametrize(
    ("status", "threads", "posted"),
    [
        (("success", "The Claude review is posted"), [descope_thread()], "state=failure"),
        (("failure", "A descope waits for a person's decision: x"), [], "state=success"),
        (
            ("failure", "A descope waits for a person's decision: x"),
            [descope_thread()],
            "state=failure",
        ),
        (("success", "The Claude review is posted"), [], ""),  # nothing to change
        (("pending", "The Claude review is running"), [descope_thread()], ""),  # the review's
        (("failure", "Not reviewed: add the review label"), [], ""),  # not ours to clear
        (("failure", "The review ran but posted no summary"), [], ""),
    ],
)
def test_descopes_status_moves_only_between_posted_and_a_descope(descopes, status, threads, posted):
    result = descopes(threads, status=status, script="status")
    assert result.returncode == 0, result.stderr
    if posted:
        assert posted in result.posted and "context=claude-review" in result.posted
    else:
        assert result.posted == ""


def test_descopes_status_says_who_approved_when_it_clears(descopes):
    approved = note("kieron", "Approved: Kieron, 2026-11-13", "2026-11-13T11:00:00Z")
    status = ("failure", "A descope waits for a person's decision: x")
    result = descopes([descope_thread(approved)], status=status, script="status")
    assert "description=The Claude review is posted; descopes decided: approved by @kieron" in (
        result.posted
    )


def test_descopes_status_fails_when_it_cannot_check(descopes):
    result = descopes([], readable=False, script="status")
    assert result.returncode == 1 and result.posted == ""


def test_the_review_and_each_reply_check_the_descopes():
    review = (REPO / ".github/workflows/sdlc-claude-review.yml").read_text()
    done = review.split("name: Mark the review as done", 1)[1].split(
        "name: Mark the review as failed"
    )[0]
    assert done.index("review-findings.sh") < done.index('.sdlc/scripts/descopes-decided.sh "$PR"')
    workflow = (REPO / ".github/workflows/sdlc-descopes.yml").read_text()
    assert "pull_request_review:\n    types: [submitted, dismissed]" in workflow
    assert "pull_request_review_comment:\n    types: [created]" in workflow
    assert "github.event.comment.user.type == 'User'" in workflow
    assert '.sdlc/scripts/descopes-status.sh "$PR" "$HEAD_SHA"' in workflow
    assert "statuses: write" in workflow
    assert synced(".sdlc/scripts/descopes-decided.sh") and synced(
        ".sdlc/scripts/descopes-status.sh"
    )


def test_the_review_rules_and_skill_use_the_lead_in_the_script_reads():
    """descopes-decided.sh finds a descope thread by its lead-in; both prompts must write it."""
    assert "Descope: needs approval" in (REPO / ".sdlc/scripts/descopes-decided.sh").read_text()
    for path in (".sdlc/REVIEW.md", ".sdlc/skills/review-findings/SKILL.md"):
        assert "Descope: needs approval" in (REPO / path).read_text(), path


SESSION = (
    "**Important (product owner decides; engineer for plan amendments):** Session decisions: "
    "needs approval. Three descopes decided in the session (#218)."
)


def test_one_reply_approves_a_session_decisions_thread(descopes):
    approved = note("kieron", "Approved: Kieron, 18 Nov", "2026-11-18T07:00:00Z")
    result = descopes([descope_thread(approved, first=SESSION)])
    assert result.returncode == 0
    assert (
        result.stdout.strip()
        == "descopes decided: session decisions approved by @kieron (2026-11-18)"
    )


def test_a_session_decisions_thread_waits_for_a_person_not_the_app(descopes):
    app = note("stickle-claude", "Approved: Kieron, 18 Nov", "2026-11-18T07:00:00Z", "Bot")
    for thread in (descope_thread(first=SESSION), descope_thread(app, first=SESSION)):
        result = descopes([thread])
        assert result.returncode == 1
        assert result.stdout.startswith("A session decision waits for a person's decision: Three")


def test_a_session_decisions_thread_sent_back_waits_for_a_re_review(descopes):
    back = note("kieron", "No, build the export after all.", "2026-11-18T07:00:00Z")
    result = descopes([descope_thread(back, first=SESSION)], reviewed="2026-11-18T06:00:00Z")
    assert result.returncode == 1 and "sent a session decision back" in result.stdout


def test_an_older_plan_changes_thread_still_counts(descopes):
    old = (
        "**Important (engineer decides; product owner for spec clauses):** "
        "Plan changes: needs approval."
    )
    assert descopes([descope_thread(first=old)]).returncode == 1
    approved = note("kieron", "Approved: Kieron, 18 Nov", "2026-11-18T07:00:00Z")
    assert descopes([descope_thread(approved, first=old)]).returncode == 0


def test_the_session_decisions_lead_in_is_written_where_the_script_reads_it():
    assert (
        "Session decisions: needs approval"
        in (REPO / ".sdlc/scripts/descopes-decided.sh").read_text()
    )
    for path in (
        ".sdlc/REVIEW.md",
        ".sdlc/skills/build/SKILL.md",
        ".sdlc/skills/review-findings/SKILL.md",
    ):
        assert "Session decisions: needs approval" in (REPO / path).read_text(), path
    assert "## Descopes decided in session" in (REPO / ".sdlc/skills/build/SKILL.md").read_text()
    assert "## Descopes decided in session" in (REPO / ".sdlc/REVIEW.md").read_text()


def test_descopes_status_clears_a_session_decision_once_approved(descopes):
    approved = note("kieron", "Approved: Kieron, 18 Nov", "2026-11-18T07:00:00Z")
    status = ("failure", "A session decision waits for a person's decision: Three items")
    result = descopes([descope_thread(approved, first=SESSION)], status=status, script="status")
    assert "state=success" in result.posted
    assert "session decisions approved by @kieron" in result.posted
