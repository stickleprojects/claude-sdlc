<!-- The frontmatter for this skill is in .claude/skills/plan/SKILL.md, which Claude Code reads. -->

# Plan a change

## 1. Which change

Follow `.sdlc/skills/routing.md`. The candidates are the changes whose next step is `plan`: the spec is merged, and there's no plan on main or in an open PR.

- **The change named is already planned** (plan.md merged, or a plan PR open): don't start again silently. Ask: build it (`/build`, recommended, which you then run for them), work through the plan PR's review (`/pr`) if one is open, amend the plan (a new plan PR that changes part of it; a build in progress then goes back to a draft build.md), replace it, or stop.
- **The plan is out of date** (`make next` says the spec changed after it): read what changed in the spec (`git log -p <plan's last commit>..origin/main -- changes/<slug>/spec.md`), then either amend the plan for it, or, if nothing in the plan is affected, confirm it by updating its `Spec:` line to say which spec commit it was checked against. Either way it goes through a plan PR.
- **Its spec isn't merged yet:** say what it's waiting on (the spec PR and who reviews it), and offer `/pr` on that PR.
- **Nothing to plan:** say so, with what each change is waiting on, and offer the step one stage back (routing step 4).

## 2. Plan it in plan mode

Planning happens in plan mode, with the change's `intent.md` (or `bug.md`) and `spec.md`. If this session isn't in plan mode, enter it (or ask the person to press Shift+Tab until it says plan mode). Read CLAUDE.md, the intent or bug, the spec, the code involved and every architecture decision record in `docs/adr/` (if there are any), then propose the plan. The engineer iterates with you until it can be implemented, then approves it.

### Scope check

Follow `.sdlc/skills/scope.md`: silence is not permission, and a rule's scope is a minimum. Before proposing, and again before saving:

- **Plan from the requirements' text, not only the criteria.** A criterion can test only part of its requirement, so work through each requirement's clauses (each separate outcome it "shows", "has", "is", "combines with", "otherwise", "when … then"), one requirement at a time: `make clauses CHANGE=<slug>` prints each one with the criteria and plan lines that cite it. Every testable clause gets a design statement and a Verification row that would fail if the clause weren't met. A clause no criterion tests is a spec gap: tell the engineer, who takes it to the product owner, rather than planning around it silently (#47).
- **Test every criterion at the level it describes.** Each Verification row names a test or command that drives the criterion the way the criterion is written: a UI behaviour through the UI, an editor plugin inside the editor, a data format with a schema and fixtures. A project rule that covers only part of the code ("every class in `core/` has a test") is a floor for that part, not a reason to leave the rest untested.
- **Find every descope**: anything the plan leaves undone, untested or unchecked, manual steps a test could do, and new code under a tool's exclusion list. Look at your own wording too ("thin", "not unit-tested", "manual", "the rule only covers …").
- **Ask about each descope on its own** with AskUserQuestion, recommending one: cover it (the plan grows), or approve the descope with its reason. Never fold descopes into approving the plan.
- **When asking for approval, lead with the descopes and risks**, quoted, then the open questions, then the steps.

### Architecture check

A single change rarely looks like an architecture decision. Several changes that each hand-build a piece a framework would provide do, and only the plan stage sees how a change is built. So before proposing, check the plan against the ADRs:

- **A trigger is met.** For each ADR whose Status is `accepted`, read its **Revisit when** lines and ask whether this plan does what one describes. Judge by what the plan does, not by its wording.
- **No ADR covers it.** The plan adds a framework, service or datastore, relies on an undocumented internal of a library, or builds by hand something a widely used library provides, for the second time or more in this repo (look at earlier plans under `changes/`).
- **Build or adopt.** Whenever the plan builds by hand something a widely used library or framework provides, say in **Approach** which one and why it isn't used.

When a trigger is met or no ADR covers the choice, tell the engineer in plain terms: the question ("Should we adopt X instead of building Y by hand?"), the ADR and trigger, and what the earlier changes built. Then ask them to choose, recommending one:

- **Keep the current architecture.** The plan says why in **Risks**, and may suggest a new or sharper trigger for the ADR (a separate ADR PR, not part of this plan).
- **Raise it with the tech lead or architect** (`.sdlc/docs/roles.md`). They write or update an ADR (from `.sdlc/templates/adr.md`, in `docs/adr/NNNN-<slug>.md`) before this plan merges; the plan may change as a result.

Either way, record it under **Risks** as `Architecture decision needed: <question> (ADR NNNN, trigger: <which>)`, or `(no ADR)`, followed by the decision. The Claude review reports a plan that meets a trigger without this line. With no `docs/adr/` folder, still do the build-or-adopt and "no ADR covers it" checks, and suggest the tech lead start one with the decision this plan depends on.

## 3. Save the approved plan

Once the plan is approved:

1. Copy `.sdlc/templates/plan.md` to `changes/<slug>/plan.md`. Fill it with the approved plan; don't add new scope.
2. Fill **Descopes**: each approved descope as `- Descope: <what isn't done, tested or checked> because <reason>. Approved: <name>, <date>.`, and each check a person must try by hand because no test can as `- Human check: <what to try, and how> because <why a test can't>. Approved: <name>, <date>.` (`scope.md`). With neither, write `None.`, never leave the template's text. A plan with a descope the engineer hasn't approved isn't approved, and `make validate` fails an entry without `Approved:`.
3. Keep the architecture check's outcome: the build-or-adopt reason in **Approach**, and any `Architecture decision needed:` line, with the engineer's decision, in **Risks**.
4. Under **Verification**, name the kinds of work this change is in the `- **Definition of done:**` line: read `.sdlc/templates/definition-of-done.md` and the repo's `docs/definition-of-done.md` (its rows replace the template's), and name every kind that fits, not the fewest. Then map each acceptance criterion from `spec.md`, and each requirement clause it doesn't fully test, to an exact command and its expected result, and show how each named row is met. What a named row asks for that the plan won't do goes under **Descopes**, approved.
5. For a bug fix (a change that starts from `bug.md`, or any fix), the first step is a failing test committed on its own, one per acceptance criterion in the short spec, with the message `test(<slug>): failing test for <symptom>`. Once that commit is on the branch, the files it touched lock automatically for a change with `bug.md` (`.sdlc/scripts/tests-locked.sh`), so the failing test can't be edited; new tests in other files still can. Nobody needs to set `SDLC_LOCK_TESTS=1`.
6. Size the steps to the change. A small change (a message, a one-line fix) needs one to three steps, not a breakdown: `/build` builds a plan that small in one session.
7. Run `make validate`, then commit `plan.md` alone on `plan/<slug>` (by explicit path, never `git add -A`), push, and open its PR titled `plan(<slug>): <summary>`. No code is written before it merges. Follow the `agent-identity` skill for the commit trailer and PR signature.

Then tell the engineer: once the plan PR merges, run `/build` (`/pr` handles its review first). `/build` builds it in its own worktree (`claude --worktree <slug>`): in one session for a small plan, or milestone by milestone from an approved `build.md` for a larger one. It finishes with `make check` and the `verifier` subagent before opening a PR.
