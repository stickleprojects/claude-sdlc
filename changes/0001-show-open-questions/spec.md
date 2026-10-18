# Spec: Show open questions in `sdlc status`

<!-- Stage 2 (Design). Generated from intent.md with the policy skills applied.
Reviewed by the product owner; flagged concerns resolved with policy owners. -->

Intent: ./intent.md

## Summary

`sdlc status` prints one tab-separated line per change. It gains a third field: the number of open questions in that change's `intent.md`. An open question is one bullet item (`- ` or `* `) under the `## Open questions` heading. A section with no bullets counts as zero. The command only reports the count. `sdlc check` is unchanged and does not fail on open questions.

## Requirements

- R1. For each change folder, `sdlc status` prints `<folder>\t<stage>\t<count>`, with `<count>` as a base-10 integer. The first two fields keep their current content and order.
- R2. `<count>` is the number of lines under `## Open questions` in `intent.md` that start at column 0 with `- ` or `* `. Indented (nested) bullets are not counted. Lines inside HTML comments count like any other line. The section ends at the next `##` heading or at the end of the file.
- R3. If the section has no such lines (for example it only says "None."), `<count>` is `0`.
- R4. Lines outside the `## Open questions` section never contribute to the count.
- R5. Output stays one line per change, with exactly two tab characters per line.
- R6. A change folder with no `intent.md`, or an `intent.md` without an `## Open questions` heading, is still listed and reports `0`. The command does not crash or print to stderr.
- R7. `sdlc status` exits 0, as it does today.
- R8. `sdlc check` behaves as before. It does not fail on open questions, and existing change folders stay valid without edits.
- R9. The count logic lives in `src/sdlc/artifacts.py` as a function that can be tested on its own, next to `headings`. The CLI only formats the output.
- R10. No new dependencies are added.
- R11. `intent.md` is read leniently: bytes that are not valid UTF-8 are replaced, and counting continues. `sdlc status` never crashes on file content.
- R12. Under `## Open questions`, `templates/intent.md` says to write `None.` when there are no open questions.

## Acceptance criteria

- A1. Given an `intent.md` whose `## Open questions` section holds three bullets, `sdlc status` prints a line ending in `\t3` for that change (R1, R2).
- A2. Given a section that holds only `None.`, the line ends in `\t0` (R3).
- A3. Given `-` and `*` bullets mixed in one section, both kinds are counted (R2).
- A4. Given bullets in `## Constraints` and none under `## Open questions`, the count is `0` (R4).
- A5. Given bullets under `## Open questions` followed by another `##` section with more bullets, only the first section's bullets are counted (R2, R4).
- A6. Given a folder with no `intent.md`, `sdlc status` still prints a line for it, ends in `\t0`, and exits 0 (R6, R7).
- A7. Every output line of `sdlc status` splits on `\t` into exactly 3 fields, and field 3 matches `^[0-9]+$` (R1, R5).
- A8. The existing change `0001-show-open-questions` (section says `None.`) prints `0001-show-open-questions\tspec\t0` once this spec exists (R1, R3).
- A9. New tests in `tests/` cover A1 to A6, and `make check` exits 0 and ends with `ok: N change(s) valid` (R8, R9).
- A10. `pyproject.toml` and `uv.lock` have no dependency changes (R10).
- A11. Given a nested bullet (`  - detail`) under a top-level bullet, the count is `1` (R2).
- A12. Given an `intent.md` containing the byte `0xff` and two bullets, `sdlc status` prints `\t2` and exits 0 (R11).
- A13. `templates/intent.md` contains `None.` guidance under `## Open questions`, and the template test still passes (R12).

## Policy concerns

Checked against `security-policy`:

- Secrets: the change reads and prints only local markdown files. It handles no secrets.
- External input: `intent.md` is local, repo-controlled input. The parser must tolerate any text, including missing headings, empty files and non-UTF-8 content, without crashing. R6 covers missing headings and files, and R11 covers non-UTF-8 content.
- Dependencies: none added (R10).
- Personal data: none collected or stored.
- Enforcement: R10 (no new dependencies) has no hook or CI check behind it. It relies on review of the diff. The other rules are covered by `make check`.

No policy restricts the intent, and no two policies conflict.

## Out of scope

- Making `sdlc check` fail on open questions (a separate, later change, per the intent).
- Listing or printing the text of the questions.
- Counting numbered items (`1.`), nested bullets, or checkbox state.
- Removing HTML comments before counting.
- Any other change to `templates/intent.md`, beyond R12.
- Any change to `spec.md` or `plan.md` parsing.

## Product owner decisions

The product owner resolved the questions raised when this spec was generated:

- Q1. Bullets inside HTML comments: counted as written, with no comment stripping (R2).
- Q2. Nested bullets: not counted; only top-level bullets count (R2, A11).
- Q3. A change with no `intent.md` reports `0`. `sdlc check` already flags a missing intent, and the field stays an integer (R6, A7).
- Q4. The template gains `None.` guidance (R12, A13).
- Q5. Non-UTF-8 content is read leniently, never a hard error (R11, A12).
