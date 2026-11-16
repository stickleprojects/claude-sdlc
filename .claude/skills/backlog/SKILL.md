---
name: backlog
description: Prioritise claude-sdlc's open issues with priority, impact and effort labels. Use when Kieron asks to review, reprioritise or label the backlog, or asks what to work on next across the issues.
---

# Prioritise the backlog

For this repo only (the framework's own issues, #204); the sync never ships it. Every open issue gets three labels: `priority: P1|P2|P3`, `impact: high|medium|low` (what fixing it gains, or what leaving it costs) and `effort: S|M|L` (one PR, two or three, a design and several). `cost` is a different label: it means the work uses the Claude subscription or CI minutes. `scripts/backlog-labels.sh` does all the GitHub work; read its header for the commands.

1. **Labels and issues.** Run `scripts/backlog-labels.sh labels` (it creates or updates the nine labels), then `scripts/backlog-labels.sh list`. Read the body of each issue you're about to propose for (`gh api repos/{owner}/{repo}/issues/<n> --jq .body`), and its latest comments when it's been worked on.
2. **Where to start from.** The labels already on an issue. On the first run, also `docs/issue-priorities.md` if it exists: its P1/P2/P3 tables, its Impact column, and its Cost column, which is effort. Issues it doesn't mention, or that have changed since it was written, get a fresh proposal; closed ones drop out.
3. **Propose, in a file.** Write a table to a temporary file (`mktemp --suffix=.md`) and give Kieron its path. One row per open issue: number, title, priority, impact, effort, its current labels, and a one-line reason. Mark each row whose priority changes from one it already had, since those get a comment. Put the P1s first. Under the table, list the issues you're least sure of, each with what would settle it. Don't put the table in the chat or in AskUserQuestion.
4. **Kieron changes it.** He edits the file or tells you what to change. Re-read the file, apply his changes, and ask again until he approves it. Never label from a proposal he hasn't approved.
5. **Apply.** For each row, run `scripts/backlog-labels.sh set <n> <P> <impact> <effort> "<reason>"`. A changed priority needs the reason, and the script posts it as the issue's only comment. A first priority, or an unchanged one, posts nothing. Stop at the first error and say which issues are done.
6. **Report:** how many issues are in each priority, the priorities that changed, and the P1s in order of what to do first.
7. **After the first run,** once every issue in `docs/issue-priorities.md` has its labels, ask Kieron whether to delete that file. It's untracked, so git can't bring it back.

`gh` acts as Kieron unless `SDLC_AGENT_IDENTITY` is set; the script signs its comments either way.
