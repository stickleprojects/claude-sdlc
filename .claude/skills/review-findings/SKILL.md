---
name: review-findings
description: Work through the Claude review's findings on a code PR with the engineer, one at a time, then edit, push, reply on every thread and resolve it. Also holds the shared rules for replying to and resolving review threads, which po-review follows. Use when someone says "handle the review findings on PR N", "go through the review on #N" or "address the review".
---

# Work through the review findings on a PR

The person talks to you in the terminal; they don't need to use GitHub for feedback. You walk them through the findings, make the changes, push, and answer every thread on GitHub. Never approve or merge the PR: a person merges.

For an `intent:` or `spec:` PR, use the `po-review` skill instead. It follows the shared rules below.

## 1. Load the PR

Use the REST API. `gh pr view`, `gh pr edit` and `gh issue view` can fail in orgs hit by the Projects (classic) GraphQL deprecation.

```
gh api repos/{owner}/{repo}/pulls/<N>                    # title, head branch
gh api repos/{owner}/{repo}/pulls/<N>/comments           # inline findings and replies
gh api repos/{owner}/{repo}/issues/<N>/comments          # the review summary and any @claude comments
gh api repos/{owner}/{repo}/pulls/<N>/files
```

Check out the PR's head branch and pull it.

## 2. Go through each open finding, one at a time

Skip a finding that is already resolved: one with a reply saying how it was handled, or one the latest summary marks resolved. Skip one the bot owns (see [One actor per finding](#one-actor-per-finding)).

For each remaining finding:

1. **Quote** the code or text it refers to, and the finding.
2. **Explain** what would go wrong, and when.
3. **Recommend** a fix.
4. **Ask** for a decision with AskUserQuestion: fix as recommended, fix another way, or dismiss with a reason.

Collect every decision first. Then make the changes.

## 3. Apply, push and reply

1. Make the changes. Run `make check`; it must exit 0.
2. Follow [Before you push](#before-you-push), then commit the files you changed by explicit path and push.
3. Reply on every thread you handled, then resolve it ([Reply and resolve](#reply-and-resolve)).
4. Tell the person what changed, which threads are resolved, any you couldn't resolve, and that a fresh review is on its way.

---

# Shared rules for review threads

## One actor per finding

A finding is handled by one actor: either this session, or the GitHub bot (`@claude`). Never both, because two agents fixing the same finding produce conflicting commits.

- **A finding the bot owns** has an `@claude` comment on its thread, or an `@claude` PR comment that names it. Leave it to the bot, and tell the person which ones you skipped.
- **Before you push,** fetch and check whether anyone else has pushed to the branch: the bot (`claude[bot]`, `github-actions[bot]`), a person, or another session under the agent's own identity (`<app>[bot]`). Any commit on the remote that you don't have counts, whoever wrote it.

  ```
  git fetch origin <branch>
  git log --format='%h %an %s' HEAD..origin/<branch>
  ```

  If there are new commits, show them to the person, merge them in (never rebase), re-run `make check`, and then push.

## Before you push

Run the check above. Add files by explicit path (`git add <file>…`), never `git add -A` or `git add .`. Follow the `agent-identity` skill (`.claude/skills/agent-identity/SKILL.md`) for commit trailers, and never @-mention anyone.

## Reply and resolve

A thread is closed with a reply that says what was decided or changed. Never resolve one silently.

1. **Reply** on the thread, signed as the `agent-identity` skill says. Under the agent's own identity (`SDLC_AGENT_IDENTITY` set), end with `— Claude (<persona>)`. Otherwise the reply appears under the person's GitHub account, so end it with `(posted from Claude Code)`:

   ```
   gh api repos/{owner}/{repo}/pulls/<N>/comments/<comment-id>/replies \
     -f body="Fixed in <sha>: <what changed>. — Claude (dev)"
   ```

   For a dismissed finding, say why it was kept as it is.
2. **Resolve** the thread with the GraphQL `resolveReviewThread` mutation. First find the thread id for the comment:

   ```
   gh api graphql -F owner={owner} -F repo={repo} -F n=<N> -f query='
     query($owner:String!, $repo:String!, $n:Int!) {
       repository(owner:$owner, name:$repo) { pullRequest(number:$n) {
         reviewThreads(first:100) { nodes { id isResolved comments(first:1) { nodes { databaseId } } } }
       } } }'
   gh api graphql -f id=<thread-id> -f query='
     mutation($id:ID!) { resolveReviewThread(input:{threadId:$id}) { thread { isResolved } } }'
   ```

   **If GraphQL fails**, for example with the Projects (classic) deprecation error some orgs get, leave the thread unresolved. Tell the person which threads to resolve by hand on GitHub; your reply is already on each one.
3. **Ask for a fresh review** of the push by adding the `review` label (pushes alone don't start one):
   `gh api repos/{owner}/{repo}/issues/<N>/labels -f "labels[]=review"`.
