---
name: intent
description: Stage 1 (Plan). Brainstorm a problem with the originator and draft changes/<slug>/intent.md, or changes/<slug>/bug.md for a bug found in testing or use. Use when someone describes a new problem, feature idea, request or bug that has no change folder yet.
---

# Draft an intent (or a bug report)

**Is it a bug?** If the person describes something that worked differently from what was specified or expected (found in testing or use), it's a bug: use the lighter path in [For a bug](#for-a-bug). If it's new behaviour, or you're not sure, ask.

1. Act as a business analyst. Ask short questions until you understand: the problem and who has it, the outcome that would count as success, the users and systems affected, constraints, and what is still unknown. Ask one round at a time; don't invent answers.
2. Pick a short kebab-case name and run `make new-change NAME=<name>`. It prints the new `intent.md` path.
3. Fill in every section of that file from the conversation. Put anything unresolved under **Open questions** rather than guessing.
4. Run `make validate`.
5. Show the originator the file and ask for corrections. Remind them that the product owner accepts it by approving the PR. Merging that PR triggers spec generation.

Do not write a spec, a plan or any code at this stage.

## For a bug

1. Ask only what `bug.md` needs: what happens, what should happen, the steps to reproduce (and whether it happens every time), and where it was seen. Use made-up or described data, never real personal data.
2. Run `make new-change NAME=<name> TYPE=bug`. It prints the new `bug.md` path; there is no `intent.md`.
3. Fill in every section, then run `make validate`.
4. Show the person the file and ask for corrections. Merging the PR triggers a short spec: requirements and one acceptance test per symptom.

## Committing

When you commit, add the change's files by explicit path (`git add changes/<slug>/intent.md` or `…/bug.md`), never `git add -A` or `git add .`.
