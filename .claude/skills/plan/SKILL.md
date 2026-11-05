---
name: plan
description: Stage 3 (Build), before /build. Save an approved plan-mode plan as changes/<slug>/plan.md. Use once the engineer has accepted a plan for a change that has intent.md and spec.md.
---

# Save the approved plan

Planning itself happens in plan mode. Start Claude Code in plan mode (`claude --permission-mode plan`) with the change's `intent.md` and `spec.md`. The engineer iterates with Claude until the plan can be implemented, then approves it.

Once the plan is approved:

1. Copy `templates/plan.md` to `changes/<slug>/plan.md`. Fill it with the approved plan; don't add new scope.
2. Under **Verification**, map each acceptance criterion from `spec.md` to an exact command and its expected result.
3. For a bug fix, the first step is a failing test committed on its own. Later steps then run with `SDLC_LOCK_TESTS=1`, so the test can't be edited.
4. Size the steps to the change. A small change (a message, a one-line fix) needs one to three steps, not a breakdown: `/build` builds a plan that small in one session.
5. Run `make validate`, then commit `plan.md` before writing any code.

Once plan.md is merged, `/build` builds it in its own worktree (`claude --worktree <slug>`): in one session for a small plan, or milestone by milestone from an approved `build.md` for a larger one. It finishes with `make check` and the `verifier` subagent before opening a PR.
