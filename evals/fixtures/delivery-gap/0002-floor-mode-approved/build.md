# Build: Floor mode

- **Change:** `changes/0002-floor-mode-approved/` ([spec](spec.md), [plan](plan.md))
- **Branch:** `build/0001-floor-mode`
- **Built against:** `origin/main` at `abc1234` (2026-11-01)
- **Coverage:** `make coverage`; python: 90% lines
- **First demo:** after M1: the dock's floor tab shows a floor with doorway lines
- **Locked tests:** none
- **Status:** in progress
- **Approved:** Sam, 2026-11-01

## Questions before approval

None.

## Milestones

### M1. Show a floor

- **Status:** done (def5678, 2026-11-02, 2 tests, 95% lines)
- **Goal:** Show a whole floor as the game places it
- **Plan steps:** 1–2
- **Acceptance criteria:** AC1, AC2
- **Demo:** the dock's floor tab shows a floor with doorway lines
- **Done when:**
  - `make check`
- **Notes:** `draw_floor` gives the dock its boxes and lines.

## Deviations from the plan

None yet.

## Flaky tests

None.

## Session log

- 2026-11-02: M1, done, def5678.
