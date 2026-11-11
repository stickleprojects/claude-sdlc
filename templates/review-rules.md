# Review rules

<!-- Your project's own rules for the Claude review. Copy this file to docs/review-rules.md and
replace the example. REVIEW.md's "Project rules" pass applies each rule to every PR's diff.
docs/review-rules.md is yours: the sync never touches it, so add project rules here rather than
by editing REVIEW.md, whose edits would clash with every framework update.

One rule per bullet. Say what breaks the rule, its severity (Important or Nit; Important when
left out), and who decides when it isn't the engineer. Point at the doc that owns a rule rather
than copying it. -->

- **Architecture:** code under `core/` never touches the UI or the scenes (see `docs/architecture.md`). Important.
