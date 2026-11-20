"""SDLC_MAIN_DOCS_SKIP (#240): a push to main that changed only docs runs `make validate`
instead of `make check FULL=1`."""

import shutil

import pytest

from conftest import REPO, commit, git, init_repo, run
from test_check_after_review import CI, load

from .helpers import CHECK_STEPS, run_check_job

SCRIPT = REPO / ".sdlc/scripts/main-docs-only.sh"
MAKEFILE = """\
.PHONY: check validate
check:
\t@echo "ran check FULL=$(FULL)"
validate:
\t@echo "ran validate"
"""


@pytest.fixture
def repo(tmp_path):
    """A repo on main with code, docs and a change folder, the script where the sync puts it."""
    r = init_repo(tmp_path / "r")
    (r / ".sdlc/scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, r / ".sdlc/scripts/main-docs-only.sh")
    commit(
        r,
        "chore: start",
        {"Makefile": MAKEFILE, "src/app.py": "x = 1\n", "readme.md": "# r\n", "docs/a.md": "a\n"},
    )
    return r


def push(repo, files):
    """Commit `files` as one merge to main would bring them; return (before, after)."""
    before = git(repo, "rev-parse", "HEAD")
    commit(repo, "merge", files)
    return before, git(repo, "rev-parse", "HEAD")


def docs_only(repo, before, after):
    return run([".sdlc/scripts/main-docs-only.sh", before, after], cwd=repo)


@pytest.mark.parametrize(
    "files",
    [
        {"docs/guide.md": "g\n"},
        {"changes/0001-x/intent.md": "# i\n", "changes/0001-x/spec.md": "# s\n"},
        {"readme.md": "# r, again\n", "CLAUDE.md": "c\n"},
        {"docs/img.png": "png\n"},  # anything under docs/
    ],
    ids=["docs", "change folder", "top-level md", "docs asset"],
)
def test_a_docs_only_push_says_validate_is_enough(repo, files):
    result = docs_only(repo, *push(repo, files))
    assert result.returncode == 0, result.stdout
    assert f"docs only: {len(files)} file(s)" in result.stdout


@pytest.mark.parametrize(
    ("files", "named"),
    [
        ({"docs/a.md": "b\n", "src/app.py": "x = 2\n"}, "src/app.py"),
        ({"src/README.md": "nested\n"}, "src/README.md"),  # nested markdown is code
        ({".github/workflows/x.yml": "on: push\n"}, ".github/workflows/x.yml"),
        ({".sdlc/skills/x.md": "skill\n"}, ".sdlc/skills/x.md"),
        ({"Makefile": MAKEFILE + "\n"}, "Makefile"),
    ],
    ids=["code beside docs", "nested md", "workflow", "skill", "Makefile"],
)
def test_any_other_file_runs_everything(repo, files, named):
    result = docs_only(repo, *push(repo, files))
    assert result.returncode == 1
    assert f"{named} is code: run everything" in result.stdout


@pytest.mark.parametrize(
    ("before", "why"),
    [
        ("0" * 40, "no earlier commit"),
        ("", "no commits to compare"),
        ("not-a-sha", "no commits to compare"),
        ("1234567890abcdef1234567890abcdef12345678", "can't find"),
    ],
    ids=["new branch", "empty", "garbage", "missing commit"],
)
def test_when_unsure_it_runs_everything(repo, before, why):
    after = git(repo, "rev-parse", "HEAD")
    result = docs_only(repo, before, after)
    assert result.returncode == 1 and why in result.stdout


def test_an_empty_push_runs_everything(repo):
    head = git(repo, "rev-parse", "HEAD")
    result = docs_only(repo, head, head)
    assert result.returncode == 1 and "nothing changed" in result.stdout


def test_a_squash_and_a_merge_commit_are_judged_alike(repo):
    """The diff is before..after, so a merge commit's branch history doesn't matter."""
    before = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "-c", "feature")
    commit(repo, "docs", {"docs/x.md": "x\n"})
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #1", "feature")
    assert docs_only(repo, before, git(repo, "rev-parse", "HEAD")).returncode == 0


def test_the_script_arrives_executable():
    assert git(REPO, "ls-files", "-s", str(SCRIPT.relative_to(REPO))).startswith("100755")


# --- the CI job on a push to main --------------------------------------------------------------


def job(repo, tmp_path, before, after, skip):
    env = {"EVENT": "push", "BEFORE": before, "AFTER": after}
    if skip is not None:
        env["SDLC_MAIN_DOCS_SKIP"] = skip
    return run_check_job(repo, env, tmp_path)


@pytest.mark.parametrize(
    ("files", "skip", "mode", "ran"),
    [
        ({"docs/guide.md": "g\n"}, "on", "docs", "ran validate"),
        ({"changes/0001-x/plan.md": "# p\n"}, "on", "docs", "ran validate"),
        ({"src/app.py": "x = 2\n"}, "on", "full", "ran check FULL=1"),
        ({"docs/guide.md": "g\n"}, None, "full", "ran check FULL=1"),  # off unless opted in
        ({"docs/guide.md": "g\n"}, "off", "full", "ran check FULL=1"),
        ({"docs/guide.md": "g\n"}, "yes", "full", "ran check FULL=1"),  # only `on` turns it on
    ],
    ids=["docs on", "change on", "code on", "docs unset", "docs off", "docs yes"],
)
def test_main_runs_validate_only_for_a_docs_only_push_when_opted_in(
    repo, tmp_path, files, skip, mode, ran
):
    got, _, result = job(repo, tmp_path, *push(repo, files), skip)
    assert got == mode
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == ran


def test_the_which_step_says_why_it_chose(repo, tmp_path):
    _, docs, _ = job(repo, tmp_path, *push(repo, {"docs/guide.md": "g\n"}), "on")
    assert docs.stdout.startswith("docs only: 1 file(s)") and "This run makes: docs" in docs.stdout
    _, code, _ = job(repo, tmp_path, *push(repo, {"src/app.py": "x = 3\n"}), "on")
    assert code.stdout.startswith("src/app.py is code: run everything")


def test_each_mode_has_its_own_named_step_for_the_jobs_api():
    """A release gate tells a full run from a docs-only one by which step succeeded and which
    was skipped (spellbound3d's release-gate, #240). The names are a contract: don't rename."""
    steps = {s.get("name"): s for s in load(CI)["jobs"]["check"]["steps"]}
    for mode, name in CHECK_STEPS.items():
        want = f"steps.which.outputs.mode == '{mode}' && env.DEFERRED != 'true'"
        assert steps[name]["if"] == want, name
    assert steps[CHECK_STEPS["full"]]["run"] == "make check FULL=1"
    assert steps[CHECK_STEPS["docs"]]["run"] == "make validate"
    settings = (REPO / ".sdlc/docs/settings.md").read_text()
    for name in (CHECK_STEPS["full"], CHECK_STEPS["docs"]):
        assert f"`{name}`" in settings, "the contract is documented"


def test_the_which_step_reads_the_variable_and_commits_through_env_only():
    step = next(
        s
        for s in load(CI)["jobs"]["check"]["steps"]
        if s.get("name") == "Which check this run makes"
    )
    assert step["env"]["SDLC_MAIN_DOCS_SKIP"] == "${{ vars.SDLC_MAIN_DOCS_SKIP }}"
    assert step["env"]["BEFORE"] == "${{ github.event.before }}"
    assert step["env"]["AFTER"] == "${{ github.sha }}"
    assert "${{" not in step["run"], "no expression in the script: it could inject shell"
