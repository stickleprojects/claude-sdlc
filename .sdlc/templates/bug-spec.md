# Spec: <short title> (bug)

<!-- Stage 2 (Design) for a bug. A short spec generated from bug.md: what must be true once
it's fixed, and one acceptance test per symptom. The plan's first step is the failing test. -->

Bug: ./bug.md

## Requirements

Numbered, testable requirements, one `- R<n>.` bullet each: the correct behaviour, one per
symptom in bug.md. The checks read only this form:

- R1. <the correct behaviour>.

## Acceptance criteria

One check per symptom, each a test that fails today and passes once fixed, one `- AC<n> (R…):`
bullet each (`- A<n>` also reads), not a numbered list:

- AC1 (R1): the test `test_export_shows_finished` fails before the fix and passes after.

<!-- Add "## Policy concerns" if a policy skill applies to the fix (e.g. it touches user data
or credentials), and "## Out of scope" if the fix deliberately leaves something alone. -->
