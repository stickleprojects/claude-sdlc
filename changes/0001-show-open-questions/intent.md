# Intent: Show open questions in `sdlc status`

<!-- Stage 1 (Plan). Drafted by Claude from the originator's brainstorm, corrected by the
originator, accepted by the product owner. Merging this file triggers spec generation. -->

Originator: Kieron
Product owner: Kieron

## Problem

Before accepting an intent, a product owner has to make sure its open questions are resolved. Today `sdlc status` only shows which stage each change has reached. To find out whether a change still has unanswered questions, you have to open each `intent.md` and read it. As the number of changes grows, unresolved questions are easy to miss, and a change can move to Design with them still unanswered.

## Proposed outcome

`sdlc status` shows, for each change, how many open questions its `intent.md` still lists, next to the stage. A product owner can see at a glance which changes are blocked on decisions, without opening any files.

Decisions made while drafting (product owner):

- One open question is one bullet item (`- ` or `* `) under `## Open questions`.
- A section with no bullets, such as one that just says "None", counts as zero.
- This change only reports the count. Making `sdlc check` fail on open questions is a separate, later change.

## Affected users and systems

- Users: product owners, who accept intents, and engineers checking whether a change is ready to plan.
- Systems: the `sdlc` CLI only (`status` command), plus its tests. The artifact templates may need a convention for listing questions.

## Constraints

- No new dependencies.
- The output of `sdlc status` must stay easy to parse: one line per change, tab-separated.
- Existing change folders must keep working without edits.

## Open questions

None.
