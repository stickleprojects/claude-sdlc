---
name: next
description: Show where every change is and what's next, then offer to start the next step. Use when someone says "/next", "/next 0002", "what's next", "where are we", "what's waiting on me" or "status of 0002".
---

# What's next

1. **Find where each change is,** following steps 1 and 3 of `.claude/skills/routing.md`: `make next REF=origin/main`, plus open PRs and build branches.
2. **Show a short table:** one row per change that isn't done (or just the named change): the change, where it is, the next step, and who it's waiting on (the person, the product owner, the engineer, or a workflow). Link any open PR. List done and withdrawn changes in one line at the end, if there are any. Show an `out of date:` change as gone back a step, with what changed.
3. **Offer the next steps the person can take now,** with AskUserQuestion: up to four, the most advanced change first, each naming the skill it runs (for example "Build 0002-breadcrumbs (/build)", "Work through the review on PR 14 (/pr 14)"). Leave out steps waiting on someone else.
4. **On a choice,** invoke that skill with the Skill tool, passing the change or PR number, and follow it.
