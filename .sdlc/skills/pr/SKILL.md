<!-- The frontmatter for this skill is in .claude/skills/sdlc-pr/SKILL.md, which Claude Code reads. Projects change this
file with an override in .sdlc-local/ (see .sdlc/docs/overrides.md), never by editing it. -->

# Work through the review on a PR

This is the one skill to remember for PR reviews. It works out what kind of PR it is and hands over to the skill that knows how to walk this person through it. Never approve or merge a PR: a person does that.

## 1. Which PR

- **A number was given:** use it.
- **No number:** list the open PRs (`gh api 'repos/{owner}/{repo}/pulls?state=open&per_page=100'`). For each, read the latest review summary comment (`gh api repos/{owner}/{repo}/issues/<N>/comments`, the one starting `Review summary`) and count its open findings. Ask which one with AskUserQuestion: PRs with open findings first, each option saying its title, its kind and how many findings are open. If none has open findings, say which PRs are waiting for a merge, and stop.

## 2. Hand over

Read the PR (`gh api repos/{owner}/{repo}/pulls/<N>`) and pick by the type in its title:

| Title starts with | Who decides | Skill |
|---|---|---|
| `intent`, `bug`, `spec` | the product owner | `sdlc-po-review` |
| `fix(<slug>)` carrying the change's `bug.md` or `spec.md` (the bug fast path, #148) | both: the product owner for the bug and spec, then the engineer for the code | `sdlc-po-review`, then `sdlc-review-findings` |
| anything else (`plan`, `feat`, `fix`, `chore`, …) | the engineer | `sdlc-review-findings` |

To tell a fast-path PR from a plain fix, list its files (`gh api repos/{owner}/{repo}/pulls/<N>/files --jq '.[].filename'`). For a fast-path PR, run the product owner's walkthrough first: its findings are about what the fix should do, and they can change the code. Then the engineer's, on the threads left. If one person holds both roles, say so and run both in turn. GitHub doesn't require the product owner's approval yet (that's #151, path-based CODEOWNERS), so when the engineer is the one running this, say the PR still needs the product owner's approval on the bug and spec before it merges.

Say which in one line ("PR 12 is a spec PR: walking you through it as the product owner"), then invoke that skill with the Skill tool, passing the PR number, and follow it.

If the person isn't the one who decides (an engineer running `/sdlc-pr` on a spec PR, say), say who decides and ask whether to go on anyway or stop.

## 3. Afterwards

When the skill has finished, run the routing check in `.sdlc/skills/routing.md` for the PR's change, and say what comes next once the PR merges: for example, "once this spec merges, run /sdlc-plan".
