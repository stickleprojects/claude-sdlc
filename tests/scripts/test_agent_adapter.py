from conftest import run

# --- agent adapter ---------------------------------------------------------------------


def test_agent_echo_reads_stdin():
    result = run([".sdlc/scripts/agent.sh", "-"], env={"AGENT": "echo"}, input="hello agent")
    assert result.returncode == 0
    assert result.stdout.strip() == "hello agent"


def test_agent_echo_reads_prompt_file(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("from a file")
    result = run([".sdlc/scripts/agent.sh", str(prompt)], env={"AGENT": "echo"})
    assert result.stdout.strip() == "from a file"


def test_agent_rejects_unknown_adapter():
    result = run([".sdlc/scripts/agent.sh", "-"], env={"AGENT": "nope"}, input="x")
    assert result.returncode == 2
    assert "unknown AGENT" in result.stderr


def test_agent_requires_a_prompt():
    assert run([".sdlc/scripts/agent.sh"]).returncode != 0
