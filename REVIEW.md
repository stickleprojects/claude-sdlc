# REVIEW.md

The policy for automated PR review (`.github/workflows/claude-review.yml`). Review findings are comments only. They never approve or block a PR: a human merges it (in team mode, after a code owner's approval). The agent that wrote a change never reviews, approves or merges it.

## Passes

Run these in order. Report only what each pass actually finds.

1. **Bugs:** logic errors, unhandled failure paths, broken edge cases, races. Code that parses text people write, such as artifact sections, must fail safe: input it doesn't recognise must not quietly read as "empty", "none" or "done".
2. **Security:** follow `.claude/skills/security-policy/SKILL.md`. Watch for secrets in diffs, unvalidated input, and new dependencies without a stated reason.
3. **Compliance with the artifact chain:** the PR's change folder under `changes/` must have `intent.md`, `spec.md` and `plan.md`. A bug has `bug.md` in place of `intent.md`, and a short spec (requirements, and one acceptance test per symptom), which is complete as it is. A `build.md`, if present, is the approved build plan: its deviations and anything marked `Engineer decides: yes` should appear in the PR body. Flag code that has no matching requirement, requirements with no code or test, and plan steps that were skipped.
   - **Maintenance exemption:** skip this pass for PRs whose title starts with `fix:`, `ci:` or `chore:`, but only if they don't change how the product behaves. That covers pipeline, tooling, docs and file permissions. For these, check instead that the PR description explains why the change is needed. If an exempt PR does change product behaviour (`src/` logic, CLI output), report that as Important: it needs an intent.
   - PRs that only add or edit artifacts (`intent:`, `bug:`, `spec:`, `plan:`) are checked only against the stage they belong to.
   - **Plan PRs and architecture decisions:** read the repo's ADRs (`docs/adr/*.md`, if any). If the plan does what an accepted ADR's **Revisit when** line describes, or makes an architecture choice no ADR covers (a new framework, service or datastore, reliance on a library's undocumented internals, or building by hand something a widely used library provides when an earlier change already did), its **Risks** must have an `Architecture decision needed:` line naming the question, the ADR and trigger (or "no ADR"), and the engineer's decision. Report a missing line as Important, quoting the plan text that meets the trigger and the trigger itself; the engineer decides. A plan that builds by hand what a widely used library provides, without saying why in **Approach**, is a Nit.
   - **ADR PRs** (`docs/adr/`): an accepted ADR's **Revisit when** lines are concrete enough to check against a single plan ("a plan hand-builds navigation state", not "if it gets complex"). Report vague triggers as Important; the tech lead decides.
   - **Repos that track changes as issues:** if the repo's `CLAUDE.md` contains the line `Change tracking: issues` (the claude-sdlc framework repo does), skip the change-folder requirement for every PR type, `feat:` included. Instead, check that the PR description links an issue, or explains the problem it solves and how the change was tested. Report a missing explanation as Important.
4. **Verification:** every acceptance criterion has a test or a command in the plan's Verification section. Bug fixes include a test that failed before the fix.
   - **At the right level:** the test drives the criterion at the level it describes (`.claude/skills/scope.md`). A UI behaviour tested only through the model beneath the UI, or a criterion whose only evidence is a file that exists, is Important.
5. **Descopes:** silence is not permission, and a rule's scope is a minimum (`.claude/skills/scope.md`). Report as Important anything the PR leaves undone, untested or unchecked that nobody has approved: wording such as "not tested", "manual", "skipped", "out of scope", "not covered" or "like the rest of …" in a plan, build.md, PR body or code comment; new `skip` or no-cover markers; and first-party files the PR adds or edits under a lint, format, type-check or coverage exclusion. A plan descope is approved only by a `Descope: … Approved: <name>, <date>.` entry in its **Descopes** section (one still in Risks counts as not approved); a spec's is its **Out of scope** section, which the product owner decides. Quote the text, and say who decides. A code PR whose body doesn't list each of the plan's `Human check:` entries under **To check by hand** is Important too: the owner has to see them before merging.

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

1. The descopes, each quoted with who approved it or "not approved", the human checks still to try, and the plan's Risks that need a decision. These come first.
2. The number of findings per severity, and whether each earlier finding is now resolved.
3. One line per open finding: a short quote of the text it's about, plus the owner who decides.
4. One line on whether the change matches its spec.
5. How to handle the findings, as a one-line reminder:
   - Whoever decides runs `/pr <N>` in Claude Code: the product owner for `intent:`, `bug:` and `spec:` PRs, the engineer for the rest.
   - Tagging `@claude` on a thread is optional. It hands that finding to the GitHub bot instead, so don't do both for one finding.

## Handling findings

Findings are worked through in a Claude Code session in the terminal with `/pr <N>`, which picks the product owner's or the engineer's walkthrough by the PR's type. Claude goes through them one at a time, then edits, pushes, replies on every thread and resolves it. The GitHub bot (`@claude` in a comment) is optional.

- **One actor per finding.** A finding is handled either by the terminal session or by the bot, never both. Before pushing, the terminal session checks the branch for bot commits and merges them in.
- **Every thread gets a reply** saying what was decided or changed, then it's resolved. Nothing is resolved silently. Replies posted from Claude Code go out under the person's account and end with `(posted from Claude Code)`.
