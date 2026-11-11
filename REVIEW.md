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
   - **Clause coverage (`spec:` PRs, and PRs that change a `spec.md`):** checking that each requirement has a criterion isn't enough, because a criterion can test only part of its requirement (#47). Split each requirement the PR adds or changes into clauses: each separate outcome it "shows", "has", "is" or "combines with", each "otherwise", and each "when … then". Every clause is tested by at least one acceptance criterion, or listed under Acceptance criteria as `- Untestable (R<n>): "<clause>" because <reason>.` An uncovered clause is Important: quote the clause, name its requirement, and suggest the criterion that would test it. The *product owner* decides, because a new or changed criterion changes the spec.
4. **Verification:** every acceptance criterion has a test or a command in the plan's Verification section. Bug fixes include a test that failed before the fix.
   - **At the right level:** the test drives the criterion at the level it describes (`.claude/skills/scope.md`). A UI behaviour tested only through the model beneath the UI, or a criterion whose only evidence is a file that exists, is Important.
   - **Clause coverage (`plan:` PRs, and PRs that change a `plan.md`):** for each requirement the PR adds or changes, and each one whose criteria or plan rows it changes, compare the plan with the requirement's text, not only with its acceptance criteria. Leave requirements the PR doesn't touch alone: done work isn't re-reviewed. Every testable clause has a design statement in the plan and a Verification row that would fail if the clause weren't met. A clause missing either is Important, quoted with its requirement; the *engineer* decides.
   - **Where the clauses come from:** when the review prompt includes the clause check's output (`scripts/clause-check.sh`, one small-model call per requirement), start from it. Confirm each entry against the files before reporting it, and report each `unchecked` entry as a requirement the check couldn't read, never as covered. An entry with no `requirement` that says the check could not run isn't a finding: say so in one line of the summary and split the requirements yourself. Without the file (a repo with no `make clauses` target, or no spec or plan changed), split the requirements yourself, one at a time.
5. **Descopes:** silence is not permission, and a rule's scope is a minimum (`.claude/skills/scope.md`). Report as Important anything the PR leaves undone, untested or unchecked that nobody has approved: wording such as "not tested", "manual", "skipped", "out of scope", "not covered" or "like the rest of …" in a plan, build.md, PR body or code comment; new `skip` or no-cover markers; and first-party files the PR adds or edits under a lint, format, type-check or coverage exclusion. A plan descope is approved only by a `Descope: … Approved: <name>, <date>.` entry in its **Descopes** section (one still in Risks counts as not approved); a spec's is its **Out of scope** section, which the product owner decides. Quote the text, and say who decides. A plan whose `- **Definition of done:**` line leaves out a kind the change plainly is (a UI change that doesn't name UI), and a code PR that falls short of a row its plan names (`templates/definition-of-done.md`, with the repo's `docs/definition-of-done.md` on top), are Important too, unless an approved descope covers the gap. A code PR whose body doesn't list each of the plan's `Human check:` entries under **To check by hand** is Important too: the owner has to see them before merging.
   - **What was delivered, against each requirement (code PRs, #106):** passing criteria don't prove a requirement was built. For each requirement the PR implements, compare its wording with what the diff delivers and with build.md's milestone Goals and Demos. When the delivery lacks the requirement's main verb or noun (it "generates a scene", and the diff only draws a diagram), and no `Approved:` descope, answered deviation or Out of scope entry covers it, post an Important finding that starts **Descope: needs approval**, quoting the requirement and what was delivered; the *product owner* decides: approve it as a descope, or send it back to be built. Where branch protection requires resolved conversations, the open thread holds the merge until they do. Post one for each entry the PR body lists under **Descope: needs approval**, too. A gap in a modifier only is wording drift: mention it in the summary, not as a finding.

## Severity

- **Important:** wrong behaviour, a security issue, or a spec requirement that isn't met. Always report these.
- **Nit:** style or naming. Report at most 3 per PR, and none if any Important finding exists.

## Exclusions

- Anything `make lint` or `make test` already enforces. CI reports those failures.
- Lockfiles and generated files.
- Wording in `intent.md` and `spec.md`: how it is phrased is for the product owner. Whether every clause of a requirement is covered (passes 3 and 4) is not wording, and is in scope.

## Writing findings

The product owner and code owners read findings on GitHub, often without the files open. Make every finding readable on its own:

- **Quote what you refer to.** Never cite a bare ID like "A8" or "R2". Quote the line: `> A8. The existing change … prints \`…\tspec\t0\``.
- **Say why it matters** in one sentence: what goes wrong, and when.
- **Suggest a fix**, as replacement wording or code where you can.
- **Say who decides:** *product owner* for intent and spec content, *engineer* for plan and code.

## Summary comment

Keep exactly **one** summary comment per PR, and replace it on each new review rather than adding another. It contains:

1. Each **Descope: needs approval** finding, then the descopes, each quoted with who approved it or "not approved", the human checks still to try, and the plan's Risks that need a decision. These come first.
2. The number of findings per severity, and whether each earlier finding is now resolved.
3. One line per open finding: a short quote of the text it's about, plus the owner who decides.
4. One line on whether the change matches its spec, saying what was compared, and claiming only what was checked. For example: "Every clause of R1–R45 traced to an acceptance criterion and to a plan step and test (112 clauses)", or "IDs only: every acceptance criterion has a Verification row".
5. How to handle the findings, as a one-line reminder:
   - Whoever decides runs `/pr <N>` in Claude Code: the product owner for `intent:`, `bug:` and `spec:` PRs, the engineer for the rest.
   - Tagging `@claude` on a thread is optional. It hands that finding to the GitHub bot instead, so don't do both for one finding.

## Handling findings

Findings are worked through in a Claude Code session in the terminal with `/pr <N>`, which picks the product owner's or the engineer's walkthrough by the PR's type. Claude goes through them one at a time, then edits, pushes, replies on every thread and resolves it. The GitHub bot (`@claude` in a comment) is optional.

- **One actor per finding.** A finding is handled either by the terminal session or by the bot, never both. Before pushing, the terminal session checks the branch for bot commits and merges them in.
- **Every thread gets a reply** saying what was decided or changed, then it's resolved. Nothing is resolved silently. Replies posted from Claude Code go out under the person's account and end with `(posted from Claude Code)`.
