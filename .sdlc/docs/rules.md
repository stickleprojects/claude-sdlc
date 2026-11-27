# Rules index

Every rule in `.sdlc/REVIEW.md`, the skills (`.sdlc/skills/`, `scope.md` and `routing.md` included) and the verifier (`.sdlc/agents/verifier.md`) has an id, one home and a line here (#201). The home is the file whose line carries the rule's marker, `<!-- rule: <id> -->`. **Held by** says what makes the rule hold when a model ignores the prompt:

- `hook: <path>`: a Claude Code hook blocks the action.
- `check: <path>` or `check: <path>::<name>`: a script, or `make validate` code, that CI or `make check` runs fails.
- `eval: <task>`: an agent eval (`evals/tasks/<task>.json`) shows the model follows it.
- `test: <path>::<name>`: a test of the code the rule describes.
- `nothing`: only the prompt holds it.

A holder can hold part of a rule only, such as the plan gate holding "no code before the plan" for edits but not for shell writes. In the framework repo, `tests/test_rules_index.py` keeps this file and the markers in step: every marker has one row, every row one marker in the file under whose heading it sits, and every holder exists.

**Adding or changing a rule:** put the marker at the end of the rule's line, add the row here, and name what holds it. A rule held by `nothing` that must always hold needs a hook or a CI check (`.sdlc/skills/security-policy/SKILL.md`). Before adding one, look for a rule here that already says it: one rule, one home.

## `.sdlc/REVIEW.md`

| Id | Rule | Held by |
|---|---|---|
| `review.never-approves` | The review never approves; the agent that wrote a change never reviews, approves or merges it | `hook: .sdlc/hooks/production-gate.sh` |
| `review.bugs` | Report bugs; text parsers fail safe | nothing |
| `review.security` | Apply the security policy; watch for secrets, unvalidated input, unexplained dependencies | nothing |
| `review.chain` | The change folder has its artifacts; flag code without a requirement and requirements without code or test | `check: .sdlc/scripts/check-pr-title.sh`, `hook: .sdlc/hooks/plan-gate.sh`, `check: .sdlc/scripts/check-plan-first.sh` |
| `review.bug-fast-path` | A fast-path fix PR needs no plan; failing tests come first; too big or `Bug path: full` is Important | `check: .sdlc/scripts/check-plan-first.sh`, `check: .sdlc/scripts/check-pr-title.sh` |
| `review.tooling-path` | A tooling PR (`Kind: tooling`) is checked against its plan's Verification rows; a product-behaviour change on it is Important | `check: .sdlc/scripts/check-plan-first.sh`, `check: .sdlc/scripts/check-pr-title.sh` |
| `review.maintenance-exemption` | Unscoped fix/ci/chore PRs skip the chain unless they change product behaviour | nothing |
| `review.artifact-stage` | Artifact PRs are checked only against their stage | nothing |
| `review.adr-trigger` | A plan that meets an ADR trigger or makes an uncovered architecture choice needs an `Architecture decision needed:` line | `eval: plan-flags-adr-trigger` |
| `review.adr-triggers-concrete` | An accepted ADR's Revisit when lines are concrete | nothing |
| `review.issue-tracking` | With `Change tracking: issues`, PRs link an issue or explain the problem instead of a change folder | nothing |
| `review.clause-coverage-spec` | Every clause of a changed requirement is tested by a criterion or listed as Untestable | `eval: review-flags-uncovered-clause-in-spec` |
| `review.verification` | Every criterion has a test or command; a bug fix has a test that failed first | nothing |
| `review.test-level` | A criterion is tested at the level it describes | nothing |
| `review.clause-coverage-plan` | Every testable clause of a touched requirement has a design statement and a Verification row | `eval: review-flags-uncovered-clause-in-plan` |
| `review.clause-one-finding` | One thread per requirement lists every clause | `eval: review-lists-every-clause-in-one-finding` |
| `review.dependent-design` | Plan text a requirement change makes stale is reported in the same review | `eval: review-flags-design-text-a-requirement-change-makes-stale` |
| `review.rereview-first-split` | On a re-review, unchanged text gets no new clause findings | `eval: review-rereview-keeps-the-first-split` |
| `review.clause-check-input` | Start from the clause check's output; an `unchecked` entry is never covered | nothing |
| `review.descopes` | Report unapproved descopes (approved only as scope.md records one), definition-of-done gaps and unlisted human checks as Important | `check: .sdlc/src/sdlc/artifacts.py::check_descopes`, `check: .sdlc/src/sdlc/artifacts.py::check_dod` |
| `review.delivery-gap` | A delivery that lacks a requirement's main verb or noun is a `Descope: needs approval` finding | nothing |
| `review.plan-amendments` | With SDLC_BUILD_AMENDS_PLAN on, all plan amendments go in the one Session decisions thread | `eval: review-raises-plan-amendments-as-one-thread`, `check: .sdlc/scripts/descopes-decided.sh`, `check: .sdlc/scripts/check-pr-title.sh` |
| `review.session-decisions` | Descopes decided in the session, and plan amendments, go in one Session decisions thread that one person's reply approves | `check: .sdlc/scripts/descopes-decided.sh`, `check: .sdlc/scripts/descopes-status.sh` |
| `review.project-rules` | Apply the repo's docs/review-rules.md | nothing |
| `review.severity-important` | Important: wrong behaviour, security, an unmet requirement; always reported | nothing |
| `review.nit-cap` | At most 3 Nits, none if any Important | nothing |
| `review.exclusions` | Don't report what lint or tests enforce, lockfiles, generated files or intent/spec wording | nothing |
| `review.finding-readable` | Quote what you refer to, say why it matters, suggest a fix, say who decides | nothing |
| `review.important-thread` | Every Important finding is its own thread, starting `**Important` | `check: .sdlc/scripts/review-findings.sh` |
| `review.ci-change-thread` | The job posts the `CI change: needs approval` thread; the review never does, and reviews those files as advice | `check: .sdlc/scripts/ci-change-thread.sh`, `check: .sdlc/scripts/descopes-decided.sh`, `test: tests/test_review_from_main.py::test_both_prompts_point_the_review_at_pr`, `eval: review-reads-the-prs-files-under-pr` |
| `review.descope-thread` | A descope thread says `Descope: needs approval`; only a person's reply decides it | `check: .sdlc/scripts/descopes-decided.sh`, `check: .sdlc/scripts/descopes-status.sh` |
| `review.nit-thread` | A Nit is a thread or a summary line starting `**Nit:**`; every counted Nit is in one | `check: .sdlc/scripts/review-findings.sh` |
| `review.rereview-open-threads` | An open earlier thread still counts; a resolved but unaddressed one gets a new thread | `check: .sdlc/scripts/review-findings.sh` |
| `review.hidden-count` | The summary ends with the hidden findings count | `check: .sdlc/scripts/review-findings.sh` |
| `review.one-summary` | One summary comment per PR, replaced on each review, in a fixed order | nothing |
| `review.earlier-notes` | On a re-review, mark every earlier summary note addressed (with its commit) or still open; never drop one | `eval: review-marks-earlier-summary-notes`, `test: tests/scripts/test_review_earlier_summary.py::test_the_review_reads_the_earlier_summary_with_mains_copy` |
| `review.claim-only-checked` | The summary claims only what was compared | nothing |
| `review.handling-line` | The summary's how-to-handle line shows only when a finding is open, and names no command with `Change tracking: issues` | `eval: review-clean-pr-has-no-handling-line`, `eval: review-issues-repo-names-no-command` |

## `.sdlc/skills/scope.md`

| Id | Rule | Held by |
|---|---|---|
| `scope.silence` | Silence is not permission | nothing |
| `scope.minimum` | A rule's scope is a minimum; exclusion lists are for vendored or generated code | nothing |
| `scope.people-decide` | Agents propose descopes; people decide them | `check: .sdlc/scripts/descopes-decided.sh`, `check: .sdlc/scripts/descopes-status.sh` |
| `scope.definition-of-done` | Each plan names its definition-of-done kinds; missing a plain kind is a descope | `check: .sdlc/src/sdlc/artifacts.py::check_dod` |
| `scope.what-is-a-descope` | What counts as a descope, with or without the wording | nothing |
| `scope.plan-descope-entry` | A plan descope is a Descopes entry with `Approved:`, approved one at a time | `check: .sdlc/src/sdlc/artifacts.py::check_descopes` |
| `scope.not-approved` | No `Approved:`, in Risks, or inherited means not approved | nothing |
| `scope.delivery-gaps` | Only a large unapproved delivery gap pulls a person in, via `Descope: needs approval` | `eval: verifier-flags-unapproved-delivery-gap`, `eval: verifier-passes-an-approved-delivery-gap` |
| `scope.clauses` | A requirement's clauses, and checking coverage one clause at a time | `eval: review-flags-uncovered-clause-in-spec`, `eval: review-flags-uncovered-clause-in-plan` |
| `scope.human-checks` | A human check is an approved descope; the verifier reports it PENDING | nothing |
| `scope.test-before-asking` | Write the test before handing a person something to try | `eval: build-scripts-checks-before-handing-them-over` |
| `scope.test-level` | Test each criterion at the level it describes | nothing |
| `scope.decisions-first` | Show descopes, risks, deviations and questions before the rest | nothing |

## `.sdlc/skills/routing.md`

| Id | Rule | Held by |
|---|---|---|
| `routing.entry-skills` | Six entry skills; the rest are internal and reached through them | `test: tests/test_routing.py::test_routing_lists_exactly_the_entry_and_internal_skills` |
| `routing.other-change-warning` | Naming another change in a copy made for one gets a one-line warning, not a block | nothing |
| `routing.change-from-branch` | With no change named, the copy's own change is used without asking | `eval: build-uses-the-change-its-branch-names`, `test: tests/scripts/test_current_change.py::test_the_branch_names_the_change` |
| `routing.pick-change` | One candidate: use it; several: ask; none: look one stage back | nothing |
| `routing.open-pr-first` | An open PR for the next artifact comes before what's on main | nothing |
| `routing.invoke-next` | Invoke the next skill; don't ask the person to type it | nothing |
| `routing.no-silent-redo` | Never redo a finished stage silently | nothing |
| `routing.waiting` | Say who a change waits on; don't offer to do their part | nothing |
| `routing.stage-branch` | A skill moves the copy to its stage's branch only when nothing would be left behind | `eval: build-moves-a-finished-copy-to-its-branch`, `eval: build-asks-before-leaving-uncommitted-work`, `eval: build-asks-before-leaving-unmerged-commits` |
| `routing.go-back-by-amending` | Going back is amending an earlier artifact through a PR | nothing |
| `routing.withdraw` | Only the product owner withdraws a change, with a `Withdrawn:` line | nothing |
| `routing.after-merge-is-a-bug` | Anything found after merge is a new bug change; never reopen a merged change | nothing |

## `.sdlc/skills/tooling.md`

| Id | Rule | Held by |
|---|---|---|
| `tooling.offer` | Offer the tooling path only with `Tooling paths:` set and no product code; otherwise the full path | `eval: intent-proposes-the-tooling-path`, `eval: intent-keeps-product-code-on-the-full-path` |
| `tooling.intent-branch` | A tooling intent says `Kind: tooling`, is committed on build/<slug>, and opens no intent PR | `eval: intent-proposes-the-tooling-path`, `test: tests/test_scenario.py::test_a_tooling_change_runs_end_to_end_in_the_consumer` |
| `tooling.plan` | A tooling plan maps each Proposed outcome statement to a Verification row and keeps its code inside `Tooling paths:` | `check: .sdlc/scripts/check-plan-first.sh` |
| `tooling.same-branch` | A tooling plan is committed on build/<slug> with no plan PR; the one PR carries intent, plan and code | `test: tests/test_scenario.py::test_a_tooling_change_runs_end_to_end_in_the_consumer` |
| `tooling.pr` | A tooling PR is titled chore(<slug>) or ci(<slug>) and its body says merging accepts intent, plan and code | `check: .sdlc/scripts/check-pr-title.sh` |
| `tooling.verify` | A tooling change is verified from its intent's Proposed outcome, through the plan's Verification rows | nothing |

## `.sdlc/skills/build/SKILL.md`

| Id | Rule | Held by |
|---|---|---|
| `build.one-pr` | Every build ends in exactly one PR | nothing |
| `build.one-decision-at-a-time` | Ask one decision at a time; lists and documents go in a file | nothing |
| `build.no-spec-edit` | spec.md isn't edited on a build branch unless the repo opts in to amendments | `check: .sdlc/scripts/check-pr-title.sh` |
| `build.no-plan-edit` | plan.md isn't edited in a build; a wrong plan goes back through a plan PR | `check: .sdlc/scripts/check-pr-title.sh` |
| `build.plan-amendments` | With SDLC_BUILD_AMENDS_PLAN on, amendments are recorded in build.md and listed under `## Plan changes` | `check: .sdlc/scripts/check-pr-title.sh`, `check: .sdlc/scripts/descopes-decided.sh` |
| `build.session-decisions` | A descope decided in the session is recorded in build.md and listed under `## Descopes decided in session`; needs-approval threads stay unresolved | `check: .sdlc/scripts/descopes-decided.sh` |
| `build.scope` | No descope without an approval; meet the named definition-of-done rows | nothing |
| `build.claude-md` | Follow the repo's CLAUDE.md | nothing |
| `build.commit-each-step` | Commit and push after each plan step, with the build's commit types | nothing |
| `build.merge-never-rebase` | Merge, never rebase, on the build branch | `hook: .sdlc/hooks/production-gate.sh` |
| `build.failing-test-locked` | A bug's failing test is committed first and its files lock | `hook: .sdlc/hooks/protect-paths.sh`, `check: .sdlc/scripts/tests-locked.sh` |
| `build.flaky-tests` | Fix flaky tests at the cause; never skip or retry past them without the engineer | nothing |
| `build.coverage` | Coverage runs before every merge: `make local-check` runs it, or the PR's CI where the `Local check:` line leaves it out; a large build adds it | `test: tests/scripts/test_local_check.py::test_a_line_runs_only_what_it_names_and_leaves_coverage_to_ci` |
| `build.never-lower-threshold` | Never lower a coverage threshold or add an exclusion to get green | nothing |
| `build.one-unit` | Stay inside the current unit of work | nothing |
| `build.plan-approved` | Build only from a plan merged on main | `hook: .sdlc/hooks/plan-gate.sh`, `check: .sdlc/scripts/check-plan-first.sh` |
| `build.sizing` | Size a build by work and certainty, not by file count | nothing |
| `build.no-hidden-decisions` | Decisions go in Questions before approval, never in notes or folded into approve | nothing |
| `build.draft-never-built` | A draft build.md is committed but never built from | nothing |
| `build.approval-no-open-questions` | An approved build.md has no open questions | `check: .sdlc/src/sdlc/artifacts.py::check_build` |
| `build.repair-first` | Repair reopened milestones before new work | nothing |
| `build.change-done` | The build PR sets `change.toml` to done | `check: .sdlc/scripts/check-plan-first.sh` |
| `build.roadmap-row` | Mark the roadmap row done in the build PR; ask before marking a milestone done | `check: .sdlc/src/sdlc/roadmap.py::check_roadmap` |
| `build.verifier` | Run the verifier before the PR; open it with unapproved large gaps listed first | nothing |
| `build.pr-body-order` | The build PR body leads with what needs a decision | nothing |
| `build.all-stop-conditions` | `/sdlc-build all` stops on PR open, FAILED, no progress, or milestones plus three workers | nothing |
| `build.worker-never-asks` | A worker never asks the person; it returns BLOCKED | nothing |
| `build.worker-descope-blocked` | A worker with an unapproved descope returns BLOCKED | nothing |
| `build.milestone-goals-match-requirements` | A milestone Goal or Demo that delivers less than its requirement is raised as a question before approval | nothing |
| `build.fast-path-tests-first` | A fast-path bug's criteria are its steps: failing tests committed alone first, then the fix | `check: .sdlc/scripts/tests-locked.sh` |
| `build.fast-path-pr-body` | A fast-path PR body says approving it ships the fix, and who checks what | nothing |
| `build.all-orchestrator-opens-pr` | In `/sdlc-build all`, the orchestrator opens the PR itself, with the run's decisions | nothing |

## `.sdlc/skills/plan/SKILL.md`

| Id | Rule | Held by |
|---|---|---|
| `plan.already-planned` | Don't start a planned change again silently | nothing |
| `plan.no-code-from-dialog` | Never write code from plan mode's approval dialog | `hook: .sdlc/hooks/plan-gate.sh`, `check: .sdlc/scripts/check-plan-first.sh` |
| `plan.from-requirement-text` | Every testable clause gets a design statement and a Verification row | nothing |
| `plan.test-level` | Each Verification row drives its criterion at the level it describes | nothing |
| `plan.descope-one-at-a-time` | Ask about each descope on its own; never fold descopes into approving the plan | nothing |
| `plan.architecture-check` | Check the plan against the ADRs and record `Architecture decision needed:` | `eval: plan-flags-adr-trigger` |
| `plan.descopes-section` | Descopes lists each approved descope and human check, or `None.` | `check: .sdlc/src/sdlc/artifacts.py::check_descopes` |
| `plan.verification` | Name every definition-of-done kind that fits; map every criterion and clause to a command | `check: .sdlc/src/sdlc/artifacts.py::check_dod` |
| `plan.bug-failing-test-first` | A bug fix's first step is a failing test committed on its own | `check: .sdlc/scripts/tests-locked.sh` |
| `plan.no-code-before-merge` | No code before the plan PR merges | `hook: .sdlc/hooks/plan-gate.sh`, `check: .sdlc/scripts/check-plan-first.sh` |

## `.sdlc/skills/intent/SKILL.md`

| Id | Rule | Held by |
|---|---|---|
| `intent.no-duplicate` | Don't draft a second change for one that exists | nothing |
| `intent.bug-or-feature` | Unexpected behaviour is a bug; pushback after merge is a new bug change | nothing |
| `intent.ask-dont-invent` | Ask one round at a time; don't invent answers | `eval: intent-from-brief` |
| `intent.slug-has-number` | A slug is the folder name with its number | `hook: .sdlc/hooks/plan-gate.sh`, `check: .sdlc/scripts/check-plan-first.sh` |
| `intent.roadmap` | Place the change on the roadmap, with an adjustment record where needed | `check: .sdlc/src/sdlc/roadmap.py::check_roadmap` |
| `intent.no-reorder` | Never reorder roadmap milestones | nothing |
| `intent.one-stage` | No spec, plan or code at the intent stage (except the fast path) | `hook: .sdlc/hooks/plan-gate.sh`, `check: .sdlc/scripts/check-plan-first.sh` |
| `intent.no-real-data` | Never real personal data in a bug report | nothing |
| `intent.bug-path` | `Bug path: full` forces the full path; otherwise take the fast path when its conditions hold | `eval: bug-fast-path`, `eval: bug-needs-decision-full-path`, `eval: bug-path-full-setting` |
| `intent.fast-path-open-question` | An open product question ends the fast path | `eval: bug-needs-decision-full-path` |
| `intent.bug-pr-branch` | A full-path bug PR never comes from `build/<slug>` | nothing |
| `intent.fast-path-branch` | A fast-path bug is built on `build/<slug>` with the number | `hook: .sdlc/hooks/plan-gate.sh`, `check: .sdlc/scripts/check-plan-first.sh` |

## `.sdlc/skills/spec/SKILL.md`

| Id | Rule | Held by |
|---|---|---|
| `spec.requirements` | Requirements are numbered and testable on their own | `check: .sdlc/src/sdlc/artifacts.py::check_requirements` |
| `spec.criteria-format` | Criteria are `- AC<n> (R<n>): …` bullets, tested at their level | `check: .sdlc/src/sdlc/artifacts.py::check_criteria` |
| `spec.clause-coverage` | Every clause has a criterion or an Untestable line | nothing |
| `spec.policy-concerns` | Apply every policy skill; write None only after checking | nothing |
| `spec.claude-owns-format` | Claude owns text formats; parsing fails safe; CI warns on what it can't read | nothing |
| `spec.no-po-decisions` | Don't resolve open questions or policy conflicts | nothing |
| `spec.bug-open-questions` | A bug spec raises unspecified behaviour as an open question | nothing |

## `.sdlc/skills/pr/SKILL.md`

| Id | Rule | Held by |
|---|---|---|
| `pr.route-by-title` | Route a PR to the walkthrough for whoever decides, by its title | nothing |
| `pr.fast-path-both` | A fast-path PR gets the product owner's walkthrough, then the engineer's | nothing |
| `pr.not-the-decider` | Say who decides when the person running it doesn't | nothing |

## `.sdlc/skills/next/SKILL.md`

| Id | Rule | Held by |
|---|---|---|
| `next.pipeline-version` | Say when the pipeline is behind a release, and only then | nothing |
| `next.roadmap-read-only` | Never reorder the roadmap or mark anything done from /sdlc-next | nothing |
| `next.offer-steps` | Offer up to four next steps, leaving out ones waiting on others | nothing |

## `.sdlc/skills/sdlc/SKILL.md`

| Id | Rule | Held by |
|---|---|---|
| `sdlc.declined-not-offered` | Don't offer features the project declined | `check: .sdlc/src/sdlc/artifacts.py::check_features` |
| `sdlc.clean-tree` | Never stash or discard the person's work | nothing |
| `sdlc.conflicts-with-person` | Resolve each sync conflict with the person | nothing |
| `sdlc.never-handle-secrets` | Never ask for or handle a secret's value | nothing |
| `sdlc.upgrade-steps` | Do every upgrade step; artifact changes go on their own change's PR; decisions go to their owner | `check: .sdlc/src/sdlc/cli.py::check_upgrade` |
| `sdlc.no-framework-edits` | Don't edit framework files to make the sync pass | nothing |
| `sdlc.decline-reason` | Record a declined feature with the person's own reason | `check: .sdlc/src/sdlc/artifacts.py::check_features` |
| `sdlc.list-declined` | After the update, list declined features once, without offering them | nothing |
| `sdlc.not-now-or-not-for-us` | A no is either not now (nothing recorded) or not for us (recorded in .sdlc.toml) | `check: .sdlc/src/sdlc/artifacts.py::check_features` |

## `.sdlc/skills/review-findings/SKILL.md`

| Id | Rule | Held by |
|---|---|---|
| `findings.descopes-first` | Descope findings first, with the PR's descopes, risks and human checks shown up front | nothing |
| `findings.decide-then-change` | Collect every decision, then make the changes | nothing |
| `findings.fix-whole-requirement` | Fix the whole requirement and the plan text that depends on it | nothing |
| `findings.pr-body-true` | Before pushing, nothing is stale: artifacts, traced requirements, the PR body | `eval: review-fix-updates-a-stale-pr-body` |
| `findings.reply-then-resolve` | Reply on every thread before resolving it; never resolve one silently | nothing |
| `findings.descope-person-decides` | Only a person's reply decides a descope thread; never approve one for them | `check: .sdlc/scripts/descopes-decided.sh`, `check: .sdlc/scripts/descopes-status.sh` |
| `findings.request-review` | Ask for a review with request-review.sh, never by adding the label | nothing |
| `findings.requirements-traced` | Before pushing, every changed requirement traces to a criterion, design text and a test | nothing |
| `findings.graphql-fallback` | If resolving fails, leave the thread and tell the person which to resolve by hand | nothing |

## `.sdlc/skills/po-review/SKILL.md`

| Id | Rule | Held by |
|---|---|---|
| `po.out-of-scope-first` | A spec's Out of scope items come first in the brief | nothing |
| `po.engineer-findings` | Engineer findings are handed on, not decided here | nothing |
| `po.edit-only-artifact` | Edit only the artifact under review; word the whole requirement | nothing |

## `.sdlc/skills/agent-identity/SKILL.md`

| Id | Rule | Held by |
|---|---|---|
| `identity.who-is-who` | The agent App is never the person; the CI reviewer isn't yours to act as | nothing |
| `identity.signing` | Sign with `— Claude` as the agent, `(posted from Claude Code)` as the person | nothing |
| `identity.rest-api` | Use `gh api` (REST), not GraphQL-based gh commands | nothing |
| `identity.explicit-add` | Add files by explicit path | nothing |
| `identity.auto-merge` | Turn on auto-merge only through auto-merge.sh, right after opening the PR | `hook: .sdlc/hooks/production-gate.sh` |
| `identity.act-when-asked` | Act only when a person asks | nothing |
| `identity.no-mentions` | Never @-mention anyone | nothing |
| `identity.one-actor` | One actor per finding: this session or the bot, which owns a thread an `@claude` comment is on or names | nothing |
| `identity.fetch-merge` | Before every push, fetch and merge anyone's commits; never rebase a pushed branch | nothing |
| `identity.no-force-push` | Never force-push or delete someone else's branch | `hook: .sdlc/hooks/production-gate.sh` |
| `identity.people-approve` | Approving and merging stay with people | `hook: .sdlc/hooks/production-gate.sh` |

## `.sdlc/skills/security-policy/SKILL.md`

| Id | Rule | Held by |
|---|---|---|
| `security.secrets` | Secrets never go in the repo, logs or prompts | nothing |
| `security.validate-input` | Validate external input at its boundary | nothing |
| `security.dependencies` | A new dependency has a stated reason and a pinned version | nothing |
| `security.personal-data` | Personal data only when a requirement names it, with a retention period | nothing |
| `security.advisory` | A rule that must hold needs a hook or CI check | nothing |

## `.sdlc/agents/verifier.md`

| Id | Rule | Held by |
|---|---|---|
| `verifier.no-code` | The verifier doesn't write code | nothing |
| `verifier.criterion-level` | PASS a criterion only on evidence at its level | nothing |
| `verifier.clauses` | Report PASS or FAIL per requirement clause | nothing |
| `verifier.delivery-gap` | Sort delivery gaps: large unapproved, large approved, wording drift | `eval: verifier-flags-unapproved-delivery-gap`, `eval: verifier-passes-an-approved-delivery-gap` |
| `verifier.descopes` | An unapproved descope is a FAIL | nothing |
| `verifier.definition-of-done` | Each named definition-of-done row is met or approved | nothing |
| `verifier.human-checks` | Human checks are PENDING, never PASS | nothing |
| `verifier.report-order` | The report leads with descopes and ends with the VERDICT line | nothing |
| `verifier.fast-path` | A fast-path bug is verified from bug.md, with its failing tests committed before the fix | nothing |

