---
name: po-review
description: Internal; reached through /pr for intent, bug and spec PRs. Guide the product owner through the PR's review: explain each finding in plain language, with the quoted text, collect their decisions, apply them to the artifact and reply on GitHub.
user-invocable: false
---

# Product owner review of a PR

The product owner decides; you explain and do the typing. This is the main way findings get handled: the product owner talks to you in the terminal and doesn't need to comment on GitHub. You walk them through the findings, edit the artifact, push, and reply on every thread. The acceptance is recorded on GitHub, where approving and merging the PR **is** the acceptance. Never approve or merge the PR yourself.

Replies, resolving threads and checking for bot commits follow the shared rules in `.claude/skills/review-findings/SKILL.md` (sections *One actor per finding*, *Before you push* and *Reply and resolve*). Read them before step 4, along with the `agent-identity` skill (signatures, commit trailers, no @-mentions).

## 1. Load the PR

Use the REST API: `gh pr view`, `gh pr edit` and `gh issue view` can fail in orgs hit by the Projects (classic) GraphQL deprecation.

```
gh api repos/{owner}/{repo}/pulls/<N>                    # title, head branch, body
gh api repos/{owner}/{repo}/pulls/<N>/files
gh api repos/{owner}/{repo}/pulls/<N>/comments           # inline findings and replies
gh api repos/{owner}/{repo}/issues/<N>/comments          # the review summary and any @claude comments
```

Work out the change folder (`changes/NNNN-name/`) and the stage: an `intent:` PR or a `spec:` PR. For any other kind of PR, say this skill isn't for it, and stop.

Check out the PR's head branch and pull it.

## 2. Brief the product owner (one short message)

- What the change is, in one sentence taken from `intent.md`.
- What this PR asks them to accept: the intent or the spec.
- How many open items there are: unresolved review findings, plus anything under "Open questions".
- For a spec, what it leaves out: its **Out of scope** items, quoted. Leaving something out is a product decision, so it comes before the rest.

## 3. Go through each item, one at a time

Skip findings that are already resolved: ones with a reply that says how they were handled, or ones the latest summary marks resolved. Skip findings the GitHub bot owns (an `@claude` comment on the thread), and say which ones you skipped. For each remaining item:

1. **Quote** the exact artifact text it refers to, such as the criterion or requirement, with its ID.
2. **Explain** the problem in plain language: what would go wrong, and when.
3. **Recommend** a fix, with the replacement wording.
4. **Ask** for a decision with AskUserQuestion: accept the recommendation, keep the text as it is (with a reason), or write their own wording.

Findings that belong to the engineer (plan or code) get noted and handed on, not decided here.

## 4. Apply and record

1. Edit only the artifact under review (`intent.md` or `spec.md`). Record each decision where the template expects it. For a spec, that's the "Product owner decisions" section.
2. Run `make validate`.
3. Check the branch for commits pushed by anyone else (*One actor per finding*). Then commit the artifact by explicit path (`git add changes/<slug>/<artifact>.md`) with `<stage>: address review (product owner decisions)`, and push.
4. Pushes don't start a review, so ask for one: `gh api repos/{owner}/{repo}/issues/<N>/labels -f "labels[]=review"`.
5. Reply on every thread you handled with what was decided ("Product owner decided: …"), signed `— Claude` under the agent identity or `(posted from Claude Code)` under the person's, then resolve it (*Reply and resolve*). If resolving fails, tell the product owner which threads to resolve by hand.

## 5. Hand back the gate

Tell the product owner:
- what changed, as a short list;
- which threads are resolved, and any they need to resolve by hand;
- that a fresh review is on its way, so they should check that its summary has no open findings;
- that they accept by merging the PR on GitHub once its checks are green (in team mode, a code owner approves first). You can't merge it for them: a hook blocks the agent from merging or approving.
