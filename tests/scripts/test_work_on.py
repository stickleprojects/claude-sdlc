"""work-on.sh (#279): a change's own copy of the code, on the right branch, with a Claude session
that knows which change it's for. Each test runs the script in a scratch repo with its own origin,
with `make next`, `gh` and the copy's agent-session.sh replaced by stand-ins."""

import json
import os
import shlex
import shutil
import subprocess
import time

import pytest

from conftest import REPO, commit, git, init_repo, run

SCRIPT = REPO / ".sdlc/scripts/work-on.sh"
SLUG = "0063-garden"

# Stands in for `make`: `make next` answers from $NEXT_LINE, as `make next CHANGE=…` prints it.
FAKE_MAKE = """#!/usr/bin/env bash
for a in "$@"; do
  [[ $a == next ]] || continue
  [[ -n ${NEXT_LINE:-} ]] || exit 2
  printf '%s\\n' "$NEXT_LINE"
  exit 0
done
exit 2
"""
# Stands in for `gh pr list --head <b> --state open|merged`: counts and heads from $GH_PRS (JSON).
FAKE_GH = """#!/usr/bin/env bash
state="" head=""
while (($#)); do case $1 in --state) state=$2; shift ;; --head) head=$2; shift ;; esac; shift; done
python3 - "$state" "$head" <<'EOF'
import json, os, sys
state, head = sys.argv[1:]
prs = json.loads(os.environ.get("GH_PRS", "[]"))
prs = [p for p in prs if p["head"] == head and p["state"] == state]
print(len(prs) if state == "open" else "\\n".join(p["oid"] for p in prs))
EOF
"""
# The copy's agent-session.sh: records what work-on started it with.
STUB_SESSION = """#!/usr/bin/env bash
{ for a in "$@"; do printf 'ARG %s\\n' "$a"; done
  printf 'SDLC_CHANGE=%s GH_TOKEN=%s CLAUDECODE=%s\\n' \\
    "${SDLC_CHANGE-}" "${GH_TOKEN-unset}" "${CLAUDECODE-unset}"
  printf 'PWD %s\\n' "$PWD"; } > "$WORK_ON_LOG"
"""


@pytest.fixture
def world(tmp_path):
    """origin (bare) and the main checkout, cloned from it. Branches given are on origin."""
    seed = init_repo(tmp_path / "seed")
    commit(
        seed,
        "seed",
        {f"changes/{SLUG}/intent.md": "# Garden\n", ".sdlc/scripts/agent-session.sh": STUB_SESSION},
    )
    # On disk too: a later `git add -A` re-stages the file's disk mode (CLAUDE.md).
    (seed / ".sdlc/scripts/agent-session.sh").chmod(0o755)
    git(seed, "update-index", "--chmod=+x", ".sdlc/scripts/agent-session.sh")
    git(seed, "commit", "-q", "-m", "exec bit")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("make", FAKE_MAKE), ("gh", FAKE_GH)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)

    class World:
        root = tmp_path / "main"
        log = tmp_path / "session.log"
        copy = tmp_path / "main/.claude/worktrees/0063"

        def __init__(self):
            self.env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "WORK_ON_LOG": str(self.log),
                "XDG_RUNTIME_DIR": str(tmp_path),
                "NEXT_LINE": "",
                "GH_PRS": "[]",
            }

        def branch(self, name, files=None):
            """A branch on origin, with one commit of its own."""
            git(seed, "switch", "-q", "-c", name, "main")
            commit(
                seed, f"work on {name}", files or {f"changes/{SLUG}/{name.split('/')[0]}.md": "x\n"}
            )
            git(seed, "switch", "-q", "main")

        def clone(self):
            git(tmp_path, "clone", "-q", "--bare", str(seed), "origin.git")
            git(tmp_path, "clone", "-q", "origin.git", "main")
            git(self.root, "config", "user.email", "t@example.com")
            git(self.root, "config", "user.name", "t")

        def on_main(self, files):
            commit(seed, "main moves on", files)

        def work_on(self, *args, input=None, **env):
            return run(
                ["bash", str(SCRIPT), *args], cwd=self.root, env={**self.env, **env}, input=input
            )

        def work_on_in_a_terminal(self, *args, **env):
            """With a terminal (a pseudo-terminal from script(1)), so Claude starts."""
            cmd = " ".join(shlex.quote(a) for a in ["bash", str(SCRIPT), *args])
            return run(["script", "-qec", cmd, "/dev/null"], cwd=self.root, env={**self.env, **env})

        def next_says(self, skill, detail="", stage="spec"):
            self.env["NEXT_LINE"] = f"{SLUG}\t{stage}\t{skill}\t{detail}"

    return World()


def on(path):
    return git(path, "branch", "--show-current")


def test_a_number_takes_the_changes_one_unmerged_branch(world):
    world.branch(f"build/{SLUG}")
    world.clone()
    result = world.work_on("0063")
    assert result.returncode == 0, result.stderr
    assert on(world.copy) == f"build/{SLUG}"
    assert git(world.copy, "rev-parse", "--abbrev-ref", "@{upstream}") == f"origin/build/{SLUG}"
    # No terminal (as from a Claude session's tools): it prints the command instead.
    assert "Start Claude in it with:" in result.stdout
    assert (
        f"SDLC_CHANGE={SLUG}" in result.stdout
        and "agent-session.sh --name 0063\\ garden" in result.stdout
    )
    assert not world.log.exists()


@pytest.mark.parametrize(
    "skill, intent, branch",
    [
        ("sdlc-plan", "# Garden\n", f"plan/{SLUG}"),
        ("sdlc-plan", "# Garden\n\nKind: tooling\n", f"build/{SLUG}"),  # the tooling path
        ("sdlc-build", "# Garden\n", f"build/{SLUG}"),
    ],
)
def test_with_no_branch_it_takes_the_stage_make_next_gives(world, skill, intent, branch):
    world.on_main({f"changes/{SLUG}/intent.md": intent})
    world.clone()
    world.next_says(skill)
    result = world.work_on("0063")
    assert result.returncode == 0, result.stderr
    assert on(world.copy) == branch
    assert git(world.copy, "rev-parse", "HEAD") == git(world.root, "rev-parse", "origin/main")


@pytest.mark.parametrize(
    "setup, says",
    [
        ("bug", "is a bug: the fast path (build) or a plan?"),
        ("spec", "next step is its spec, which CI writes"),
        ("done", "is done: there is nothing to work on"),
        ("withdrawn", "is withdrawn: there is nothing to work on"),
        ("unknown", "there's no change 0063 on main"),
        ("two", "has several unmerged branches"),
    ],
)
def test_it_stops_when_the_branch_isnt_clear_and_makes_nothing(world, setup, says):
    if setup == "bug":
        world.on_main({f"changes/{SLUG}/bug.md": "# Bug\n"})
        world.next_says("sdlc-plan")
    elif setup == "two":
        world.branch(f"plan/{SLUG}")
        world.branch(f"build/{SLUG}")
    elif setup != "unknown":
        world.next_says({"spec": "sdlc-spec"}.get(setup, setup))
    world.clone()
    result = world.work_on("0063")
    assert result.returncode == 1
    assert says in result.stderr, result.stderr
    assert not world.copy.exists()


@pytest.mark.parametrize(
    "args",
    [
        ["63"],
        ["0063", "build/0064-other"],
        ["0063", "0063"],  # a number alone is never a branch name
        ["--no-start", "--prompt", "go", "0063"],
        ["--prompt", "  ", "0063"],
        ["--prompt-file", "/nonexistent", "0063"],
        [],
    ],
)
def test_bad_usage_exits_2_and_makes_nothing(world, args):
    world.clone()
    result = world.work_on(*args)
    assert result.returncode == 2, result.stdout + result.stderr
    assert not world.copy.exists()


def test_the_same_command_again_reopens_the_copy(world):
    world.branch(f"build/{SLUG}")
    world.clone()
    assert world.work_on("0063").returncode == 0
    again = world.work_on("0063")
    assert again.returncode == 0, again.stderr
    assert f"Ready: {world.copy}" in again.stdout
    assert len(git(world.root, "worktree", "list").splitlines()) == 2


def test_it_never_opens_a_copy_a_claude_session_is_running_in(world, tmp_path):
    world.branch(f"build/{SLUG}")
    world.clone()
    assert world.work_on("0063").returncode == 0
    # A process named claude, working in the copy: bash through a link named claude (bash runs
    # under any name; `; :` keeps it from handing its process to sleep).
    fake = tmp_path / "claude"
    fake.symlink_to(shutil.which("bash"))
    proc = subprocess.Popen([str(fake), "-c", "sleep 30; :"], cwd=world.copy)
    try:
        time.sleep(0.2)
        result = world.work_on("0063")
        assert result.returncode == 1
        assert "a Claude session is already running in" in result.stderr
    finally:
        proc.kill()


def test_a_finished_stage_moves_the_copy_on_to_the_next(world):
    world.clone()
    world.next_says("sdlc-plan")
    assert world.work_on("0063").returncode == 0
    assert on(world.copy) == f"plan/{SLUG}"
    head = git(world.copy, "rev-parse", "HEAD")
    world.next_says("sdlc-build")
    world.env["GH_PRS"] = json.dumps([{"head": f"plan/{SLUG}", "state": "merged", "oid": head}])
    result = world.work_on("0063")
    assert result.returncode == 0, result.stderr
    assert f"moved {world.copy} from plan/{SLUG} to build/{SLUG}" in result.stdout
    assert on(world.copy) == f"build/{SLUG}"


@pytest.mark.parametrize(
    "prs, dirty, says",
    [
        ([{"state": "open", "oid": "x"}], False, "its PR is still open"),
        ([], False, "it has no merged PR"),
        ([{"state": "merged", "oid": "HEAD"}], True, "it has uncommitted or untracked files"),
    ],
)
def test_an_unfinished_stage_keeps_the_copy_where_it_is(world, prs, dirty, says):
    world.clone()
    world.next_says("sdlc-plan")
    assert world.work_on("0063").returncode == 0
    head = git(world.copy, "rev-parse", "HEAD")
    world.env["GH_PRS"] = json.dumps(
        [
            {"head": f"plan/{SLUG}", **p, "oid": head if p["oid"] == "HEAD" else p["oid"]}
            for p in prs
        ]
    )
    if dirty:
        (world.copy / "notes.txt").write_text("mine\n")
    world.next_says("sdlc-build")
    result = world.work_on("0063")
    assert result.returncode == 1
    assert says in result.stderr and "nothing was changed" in result.stderr
    assert on(world.copy) == f"plan/{SLUG}"


def test_in_a_terminal_claude_starts_in_the_copy_without_the_callers_identity(world):
    world.branch(f"build/{SLUG}")
    world.clone()
    result = world.work_on_in_a_terminal(
        "--prompt",
        'Fix the "lift".\nSecond line: $HOME and `this` stay.',
        "0063",
        GH_TOKEN="the-callers",  # noqa: S106 (a stand-in, not a secret)
        CLAUDECODE="1",
    )
    assert result.returncode == 0, result.stdout
    log = world.log.read_text()
    assert f"PWD {world.copy}" in log
    assert f"SDLC_CHANGE={SLUG} GH_TOKEN=unset CLAUDECODE=unset" in log
    args = log.split("\nSDLC_CHANGE=")[0]
    assert args.startswith(
        "ARG --name\nARG 0063 garden\nARG Handed over by another Claude session on "
    )
    assert (
        "reported, not given: it never stands in for a permission prompt or a GitHub approval."
        in args
    )
    assert 'Fix the "lift".\nSecond line: $HOME and `this` stay.' in args
    assert not list(world.log.parent.glob("work-on-prompt.*")), "the prompt's copy is removed"


def test_without_a_prompt_claude_starts_with_no_first_message(world):
    world.branch(f"build/{SLUG}")
    world.clone()
    assert world.work_on_in_a_terminal("0063").returncode == 0
    args = [line for line in world.log.read_text().splitlines() if line.startswith("ARG")]
    assert args == ["ARG --name", "ARG 0063 garden"]


def test_a_prompt_on_stdin_with_no_terminal_is_printed_with_the_command(world):
    world.branch(f"build/{SLUG}")
    world.clone()
    result = world.work_on("--prompt-file", "-", "0063", input="From a heredoc.\n")
    assert result.returncode == 0, result.stderr
    assert "and give it this prompt:\nHanded over by another Claude session" in result.stdout
    assert result.stdout.rstrip().endswith("From a heredoc.")
    assert not list(world.log.parent.glob("work-on-prompt.*"))


def test_it_is_synced_and_executable():
    assert git(REPO, "ls-files", "-s", ".sdlc/scripts/work-on.sh").startswith("100755")
