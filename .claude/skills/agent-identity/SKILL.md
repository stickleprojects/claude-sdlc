---
name: agent-identity
description: How Claude acts on GitHub, under its own identity or the person's: who commits, how comments are signed, and the rules that stop agents triggering each other or fighting over a branch. Apply whenever you commit, push, open or update a PR, or post a comment or reply on GitHub.
user-invocable: false
---

# Acting on GitHub as the agent

Claude sessions can run under their own GitHub identity, a GitHub App that shows as `<app>[bot]` (see `docs/agent-identity.md`). When they do, the environment has `SDLC_AGENT_IDENTITY` set, and `git` and `gh` already commit, push and comment as the App. You don't need to log in or pass tokens.

Check which applies: `echo "${SDLC_AGENT_IDENTITY:-person}"`.

## Who acts as whom

One App, the identity `agent`, serves every local Claude session and the spec workflow. It is never the person. The CI reviewer and the `@claude` bot are a different identity (`claude[bot]`, from the review and mention workflows); they aren't yours to act as.

## Signing what you post

- **As the agent** (`SDLC_AGENT_IDENTITY` set): end each comment, reply and PR body with `— Claude`. When you record someone's decision, say whose it is, in plain text: "Product owner decided: …".
- **As the person** (not set): the post appears under their account, so end it with `(posted from Claude Code)`.

## Commits

As the agent, `git` already sets the author to the App. Add this trailer to the commit message, after the body and before any attribution lines:

```
Requested-by: <$SDLC_AGENT_REQUESTED_BY>
```

Add files by explicit path, never `git add -A` or `git add .`.

## Right after opening a PR

Run `scripts/auto-merge.sh <N>` on the PR you just opened, and pass on the line it prints. It turns on auto-merge only where the repo opted in (`SDLC_AUTO_MERGE`) and a person's approval is still required, so the approval stays the gate. Otherwise it says why it didn't, or prints nothing when the repo hasn't opted in. Run it straight away: GitHub refuses once a PR is approved and green. Never enable auto-merge any other way (`gh pr merge --auto`, the GraphQL mutation); a hook blocks both.

## Rules that prevent loops and conflicts

1. **Act only when a person asks,** in this session. Never start work because a bot commented, a review finished or a check failed, unless the person asked you to watch for it.
2. **Never @-mention anyone** in comments, replies, commits or PR bodies, bots and people alike. Write a name without the `@`. Above all, never write `@claude`: it starts the mention bot, which is a second agent.
3. **One actor per finding.** If a thread has an `@claude` comment, the bot owns it; leave it.
4. **Before every push, fetch and merge.** Run `git fetch origin <branch>` and `git log --format='%h %an %s' HEAD..origin/<branch>`. Anything there was pushed by someone else: a person, the bot, or another session using this same identity. Show it, merge it (never rebase a pushed branch), re-run `make check`, then push.
5. **Never force-push** (a hook blocks it), and never delete a branch someone else pushed to.
6. **Approving and merging stay with people.** With your own identity, branch protection requires a person's approval. Never ask for a workaround, and never approve anything, even someone else's PR. Auto-merge through `scripts/auto-merge.sh` doesn't change this: it merges only after a person approves.
