---
name: spec
description: Stage 2 (Design). Turn an accepted changes/<slug>/intent.md into changes/<slug>/spec.md, applying the policy skills and flagging conflicts. Use when asked to write or regenerate a spec, or by the spec-from-intent CI job.
---

# Write a spec from an intent

Input: a change folder, `changes/<slug>/`, that contains an accepted `intent.md`.

1. Read `intent.md`, `CLAUDE.md` and the code the intent touches.
2. Copy `templates/spec.md` to `changes/<slug>/spec.md` and fill in every section:
   - **Requirements:** numbered (R1, R2, …). Each one is testable on its own.
   - **Acceptance criteria:** quantifiable checks, e.g. "`make check` exits 0" or "command prints X".
   - **Policy concerns:** apply every policy skill in `.claude/skills/` (e.g. `security-policy`). Flag anything the intent asks for that a policy restricts, and any case where two policies contradict each other. Write "None" only if you checked and found nothing.
3. **Requirements that rely on people writing text in a set format.** When the change reads text that a person writes, such as an intent section or a list in a markdown file, don't expect the product owner to follow formatting rules. Write requirements so that:
   - **Claude owns the format.** The template and the skill that writes the file state the convention, and Claude applies it. The product owner talks and decides; they never format.
   - **Parsing fails safe.** Text the parser doesn't recognise is treated as the riskier case (for example "has open questions"), never as "nothing there".
   - **CI flags what it can't read**, as a warning rather than an error, so Claude or the engineer fixes the wording and the product owner never has to.
4. Do not resolve open questions or policy conflicts yourself. List them for the product owner.
5. Run `make validate`.

Do not write a plan or code.
