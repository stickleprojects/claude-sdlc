# Build: <short title>

<!-- Stage 3 (Build), written by the /sdlc-build skill once plan.md is merged. It splits the plan into
milestones, one per session. The person reviews this file as a draft and approves it before any code
is written. After that, each session checks the previous one (committed, pushed, Done-when passing)
before starting its own milestone. -->

- **Change:** `changes/<slug>/` ([spec](spec.md), [plan](plan.md))
- **Branch:** `build/<slug>`
- **Built against:** `origin/main` at `<sha>` (<date>)
- **Coverage:** `make coverage`; <suite>: <thresholds, e.g. 90% lines, 80% branches>, one per suite
- **First demo:** after M<n>: <what a person can first see or click> <!-- or "none: backend only", with the reason -->
- **Locked tests:** none <!-- bug fixes: `<sha>`: <test files>, from the failing-test commit -->
- **Status:** draft, awaiting approval <!-- draft, awaiting approval | in progress | PR open (#N). Whether it merged comes from the PR, not from here. -->
- **Approved:** not yet <!-- <who>, <date>, set when the status moves to in progress -->

## Questions before approval

<!-- Everything the person must decide before approving, each with its options and a recommendation:
plan gaps, readings of an ambiguous plan, deviations, a backend-first order, a breakdown of more
than eight milestones. Nothing to decide goes in milestone notes. Each answer moves to a milestone
or to Deviations, and this section reads "None." before the status leaves draft. -->

None.

## Milestones

<!-- Status values: todo | in progress | done (<sha>, <date>, <N> tests, <coverage per suite>) | reopened (<reason>) -->

### M1. <name>

- **Status:** todo
- **Goal:** <one line>
- **Plan steps:** <e.g. 1–2>
- **Acceptance criteria:** <e.g. A5, A20 (partial: lint only)>
- **Demo:** <what a person can see or click after this milestone, or "nothing, backend only">
- **Done when:**
  - `make check`
  - `make coverage` <!-- from the milestone that adds it onwards -->
  - `<command from the plan's Verification row>`
- **Notes:** <what's done, what's next; kept current during the session>

### M2. <name>

- **Status:** todo
- **Goal:**
- **Plan steps:**
- **Acceptance criteria:**
- **Demo:**
- **Done when:**
- **Notes:**

<!-- The last milestone always ends with: make check, make coverage, the sdlc-verifier subagent, and the PR. -->

## Deviations from the plan

<!-- One per line: what differs, why, plan section, and whether the engineer needs to decide (yes/no). -->

None yet.

## Flaky tests

<!-- Only tests still flaky after at least three fix attempts. One entry each: the test, how it
fails and how often, each approach tried and its result, and "Engineer decides: yes". -->

None.

## Session log

<!-- One line per session: date, unit of work, result, commit. -->
