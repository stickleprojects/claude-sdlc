import os
import stat
import textwrap

import pytest

from conftest import REPO, commit, git, init_repo, run

# --- a consumer trial before every release (#200) --------------------------------------------

SCRIPT = REPO / "scripts/consumer-trial.sh"

# A consumer's sync script that records the ref it was given and stages a file, as the real
# one does. $STUB_SYNC_FAIL makes it stop as on a conflict; $STUB_SYNC_PENDING leaves upgrade
# steps behind.
STUB_SYNC = r"""#!/usr/bin/env bash
set -euo pipefail
echo "$1" > synced-ref
if [[ -n "${STUB_SYNC_PENDING:-}" ]]; then
  mkdir -p .sdlc && echo "1. Do it." > .sdlc/upgrade-pending.md
fi
git add -A
[[ -z "${STUB_SYNC_FAIL:-}" ]]
"""

# A gh that records its calls and answers `pr create` with a URL.
FAKE_GH = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_GH_DIR/calls"
[[ "$1 $2" == "pr create" ]] && echo "https://github.com/o/consumer/pull/12"
exit 0
"""

MAKEFILE = "setup:\n\t@echo set up\ncheck:\n\t@echo checking; test ! -f broken\n"


@pytest.fixture
def trial(tmp_path):
    """A framework with a main branch, and a consumer (bare origin) that has a sync script."""
    framework = init_repo(tmp_path / "framework")
    commit(framework, "feat: new thing")
    sha = git(framework, "rev-parse", "HEAD")

    seed = init_repo(tmp_path / "seed")
    commit(seed, "chore: consumer", {".sdlc/scripts/sync-sdlc.sh": STUB_SYNC, "Makefile": MAKEFILE})
    origin = tmp_path / "consumer.git"
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(origin))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH)
    (bin_dir / "gh").chmod(0o755)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env = {
        "SDLC_SOURCE": str(framework),
        "SDLC_TRIAL_REPO": "o/consumer",
        "SDLC_TRIAL_CLONE": str(origin),
        "TMPDIR": str(scratch),
        "FAKE_GH_DIR": str(tmp_path),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        # The commit in the trial clone needs an identity, as on a runner with no global config.
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    return {"env": env, "sha": sha, "origin": origin, "scratch": scratch, "tmp": tmp_path}


def _trial(t, *args, env=None):
    return run(["bash", str(SCRIPT), *args], cwd=t["tmp"], env={**t["env"], **(env or {})})


def _sync(t, *args, env=None):
    result = _trial(t, "sync", *args, env=env)
    folder = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    return result, folder


def _calls(t):
    path = t["tmp"] / "calls"
    return path.read_text() if path.exists() else ""


def test_the_script_is_executable_in_git():
    """On a runner a non-executable script fails (CLAUDE.md, known mistakes)."""
    mode = git(REPO, "ls-files", "-s", "scripts/consumer-trial.sh").split()[0]
    assert mode == "100755"


def test_sync_pins_mains_sha_and_commits_it_on_a_trial_branch_in_a_fresh_clone(trial):
    result, folder = _sync(trial)
    assert result.returncode == 0, result.stderr
    repo = trial["tmp"] / folder / "repo"
    assert os.path.dirname(folder) == str(trial["scratch"]), "a new scratch folder"
    assert (repo / "synced-ref").read_text().strip() == trial["sha"], "the SHA, not 'main'"
    short = trial["sha"][:7]
    assert git(repo, "branch", "--show-current") == f"chore/sdlc-trial-{short}"
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "log", "-1", "--format=%s") == f"chore: trial sync of claude-sdlc {short}"


def test_sync_takes_a_tag_or_a_commit(trial):
    framework = trial["tmp"] / "framework"
    git(framework, "tag", "v1.0.0")
    commit(framework, "fix: later")
    _, folder = _sync(trial, "v1.0.0")
    assert (trial["tmp"] / folder / "repo/synced-ref").read_text().strip() == trial["sha"]
    _, folder = _sync(trial, trial["sha"][:10])
    assert (trial["tmp"] / folder / "repo/synced-ref").read_text().strip() == trial["sha"][:10]


def test_sync_refuses_a_ref_that_isnt_there(trial):
    result, _ = _sync(trial, "no-such-branch")
    assert result.returncode == 1
    assert "no no-such-branch" in result.stderr
    assert list(trial["scratch"].iterdir()) == [], "no folder left behind"


def test_sync_finds_an_older_layouts_sync_script(trial):
    seed = trial["tmp"] / "seed"
    git(seed, "mv", ".sdlc/scripts/sync-sdlc.sh", "scripts-sync.sh")
    (seed / "scripts").mkdir()
    git(seed, "mv", "scripts-sync.sh", "scripts/sync-sdlc.sh")
    commit(seed, "chore: old layout")
    git(trial["origin"], "fetch", "-q", str(seed), "+main:main")
    result, folder = _sync(trial)
    assert result.returncode == 0, result.stderr
    assert (trial["tmp"] / folder / "repo/synced-ref").exists()


def test_a_sync_that_stops_keeps_the_folder_for_resolving(trial):
    result, folder = _sync(trial, env={"STUB_SYNC_FAIL": "1"})
    assert result.returncode == 1
    assert "resolve them" in result.stderr
    repo = trial["tmp"] / folder / "repo"
    assert repo.is_dir()
    assert git(repo, "log", "-1", "--format=%s") == "chore: consumer", "nothing committed"


def test_sync_says_when_upgrade_steps_are_pending(trial):
    result, folder = _sync(trial, env={"STUB_SYNC_PENDING": "1"})
    assert result.returncode == 0
    assert "upgrade-pending.md" in result.stderr
    assert (trial["tmp"] / folder / "repo/.sdlc/upgrade-pending.md").exists()


def test_check_runs_setup_and_check_and_keeps_the_log(trial):
    _, folder = _sync(trial)
    result = _trial(trial, "check", folder)
    assert result.returncode == 0, result.stderr
    assert "make check passed in o/consumer" in result.stdout
    log = (trial["tmp"] / folder / "check.log").read_text()
    assert log.index("set up") < log.index("checking")


def test_check_fails_when_the_consumers_check_fails(trial):
    _, folder = _sync(trial)
    (trial["tmp"] / folder / "repo/broken").write_text("")
    result = _trial(trial, "check", folder)
    assert result.returncode != 0
    assert "make check FAILED in o/consumer" in result.stderr


def test_pr_pushes_the_branch_and_opens_one_draft_do_not_merge_pr(trial):
    _, folder = _sync(trial)
    result = _trial(trial, "pr", folder)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://github.com/o/consumer/pull/12"
    short = trial["sha"][:7]
    assert git(trial["origin"], "rev-parse", f"chore/sdlc-trial-{short}")
    create = [c for c in _calls(trial).splitlines() if c.startswith("pr create")]
    assert len(create) == 1
    assert "-R o/consumer --draft" in create[0]
    assert f"chore: trial sync of claude-sdlc {short} (do not merge)" in create[0]

    again = _trial(trial, "pr", folder)
    assert again.stdout.strip() == "https://github.com/o/consumer/pull/12"
    assert len([c for c in _calls(trial).splitlines() if c.startswith("pr create")]) == 1


def test_close_closes_the_pr_deletes_its_branch_and_the_folder(trial):
    _, folder = _sync(trial)
    _trial(trial, "pr", folder)
    result = _trial(trial, "close", folder)
    assert result.returncode == 0, result.stderr
    close = [c for c in _calls(trial).splitlines() if c.startswith("pr close")]
    assert (
        close and "https://github.com/o/consumer/pull/12 -R o/consumer --delete-branch" in close[0]
    )
    assert not (trial["tmp"] / folder).exists()


def test_close_without_a_pr_only_removes_the_folder(trial):
    _, folder = _sync(trial)
    assert _trial(trial, "close", folder).returncode == 0
    assert "pr close" not in _calls(trial)
    assert not (trial["tmp"] / folder).exists()


@pytest.mark.parametrize("step", ["check", "pr", "close"])
def test_steps_refuse_a_folder_that_sync_didnt_make(trial, step):
    other = trial["tmp"] / "precious"
    other.mkdir()
    (other / "work.txt").write_text("keep me")
    result = _trial(trial, step, str(other))
    assert result.returncode == 1
    assert "not a trial folder" in result.stderr
    assert (other / "work.txt").exists()


def test_no_step_prints_usage(trial):
    result = _trial(trial)
    assert result.returncode == 2
    assert "sync [ref]" in result.stderr


# --- the release needs a trial (#200) ---------------------------------------------------------


def _version_step() -> str:
    """The run script of release.yml's "Work out the next version" step."""
    lines = (REPO / ".github/workflows/release.yml").read_text().splitlines()
    start = lines.index("      - name: Work out the next version")
    run_at = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    body = []
    for line in lines[run_at + 1 :]:
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line)
    return textwrap.dedent("\n".join(body))


@pytest.mark.parametrize(
    ("dry_run", "trial_line", "gated"),
    [("false", "", True), ("false", "o/c#1: passed", False), ("true", "", False)],
)
def test_a_real_release_needs_a_trial_result(tmp_path, dry_run, trial_line, gated):
    script = tmp_path / "step.sh"
    script.write_text(_version_step())
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    env = {
        "DRY_RUN": dry_run,
        "SDLC_TRIAL": trial_line,
        "GITHUB_OUTPUT": str(tmp_path / "out"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "GITHUB_REPOSITORY": "o/r",
    }
    # A repo with something to release, so the step gets past the version whatever main holds.
    repo = init_repo(tmp_path / "r")
    commit(repo, "chore: initial")
    git(repo, "tag", "v0.4.2")
    commit(repo, "fix: thing (#3)")
    (repo / "scripts").symlink_to(REPO / "scripts")
    result = run(["bash", "-e", str(script)], cwd=repo, env=env)
    assert ("no consumer trial" in result.stdout) is gated
    if gated:
        assert result.returncode == 1
    elif trial_line:
        assert f"## Consumer trial\n\n{trial_line}" in (tmp_path / "summary").read_text()


def test_the_trial_result_goes_in_the_notes(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(repo, "chore: initial")
    git(repo, "tag", "v0.4.2")
    commit(repo, "fix: thing (#3)")
    script = str(REPO / "scripts/release-notes.sh")
    line = "o/c#12: sync clean, make check and CI passed"
    notes = run(["bash", script, "v0.4.3", "o/r"], cwd=repo, env={"SDLC_TRIAL": line}).stdout
    assert f"## Consumer trial\n\n{line}\n" in notes
    assert notes.index("## Consumer trial") < notes.index("## Upgrading a consumer repo")
    assert "## Consumer trial" not in run(["bash", script, "v0.4.3", "o/r"], cwd=repo).stdout
