import json
import re

from conftest import REPO

# --- the /sdlc skill reads the sync's output -----------------------------------------------


def test_sdlc_skill_matches_what_the_sync_prints():
    """/sdlc acts on the sync's messages and lists the stack contract; keep them in step."""
    sync = (REPO / ".sdlc/scripts/sync-sdlc.sh").read_text()
    skill = (REPO / ".sdlc/skills/sdlc/SKILL.md").read_text()
    for message in [
        "kept your local changes",
        "CONFLICT",
        ".sdlc-new",
        "kept (the framework dropped these",
        "your Makefile doesn't define these targets",
        "your Makefile doesn't include the pipeline's targets",
        "your Makefile defines targets .sdlc/sdlc.mk now provides",
        "allowed actions leave out",
    ]:
        assert message in sync, f"the sync no longer prints {message!r}"
        assert message in skill, f"/sdlc doesn't handle {message!r}"
    block = sync.split("local contract_targets=(")[1].split(")")[0]
    contract = re.findall(r'^\s*"([a-z-]+) ', block, re.MULTILINE)
    assert contract, "couldn't read contract_targets from the sync"
    assert f"`{' '.join(contract)}`" in skill, "the stack contract in /sdlc differs from the sync's"


def test_agent_allows_the_make_targets_the_skills_run_first():
    """CI ignores .claude/settings.json's allow list, so agent.sh's own list must cover what the
    skills run unprompted: the routing check (`make next`) and the scaffold. Without `make next`
    the intent eval stopped for approval and failed the v0.7.1 release."""
    allowed = (REPO / ".sdlc/scripts/agent.sh").read_text()
    routing = (REPO / ".sdlc/skills/routing.md").read_text()
    assert "make next" in routing
    for target in ("make next:*", "make new-change:*", "make validate"):
        assert f"Bash({target})" in allowed

    # Every stub starts by running the resolver (#133): without it no skill loads in CI.
    assert "Bash(.sdlc/scripts/resolve.sh:*)" in allowed
    settings = json.loads((REPO / ".claude/settings.json").read_text())
    assert "Bash(.sdlc/scripts/resolve.sh:*)" in settings["permissions"]["allow"]
    for stub in [
        *REPO.glob(".sdlc/claude/skills/*/SKILL.md"),
        *REPO.glob(".sdlc/claude/agents/*.md"),
    ]:
        assert "`.sdlc/scripts/resolve.sh " in stub.read_text(), stub
