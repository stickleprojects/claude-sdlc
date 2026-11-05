---
name: plan
description: Stage 3 (Build). Save an approved plan-mode plan as changes/<slug>/plan.md. Use once the engineer has accepted a plan for a change that has intent.md and spec.md.
---

# Save the approved plan

Planning itself happens in plan mode. Start Claude Code in plan mode (`claude --permission-mode plan`) with the change's `intent.md` (or `bug.md`) and `spec.md`. The engineer iterates with Claude until the plan can be implemented, then approves it.

Once the plan is approved:

1. Copy `templates/plan.md` to `changes/<slug>/plan.md`. Fill it with the approved plan; don't add new scope.
2. Under **Verification**, map each acceptance criterion from `spec.md` to an exact command and its expected result.
3. For a bug fix (a change that starts from `bug.md`, or any fix), the first step is a failing test committed on its own, one per acceptance criterion in the short spec, with the message `test(<slug>): failing test for <symptom>`. Once that commit is on the branch, the files it touched lock automatically for a change with `bug.md` (`scripts/tests-locked.sh`), so the failing test can't be edited; new tests in other files still can. Nobody needs to set `SDLC_LOCK_TESTS=1`.
4. Run `make validate`, then commit `plan.md` (by explicit path, never `git add -A`) before writing any code. Follow the `agent-identity` skill for commit trailers and PR signatures.

Implementation runs in its own worktree (`claude --worktree <slug>`). Finish it with `make check` and the `verifier` subagent before opening a PR.
