---
name: intent
description: Stage 1 (Plan). Brainstorm a problem with the originator and draft changes/<slug>/intent.md. Use when someone describes a new problem, feature idea or request that has no change folder yet.
---

# Draft an intent

1. Act as a business analyst. Ask short questions until you understand: the problem and who has it, the outcome that would count as success, the users and systems affected, constraints, and what is still unknown. Ask one round at a time; don't invent answers.
2. Pick a short kebab-case name and run `uv run sdlc new <name>`. It prints the new `intent.md` path.
3. Fill in every section of that file from the conversation. Put anything unresolved under **Open questions** rather than guessing.
4. Run `make validate`.
5. Show the originator the file and ask for corrections. Remind them that the product owner accepts it by approving the PR. Merging that PR triggers spec generation.

Do not write a spec, a plan or any code at this stage.
