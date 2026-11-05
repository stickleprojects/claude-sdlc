---
name: pr
description: Work through the review on a PR, whatever its kind. Routes an intent, bug or spec PR to the product owner's walkthrough (po-review) and a plan or code PR to the engineer's (review-findings). With no number, lists the PRs waiting on the person and asks which. Use when someone says "/pr", "/pr 12", "handle the review on PR 12", "walk me through PR 12", "address the review" or "what's on my PRs".
---

# Work through the review on a PR

This is the one skill to remember for PR reviews. It works out what kind of PR it is and hands over to the skill that knows how to walk this person through it. Never approve or merge a PR: a person does that.

## 1. Which PR

- **A number was given:** use it.
- **No number:** list the open PRs (`gh api 'repos/{owner}/{repo}/pulls?state=open&per_page=100'`). For each, read the latest review summary comment (`gh api repos/{owner}/{repo}/issues/<N>/comments`, the one starting `Review summary`) and count its open findings. Ask which one with AskUserQuestion: PRs with open findings first, each option saying its title, its kind and how many findings are open. If none has open findings, say which PRs are waiting for a merge, and stop.

## 2. Hand over

Read the PR (`gh api repos/{owner}/{repo}/pulls/<N>`) and pick by the type in its title:

| Title starts with | Who decides | Skill |
|---|---|---|
| `intent`, `bug`, `spec` | the product owner | `po-review` |
| anything else (`plan`, `feat`, `fix`, `chore`, …) | the engineer | `review-findings` |

Say which in one line ("PR 12 is a spec PR: walking you through it as the product owner"), then invoke that skill with the Skill tool, passing the PR number, and follow it.

If the person isn't the one who decides (an engineer running `/pr` on a spec PR, say), say who decides and ask whether to go on anyway or stop.

## 3. Afterwards

When the skill has finished, run the routing check in `.claude/skills/routing.md` for the PR's change, and say what comes next once the PR merges: for example, "once this spec merges, run /plan".
