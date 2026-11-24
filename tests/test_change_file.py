"""change.toml: its checks, the sweep, and what make next does with it (#272)."""

from pathlib import Path

import pytest

from conftest import REPO, commit, git, init_repo, run
from sdlc.cli import main
from sdlc.meta import META, Meta, MetaError, check_meta, parse, read
from sdlc.routing import steps
from sdlc.sweep import sweep

SLUG = "0001-x"


def toml(slug=SLUG, title="A title", status="open", pr=None):
    return Meta(slug[:4], slug, title, status, pr).render()


def files(status: str | None = "open", slug=SLUG, upto="plan", **kw) -> dict[str, str]:
    base = f"changes/{slug}/"
    out = {base + "intent.md": "# Intent: A title\n"}
    if upto == "plan":
        out |= {base + "spec.md": "# S\n", base + "plan.md": "# P\n"}
    if status:
        out[base + META] = toml(slug, status=status, **kw)
    return out


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return init_repo(tmp_path / "r")


def merge_build(repo: Path, status: str | None = None) -> None:
    git(repo, "switch", "-q", "-c", f"build/{SLUG}")
    extra = {f"changes/{SLUG}/{META}": toml(status=status)} if status else {}
    commit(repo, "feat: code", {"a.py": "x\n", **extra})
    git(repo, "switch", "-q", "main")
    title = f"Merge pull request #12 from o/build/{SLUG}"
    git(repo, "merge", "-q", "--no-ff", "-m", title, f"build/{SLUG}")


def test_render_round_trips_quotes_and_unicode() -> None:
    meta = Meta("0001", SLUG, 'a "quoted" \\ café', "done", "#3")
    assert parse(meta.render()) == meta


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("status = ", "TOML"),
        (toml().replace("open", "finished"), "status"),
        (toml() + 'stage = "x"\n', "unknown keys: stage"),
        (toml().replace('number = "0001"\n', ""), "number"),
        (toml().replace('"0001"', "1"), "number"),
        (toml(pr="12"), "PR number"),
    ],
)
def test_unreadable_files_are_refused(text: str, why: str) -> None:
    with pytest.raises(MetaError, match=why):
        parse(text)


@pytest.mark.parametrize(
    ("text", "heading", "why"),
    [
        (toml(slug="0002-y"), "# Intent: A title\n", "folder is 0001-x"),
        (toml(title="Other"), "# Intent: A title\n", "heading says 'A title'"),
        (toml(), "# Bug: A title\nWithdrawn: PO, today: no\n", "there's a Withdrawn: line"),
        (toml(status="withdrawn"), "# Bug: A title\n", "no Withdrawn: line"),
        ("nope", "# Bug: A title\n", "TOML"),
    ],
)
def test_validate_holds_the_file_to_its_folder(tmp_path, text, heading, why) -> None:
    d = tmp_path / SLUG
    d.mkdir()
    (d / "intent.md").write_text(heading)
    assert check_meta([d]) == [], "no file is allowed for now"
    (d / META).write_text(text)
    assert any(why in p.message for p in check_meta([d]))


def test_validate_reports_it(tmp_path, capsys) -> None:
    commit(init_repo(tmp_path / "r"), "x", files(title="Other"))
    assert main(["--root", str(tmp_path / "r"), "check"]) == 1
    assert "heading says" in capsys.readouterr().err


def test_sweep_fills_in_a_repo_with_no_files(repo) -> None:
    commit(repo, "x", files(None) | files(None, "0002-y", upto="intent"))
    merge_build(repo)
    assert main(["--root", str(repo), "sync-changes"]) == 1
    assert not list(repo.glob(f"changes/*/{META}")), "the report writes nothing"
    assert main(["--root", str(repo), "sync-changes", "--fix"]) == 0
    assert read(repo / "changes" / SLUG) == Meta("0001", SLUG, "A title", "done", "#12")
    assert read(repo / "changes/0002-y").status == "open"
    assert sweep(repo) == []


def test_sweep_marks_a_missed_merge_done(repo) -> None:
    commit(repo, "x", files("open"))
    merge_build(repo)
    [step] = steps(repo, "HEAD")
    assert step.skill == "sdlc-next" and "#12" in step.detail
    assert main(["--root", str(repo), "sync-changes", "--fix"]) == 0
    assert read(repo / "changes" / SLUG).status == "done"


def test_sweep_leaves_a_reverted_build_open(repo) -> None:
    commit(repo, "x", files("open"))
    merge_build(repo, "done")
    assert steps(repo, "HEAD")[0].skill == "done"
    git(repo, "revert", "-m", "1", "--no-edit", "HEAD")
    assert steps(repo, "HEAD")[0].skill == "sdlc-build"
    [finding] = sweep(repo)
    assert finding.meta is None and "reopened" in finding.message


def test_sweep_never_turns_done_back_to_open(repo) -> None:
    commit(repo, "x", files("done"))
    [finding] = sweep(repo)
    assert finding.meta is None and "no merge" in finding.message
    assert steps(repo, "HEAD")[0].skill == "done", "make next trusts the file"
    args = ["--root", str(repo), "sync-changes", "0001", "--status", "done", "--pr", "7", "--fix"]
    assert main(args) == 0
    assert read(repo / "changes" / SLUG).pr == "#7"
    assert sweep(repo) == []


def test_a_build_branch_marked_done_is_not_done_until_it_merges(repo) -> None:
    commit(repo, "x", files("open"))
    git(repo, "switch", "-q", "-c", f"build/{SLUG}")
    commit(repo, "feat", files("done"))
    assert sweep(repo) == []
    [step] = steps(repo)
    assert step.skill == "sdlc-pr" and "isn't merged" in step.detail


def test_a_mislaid_file_doesnt_bring_its_status(repo) -> None:
    commit(repo, "x", files(None) | {f"changes/{SLUG}/{META}": toml("0009-z", status="done")})
    assert main(["--root", str(repo), "sync-changes", "--fix"]) == 0
    assert read(repo / "changes" / SLUG) == Meta("0001", SLUG, "A title", "open")


def test_withdrawing(repo) -> None:
    commit(repo, "x", files("open"))
    intent = repo / "changes" / SLUG / "intent.md"
    intent.write_text(intent.read_text() + "Withdrawn: PO, today: no\n")
    assert main(["--root", str(repo), "sync-changes", "--fix"]) == 0
    assert read(intent.parent).status == "withdrawn"


def test_an_unreadable_file_is_left_for_a_person(repo, capsys) -> None:
    commit(repo, "x", files(None) | {f"changes/{SLUG}/{META}": "nope"})
    assert main(["--root", str(repo), "sync-changes", "--fix"]) == 1
    assert capsys.readouterr().out.startswith("decide\t")
    assert steps(repo, "HEAD")[0].skill == "sdlc-next"
    assert main(["--root", str(repo), "sync-changes", "0001", "--status", "open", "--fix"]) == 0
    assert read(repo / "changes" / SLUG).status == "open"


def test_a_shallow_clone_doesnt_guess(repo, tmp_path) -> None:
    commit(repo, "x", files(None))
    merge_build(repo)
    clone = tmp_path / "shallow"
    run(["git", "clone", "-q", "--depth=1", f"file://{repo}", str(clone)], check=True)
    [finding] = sweep(clone)
    assert finding.meta is None and "history" in finding.message


@pytest.mark.parametrize("args", [["--status", "done"], ["9999"], ["0001", "--pr", "3"]])
def test_bad_arguments(repo, args) -> None:
    commit(repo, "x", files("open"))
    assert main(["--root", str(repo), "sync-changes", *args]) == 2


def test_open_leaves_out_done_and_withdrawn(repo, capsys) -> None:
    commit(repo, "x", files("done") | files("open", "0002-y") | files("withdrawn", "0003-z"))
    assert main(["--root", str(repo), "next", "--ref", "HEAD", "--open"]) == 0
    out, err = capsys.readouterr()
    assert [ln.split("\t")[0] for ln in out.splitlines()] == ["0002-y"]
    assert err == "left out: 1 done, 1 withdrawn\n"


def test_status_shows_it(repo, capsys) -> None:
    commit(repo, "x", files("done", pr="#4"))
    main(["--root", str(repo), "status"])
    assert capsys.readouterr().out == f"{SLUG}\tplan\tdone (#4)\n"


@pytest.mark.parametrize(
    ("branch", "text", "code"),
    [
        (f"build/{SLUG}", toml(status="open"), 1),
        (f"build/{SLUG}", toml(status="withdrawn"), 1),
        (f"build/{SLUG}", "nope", 1),
        (f"build/{SLUG}", toml(status="done"), 0),
        (f"build/{SLUG}", None, 0),
        (f"plan/{SLUG}", toml(status="open"), 0),
    ],
)
@pytest.mark.parametrize("bug", [False, True], ids=["planned", "fast path"])
def test_ci_holds_a_build_pr_to_done(tmp_path, branch, text, code, bug) -> None:
    if bug and branch.startswith("plan/"):
        pytest.skip("the fast path is only on build/")
    d = tmp_path / "changes" / SLUG
    d.mkdir(parents=True)
    for name in ("bug.md", "spec.md") if bug else ("intent.md", "spec.md", "plan.md"):
        (d / name).write_text("x\n")
    if text:
        (d / META).write_text(text)
    script = str(REPO / ".sdlc/scripts/check-plan-first.sh")
    result = run(["bash", script, branch], cwd=tmp_path, input="src/a.py\n")
    assert result.returncode == code, result.stdout
    if code:
        assert "::error::" in result.stdout and "change.toml" in result.stdout


def test_the_roadmap_row_and_the_status_agree(tmp_path) -> None:
    from sdlc.roadmap import check_roadmap

    commit(init_repo(tmp_path / "r"), "x", files("open"))
    root = tmp_path / "r"
    intent = root / "changes" / SLUG / "intent.md"
    intent.write_text("# Intent: A title\n\nMilestone: M1\n")
    (root / "docs").mkdir()
    (root / "docs/roadmap.md").write_text(
        "# R\n\n## M1: One · `draft`\n\n### Changes\n\n| Change | Summary | Status |\n"
        f"|---|---|---|\n| [{SLUG}](../changes/{SLUG}/) | s | ✅ done |\n"
    )
    assert any("change.toml says open" in p.message for p in check_roadmap(root))
    (intent.parent / META).write_text(toml(status="done"))
    assert not any("change.toml" in p.message for p in check_roadmap(root))
