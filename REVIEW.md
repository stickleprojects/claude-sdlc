# REVIEW.md

The policy for automated PR review (`.github/workflows/claude-review.yml`). Review findings are comments only. They never approve or block a PR: a human merges it (in team mode, after a code owner's approval). The agent that wrote a change never reviews, approves or merges it.

## Passes

Run these in order. Report only what each pass actually finds.

1. **Bugs:** logic errors, unhandled failure paths, broken edge cases, races.
2. **Security:** follow `.claude/skills/security-policy/SKILL.md`. Watch for secrets in diffs, unvalidated input, and new dependencies without a stated reason.
3. **Compliance with the artifact chain:** the PR's change folder under `changes/` must have `intent.md`, `spec.md` and `plan.md`. Flag code that has no matching requirement, requirements with no code or test, and plan steps that were skipped.
   - **Maintenance exemption:** skip this pass for PRs whose title starts with `fix:`, `ci:` or `chore:`, but only if they don't change how the product behaves. That covers pipeline, tooling, docs and file permissions. For these, check instead that the PR description explains why the change is needed. If an exempt PR does change product behaviour (`src/` logic, CLI output), report that as Important: it needs an intent.
   - PRs that only add or edit artifacts (`intent:`, `spec:`, `plan:`) are checked only against the stage they belong to.
   - **Repos that track changes as issues:** if the repo's `CLAUDE.md` contains the line `Change tracking: issues` (the claude-sdlc framework repo does), skip the change-folder requirement for every PR type, `feat:` included. Instead, check that the PR description links an issue, or explains the problem it solves and how the change was tested. Report a missing explanation as Important.
4. **Verification:** every acceptance criterion has a test or a command in the plan's Verification section. Bug fixes include a test that failed before the fix.

## Severity

- **Important:** wrong behaviour, a security issue, or a spec requirement that isn't met. Always report these.
- **Nit:** style or naming. Report at most 3 per PR, and none if any Important finding exists.

## Exclusions

- Anything `make lint` or `make test` already enforces. CI reports those failures.
- Lockfiles and generated files.
- Wording in `intent.md` and `spec.md`. The product owner reviews those, not this pass.

## Writing findings

The product owner and code owners read findings on GitHub, often without the files open. Make every finding readable on its own:

- **Quote what you refer to.** Never cite a bare ID like "A8" or "R2". Quote the line: `> A8. The existing change … prints \`…\tspec\t0\``.
- **Say why it matters** in one sentence: what goes wrong, and when.
- **Suggest a fix**, as replacement wording or code where you can.
- **Say who decides:** *product owner* for intent and spec content, *engineer* for plan and code.

## Summary comment

Keep exactly **one** summary comment per PR, and replace it on each new review rather than adding another. It contains:

1. The number of findings per severity, and whether each earlier finding is now resolved.
2. One line per open finding: a short quote of the text it's about, plus the owner who decides.
3. One line on whether the change matches its spec.
4. For `intent:` and `spec:` PRs, a reminder that the product owner can run `/po-review <PR#>` in Claude Code to work through the findings.
