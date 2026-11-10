"""Layer 1: the guardrail hooks block and allow exactly what they should."""

import pytest

from conftest import REPO, hook

DEPLOY = "deploy" + "-prod"  # split so this file's own text never trips the gate


@pytest.mark.parametrize(
    ("command", "blocked"),
    [
        (f"make {DEPLOY}", True),
        (f"make {DEPLOY} RELEASE_AUTHORIZED_BY=me", True),
        ("make deploy-dev", False),
        ("git push origin main", True),
        ("git push origin HEAD:main", True),
        ("git push origin master", True),
        ("git push --force origin feat", True),
        ("git push -f origin feat", True),
        ("git push --force-with-lease origin feat", True),
        ("git fetch && git push origin main", True),
        ("cd repo; git push origin main", True),
        ("git push -u origin feat/x", False),
        ("git push -u origin feat/main-fix", False),
        ("git push", False),
        ("git merge -q --no-edit main && git push -q", False),
        ("git switch main && git pull", False),
        ("make check", False),
        # #78: running the target is blocked, however it's reached...
        (f"make -C app {DEPLOY}", True),
        (f"env X=1 make {DEPLOY}", True),
        (f"gmake {DEPLOY}", True),
        (f"$(MAKE) {DEPLOY}", True),
        (f"${{MAKE}} {DEPLOY}", True),
        (f"make -n setup {DEPLOY}", True),  # a dry run too: simpler, and fails safe
        (f"cd app && make {DEPLOY}", True),
        (f'bash -c "make {DEPLOY}"', True),
        (f"sh -c 'cd app && make {DEPLOY}'", True),
        (f'eval "make {DEPLOY}"', True),
        (f"echo {DEPLOY} | xargs make", True),
        (f'echo "$(make {DEPLOY})"', True),
        (f"bash <<'EOF'\nmake {DEPLOY}\nEOF", True),
        (f"cat <<'EOF' | sh\nmake {DEPLOY}\nEOF", True),
        # Review on #86: a quoted target, a line continuation, other interpreters.
        (f'make "{DEPLOY}"', True),
        (f"make '{DEPLOY}'", True),
        (f'make -f Makefile "{DEPLOY}"', True),
        ('make dep"loy-prod"', True),
        (f"make \\\n  {DEPLOY}", True),
        (f"make -C app \\\n {DEPLOY} X=1", True),
        (f"python3 -c \"import os; os.system('make {DEPLOY}')\"", True),
        (f"perl -e 'system(\"make {DEPLOY}\")'", True),
        (f'node -e \'require("child_process").execSync("make {DEPLOY}")\'', True),
        (f"env -S 'make {DEPLOY}'", True),
        (f"awk 'BEGIN {{ system(\"make {DEPLOY}\") }}'", True),
        (f"git status && bash <<'EOF'\nmake {DEPLOY}\nEOF", True),
        # Review round 2: git and gh run strings through config and aliases.
        (f"git -c alias.d='!make {DEPLOY}' d", True),
        (f"git -c core.pager='make {DEPLOY}' log", True),
        (f"git --config-env=core.pager=X log && X='make {DEPLOY}'", True),
        (f"git config alias.d '!make {DEPLOY}' && git d", True),
        (f"gh alias set d --shell 'make {DEPLOY}'", True),
        # Review round 3: other git subcommands and tools that run a string.
        (f"git rebase -x 'make {DEPLOY}' HEAD~1", True),
        (f"git submodule foreach 'make {DEPLOY}'", True),
        (f"git bisect run sh -c 'make {DEPLOY}'", True),
        (f"git grep -O'make {DEPLOY}' foo", True),
        (f"rg --pre 'make {DEPLOY}' x .", True),
        (f"sort --compress-program='make {DEPLOY}' f", True),
        # Review round 4: a text tool piped into something that runs it.
        (f"echo 'make {DEPLOY}' | sh", True),
        (f"printf '%s\\n' 'make {DEPLOY}' | bash", True),
        (f'echo "make {DEPLOY}" | bash -s', True),
        (f"echo 'make {DEPLOY}' | tee >(sh)", True),
        (f"git log -1 --format='make {DEPLOY}' | sh", True),
        # Review round 5: ANSI-C quoting and backslash escapes (brace expansion and a target
        # built from variables are deliberate disguises, out of scope).
        (f"make $'{DEPLOY}'", True),
        (f'make $"{DEPLOY}"', True),
        ("make deploy\\-prod", True),
        ("make dep\\loy-prod", True),
        # Review round 6: variables a text tool runs (GIT_PAGER, GIT_EDITOR, …).
        (f"GIT_PAGER='make {DEPLOY}' git log", True),
        (f'GIT_EDITOR="make {DEPLOY}" git commit', True),
        (f"env PAGER='make {DEPLOY}' git show", True),
        (f"cd app && GIT_SSH_COMMAND='make {DEPLOY}' git log", True),
        (f"GIT_PAGER=sh git log -1 --format='make {DEPLOY}'", True),  # the pager runs the output
        (f"env PAGER=sh git show -s --format='make {DEPLOY}'", True),
        # Review round 7: an unquoted heredoc runs $( and backticks in its body.
        (f"cat <<EOF\n$(make {DEPLOY})\nEOF", True),
        (f"git commit -F - <<EOF\nfix: x `make {DEPLOY}`\nEOF", True),
        (f"cat > notes.md <<EOF\nsee $(date)\nrun make {DEPLOY} later\nEOF", False),
        # Not a text tool, so its heredoc is checked as code: the cost of failing safe.
        (f"python3 - <<'EOF'\nnote = 'make {DEPLOY} needs a human'\nEOF", True),
        # ...and mentioning it isn't.
        (f'git commit -m "fix: the {DEPLOY} gate"', False),
        (f'gh pr create --title t --body "missing targets: make {DEPLOY} (optional)"', False),
        (f"gh pr create --body \"$(cat <<'EOF'\n  make {DEPLOY}  (optional: x)\nEOF\n)\"", False),
        (f"gh api repos/o/r/pulls -F body=@- <<EOF\nmissing: deploy-dev, {DEPLOY}\nEOF", False),
        (f"cat > notes.md <<EOF\nrun make {DEPLOY}\nEOF", False),
        (f"echo 'make {DEPLOY}'", False),
        (f"echo 'make {DEPLOY}' | tee notes.txt | wc -l", False),
        (f'git commit -m "fix: make {DEPLOY} gate" && make check', False),
        (f'git -C repo commit -q -m "fix: make {DEPLOY} gate"', False),
        (f"git --no-pager log --grep 'make {DEPLOY}'", False),
        (f'gh issue comment 1 --body "run make {DEPLOY} later"', False),
        (f"grep -n '{DEPLOY}' Makefile", False),
        (f"grep -n {DEPLOY} Makefile && sed -n 1,5p Makefile", False),
        (f"awk '/{DEPLOY}/' Makefile", False),
        (f"x=$(cat <<<'{DEPLOY}') && make check", False),
        # #88: a quoted string spanning several lines is one string, not a line each.
        (f'gh pr create --body "intro\nrun make {DEPLOY} later\nend"', False),
        (f'git commit -m "fix: the gate\n\nmake {DEPLOY} needs a human"', False),
        (f'gh pr create --body "it\'s fine\nmake {DEPLOY}\nend"', False),  # \' in "…" opens nothing
        (f'git commit -m "say \\"hi\\"\nmake {DEPLOY}\nend"', False),  # escaped quotes stay inside
        (f'bash -c "echo hi\nmake {DEPLOY}"', True),  # not a text tool: checked as code
        (f'echo "notes\nmake {DEPLOY}" | sh', True),  # piped on to a shell
        (f'git commit -m "a\nb" && make {DEPLOY}', True),  # after the string closes
        (f'git commit -m "a\nb"\nmake {DEPLOY}', True),
        (f'echo "unclosed\nmake {DEPLOY}', True),  # a quote that never closes: fail safe
        (f"# don't\nmake {DEPLOY}", True),  # a comment opens no quote
        (f'git commit -m "x\n$(make {DEPLOY})\ny"', True),  # $( runs inside double quotes
    ],
)
def test_production_gate(command, blocked):
    result = hook("production-gate.sh", {"tool_input": {"command": command}})
    assert result.returncode == (2 if blocked else 0), result.stderr
    if blocked:
        assert "Blocked" in result.stderr


@pytest.mark.parametrize(
    ("rel_path", "env", "blocked"),
    [
        (".claude/settings.json", {}, True),
        (".claude/hooks/production-gate.sh", {}, True),
        (".git/config", {}, True),
        ("uv.lock", {}, True),
        (".env", {}, True),
        (".env.local", {}, True),
        ("certs/server.pem", {}, True),
        ("tests/test_x.py", {"SDLC_LOCK_TESTS": "1"}, True),
        ("tests/test_x.py", {}, False),
        ("src/sdlc/cli.py", {"SDLC_LOCK_TESTS": "1"}, False),
        (".claude/skills/intent/SKILL.md", {}, False),
        ("docs/roles.md", {}, False),
    ],
)
def test_protect_paths(rel_path, env, blocked):
    payload = {"tool_input": {"file_path": str(REPO / rel_path)}}
    result = hook("protect-paths.sh", payload, env=env)
    assert result.returncode == (2 if blocked else 0), result.stderr


def test_protect_paths_reads_notebook_path():
    payload = {"tool_input": {"notebook_path": str(REPO / ".env")}}
    assert hook("protect-paths.sh", payload).returncode == 2


def test_protect_paths_ignores_tools_without_a_path():
    assert hook("protect-paths.sh", {"tool_input": {}}).returncode == 0


def test_format_hook_never_fails():
    payload = {"tool_input": {"file_path": str(REPO / "does-not-exist.py")}}
    assert hook("format.sh", payload).returncode == 0


MERGE = "gh pr " + "merge"  # split so this file's text never trips the gate
AUTO = "enablePullRequest" + "AutoMerge"


@pytest.mark.parametrize(
    ("command", "blocked"),
    [
        (f"{MERGE} 21", True),
        (f"{MERGE} 21 --merge --admin --delete-branch", True),
        (f"git fetch && {MERGE} 21 --squash", True),
        ("gh pr review 21 --approve", True),
        ("gh pr review 21 -a -b lgtm", True),
        ("gh api -X PUT repos/o/r/pulls/21/merge", True),
        ("gh api repos/o/r/pulls/21/reviews -f event=APPROVE", True),
        ("gh pr review 21 --comment -b 'see inline'", False),
        ("gh pr review 21 --request-changes -b 'fix x'", False),
        ("gh pr create --fill", False),
        ("gh pr view 21 --json mergeable", False),
        ("gh pr checks 21", False),
        ("gh api repos/o/r/pulls/21/comments", False),
        ("git merge --no-edit main", False),
        (f"{MERGE} 21 --auto --merge", True),
        (f"gh api graphql -f query='mutation {{ {AUTO}(input: {{pullRequestId: 1}}) }}'", True),
        (f"gh api graphql -f query='\n  mutation {{\n    {AUTO}(input: {{}})\n  }}'", True),
        ("scripts/auto-merge.sh 21", False),
        (f"grep -n {AUTO} scripts/auto-merge.sh", False),
    ],
)
def test_agent_cannot_merge_or_approve(command, blocked):
    result = hook("production-gate.sh", {"tool_input": {"command": command}})
    assert result.returncode == (2 if blocked else 0), result.stderr
    if blocked:
        assert "human decision" in result.stderr or "scripts/auto-merge.sh" in result.stderr


def test_protect_paths_locks_a_bug_fixes_tests_after_its_failing_test(tmp_path):
    # The hook asks scripts/tests-locked.sh, so nobody has to set SDLC_LOCK_TESTS=1.
    import shutil

    from conftest import commit, git, init_repo

    repo = init_repo(tmp_path / "r")
    (repo / "scripts").mkdir()
    shutil.copy2(REPO / "scripts/tests-locked.sh", repo / "scripts/tests-locked.sh")
    commit(repo, "bug: 0003-x", {"changes/0003-x/bug.md": "# bug\n"})
    git(repo, "switch", "-q", "-c", "build/0003-x")
    payload = {"tool_input": {"file_path": str(repo / "tests/test_x.py")}}
    env = {"SDLC_LOCK_TESTS": ""}
    assert hook("protect-paths.sh", payload, env=env, cwd=repo).returncode == 0
    commit(repo, "test(0003-x): failing test for x", {"tests/test_x.py": "x\n"})
    locked = hook("protect-paths.sh", payload, env=env, cwd=repo)
    assert locked.returncode == 2 and "bug fix" in locked.stderr
    code = {"tool_input": {"file_path": str(repo / "src/x.py")}}
    assert hook("protect-paths.sh", code, env=env, cwd=repo).returncode == 0
