# Working on a change in its own copy of the code

`work-on.sh` gives a change its own copy of the code (a git worktree) on the right branch, with a Claude session that knows which change it's for. Several changes can run side by side without touching each other's files. `tidy-worktrees.py` removes the copies once their work has merged.

## Work on a change

```
.sdlc/scripts/work-on.sh 0063
```

From anywhere in the repo, this:

1. **Works out the branch.** It takes the change's one unmerged branch (`plan/0063-…`, `build/0063-…`), and with none, the next stage `make next` gives. A tooling change (`Kind: tooling`) goes straight to `build/`. It stops and says what to run instead when that isn't clear:
   - the change has several unmerged branches;
   - it's a bug that could take the fast path or be planned;
   - its next step is a spec, which CI writes;
   - it's done or withdrawn.

   Name the branch to choose: `work-on.sh 0063 build/0063-garden`. A number alone is never taken as a branch name.
2. **Makes or reopens the copy**, at `.claude/worktrees/0063` in the main checkout. Running it again for the same change reopens the same copy. A change keeps one copy through its stages: once a stage's PR has merged, the same command moves the copy on to the next stage's branch. It doesn't move the copy while that PR is open, while the copy has uncommitted files, or while it has commits that aren't on main. It never opens a copy a Claude session is running in.
3. **Starts Claude in it**, in this terminal, through `agent-session.sh`. So the session uses the agent's GitHub identity when that is set up, and `SDLC_CHANGE` names the change. A plain `/sdlc-build` or `/sdlc-next` in that session means that change. It carries none of the calling session's identity (`GH_TOKEN`, git author, Claude's own variables).

With `--no-start`, or with no terminal (run from a Claude session's tools), it sets up the copy and prints the command that starts Claude in it.

## Hand over the first prompt

When a session finds work that belongs in its own change and the person asks for that work to start, it can hand over the first prompt:

```
.sdlc/scripts/work-on.sh --prompt-file /path/to/prompt.md 0077
.sdlc/scripts/work-on.sh --prompt '/sdlc-build' 0063
.sdlc/scripts/work-on.sh --prompt-file - 0077 <<'EOF'
/sdlc-intent bug: the lift stutters on arrival.
Evidence: changes/0072-…/build.md, M1's notes.
EOF
```

The new session starts on that text at once. The text gets a header saying another Claude session handed it over at the person's request, and that any decision or approval quoted in it is reported, not given. The new session still asks wherever it must. In single quotes or a quoted heredoc (`<<'EOF'`), `$`, backticks and `!` stay as typed. The text never goes into the repo: it's held in a file only you can read, which is deleted once read.

## Clean up

```
.sdlc/scripts/tidy-worktrees.py        # what would be removed, and why the rest stay
.sdlc/scripts/tidy-worktrees.py --go   # remove them
```

A copy is removed only when:
- its branch has a merged PR, and its commit is part of that PR and of `origin/main` (so a new copy with no commits stays);
- the branch has no open PR;
- nothing in it is uncommitted or untracked;
- it isn't the main checkout, locked, or the folder you're in;
- no process works in it (a Claude session, a build).

**Squash or rebase merges:** both the move to the next stage and the clean-up need the copy's commit to be on `origin/main`. A squash or rebase merge puts new commits there instead, so both refuse and change nothing: remove a finished copy yourself with `git worktree remove .claude/worktrees/<number>`.

Ignored files you made by hand (notes, mock-ups; not caches, logs or test reports) are first copied to `~/.local/state/removed-worktrees/<repo>/<time>/`. The branches stay: `git branch -d <branch>` deletes a merged one.

## Needs

- `git`, plus `gh` signed in (to read PRs);
- Linux's `/proc` or `lsof` (macOS), to see which folders a Claude session runs in. With neither, `work-on.sh` refuses rather than guess;
- bash 3.2 or later, so stock macOS will do;
- for `work-on.sh` to start Claude, a terminal and `claude` on `PATH`.

Opening a new terminal window is up to your desktop: a launcher can run `work-on.sh` in a new window.
