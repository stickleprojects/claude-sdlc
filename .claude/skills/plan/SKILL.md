---
name: plan
description: Stage 3 (Build), before /build. Plan a change whose spec is merged, in plan mode, then save the approved plan as changes/<slug>/plan.md and open its PR. Works out which change to plan (asks when several are ready); on a change already planned, asks whether to replace the plan or build it; with nothing to plan, offers what comes before. Use when someone says "/plan", "/plan 0002", "plan the next change" or "save the plan".
---

# Plan a change

## 1. Which change

Follow `.claude/skills/routing.md`. The candidates are the changes whose next step is `plan`: the spec is merged, and there's no plan on main or in an open PR.

- **The change named is already planned** (plan.md merged, or a plan PR open): don't start again silently. Ask: build it (`/build`, recommended, which you then run for them), work through the plan PR's review (`/pr`) if one is open, or replace the plan, or stop.
- **Its spec isn't merged yet:** say what it's waiting on (the spec PR and who reviews it), and offer `/pr` on that PR.
- **Nothing to plan:** say so, with what each change is waiting on, and offer the step one stage back (routing step 4).

## 2. Plan it in plan mode

Planning happens in plan mode, with the change's `intent.md` (or `bug.md`) and `spec.md`. If this session isn't in plan mode, enter it (or ask the person to press Shift+Tab until it says plan mode). Read CLAUDE.md, the intent or bug, the spec and the code involved, then propose the plan. The engineer iterates with you until it can be implemented, then approves it.

## 3. Save the approved plan

Once the plan is approved:

1. Copy `templates/plan.md` to `changes/<slug>/plan.md`. Fill it with the approved plan; don't add new scope.
2. Under **Verification**, map each acceptance criterion from `spec.md` to an exact command and its expected result.
3. For a bug fix (a change that starts from `bug.md`, or any fix), the first step is a failing test committed on its own, one per acceptance criterion in the short spec, with the message `test(<slug>): failing test for <symptom>`. Once that commit is on the branch, the files it touched lock automatically for a change with `bug.md` (`scripts/tests-locked.sh`), so the failing test can't be edited; new tests in other files still can. Nobody needs to set `SDLC_LOCK_TESTS=1`.
4. Size the steps to the change. A small change (a message, a one-line fix) needs one to three steps, not a breakdown: `/build` builds a plan that small in one session.
5. Run `make validate`, then commit `plan.md` alone on `plan/<slug>` (by explicit path, never `git add -A`), push, and open its PR titled `plan(<slug>): <summary>`. No code is written before it merges. Follow the `agent-identity` skill for the commit trailer and PR signature.

Then tell the engineer: once the plan PR merges, run `/build` (`/pr` handles its review first). `/build` builds it in its own worktree (`claude --worktree <slug>`): in one session for a small plan, or milestone by milestone from an approved `build.md` for a larger one. It finishes with `make check` and the `verifier` subagent before opening a PR.
