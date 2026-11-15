from conftest import REPO

# --- agents ----------------------------------------------------------------------------


def test_verifier_runs_on_a_set_model():
    # Without a model the verifier inherits the caller's, so an Opus session runs it on Opus.
    agent = (
        REPO / ".sdlc/claude/agents/sdlc-verifier.md"
    ).read_text()  # the stub holds the frontmatter
    front = agent.split("---")[1]
    assert "\nmodel: sonnet\n" in front
