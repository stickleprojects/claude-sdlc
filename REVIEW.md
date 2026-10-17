# REVIEW.md

The policy for automated PR review (`.github/workflows/claude-review.yml`). Review findings are comments only. They never approve or block a PR: a code owner approves through branch protection. The agent that wrote a change never reviews it.

## Passes

Run these in order. Report only what each pass actually finds.

1. **Bugs:** logic errors, unhandled failure paths, broken edge cases, races.
2. **Security:** follow `.claude/skills/security-policy/SKILL.md`. Watch for secrets in diffs, unvalidated input, and new dependencies without a stated reason.
3. **Compliance with the artifact chain:** the PR's change folder under `changes/` must have `intent.md`, `spec.md` and `plan.md`. Flag code that has no matching requirement, requirements with no code or test, and plan steps that were skipped.
4. **Verification:** every acceptance criterion has a test or a command in the plan's Verification section. Bug fixes include a test that failed before the fix.

## Severity

- **Important:** wrong behaviour, a security issue, or a spec requirement that isn't met. Always report these.
- **Nit:** style or naming. Report at most 3 per PR, and none if any Important finding exists.

## Exclusions

- Anything `make lint` or `make test` already enforces. CI reports those failures.
- Lockfiles and generated files.
- Wording in `intent.md` and `spec.md`. The product owner reviews those, not this pass.

## Summary comment

End with a single comment: the number of findings per severity, then one line on whether the change matches its spec.
