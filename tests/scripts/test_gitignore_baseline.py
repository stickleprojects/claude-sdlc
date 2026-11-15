import shutil

from conftest import REPO, init_repo, run

# --- commit guards: .gitignore baseline --------------------------------------------------------


def test_bootstrap_adds_missing_gitignore_lines_once(tmp_path):
    repo = init_repo(tmp_path / "r")
    (repo / ".sdlc" / "templates").mkdir(parents=True)
    shutil.copy(
        REPO / ".sdlc" / "templates" / "gitignore", repo / ".sdlc" / "templates" / "gitignore"
    )
    (repo / ".gitignore").write_text("node_modules/\nmy-own-thing/\n")
    first = run(
        ["bash", str(REPO / ".sdlc/scripts/bootstrap-github.sh"), "--gitignore-only"], cwd=repo
    )
    assert first.returncode == 0, first.stderr
    text = (repo / ".gitignore").read_text()
    assert text.startswith("node_modules/\nmy-own-thing/\n")
    assert text.count("node_modules/") == 1
    for line in [".venv/", "__pycache__/", ".env", "!.env.example", "dist/"]:
        assert f"\n{line}\n" in text
    second = run(
        ["bash", str(REPO / ".sdlc/scripts/bootstrap-github.sh"), "--gitignore-only"], cwd=repo
    )
    assert second.returncode == 0
    assert (repo / ".gitignore").read_text() == text
    assert "has every baseline line" in second.stdout


def test_bootstrap_turns_on_branch_deletion_idempotently():
    script = (REPO / ".sdlc/scripts/bootstrap-github.sh").read_text()
    assert '-q .delete_branch_on_merge)" == true ]]' in script
    assert "-F delete_branch_on_merge=true" in script
    # The protection comparison includes `strict`, so an existing rule without it is updated.
    assert "strict: .required_status_checks.strict" in script


def test_bootstrap_can_refresh_the_app_key_secret():
    script = (REPO / ".sdlc/scripts/bootstrap-github.sh").read_text()
    assert "--update-agent-key) update_agent_key=1" in script
    assert "((update_agent_key == 0)) && gh secret list" in script


def test_bootstrap_help_lists_every_step():
    help_text = run([".sdlc/scripts/bootstrap-github.sh", "--help"]).stdout
    for n in range(1, 12):
        assert f"{n:>2}. " in help_text or f"#   {n}. " in help_text, n
    assert "set -euo" not in help_text
